"""Flask entry point exposing the rotables simulation and dashboard UI."""

import copy
import threading
from typing import Dict, List, Tuple, Optional

from flask import Flask, jsonify, render_template, request

from rotables_optimizer.app import STRATEGY_REGISTRY
from rotables_optimizer.engine.simulation_state import SimulationState
from rotables_optimizer.engine.stock_coordinator import StockCoordinator
from rotables_optimizer.infra.data_loader import DatasetLoader
from rotables_optimizer.infra.game_api import GameApiClient

app = Flask(__name__)

# Slider → strategy thresholds (max_percent, strategy_key).
STRATEGY_SCALE: List[Tuple[int, str]] = [
    (7, "no_purchase"),
    (15, "lean_buffers"),
    (23, "conservative"),
    (31, "capacity_guard"),
    (39, "no_overflow"),
    (47, "balanced"),
    (55, "outstation_support"),
    (63, "progressive_outstation"),
    (71, "high_economy"),
    (78, "progressive_purchase"),
    (85, "ramp_loads"),
    (90, "late_game_push"),
    (95, "hub_priority"),
    (100, "aggressive"),
]
TOTAL_STEPS = 30 * 24


def strategy_options() -> List[str]:
    """Return the ordered strategies used on the slider for front-end display."""
    return [name for _, name in STRATEGY_SCALE]


def strategy_for_approach(pct: int) -> str:
    """Map slider percentage to a strategy key understood by STRATEGY_REGISTRY."""
    safe_pct = max(0, min(100, int(pct)))
    for threshold, name in STRATEGY_SCALE:
        if safe_pct <= threshold:
            return name
    return STRATEGY_SCALE[-1][1]


class SimulationRunner:
    """Background driver that streams state to the Flask UI without touching engine code."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status = self._blank_status()

    def _blank_status(self) -> Dict:
        return {
            "session_id": None,
            "running": False,
            "completed": False,
            "error": None,
            "strategy": None,
            "approach": 50,
            "final_score": 0,
            "progress": {
                "day": 0,
                "hour": 0,
                "step": 0,
                "total_steps": TOTAL_STEPS,
                "percent_complete": 0.0,
            },
            "events": [],
            "daily": [],
            "logs": [],
        }

    def status(self) -> Dict:
        with self._lock:
            return copy.deepcopy(self._status)

    def _update_status(self, **fields):
        with self._lock:
            self._status.update(fields)

    def _append_log(self, message: str):
        with self._lock:
            logs = self._status.get("logs", [])
            logs.append(message)
            self._status["logs"] = logs[-200:]

    def _append_event(self, event: Dict):
        with self._lock:
            events = self._status.get("events", [])
            events.append(event)
            self._status["events"] = events[-200:]

    def _upsert_daily(self, day: int, purchase: Dict, cost: float):
        with self._lock:
            daily = {row["day"]: row for row in self._status.get("daily", [])}
            row = daily.get(
                day,
                {
                    "day": day,
                    "purchases": {
                        "first_class": 0,
                        "business_class": 0,
                        "premium_economy": 0,
                        "economy": 0,
                    },
                    "cost": 0.0,
                },
            )
            for key, value in purchase.items():
                row["purchases"][key] = row["purchases"].get(key, 0) + value
            row["cost"] = round(row["cost"] + cost, 2)
            daily[day] = row
            # Keep list sorted for UI readability.
            self._status["daily"] = [daily[k] for k in sorted(daily.keys())]

    def start(self, strategy_name: Optional[str] = None, approach: int = 50) -> bool:
        """Start the simulation if idle. Returns False when already running."""
        with self._lock:
            if self._status.get("running"):
                return False
            chosen_strategy = strategy_name or strategy_for_approach(approach)
            if chosen_strategy not in STRATEGY_REGISTRY:
                raise ValueError(f"Unknown strategy '{chosen_strategy}'")

            self._status = self._blank_status()
            self._status["running"] = True
            self._status["strategy"] = chosen_strategy
            self._status["approach"] = approach
            self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run_simulation,
            args=(chosen_strategy, approach),
            daemon=True,
        )
        self._thread.start()
        return True

    def reset(self) -> bool:
        """Signal any running simulation to stop and reset state."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        with self._lock:
            self._status = self._blank_status()
        return True

    # ------------------------------------------------------------------
    # Internal execution pipeline
    # ------------------------------------------------------------------
    def _run_simulation(self, strategy_name: str, approach: int):
        loader = DatasetLoader()
        airports = loader.load_airport_profiles()
        aircraft_caps = loader.load_aircraft_capacities()

        stock = StockCoordinator(airports)
        sim_state = SimulationState()
        sim_state.aircraft_capacities = aircraft_caps

        api = GameApiClient()
        previous_total = 0.0

        try:
            self._append_log(f"Starting session with strategy '{strategy_name}' (approach {approach}%).")
            api.start_session()
            self._update_status(session_id=api.session_id)

            strategy_cls = STRATEGY_REGISTRY[strategy_name]
            strategy = strategy_cls(stock, aircraft_caps)

            for day in range(0, 30):
                for hour in range(0, 24):
                    if self._stop_event.is_set():
                        self._append_log("Simulation stopped by user reset.")
                        self._update_status(running=False, completed=False)
                        api.end_session()
                        return

                    instruction = strategy.plan_round(day, hour, sim_state)
                    outcome = api.play_round(instruction)

                    sim_state.ingest_backend_round(outcome)
                    stock.receive_purchase_at_hub(instruction.procurement)

                    for event in outcome.flight_events:
                        if event.event_type.value == "LANDED":
                            used_kits = strategy.last_kits_per_flight.get(event.flight_id)
                            if used_kits:
                                stock.enqueue_processing_after_landing(
                                    airport_code=event.destination_airport,
                                    used_kits=used_kits,
                                    day=outcome.day,
                                    hour=outcome.hour,
                                )
                            strategy.last_kits_per_flight.pop(event.flight_id, None)

                    hourly_cost = outcome.total_cost - previous_total if previous_total else outcome.total_cost
                    previous_total = outcome.total_cost

                    purchase_payload = {
                        "first_class": instruction.procurement.first_class,
                        "business_class": instruction.procurement.business_class,
                        "premium_economy": instruction.procurement.premium_economy,
                        "economy": instruction.procurement.economy,
                    }
                    self._append_event(
                        {
                            "day": outcome.day,
                            "hour": outcome.hour,
                            "hourly_cost": round(hourly_cost, 2),
                            "purchase": purchase_payload,
                            "cumulative_cost": outcome.total_cost,
                        }
                    )
                    self._upsert_daily(outcome.day, purchase_payload, hourly_cost)
                    self._append_log(
                        f"Day {outcome.day} hour {outcome.hour} cost={outcome.total_cost:.2f} strategy={strategy_name}"
                    )

                    step_idx = (day * 24) + hour + 1
                    percent = round((step_idx / TOTAL_STEPS) * 100, 2)
                    self._update_status(
                        progress={
                            "day": outcome.day,
                            "hour": outcome.hour,
                            "step": step_idx,
                            "total_steps": TOTAL_STEPS,
                            "percent_complete": percent,
                        },
                        final_score=previous_total,
                        running=True,
                        completed=False,
                        error=None,
                    )

            api.end_session()
            self._update_status(running=False, completed=True, final_score=previous_total)
            self._append_log("Simulation completed.")

        except Exception as exc:  # noqa: BLE001
            self._append_log(f"Simulation error: {exc}")
            self._update_status(running=False, completed=False, error=str(exc))


runner = SimulationRunner()


@app.route("/")
def index():
    return render_template(
        "index.html",
        status=runner.status(),
        strategies=strategy_options(),
        strategy_scale=[{"max": pct, "strategy": name} for pct, name in STRATEGY_SCALE],
    )


@app.post("/api/simulation/start")
def start_simulation():
    payload = request.get_json(silent=True) or {}
    approach = int(payload.get("approach", 50))
    client_strategy = payload.get("strategy")

    chosen = client_strategy or strategy_for_approach(approach)
    started = runner.start(strategy_name=chosen, approach=approach)
    status = runner.status()
    status["started"] = started
    return jsonify(status), (202 if started else 409)


@app.get("/api/simulation/status")
def simulation_status():
    return jsonify(runner.status())


@app.post("/api/simulation/reset")
def reset_simulation():
    reset_ok = runner.reset()
    status = runner.status()
    status["reset"] = reset_ok
    return jsonify(status), (200 if reset_ok else 409)


@app.errorhandler(Exception)
def handle_error(exc):  # noqa: D401
    """Return JSON errors to the front-end."""
    return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

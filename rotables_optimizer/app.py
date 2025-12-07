"""Entry point for the refactored rotables engine and a thin orchestration layer.

The module now exposes a SimulationRunner that can be driven from a Flask UI
while keeping the original CLI-friendly `run()` entry point.
"""

import sys
import threading
import types
from pathlib import Path
from typing import Dict, List, Optional

# Bootstrap: expose this folder (which has a hyphen in its name) as an importable
# package named "rotables_optimizer" and, for backward compatibility, "rotables".
PACKAGE_ROOT = Path(__file__).resolve().parent
for alias in ("rotables_optimizer", "rotables"):
    if alias not in sys.modules:
        module = types.ModuleType(alias)
        module.__path__ = [str(PACKAGE_ROOT)]
        sys.modules[alias] = module

# Ensure the parent directory is on sys.path so subpackages are discoverable.
REPO_ROOT = PACKAGE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rotables_optimizer.domain.contracts import CabinKits, RoundInstruction
from rotables_optimizer.engine.simulation_state import SimulationState
from rotables_optimizer.engine.stock_coordinator import StockCoordinator
from rotables_optimizer.engine.strategy import BalancedDispatchStrategy
from rotables_optimizer.infra.data_loader import DatasetLoader
from rotables_optimizer.infra.game_api import DEFAULT_API_KEY, GameApiClient

TOTAL_STEPS = 30 * 24  # 30 days x 24 hours


def _kits_to_dict(kits: CabinKits) -> Dict[str, int]:
    return {
        "first_class": kits.first_class,
        "business_class": kits.business_class,
        "premium_economy": kits.premium_economy,
        "economy": kits.economy,
    }


class SimulationRunner:
    """
    Drives the rotables strategy against the backend game API while collecting
    progress information for presentation layers (CLI, Flask, etc.).
    """

    def __init__(self, api_key: str = DEFAULT_API_KEY):
        self.api_key = api_key
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None

        self.api: Optional[GameApiClient] = None
        self.running = False
        self.completed = False
        self.error: Optional[str] = None
        self.progress: Dict = {}
        self.events: List[Dict] = []
        self.logs: List[str] = []
        self.daily: Dict[int, Dict] = {}
        self.cumulative_cost: float = 0.0
        self.session_id: Optional[str] = None
        self._reset_state()

    def _reset_state(self):
        with self.lock:
            self.running = False
            self.completed = False
            self.error = None
            self.progress = {
                "step": 0,
                "total_steps": TOTAL_STEPS,
                "percent_complete": 0.0,
                "day": 0,
                "hour": 0,
            }
            self.events = []
            self.logs = []
            self.daily = {}
            self.cumulative_cost = 0.0
            self.session_id = None

    def start(self) -> bool:
        """Start the simulation in a background thread."""
        with self.lock:
            if self.running:
                return False
            self._reset_state()
            self.running = True

        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        return True

    def _record_daily(self, day: int, purchase: CabinKits, cost: float):
        daily_entry = self.daily.setdefault(
            day,
            {"purchases": {"first_class": 0, "business_class": 0, "premium_economy": 0, "economy": 0}, "cost": 0.0},
        )
        daily_entry["purchases"]["first_class"] += purchase.first_class
        daily_entry["purchases"]["business_class"] += purchase.business_class
        daily_entry["purchases"]["premium_economy"] += purchase.premium_economy
        daily_entry["purchases"]["economy"] += purchase.economy
        daily_entry["cost"] += cost

    def _record_tick(self, outcome, instruction: RoundInstruction, strategy: BalancedDispatchStrategy):
        purchase = instruction.procurement
        self.cumulative_cost += outcome.total_cost

        log_line = (
            f"Day {outcome.day}, hour {outcome.hour}: "
            f"purchased {purchase.first_class}/{purchase.business_class}/"
            f"{purchase.premium_economy}/{purchase.economy} kits; "
            f"cost this hour {outcome.total_cost:.2f}"
        )

        with self.lock:
            self.progress.update(
                {
                    "day": outcome.day,
                    "hour": outcome.hour,
                    "step": outcome.day * 24 + outcome.hour + 1,
                }
            )
            self.progress["percent_complete"] = round(
                100.0 * self.progress["step"] / float(self.progress["total_steps"]), 2
            )
            self.logs.append(log_line)
            self.events.append(
                {
                    "day": outcome.day,
                    "hour": outcome.hour,
                    "purchase": _kits_to_dict(purchase),
                    "hourly_cost": outcome.total_cost,
                    "cumulative_cost": round(self.cumulative_cost, 2),
                }
            )
            self._record_daily(outcome.day, purchase, outcome.total_cost)

            # Keep memory bounded for long runs.
            self.logs = self.logs[-400:]
            self.events = self.events[-400:]

        # Landed flights return kits into processing.
        for event in outcome.flight_events:
            if event.event_type.value == "LANDED":
                used_kits = strategy.last_kits_per_flight.get(event.flight_id)
                if used_kits:
                    strategy.stock.enqueue_processing_after_landing(
                        airport_code=event.destination_airport,
                        used_kits=used_kits,
                        day=outcome.day,
                        hour=outcome.hour,
                    )
                strategy.last_kits_per_flight.pop(event.flight_id, None)

    def _run_loop(self):
        try:
            loader = DatasetLoader()
            airports = loader.load_airport_profiles()
            aircraft_caps = loader.load_aircraft_capacities()

            stock = StockCoordinator(airports)
            sim_state = SimulationState()
            sim_state.aircraft_capacities = aircraft_caps

            self.api = GameApiClient(api_key=self.api_key)
            strategy = BalancedDispatchStrategy(stock, aircraft_caps)

            self.api.start_session()
            self.session_id = self.api.session_id

            day = 0
            hour = 0

            while True:
                instruction: RoundInstruction = strategy.plan_round(day, hour, sim_state)
                outcome = self.api.play_round(instruction)

                sim_state.ingest_backend_round(outcome)

                # Apply procurement to HUB inventory right away.
                purchase = instruction.procurement
                if purchase.first_class or purchase.business_class or purchase.premium_economy or purchase.economy:
                    stock.receive_purchase_at_hub(purchase)

                self._record_tick(outcome, instruction, strategy)

                if outcome.day == 29 and outcome.hour == 23:
                    break

                hour += 1
                if hour == 24:
                    hour = 0
                    day += 1
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.error = str(exc)
        finally:
            try:
                if self.api:
                    self.api.end_session()
            finally:
                with self.lock:
                    self.running = False
                    self.completed = True

    def status(self) -> Dict:
        with self.lock:
            daily_rows = []
            for day, payload in sorted(self.daily.items()):
                daily_rows.append(
                    {
                        "day": day,
                        "purchases": payload["purchases"],
                        "cost": round(payload["cost"], 2),
                    }
                )

            return {
                "running": self.running,
                "completed": self.completed,
                "error": self.error,
                "session_id": self.session_id,
                "progress": self.progress,
                "events": list(self.events),
                "daily": daily_rows,
                "logs": list(self.logs),
                "final_score": round(self.cumulative_cost, 2),
            }

    def reset(self):
        if self.running:
            # No cooperative stop implemented; caller should wait for completion.
            return False
        self._reset_state()
        return True

    def run_sync(self):
        """Convenience for CLI usage."""
        started = self.start()
        if not started:
            return
        if self.thread:
            self.thread.join()


def run():
    runner = SimulationRunner()
    runner.run_sync()
    print("=== SIMULATION END ===")
    if runner.error:
        print(f"ERROR: {runner.error}")
    else:
        print("SESSION CLOSED BY BACKEND")


if __name__ == "__main__":
    run()

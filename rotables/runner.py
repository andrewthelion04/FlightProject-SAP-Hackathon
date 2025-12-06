"""Session runner wiring the matrix model to the backend API."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

# Ensure package imports work when running this file directly (`python rotables/runner.py`)
if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from rotables.client import ApiClient

from rotables.models.aircraft import AircraftType, load_aircraft_types_from_csv
from rotables.models.airport import Airport, load_airports_from_csv
from rotables.models.flight import FlightInstance, FlightPlanEntry, FlightStatus, load_flight_plan_from_csv
from rotables.models.kit_types import KitType, PASSENGER_KEYS_BY_TYPE
from rotables.state.matrix_state import MatrixState
from rotables.state.time_index import MAX_HOUR, from_global_hour, to_global_hour
from rotables.strategy.base import KitLoadDecision, PurchaseDecision, Strategy
from rotables.strategy.lookahead import LookaheadStrategy


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "eval-platform" / "src" / "main" / "resources" / "liquibase" / "data"


class SessionRunner:
    """Coordinates session lifecycle, event processing, and matrix updates."""

    def __init__(
        self,
        data_dir: Path = DEFAULT_DATA_DIR,
        strategy: Optional[Strategy] = None,
        client: Optional[ApiClient] = None,
    ) -> None:
        self.data_dir = data_dir
        self.strategy: Strategy = strategy or LookaheadStrategy()
        self.client = client or ApiClient()

        self.airports: Dict[str, Airport] = load_airports_from_csv(self.data_dir / "airports_with_stocks.csv")
        self.aircraft_types: Dict[str, AircraftType] = load_aircraft_types_from_csv(self.data_dir / "aircraft_types.csv")
        self.flight_plan: List[FlightPlanEntry] = load_flight_plan_from_csv(self.data_dir / "flight_plan.csv")
        self.matrix = MatrixState(self.airports, self.aircraft_types)

        self.flights_by_id: Dict[str, FlightInstance] = {}
        self.loaded_flights: set[str] = set()
        self.penalties_log: List[Dict] = []
        self.total_cost: Optional[float] = None
        self.current_day = 0
        self.current_hour = 0

    def start_session(self) -> Optional[str]:
        return self.client.start_session()

    def end_session(self) -> None:
        self.client.end_session()

    def run(self, max_global_hour: int = MAX_HOUR) -> None:
        """Run the session loop with the current strategy."""
        if not self.start_session():
            print("Failed to start session; aborting run.")
            return
        global_hour = to_global_hour(self.current_day, self.current_hour)
        while global_hour < max_global_hour:
            self.step()
            global_hour = to_global_hour(self.current_day, self.current_hour)
        self.end_session()

    def step(self) -> None:
        """Process one hour: update stocks, decide actions, call API."""
        global_hour = to_global_hour(self.current_day, self.current_hour)
        self.matrix.apply_movements_for_hour(global_hour)
        flights_now = self._flights_departing_now(global_hour)

        load_decisions, purchase_decisions = self.strategy.decide(
            current_day=self.current_day,
            current_hour=self.current_hour,
            flights_now=flights_now,
            matrix=self.matrix,
            all_flights=list(self.flights_by_id.values()),
        )

        self._apply_decisions_to_matrix(global_hour, load_decisions, purchase_decisions)
        payload = self._decisions_to_payload(load_decisions, purchase_decisions)

        response = self.client.play_round(self.current_day, self.current_hour, payload)
        if response:
            self._process_response(response)
        self._advance_time()

    def _flights_departing_now(self, global_hour: int) -> List[FlightInstance]:
        """Return flights that should depart at the current hour."""
        flights: List[FlightInstance] = []
        for flight in self.flights_by_id.values():
            if flight.flight_id in self.loaded_flights:
                continue
            if flight.departure_global_hour == global_hour and flight.status in {
                FlightStatus.SCHEDULED,
                FlightStatus.CHECKED_IN,
            }:
                flights.append(flight)
        return flights

    def _apply_decisions_to_matrix(
        self,
        global_hour: int,
        load_decisions: List[KitLoadDecision],
        purchase_decisions: List[PurchaseDecision],
    ) -> None:
        for decision in load_decisions:
            if decision.flight_id in self.loaded_flights:
                continue
            flight = self.flights_by_id.get(decision.flight_id)
            if not flight:
                continue
            self.matrix.schedule_flight_load(flight, decision.kits_per_type)
            self.loaded_flights.add(decision.flight_id)

        for purchase in purchase_decisions:
            self.matrix.schedule_purchase(purchase.kit_type, purchase.quantity, global_hour)

    def _decisions_to_payload(
        self, load_decisions: List[KitLoadDecision], purchase_decisions: List[PurchaseDecision]
    ) -> Dict:
        flight_loads = []
        for decision in load_decisions:
            # Backend expects all four class keys present even if 0
            kits_json = {PASSENGER_KEYS_BY_TYPE[kit]: int(decision.kits_per_type.get(kit, 0)) for kit in KitType}
            flight_loads.append({"flightId": decision.flight_id, "loadedKits": kits_json})

        purchases_by_type: Dict[KitType, int] = {kit: 0 for kit in KitType}
        for purchase in purchase_decisions:
            purchases_by_type[purchase.kit_type] += purchase.quantity

        purchasing_orders = {PASSENGER_KEYS_BY_TYPE[kit]: qty for kit, qty in purchases_by_type.items()}
        return {"flightLoads": flight_loads, "kitPurchasingOrders": purchasing_orders}

    def _process_response(self, response: Dict) -> None:
        """Update flight registry and penalties from API response."""
        self.total_cost = response.get("totalCost", self.total_cost)
        penalties = response.get("penalties") or []
        if penalties:
            self.penalties_log.extend(penalties)
        for event in response.get("flightUpdates") or []:
            self._upsert_flight(event)

    def _upsert_flight(self, event: Dict) -> None:
        raw_id = event.get("flightId")
        if raw_id is None:
            return
        flight_id = str(raw_id)
        if not flight_id:
            return
        flight = self.flights_by_id.get(flight_id)
        if not flight:
            dep = event.get("departure", {})
            arr = event.get("arrival", {})
            passengers = event.get("passengers", {}) or {}
            planned_passengers: Dict[KitType, int] = {}
            for key, value in passengers.items():
                try:
                    kit = KitType.from_passenger_key(key)
                except ValueError:
                    continue
                planned_passengers[kit] = int(value)
            flight = FlightInstance(
                flight_id=str(flight_id),
                flight_number=event.get("flightNumber", ""),
                origin=event.get("originAirport", ""),
                destination=event.get("destinationAirport", ""),
                aircraft_type_code=event.get("aircraftType", ""),
                planned_departure=(int(dep.get("day", 0)), int(dep.get("hour", 0))),
                planned_arrival=(int(arr.get("day", 0)), int(arr.get("hour", 0))),
                planned_distance=float(event.get("distance", 0.0) or 0.0),
                planned_passengers=planned_passengers,
            )
            self.flights_by_id[flight_id] = flight
        flight.update_from_event(event)

    def _advance_time(self) -> None:
        """Move to the next hour, wrapping day/hour accordingly."""
        global_hour = to_global_hour(self.current_day, self.current_hour) + 1
        self.current_day, self.current_hour = from_global_hour(global_hour)


def read_csv_preview(path: Path, lines: int = 3) -> List[str]:
    """Utility for quickly peeking CSV headers (used for debugging)."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [next(handle).strip() for _ in range(lines)]


if __name__ == "__main__":
    runner = SessionRunner()
    runner.run()

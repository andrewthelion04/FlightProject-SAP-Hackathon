"""Session runner orchestrating API calls and the matrix state."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from client import ApiClient
from config import API_BASE_URL, API_KEY
from rotables.models.aircraft import AircraftType, load_aircraft_types
from rotables.models.airport import Airport, load_airports
from rotables.models.flight import FlightInstance
from rotables.models.flight_plan import FlightPlanEntry, load_flight_plan
from rotables.models.kit_types import KitType
from rotables.state.matrix_state import MatrixState
from rotables.state.time_index import MAX_HOUR, from_global_hour, to_global_hour
from rotables.strategy.base import KitLoadDecision, PurchaseDecision, Strategy


AIRPORTS_CSV = Path("eval-platform/src/main/resources/liquibase/data/airports_with_stocks.csv")
FLIGHT_PLAN_CSV = Path("eval-platform/src/main/resources/liquibase/data/flight_plan.csv")
AIRCRAFT_TYPES_CSV = Path("eval-platform/src/main/resources/liquibase/data/aircraft_types.csv")


def _empty_loaded_kits() -> Dict[str, int]:
    return {kt.passenger_key: 0 for kt in KitType}


@dataclass
class SessionRunner:
    strategy: Strategy
    airports: Dict[str, Airport] = field(init=False)
    aircraft_types: Dict[str, AircraftType] = field(init=False)
    flight_plan: List[FlightPlanEntry] = field(init=False)
    matrix: MatrixState = field(init=False)
    client: ApiClient = field(init=False)
    flights_by_id: Dict[str, FlightInstance] = field(default_factory=dict)
    session_id: Optional[str] = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.airports = load_airports(AIRPORTS_CSV)
        self.aircraft_types = load_aircraft_types(AIRCRAFT_TYPES_CSV)
        self.flight_plan = load_flight_plan(FLIGHT_PLAN_CSV)
        self.matrix = MatrixState(airports=self.airports, aircraft_types=self.aircraft_types)
        self.client = ApiClient(base_url=API_BASE_URL, api_key=API_KEY)

    def start_session(self) -> Optional[str]:
        self.session_id = self.client.start_session()
        return self.session_id

    def end_session(self) -> None:
        self.client.end_session()

    def _process_flight_updates(self, updates: List[Dict]) -> None:
        for upd in updates:
            flight_id = str(upd.get("flightId") or upd.get("id"))
            if not flight_id:
                continue
            flight = self.flights_by_id.get(
                flight_id,
                FlightInstance(
                    flight_id=flight_id,
                    flight_number=str(upd.get("flightNumber") or flight_id),
                    origin=upd.get("originAirport") or "",
                    destination=upd.get("destinationAirport") or "",
                ),
            )
            flight.update_from_event(upd)
            if flight.status == "LANDED":
                self.flights_by_id.pop(flight_id, None)
            else:
                self.flights_by_id[flight_id] = flight

    def _apply_decisions(
        self, current_day: int, current_hour: int, load_decisions: List[KitLoadDecision], purchases: List[PurchaseDecision]
    ) -> tuple[List[Dict], Optional[Dict]]:
        """Schedule movements in the matrix and build API payload parts."""
        flight_loads_payload = []
        for decision in load_decisions:
            flight = self.flights_by_id.get(decision.flight_id)
            if not flight:
                continue
            dep_t = flight.departure_global_hour()
            arr_t = flight.arrival_global_hour()
            if dep_t is None or arr_t is None:
                continue
            dep_day, dep_hour = from_global_hour(dep_t)
            arr_day, arr_hour = from_global_hour(arr_t)
            accepted = self.matrix.schedule_flight_load(
                flight_id=flight.flight_id,
                origin=flight.origin,
                destination=flight.destination,
                aircraft_type_code=flight.aircraft_type_code or "",
                depart_day=dep_day,
                depart_hour=dep_hour,
                arrival_day=arr_day,
                arrival_hour=arr_hour,
                load_per_kit=decision.kits_per_type,
            )
            # Immediately deduct from origin node for this hour
            origin_node = self.matrix.ensure_node(flight.origin, dep_t)
            for kt, qty in accepted.items():
                origin_node.available_kits[kt] = origin_node.available_kits.get(kt, 0) - qty
            if accepted:
                loaded_kits = _empty_loaded_kits()
                for kt, qty in accepted.items():
                    loaded_kits[kt.passenger_key] = qty
                flight_loads_payload.append({"flightId": flight.flight_id, "loadedKits": loaded_kits})

        purchase_payload = None
        if purchases:
            purchase_payload = _empty_loaded_kits()
            current_t = to_global_hour(current_day, current_hour)
            for p in purchases:
                mv = self.matrix.schedule_purchase(p.kit_type, p.quantity, current_t)
                if mv:
                    purchase_payload[p.kit_type.passenger_key] += p.quantity
        return flight_loads_payload, purchase_payload

    def run(self, max_global_hour: int = MAX_HOUR, end_day: int = 29, end_hour: int = 23) -> None:
        if not self.session_id:
            self.start_session()
        if not self.session_id:
            print("Failed to start session; aborting.")
            return

        response_cache: Dict = {}
        current_day, current_hour = 0, 0
        last_round_t = to_global_hour(end_day, end_hour)
        while True:
            current_t = to_global_hour(current_day, current_hour)
            self.matrix.apply_movements_for_hour(current_t)

            # Strategy decisions
            flights_now = list(self.flights_by_id.values())
            load_decisions, purchase_decisions = self.strategy.decide(current_day, current_hour, flights_now, self.matrix)
            flight_loads_payload, purchase_payload = self._apply_decisions(
                current_day, current_hour, load_decisions, purchase_decisions
            )

            payload = {"day": current_day, "hour": current_hour, "flightLoads": flight_loads_payload}
            if purchase_payload:
                payload["kitPurchasingOrders"] = purchase_payload
            else:
                payload["kitPurchasingOrders"] = None

            print(f"Posting play_round for day={current_day} hour={current_hour}")
            response_cache = self.client.play_round(current_day, current_hour, payload) or {}
            updates = response_cache.get("flightUpdates", []) if isinstance(response_cache, dict) else []
            self._process_flight_updates(updates)

            if current_t >= last_round_t:
                break

            current_hour += 1
            if current_hour >= 24:
                current_hour = 0
                current_day += 1

        end_resp = self.client.end_session()
        if end_resp is not None:
            print("Session end response:", end_resp)

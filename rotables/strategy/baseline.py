"""Simple baseline strategy for feasibility checks."""
from __future__ import annotations

from typing import List, Tuple

from rotables.models.kit_types import KitType
from rotables.models.flight import FlightInstance
from rotables.state.matrix_state import MatrixState
from rotables.strategy.base import KitLoadDecision, PurchaseDecision, Strategy


class BaselineStrategy(Strategy):
    """Greedy loader that tries to match passengers without purchasing."""

    def decide(
        self,
        current_day: int,
        current_hour: int,
        flights_now: List[FlightInstance],
        matrix: MatrixState,
        all_flights: List[FlightInstance],
    ) -> Tuple[List[KitLoadDecision], List[PurchaseDecision]]:
        load_decisions: List[KitLoadDecision] = []
        purchase_decisions: List[PurchaseDecision] = []
        availability_cache: dict[tuple[str, int], dict[KitType, int]] = {}

        for flight in flights_now:
            aircraft = matrix.aircraft_types.get(flight.aircraft_type_code)
            if not aircraft:
                continue

            origin_key = (flight.origin, flight.departure_global_hour)
            if origin_key not in availability_cache:
                availability_cache[origin_key] = matrix.get_available_kits(flight.origin, flight.departure_global_hour)
            available = availability_cache[origin_key]
            passengers = flight.actual_passengers or flight.planned_passengers
            kits: dict[KitType, int] = {}
            for kit in KitType:
                desired = passengers.get(kit, 0)
                capacity = aircraft.kit_capacity_per_class.get(kit, 0)
                to_load = min(desired, capacity, available.get(kit, 0))
                if to_load > 0:
                    kits[kit] = to_load
                    available[kit] = available.get(kit, 0) - to_load
            if kits:
                load_decisions.append(KitLoadDecision(flight_id=flight.flight_id, kits_per_type=kits))

        # Placeholder: no purchasing in baseline
        return load_decisions, purchase_decisions

"""Baseline heuristic strategy: load as many kits as safely possible."""
from __future__ import annotations

from typing import Dict, List

from rotables.models.flight import FlightInstance
from rotables.models.kit_types import KitType
from rotables.state.matrix_state import MatrixState
from rotables.state.time_index import to_global_hour
from rotables.strategy.base import KitLoadDecision, PurchaseDecision, Strategy


class BaselineStrategy(Strategy):
    def decide(
        self,
        current_day: int,
        current_hour: int,
        flights_now: List[FlightInstance],
        matrix: MatrixState,
    ) -> tuple[List[KitLoadDecision], List[PurchaseDecision]]:
        current_t = to_global_hour(current_day, current_hour)
        load_decisions: List[KitLoadDecision] = []
        for flight in flights_now:
            dep_t = flight.departure_global_hour()
            if dep_t is None or dep_t != current_t:
                continue
            origin_stock = matrix.get_available_kits(flight.origin, dep_t)
            aircraft = matrix.aircraft_types.get(flight.aircraft_type_code or "", None)
            load_map: Dict[KitType, int] = {}
            for kt in KitType:
                passengers = flight.actual_passengers.get(kt, 0) or flight.planned_passengers.get(kt, 0) or 0
                cap = aircraft.kit_capacity_per_class.get(kt, passengers) if aircraft else passengers
                available = origin_stock.get(kt, 0)
                load_qty = min(passengers, cap, available)
                if load_qty > 0:
                    load_map[kt] = load_qty
            if load_map:
                load_decisions.append(KitLoadDecision(flight_id=flight.flight_id, kits_per_type=load_map))

        return load_decisions, []

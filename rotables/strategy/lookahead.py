"""Deterministic lookahead strategy that prioritizes penalties avoidance."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

from rotables.models.flight import FlightInstance, FlightStatus
from rotables.models.kit_types import KitType
from rotables.state.matrix_state import MatrixState
from rotables.state.movements import EdgeType
from rotables.state.time_index import MAX_HOUR, to_global_hour
from rotables.strategy.base import KitLoadDecision, PurchaseDecision, Strategy
from rotables.strategy.config import StrategyConfig


class LookaheadStrategy(Strategy):
    """
    Greedy-but-safe heuristic:
    - Serve passengers first using available stock.
    - Forecast short-horizon demand vs. incoming kits to trigger hub purchases.
    - Reposition surplus kits on short/cheap legs toward airports with forecast deficit.
    """

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()

    def decide(
        self,
        current_day: int,
        current_hour: int,
        flights_now: List[FlightInstance],
        matrix: MatrixState,
        all_flights: List[FlightInstance],
    ) -> Tuple[List[KitLoadDecision], List[PurchaseDecision]]:
        global_hour = to_global_hour(current_day, current_hour)
        stock = {code: matrix.get_available_kits(code, global_hour) for code in matrix.airports}

        loads: Dict[str, Dict[KitType, int]] = self._allocate_passenger_loads(flights_now, stock, matrix)
        horizon_by_kit = self._horizon_by_kit(matrix, global_hour)

        demand = self._forecast_demand(all_flights, global_hour, horizon_by_kit, matrix)
        incoming = self._forecast_incoming(matrix, global_hour, horizon_by_kit)

        deficit = self._compute_deficit(stock, demand, incoming)
        surplus = self._compute_surplus(stock, demand, incoming)

        if self.config.allow_reposition:
            self._plan_reposition(flights_now, loads, stock, deficit, surplus, incoming, demand, matrix)
        purchases = self._plan_purchases(stock, demand, incoming, matrix, global_hour)

        load_decisions = self._to_load_decisions(loads)
        return load_decisions, purchases

    # -------------------------
    # Allocation helpers
    # -------------------------
    def _allocate_passenger_loads(
        self,
        flights_now: List[FlightInstance],
        stock: Dict[str, Dict[KitType, int]],
        matrix: MatrixState,
    ) -> Dict[str, Dict[KitType, int]]:
        loads: Dict[str, Dict[KitType, int]] = defaultdict(dict)
        flights_by_origin: Dict[str, List[FlightInstance]] = defaultdict(list)
        for flight in flights_now:
            flights_by_origin[flight.origin].append(flight)

        for origin, flights in flights_by_origin.items():
            origin_stock = stock.setdefault(origin, {kit: 0 for kit in KitType})
            for kit in KitType:
                orig_available = origin_stock.get(kit, 0)
                effective_available = int(orig_available * self.config.safe_load_ratio)
                loaded_total = 0
                candidates: List[tuple[float, int, FlightInstance, int]] = []
                for flight in flights:
                    aircraft = matrix.aircraft_types.get(flight.aircraft_type_code)
                    if not aircraft:
                        continue
                    passengers = self._passengers_for(flight, kit)
                    if passengers <= 0:
                        continue
                    capacity = aircraft.kit_capacity_per_class.get(kit, 0)
                    if capacity <= 0:
                        continue
                    ideal = min(passengers, capacity)
                    priority = self._priority_score(flight, kit)
                    candidates.append((priority, ideal, flight, capacity))

                candidates.sort(key=lambda item: item[0], reverse=True)
                for _, ideal, flight, capacity in candidates:
                    load_qty = min(ideal, effective_available, capacity)
                    if load_qty <= 0:
                        continue
                    load_for_flight = loads[flight.flight_id]
                    load_for_flight[kit] = load_for_flight.get(kit, 0) + int(load_qty)
                    effective_available -= load_qty
                    loaded_total += load_qty
                origin_stock[kit] = max(0, int(orig_available - loaded_total))
        return loads

    def _plan_reposition(
        self,
        flights_now: List[FlightInstance],
        loads: Dict[str, Dict[KitType, int]],
        stock: Dict[str, Dict[KitType, int]],
        deficit: Dict[str, Dict[KitType, int]],
        surplus: Dict[str, Dict[KitType, int]],
        incoming: Dict[str, Dict[KitType, int]],
        demand: Dict[str, Dict[KitType, int]],
        matrix: MatrixState,
    ) -> None:
        for flight in flights_now:
            aircraft = matrix.aircraft_types.get(flight.aircraft_type_code)
            if not aircraft:
                continue
            origin_stock = stock.get(flight.origin, {})
            for kit in KitType:
                current_load = loads.get(flight.flight_id, {}).get(kit, 0)
                capacity = aircraft.kit_capacity_per_class.get(kit, 0)
                remaining_capacity = max(0, capacity - current_load)
                if remaining_capacity <= 0:
                    continue
                origin_surplus = surplus.get(flight.origin, {}).get(kit, 0)
                reserve_ratio = self.config.safety_stock_ratio.get(kit, 0.0)
                reserve = max(
                    self.config.min_reserve_at_origin,
                    int(reserve_ratio * demand.get(flight.origin, {}).get(kit, 0)),
                )
                origin_available = min(origin_stock.get(kit, 0), max(0, origin_surplus - reserve))
                dest_deficit = deficit.get(flight.destination, {}).get(kit, 0)
                if origin_available <= 0 or dest_deficit <= 0:
                    continue
                if not self._should_reposition(flight, kit, matrix):
                    continue

                dest_airport = matrix.airports.get(flight.destination)
                if not dest_airport:
                    continue
                dest_capacity = dest_airport.capacity_per_kit.get(kit, 0)
                dest_current = stock.get(flight.destination, {}).get(kit, 0)
                dest_incoming = incoming.get(flight.destination, {}).get(kit, 0)
                dest_space = max(0, dest_capacity - (dest_current + dest_incoming))
                if dest_space <= 0:
                    continue

                extra = min(remaining_capacity, origin_available, dest_deficit, dest_space)
                if extra <= 0:
                    continue

                loads.setdefault(flight.flight_id, {})[kit] = current_load + int(extra)
                stock[flight.origin][kit] = max(0, origin_stock.get(kit, 0) - int(extra))
                deficit[flight.destination][kit] = max(0, dest_deficit - int(extra))
                surplus[flight.origin][kit] = max(0, origin_surplus - int(extra))

    def _plan_purchases(
        self,
        stock: Dict[str, Dict[KitType, int]],
        demand: Dict[str, Dict[KitType, int]],
        incoming: Dict[str, Dict[KitType, int]],
        matrix: MatrixState,
        global_hour: int,
    ) -> List[PurchaseDecision]:
        purchases: List[PurchaseDecision] = []
        hub_code = "HUB1"
        hub = matrix.airports.get(hub_code)
        if not hub:
            return purchases

        hub_stock = stock.get(hub_code, {kit: 0 for kit in KitType})
        hub_incoming = incoming.get(hub_code, {kit: 0 for kit in KitType})
        hub_capacity = hub.capacity_per_kit

        for kit in KitType:
            available_space = max(0, hub_capacity.get(kit, 0) - (hub_stock.get(kit, 0) + hub_incoming.get(kit, 0)))
            if available_space <= 0:
                continue
            projected_need = demand.get(hub_code, {}).get(kit, 0)
            net_balance = (hub_stock.get(kit, 0) + hub_incoming.get(kit, 0)) - projected_need
            if net_balance >= self.config.min_purchase_threshold:
                continue

            deficit = max(0, projected_need - (hub_stock.get(kit, 0) + hub_incoming.get(kit, 0)))
            safety = max(self.config.min_purchase_threshold, int(self.config.purchase_safety_ratio * projected_need))
            if self.config.endgame_aggressive_purchase and global_hour >= MAX_HOUR - self.config.endgame_lookahead_hours:
                safety += int(projected_need * 0.2)
            qty = min(available_space, deficit + safety)
            if qty > 0:
                purchases.append(PurchaseDecision(kit_type=kit, quantity=int(qty)))
        return purchases

    # -------------------------
    # Forecasting helpers
    # -------------------------
    def _horizon_by_kit(self, matrix: MatrixState, current_global_hour: int) -> Dict[KitType, int]:
        horizons: Dict[KitType, int] = {}
        for kit in KitType:
            max_processing = max(
                (airport.processing_time_hours.get(kit, 0) for airport in matrix.airports.values()),
                default=0,
            )
            lead_time = kit.replacement_lead_time_hours * self._kit_horizon_multiplier(kit)
            base = lead_time + max_processing + self.config.safety_buffer_hours
            endgame_extension = self.config.endgame_lookahead_hours if current_global_hour >= MAX_HOUR - self.config.endgame_lookahead_hours else 0
            horizons[kit] = min(MAX_HOUR, int(base + endgame_extension))
        return horizons

    def _forecast_demand(
        self,
        flights: List[FlightInstance],
        current_global_hour: int,
        horizon_by_kit: Dict[KitType, int],
        matrix: MatrixState,
    ) -> Dict[str, Dict[KitType, int]]:
        demand: Dict[str, Dict[KitType, int]] = {code: {kit: 0 for kit in KitType} for code in matrix.airports}
        for flight in flights:
            if flight.status == FlightStatus.LANDED:
                continue
            dep_hour = flight.departure_global_hour
            if dep_hour <= current_global_hour:
                continue
            for kit in KitType:
                horizon_limit = current_global_hour + horizon_by_kit[kit]
                if dep_hour > horizon_limit:
                    continue
                qty = self._passengers_for(flight, kit)
                if qty <= 0:
                    continue
                demand[flight.origin][kit] = demand[flight.origin].get(kit, 0) + qty
        return demand

    def _forecast_incoming(
        self,
        matrix: MatrixState,
        current_global_hour: int,
        horizon_by_kit: Dict[KitType, int],
    ) -> Dict[str, Dict[KitType, int]]:
        incoming: Dict[str, Dict[KitType, int]] = {code: {kit: 0 for kit in KitType} for code in matrix.airports}
        for movement in matrix.movements:
            if movement.edge_type not in {EdgeType.PROCESSING, EdgeType.PURCHASE}:
                continue
            if movement.destination_hour <= current_global_hour:
                continue
            kit = movement.kit_type
            horizon_limit = current_global_hour + horizon_by_kit[kit]
            if movement.destination_hour > horizon_limit:
                continue
            airport_map = incoming.setdefault(movement.destination_airport, {k: 0 for k in KitType})
            airport_map[kit] = airport_map.get(kit, 0) + movement.quantity
        return incoming

    def _compute_deficit(
        self,
        stock: Dict[str, Dict[KitType, int]],
        demand: Dict[str, Dict[KitType, int]],
        incoming: Dict[str, Dict[KitType, int]],
    ) -> Dict[str, Dict[KitType, int]]:
        deficit: Dict[str, Dict[KitType, int]] = {}
        for airport, stock_map in stock.items():
            airport_deficit: Dict[KitType, int] = {}
            for kit in KitType:
                available = stock_map.get(kit, 0) + incoming.get(airport, {}).get(kit, 0)
                need = demand.get(airport, {}).get(kit, 0)
                airport_deficit[kit] = max(0, need - available)
            deficit[airport] = airport_deficit
        return deficit

    def _compute_surplus(
        self,
        stock: Dict[str, Dict[KitType, int]],
        demand: Dict[str, Dict[KitType, int]],
        incoming: Dict[str, Dict[KitType, int]],
    ) -> Dict[str, Dict[KitType, int]]:
        surplus: Dict[str, Dict[KitType, int]] = {}
        for airport, stock_map in stock.items():
            airport_surplus: Dict[KitType, int] = {}
            for kit in KitType:
                available = stock_map.get(kit, 0) + incoming.get(airport, {}).get(kit, 0)
                need = demand.get(airport, {}).get(kit, 0)
                airport_surplus[kit] = max(0, available - need)
            surplus[airport] = airport_surplus
        return surplus

    # -------------------------
    # Utilities
    # -------------------------
    def _passengers_for(self, flight: FlightInstance, kit: KitType) -> int:
        passengers = flight.actual_passengers or flight.planned_passengers or {}
        return int(passengers.get(kit, 0))

    def _priority_score(self, flight: FlightInstance, kit: KitType) -> float:
        distance = self._distance(flight)
        return distance * kit.kit_cost

    def _distance(self, flight: FlightInstance) -> float:
        return float(flight.actual_distance or flight.planned_distance or 0.0)

    def _kit_horizon_multiplier(self, kit: KitType) -> float:
        if kit == KitType.A_FIRST_CLASS:
            return self.config.horizon_multiplier_first
        if kit == KitType.B_BUSINESS:
            return self.config.horizon_multiplier_business
        if kit == KitType.C_PREMIUM_ECONOMY:
            return self.config.horizon_multiplier_premium
        return self.config.horizon_multiplier_economy

    def _should_reposition(self, flight: FlightInstance, kit: KitType, matrix: MatrixState) -> bool:
        distance = self._distance(flight)
        if distance <= self.config.reposition_distance_threshold:
            return True
        aircraft = matrix.aircraft_types.get(flight.aircraft_type_code)
        if not aircraft:
            return False
        origin_airport = matrix.airports.get(flight.origin)
        loading_cost = origin_airport.loading_cost_per_kit.get(kit, 0.0) if origin_airport else 0.0
        transport_cost = loading_cost + distance * aircraft.fuel_cost_per_kg_km * kit.weight_kg
        return transport_cost <= kit.kit_cost * self.config.cost_dominated_factor

    def _to_load_decisions(self, loads: Dict[str, Dict[KitType, int]]) -> List[KitLoadDecision]:
        decisions: List[KitLoadDecision] = []
        for flight_id, kits in loads.items():
            clean_kits = {kit: int(qty) for kit, qty in kits.items() if qty > 0}
            if clean_kits:
                decisions.append(KitLoadDecision(flight_id=flight_id, kits_per_type=clean_kits))
        return decisions

"""Time-expanded inventory matrix for airports × hours."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from rotables.models.aircraft import AircraftType
from rotables.models.airport import Airport
from rotables.models.kit_types import KitType
from rotables.state.inventory_node import InventoryNode
from rotables.state.movements import EdgeType, KitMovement
from rotables.state.time_index import MAX_HOUR, to_global_hour


@dataclass
class MatrixState:
    airports: Dict[str, Airport]
    aircraft_types: Dict[str, AircraftType]
    nodes: Dict[tuple[str, int], InventoryNode] = field(default_factory=dict)
    movements: List[KitMovement] = field(default_factory=list)

    def __post_init__(self) -> None:
        for airport in self.airports.values():
            self.nodes[(airport.code, 0)] = InventoryNode(
                airport=airport,
                global_hour=0,
                available_kits=dict(airport.initial_stock_per_kit),
            )

    def ensure_node(self, airport_code: str, hour: int) -> InventoryNode:
        key = (airport_code, hour)
        if key in self.nodes:
            return self.nodes[key]
        if hour == 0:
            airport = self.airports[airport_code]
            node = InventoryNode(airport=airport, global_hour=hour, available_kits=dict(airport.initial_stock_per_kit))
            self.nodes[key] = node
            return node
        prev = self.ensure_node(airport_code, hour - 1)
        node = prev.copy(new_hour=hour)
        self.nodes[key] = node
        return node

    def apply_movements_for_hour(self, hour: int) -> None:
        if hour > MAX_HOUR:
            return
        # propagate carry-over nodes
        for airport_code in self.airports.keys():
            self.ensure_node(airport_code, hour)
        for mv in list(self.movements):
            if mv.destination_hour == hour:
                dest = self.ensure_node(mv.destination_airport, hour)
                dest.available_kits[mv.kit_type] = dest.available_kits.get(mv.kit_type, 0) + mv.quantity
            if mv.origin_hour == hour:
                origin = self.ensure_node(mv.origin_airport, hour)
                origin.available_kits[mv.kit_type] = origin.available_kits.get(mv.kit_type, 0) - mv.quantity

    def schedule_flight_load(
        self,
        flight_id: str,
        origin: str,
        destination: str,
        aircraft_type_code: str,
        depart_day: int,
        depart_hour: int,
        arrival_day: int,
        arrival_hour: int,
        load_per_kit: Dict[KitType, int],
    ) -> Dict[KitType, int]:
        """Schedule flight and processing movements. Returns the accepted load per kit."""
        dep_t = to_global_hour(depart_day, depart_hour)
        arr_t = to_global_hour(arrival_day, arrival_hour)
        accepted: Dict[KitType, int] = {}
        aircraft = self.aircraft_types.get(aircraft_type_code)
        for kit_type, qty in load_per_kit.items():
            if qty <= 0:
                continue
            origin_node = self.ensure_node(origin, dep_t)
            available = origin_node.available_kits.get(kit_type, 0)
            cap = aircraft.kit_capacity_per_class.get(kit_type, qty) if aircraft else qty
            load_qty = min(qty, available, cap)
            if load_qty <= 0:
                continue
            accepted[kit_type] = load_qty
            flight_mv = KitMovement(
                edge_type=EdgeType.FLIGHT,
                origin_airport=origin,
                origin_hour=dep_t,
                destination_airport=destination,
                destination_hour=arr_t,
                kit_type=kit_type,
                quantity=load_qty,
                flight_id=flight_id,
                reason="flight_load",
            )
            self.movements.append(flight_mv)
            processing_time = self.airports[destination].processing_time_hours.get(kit_type, 0)
            processing_mv = KitMovement(
                edge_type=EdgeType.PROCESSING,
                origin_airport=destination,
                origin_hour=arr_t,
                destination_airport=destination,
                destination_hour=arr_t + processing_time,
                kit_type=kit_type,
                quantity=load_qty,
                flight_id=flight_id,
                reason="processing",
            )
            self.movements.append(processing_mv)
        return accepted

    def schedule_purchase(self, kit_type: KitType, quantity: int, purchase_global_hour: int) -> Optional[KitMovement]:
        if quantity <= 0:
            return None
        lead = kit_type.replacement_lead_time_hours
        mv = KitMovement(
            edge_type=EdgeType.PURCHASE,
            origin_airport="HUB1",
            origin_hour=purchase_global_hour,
            destination_airport="HUB1",
            destination_hour=purchase_global_hour + lead,
            kit_type=kit_type,
            quantity=quantity,
            flight_id=None,
            reason="purchase",
        )
        self.movements.append(mv)
        return mv

    def get_available_kits(self, airport_code: str, global_hour: int) -> Dict[KitType, int]:
        node = self.ensure_node(airport_code, global_hour)
        return dict(node.available_kits)

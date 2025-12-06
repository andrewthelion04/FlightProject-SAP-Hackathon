"""Time-expanded network representation of kit inventories."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from rotables.models.flight import FlightInstance
from rotables.models.aircraft import AircraftType
from rotables.models.airport import Airport
from rotables.models.kit_types import KitType
from rotables.state.inventory_node import InventoryNode
from rotables.state.movements import EdgeType, KitMovement
from rotables.state.time_index import MAX_HOUR


class MatrixState:
    """Owns the inventory nodes and kit movements across the planning horizon."""

    def __init__(self, airports: Dict[str, Airport], aircraft_types: Dict[str, AircraftType]) -> None:
        self.airports = airports
        self.aircraft_types = aircraft_types
        self.nodes: Dict[tuple[str, int], InventoryNode] = {}
        self.movements: List[KitMovement] = []
        self.movements_by_origin_hour: dict[int, List[KitMovement]] = defaultdict(list)
        self.movements_by_destination_hour: dict[int, List[KitMovement]] = defaultdict(list)
        self.negative_inventory: List[tuple[str, KitType, int, int]] = []

        for airport in airports.values():
            self.nodes[(airport.code, 0)] = InventoryNode(
                airport=airport,
                global_hour=0,
                available_kits=dict(airport.initial_stock_per_kit),
            )

    def _ensure_node(self, airport_code: str, global_hour: int) -> InventoryNode:
        key = (airport_code, global_hour)
        if key not in self.nodes:
            airport = self.airports[airport_code]
            if global_hour == 0:
                base = dict(airport.initial_stock_per_kit)
            else:
                prev = self._ensure_node(airport_code, global_hour - 1)
                base = dict(prev.available_kits)
            self.nodes[key] = InventoryNode(airport=airport, global_hour=global_hour, available_kits=base)
        return self.nodes[key]

    def apply_movements_for_hour(self, global_hour: int) -> None:
        """Apply all movements occurring at the given hour and roll stock forward."""
        if global_hour > MAX_HOUR:
            return

        for airport_code in self.airports:
            self._ensure_node(airport_code, global_hour)

        for movement in self.movements_by_destination_hour.get(global_hour, []):
            node = self._ensure_node(movement.destination_airport, global_hour)
            node.available_kits[movement.kit_type] = node.available_kits.get(movement.kit_type, 0) + movement.quantity

        for movement in self.movements_by_origin_hour.get(global_hour, []):
            node = self._ensure_node(movement.origin_airport, global_hour)
            node.available_kits[movement.kit_type] = node.available_kits.get(movement.kit_type, 0) - movement.quantity
            if node.available_kits[movement.kit_type] < 0:
                self.negative_inventory.append(
                    (movement.origin_airport, movement.kit_type, global_hour, movement.quantity)
                )

    def schedule_flight_load(self, flight: FlightInstance, load_per_kit: Dict[KitType, int]) -> None:
        """Create flight and processing movements while deducting inventory."""
        aircraft = self.aircraft_types.get(flight.aircraft_type_code)
        if not aircraft:
            raise ValueError(f"Unknown aircraft type: {flight.aircraft_type_code}")

        depart_hour = flight.departure_global_hour
        arrival_hour = flight.arrival_global_hour
        origin_node = self._ensure_node(flight.origin, depart_hour)

        for kit_type, requested_qty in load_per_kit.items():
            if requested_qty <= 0:
                continue
            capacity = aircraft.kit_capacity_per_class.get(kit_type, 0)
            load_qty = min(requested_qty, capacity, origin_node.available_kits.get(kit_type, 0))
            if load_qty <= 0:
                continue

            origin_node.available_kits[kit_type] = origin_node.available_kits.get(kit_type, 0) - load_qty
            flight_movement = KitMovement(
                edge_type=EdgeType.FLIGHT,
                origin_airport=flight.origin,
                origin_hour=depart_hour,
                destination_airport=flight.destination,
                destination_hour=arrival_hour,
                kit_type=kit_type,
                quantity=load_qty,
                flight_id=flight.flight_id,
                reason="flight_load",
            )
            self._register_movement(flight_movement)

            processing_time = self.airports[flight.destination].processing_time_hours.get(kit_type, 0)
            ready_hour = min(arrival_hour + processing_time, MAX_HOUR)
            processing_movement = KitMovement(
                edge_type=EdgeType.PROCESSING,
                origin_airport=flight.destination,
                origin_hour=arrival_hour,
                destination_airport=flight.destination,
                destination_hour=ready_hour,
                kit_type=kit_type,
                quantity=load_qty,
                flight_id=flight.flight_id,
                reason="turnaround_processing",
            )
            self._register_movement(processing_movement)

    def schedule_purchase(self, kit_type: KitType, quantity: int, purchase_global_hour: int) -> None:
        """Schedule a kit purchase at the hub with lead time."""
        if quantity <= 0:
            return
        hub_code = "HUB1"
        if hub_code not in self.airports or not self.airports[hub_code].is_hub:
            raise ValueError("Hub airport HUB1 not configured.")

        ready_hour = min(purchase_global_hour + kit_type.replacement_lead_time_hours, MAX_HOUR)
        movement = KitMovement(
            edge_type=EdgeType.PURCHASE,
            origin_airport=hub_code,
            origin_hour=purchase_global_hour,
            destination_airport=hub_code,
            destination_hour=ready_hour,
            kit_type=kit_type,
            quantity=quantity,
            flight_id=None,
            reason="purchase",
        )
        self._register_movement(movement)

    def _register_movement(self, movement: KitMovement) -> None:
        self.movements.append(movement)
        self.movements_by_origin_hour[movement.origin_hour].append(movement)
        self.movements_by_destination_hour[movement.destination_hour].append(movement)

    def get_available_kits(self, airport_code: str, global_hour: int) -> Dict[KitType, int]:
        """Return the projected clean kits at the start of the given hour."""
        node = self._ensure_node(airport_code, global_hour)
        return dict(node.available_kits)

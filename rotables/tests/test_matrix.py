"""Simple matrix state sanity checks."""
from __future__ import annotations

import unittest

from rotables.models.aircraft import AircraftType
from rotables.models.airport import Airport
from rotables.models.flight import FlightInstance
from rotables.models.kit_types import KitType
from rotables.state.matrix_state import MatrixState


def _default_kit_dict(value: int) -> dict[KitType, int]:
    return {kit: value for kit in KitType}


class MatrixStateTest(unittest.TestCase):
    def setUp(self) -> None:
        capacity = _default_kit_dict(100)
        initial = {kit: 0 for kit in KitType}
        initial[KitType.D_ECONOMY] = 10
        costs = {kit: 0.0 for kit in KitType}
        processing_time = {kit: 1 for kit in KitType}

        self.hub = Airport(
            code="HUB1",
            name="Hub",
            is_hub=True,
            capacity_per_kit=capacity,
            initial_stock_per_kit=initial,
            loading_cost_per_kit=costs,
            processing_cost_per_kit=costs,
            processing_time_hours=processing_time,
        )
        self.out = Airport(
            code="OUT1",
            name="Out",
            is_hub=False,
            capacity_per_kit=capacity,
            initial_stock_per_kit=_default_kit_dict(0),
            loading_cost_per_kit=costs,
            processing_cost_per_kit=costs,
            processing_time_hours=processing_time,
        )
        aircraft = AircraftType(
            code="T1",
            fuel_cost_per_kg_km=0.1,
            passenger_capacity_per_class=_default_kit_dict(200),
            kit_capacity_per_class=_default_kit_dict(50),
        )
        self.matrix = MatrixState(airports={self.hub.code: self.hub, self.out.code: self.out}, aircraft_types={"T1": aircraft})

    def test_flight_load_and_processing(self) -> None:
        flight = FlightInstance(
            flight_id="F1",
            flight_number="F1",
            origin="HUB1",
            destination="OUT1",
            aircraft_type_code="T1",
            planned_departure=(0, 0),
            planned_arrival=(0, 2),
            planned_distance=100.0,
            planned_passengers={KitType.D_ECONOMY: 3},
        )

        # Hour 0: apply initial movements and schedule load
        self.matrix.apply_movements_for_hour(0)
        self.matrix.schedule_flight_load(flight, {KitType.D_ECONOMY: 3})
        hub_stock_now = self.matrix.get_available_kits("HUB1", 0)[KitType.D_ECONOMY]
        self.assertEqual(hub_stock_now, 7)

        # Hour 1: stock should carry with deduction
        self.matrix.apply_movements_for_hour(1)
        hub_stock_hour1 = self.matrix.get_available_kits("HUB1", 1)[KitType.D_ECONOMY]
        self.assertEqual(hub_stock_hour1, 7)

        # Hour 2: kits land and enter processing (not yet available)
        self.matrix.apply_movements_for_hour(2)
        out_stock_hour2 = self.matrix.get_available_kits("OUT1", 2)[KitType.D_ECONOMY]
        self.assertEqual(out_stock_hour2, 0)

        # Hour 3: kits become available after processing time
        self.matrix.apply_movements_for_hour(3)
        out_stock_hour3 = self.matrix.get_available_kits("OUT1", 3)[KitType.D_ECONOMY]
        self.assertEqual(out_stock_hour3, 3)


if __name__ == "__main__":
    unittest.main()


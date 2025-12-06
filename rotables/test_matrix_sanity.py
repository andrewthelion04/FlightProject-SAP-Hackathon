"""Simple sanity checks for MatrixState flows."""
from rotables.models.aircraft import AircraftType
from rotables.models.airport import Airport
from rotables.models.kit_types import KitType
from rotables.state.matrix_state import MatrixState


def test_simple_flow() -> None:
    hub = Airport(
        code="HUB1",
        is_hub=True,
        capacity_per_kit={kt: 100 for kt in KitType},
        initial_stock_per_kit={kt: 10 for kt in KitType},
        loading_cost_per_kit={kt: 1.0 for kt in KitType},
        processing_cost_per_kit={kt: 1.0 for kt in KitType},
        processing_time_hours={kt: 2 for kt in KitType},
    )
    out = Airport(
        code="A1",
        is_hub=False,
        capacity_per_kit={kt: 100 for kt in KitType},
        initial_stock_per_kit={kt: 0 for kt in KitType},
        loading_cost_per_kit={kt: 1.0 for kt in KitType},
        processing_cost_per_kit={kt: 1.0 for kt in KitType},
        processing_time_hours={kt: 1 for kt in KitType},
    )
    ac = AircraftType(
        code="X",
        fuel_cost_per_km=0.1,
        passenger_capacity_per_class={kt: 50 for kt in KitType},
        kit_capacity_per_class={kt: 50 for kt in KitType},
    )
    matrix = MatrixState(airports={"HUB1": hub, "A1": out}, aircraft_types={"X": ac})
    accepted = matrix.schedule_flight_load(
        flight_id="F1",
        origin="HUB1",
        destination="A1",
        aircraft_type_code="X",
        depart_day=0,
        depart_hour=0,
        arrival_day=0,
        arrival_hour=1,
        load_per_kit={KitType.D_ECONOMY: 5},
    )
    assert accepted[KitType.D_ECONOMY] == 5
    matrix.apply_movements_for_hour(0)
    assert matrix.get_available_kits("HUB1", 0)[KitType.D_ECONOMY] == 5
    matrix.apply_movements_for_hour(1)
    assert matrix.get_available_kits("A1", 1)[KitType.D_ECONOMY] == 5
    matrix.apply_movements_for_hour(2)
    matrix.apply_movements_for_hour(3)
    assert matrix.get_available_kits("A1", 3)[KitType.D_ECONOMY] == 5


if __name__ == "__main__":
    test_simple_flow()
    print("MatrixState sanity test passed.")

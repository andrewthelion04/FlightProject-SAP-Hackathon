"""Flight instance model reflecting live events."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from .kit_types import KitType
from rotables.state.time_index import to_global_hour


def _grab_int(container: dict, key: str, default: Optional[int] = None) -> Optional[int]:
    if not isinstance(container, dict):
        return default
    value = container.get(key, default)
    try:
        return int(value)
    except Exception:
        return default


def _parse_reference_hour(obj: dict) -> tuple[Optional[int], Optional[int]]:
    if not isinstance(obj, dict):
        return None, None
    day = _grab_int(obj, "day", None)
    hour = _grab_int(obj, "hour", None)
    return day, hour


@dataclass
class FlightInstance:
    flight_id: str
    flight_number: str
    origin: str
    destination: str
    aircraft_type_code: Optional[str] = None
    planned_departure: tuple[Optional[int], Optional[int]] = (None, None)
    planned_arrival: tuple[Optional[int], Optional[int]] = (None, None)
    actual_departure: tuple[Optional[int], Optional[int]] = (None, None)
    actual_arrival: tuple[Optional[int], Optional[int]] = (None, None)
    planned_distance: Optional[float] = None
    actual_distance: Optional[float] = None
    planned_passengers: Dict[KitType, int] = field(default_factory=dict)
    actual_passengers: Dict[KitType, int] = field(default_factory=dict)
    status: str = "SCHEDULED"

    def update_from_event(self, event: Dict) -> None:
        event_type = str(event.get("eventType") or event.get("status") or self.status).upper()
        self.status = event_type
        self.flight_number = str(event.get("flightNumber") or self.flight_number)
        self.aircraft_type_code = event.get("aircraftType") or self.aircraft_type_code
        self.origin = event.get("originAirport") or self.origin
        self.destination = event.get("destinationAirport") or self.destination

        # Reference hours
        dep_day, dep_hour = _parse_reference_hour(event.get("departure", {}))
        arr_day, arr_hour = _parse_reference_hour(event.get("arrival", {}))
        if dep_day is not None and dep_hour is not None:
            if event_type == "CHECKED_IN":
                self.actual_departure = (dep_day, dep_hour)
            else:
                self.planned_departure = (dep_day, dep_hour)
        if arr_day is not None and arr_hour is not None:
            if event_type == "LANDED":
                self.actual_arrival = (arr_day, arr_hour)
            else:
                self.planned_arrival = (arr_day, arr_hour)

        # Distances: scheduled for SCHEDULED/CHECKED_IN, actual for LANDED
        distance_value = event.get("distance")
        if distance_value is not None:
            try:
                distance_value = float(distance_value)
            except Exception:
                distance_value = None
        if event_type == "LANDED":
            if distance_value is not None:
                self.actual_distance = distance_value
        else:
            if distance_value is not None:
                self.planned_distance = distance_value

        passengers_obj = event.get("passengers", {})
        if isinstance(passengers_obj, dict):
            mapped = {}
            for kit_type in KitType:
                val = passengers_obj.get(kit_type.passenger_key, 0)
                try:
                    mapped[kit_type] = int(val)
                except Exception:
                    mapped[kit_type] = 0
            if event_type == "CHECKED_IN":
                self.actual_passengers = mapped
            elif event_type == "LANDED":
                self.actual_passengers = mapped or self.actual_passengers
            else:
                self.planned_passengers = mapped

    def departure_global_hour(self) -> Optional[int]:
        day, hour = self.actual_departure if any(self.actual_departure) else self.planned_departure
        if day is None or hour is None:
            return None
        return to_global_hour(day, hour)

    def arrival_global_hour(self) -> Optional[int]:
        day, hour = self.actual_arrival if any(self.actual_arrival) else self.planned_arrival
        if day is None or hour is None:
            return None
        return to_global_hour(day, hour)

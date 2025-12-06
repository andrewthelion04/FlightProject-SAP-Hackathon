"""Flight plan and live instance models."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from rotables.config import CSV_DELIMITER

from rotables.state.time_index import to_global_hour

from .kit_types import KitType, _PASSENGER_KEY_TO_TYPE


@dataclass
class FlightPlanEntry:
    """Represents one scheduled flight entry from the static plan."""

    origin: str
    destination: str
    scheduled_departure_hour: int
    scheduled_arrival_hour: int
    arrival_next_day: bool
    distance_km: float
    days_of_week: List[int]
    aircraft_type_code: Optional[str] = None
    flight_number: Optional[str] = None


def load_flight_plan_from_csv(path: Path) -> List[FlightPlanEntry]:
    """Parse flight_plan.csv into FlightPlanEntry objects."""
    entries: List[FlightPlanEntry] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=CSV_DELIMITER)
        for row in reader:
            origin = row["depart_code"]
            destination = row["arrival_code"]
            scheduled_hour = int(row.get("scheduled_hour", 0))
            scheduled_arrival_hour = int(row.get("scheduled_arrival_hour", 0))
            arrival_next_day = bool(int(row.get("arrival_next_day", 0)))
            distance_km = float(row.get("distance_km", 0.0) or 0.0)

            days_of_week: List[int] = []
            for idx, day_name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
                value = row.get(day_name, "0")
                if value and int(value):
                    days_of_week.append(idx)

            entries.append(
                FlightPlanEntry(
                    origin=origin,
                    destination=destination,
                    scheduled_departure_hour=scheduled_hour,
                    scheduled_arrival_hour=scheduled_arrival_hour,
                    arrival_next_day=arrival_next_day,
                    distance_km=distance_km,
                    days_of_week=days_of_week,
                    aircraft_type_code=row.get("aircraft_type_code") or None,
                    flight_number=row.get("flight_number") or None,
                )
            )
    return entries


class FlightStatus(Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    LANDED = "LANDED"


def _passenger_dict(event_passengers: Dict[str, int]) -> Dict[KitType, int]:
    passengers: Dict[KitType, int] = {}
    for key, kit in _PASSENGER_KEY_TO_TYPE.items():
        passengers[kit] = int(event_passengers.get(key, 0))
    return passengers


@dataclass
class FlightInstance:
    """Mutable representation of a live flight across the session."""

    flight_id: str
    flight_number: str
    origin: str
    destination: str
    aircraft_type_code: str
    planned_departure: tuple[int, int]
    planned_arrival: tuple[int, int]
    planned_distance: float
    planned_passengers: Dict[KitType, int] = field(default_factory=dict)
    actual_departure: Optional[tuple[int, int]] = None
    actual_arrival: Optional[tuple[int, int]] = None
    actual_distance: Optional[float] = None
    actual_passengers: Dict[KitType, int] = field(default_factory=dict)
    status: FlightStatus = FlightStatus.SCHEDULED

    def update_from_event(self, event_json: Dict) -> None:
        """Update fields from a flight event payload."""
        event_type = event_json.get("eventType", "SCHEDULED")
        self.status = FlightStatus(event_type)
        self.flight_number = event_json.get("flightNumber", self.flight_number)
        self.origin = event_json.get("originAirport", self.origin)
        self.destination = event_json.get("destinationAirport", self.destination)
        self.aircraft_type_code = event_json.get("aircraftType", self.aircraft_type_code)
        distance = event_json.get("distance")
        if distance is not None:
            self.actual_distance = float(distance)

        passengers_json = event_json.get("passengers") or {}
        passengers = _passenger_dict(passengers_json)
        if passengers:
            if self.status == FlightStatus.SCHEDULED:
                self.planned_passengers = passengers
            else:
                self.actual_passengers = passengers

        departure = event_json.get("departure")
        arrival = event_json.get("arrival")
        if departure:
            time_tuple = (int(departure.get("day", 0)), int(departure.get("hour", 0)))
            if self.status == FlightStatus.SCHEDULED:
                self.planned_departure = time_tuple
            else:
                self.actual_departure = time_tuple
        if arrival:
            time_tuple = (int(arrival.get("day", 0)), int(arrival.get("hour", 0)))
            if self.status == FlightStatus.LANDED:
                self.actual_arrival = time_tuple
            else:
                self.planned_arrival = time_tuple

    @property
    def departure_global_hour(self) -> int:
        time_tuple = self.actual_departure or self.planned_departure
        return to_global_hour(*time_tuple)

    @property
    def arrival_global_hour(self) -> int:
        time_tuple = self.actual_arrival or self.planned_arrival
        return to_global_hour(*time_tuple)

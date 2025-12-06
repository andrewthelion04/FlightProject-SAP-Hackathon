"""Domain models with defensive parsing for the Flight Rotables optimizer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


CLASS_KEYS = ["first", "business", "premiumEconomy", "economy"]


def _safe_int(value, default: Optional[int] = 0) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Airport:
    code: str
    stocks: Dict[str, int]
    processing_times: Dict[str, int] = field(default_factory=dict)
    capacities: Dict[str, int] = field(default_factory=dict)
    reserved: Dict[str, int] = field(default_factory=dict)

    def available(self, class_name: str) -> int:
        stock = self.stocks.get(class_name, 0)
        reserved = self.reserved.get(class_name, 0)
        return max(stock - reserved, 0)

    def reserve(self, class_name: str, quantity: int) -> int:
        if quantity <= 0:
            return 0
        available_now = self.available(class_name)
        reserved_qty = min(quantity, available_now)
        if reserved_qty > 0:
            self.reserved[class_name] = self.reserved.get(class_name, 0) + reserved_qty
        return reserved_qty

    def commit_departure(self, kits: Dict[str, int]) -> None:
        for class_name, qty in kits.items():
            qty = _safe_int(qty, 0)
            if qty <= 0:
                continue
            reserved_qty = self.reserved.get(class_name, 0)
            consume_from_reserved = min(reserved_qty, qty)
            if consume_from_reserved:
                self.reserved[class_name] = reserved_qty - consume_from_reserved
            current = self.stocks.get(class_name, 0)
            self.stocks[class_name] = current - qty

    def update_stock(self, class_name: str, delta: int) -> None:
        self.stocks[class_name] = self.stocks.get(class_name, 0) + _safe_int(delta, 0)

    def ensure_keys(self) -> None:
        for key in CLASS_KEYS:
            self.stocks.setdefault(key, 0)
            self.reserved.setdefault(key, 0)


@dataclass
class Flight:
    id: str
    flight_number: str
    origin: str
    destination: str
    passengers: Dict[str, int]
    status: str
    scheduled_day: Optional[int] = None
    scheduled_hour: Optional[int] = None
    aircraft_type: Optional[str] = None
    planned_distance: Optional[float] = None
    actual_distance: Optional[float] = None

    @classmethod
    def from_json(cls, data: Dict) -> Optional["Flight"]:
        if not isinstance(data, dict):
            return None

        def grab(keys, container, default=0):
            for key in keys:
                if key in container and container[key] is not None:
                    return container[key]
            return default

        flight_id = data.get("id") or data.get("flightId")
        if not flight_id:
            return None

        flight_number = data.get("flightNumber") or data.get("number") or data.get("code") or flight_id
        origin = (
            data.get("originAirport")
            or data.get("origin")
            or data.get("from")
            or data.get("depart_code")
            or data.get("departure")
        )
        destination = (
            data.get("destinationAirport")
            or data.get("destination")
            or data.get("to")
            or data.get("arrival_code")
            or data.get("arrival")
        )
        passenger_blob = data.get("passengers") if isinstance(data.get("passengers"), dict) else data

        passengers = {
            "first": _safe_int(grab(["firstClass", "first", "fc", "FIRST"], passenger_blob, 0)),
            "business": _safe_int(grab(["businessClass", "business", "bc", "BUSINESS"], passenger_blob, 0)),
            "premiumEconomy": _safe_int(
                grab(["premiumEconomy", "premium", "pe", "premium_class"], passenger_blob, 0)
            ),
            "economy": _safe_int(grab(["economy", "eco", "ec", "ECONOMY"], passenger_blob, 0)),
        }

        status = str(data.get("eventType") or data.get("status") or "SCHEDULED").upper()
        scheduled_day = data.get("scheduledDay") or data.get("departureDay")
        scheduled_hour = (
            data.get("scheduledHour")
            or data.get("scheduledDepartureHour")
            or data.get("departureHour")
            or data.get("plannedDepartureHour")
        )
        aircraft_type = data.get("aircraftType") or data.get("aircraft")

        scheduled_distance = _safe_float(
            grab(["scheduledDistance", "plannedDistance", "distance"], data, None), None
        )
        actual_distance = _safe_float(grab(["actualDistance", "actual_distance"], data, None), None)

        # API contract: distance is scheduled for SCHEDULED/CHECKED-IN and actual for LANDED.
        distance_value = _safe_float(data.get("distance"), None)
        if status == "LANDED":
            actual_distance = actual_distance if actual_distance is not None else distance_value
        else:
            scheduled_distance = scheduled_distance if scheduled_distance is not None else distance_value

        return cls(
            id=str(flight_id),
            flight_number=str(flight_number),
            origin=str(origin) if origin else "",
            destination=str(destination) if destination else "",
            passengers=passengers,
            status=status,
            scheduled_day=_safe_int(scheduled_day, None) if scheduled_day is not None else None,
            scheduled_hour=_safe_int(scheduled_hour, None) if scheduled_hour is not None else None,
            aircraft_type=aircraft_type,
            planned_distance=scheduled_distance,
            actual_distance=actual_distance,
        )

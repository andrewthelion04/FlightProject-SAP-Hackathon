"""Domain contracts and serialization helpers for the refactored rotables engine.

This module defines *only* data shapes that cross process boundaries or travel
between subsystems (API <-> engine, strategy <-> state, etc.).
Every class here focuses on explicit field names and clear JSON translation so
callers do not need to remember backend-specific key casing.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict
from uuid import UUID


class FlightEventKind(Enum):
    """Enumeration mirroring backend event types. Values must match API payloads."""

    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    LANDED = "LANDED"


@dataclass
class CabinKits:
    """Quantity of ready-to-use kits per cabin."""

    first_class: int = 0
    business_class: int = 0
    premium_economy: int = 0
    economy: int = 0

    def to_wire(self) -> Dict:
        """Represent the object in the exact shape expected by the HTTP API."""
        return {
            "first": self.first_class,
            "business": self.business_class,
            "premiumEconomy": self.premium_economy,
            "economy": self.economy,
        }

    @staticmethod
    def from_wire(payload: Optional[Dict]):
        if payload is None:
            return CabinKits()
        return CabinKits(
            first_class=payload.get("first", 0),
            business_class=payload.get("business", 0),
            premium_economy=payload.get("premiumEconomy", 0),
            economy=payload.get("economy", 0),
        )


@dataclass
class FlightLoadPlan:
    """Decision for how many kits to place on a single flight."""

    flight_id: UUID
    planned_kits: CabinKits

    def to_wire(self) -> Dict:
        return {
            "flightId": str(self.flight_id),
            "loadedKits": self.planned_kits.to_wire(),
        }


@dataclass
class RoundInstruction:
    """Full decision package sent to the backend for one hour."""

    day: int
    hour: int
    load_plans: List[FlightLoadPlan] = field(default_factory=list)
    procurement: CabinKits = field(default_factory=CabinKits)

    def to_wire(self) -> Dict:
        return {
            "day": self.day,
            "hour": self.hour,
            "flightLoads": [plan.to_wire() for plan in self.load_plans],
            "kitPurchasingOrders": self.procurement.to_wire(),
        }


@dataclass
class ReferenceTime:
    day: int
    hour: int

    @staticmethod
    def from_wire(payload: Dict):
        return ReferenceTime(day=payload["day"], hour=payload["hour"])


@dataclass
class FlightUpdate:
    event_type: FlightEventKind
    flight_number: str
    flight_id: UUID
    origin_airport: str
    destination_airport: str
    departure: ReferenceTime
    arrival: ReferenceTime
    passengers: CabinKits
    aircraft_type: str

    @staticmethod
    def from_wire(payload: Dict):
        return FlightUpdate(
            event_type=FlightEventKind(payload["eventType"]),
            flight_number=payload["flightNumber"],
            flight_id=UUID(payload["flightId"]),
            origin_airport=payload["originAirport"],
            destination_airport=payload["destinationAirport"],
            departure=ReferenceTime.from_wire(payload["departure"]),
            arrival=ReferenceTime.from_wire(payload["arrival"]),
            passengers=CabinKits.from_wire(payload.get("passengers")),
            aircraft_type=payload["aircraftType"],
        )


@dataclass
class PenaltyNotice:
    code: str
    flight_id: Optional[UUID]
    flight_number: Optional[str]
    issued_day: int
    issued_hour: int
    amount: float
    reason: str

    @staticmethod
    def from_wire(payload: Dict):
        return PenaltyNotice(
            code=payload["code"],
            flight_id=UUID(payload["flightId"]) if payload.get("flightId") else None,
            flight_number=payload.get("flightNumber"),
            issued_day=payload["issuedDay"],
            issued_hour=payload["issuedHour"],
            amount=payload["penalty"],
            reason=payload["reason"],
        )


@dataclass
class RoundOutcome:
    day: int
    hour: int
    flight_events: List[FlightUpdate]
    penalties: List[PenaltyNotice]
    total_cost: float

    @staticmethod
    def from_wire(payload: Dict):
        return RoundOutcome(
            day=payload["day"],
            hour=payload["hour"],
            flight_events=[FlightUpdate.from_wire(evt) for evt in (payload.get("flightUpdates") or [])],
            penalties=[PenaltyNotice.from_wire(p) for p in (payload.get("penalties") or [])],
            total_cost=payload["totalCost"],
        )

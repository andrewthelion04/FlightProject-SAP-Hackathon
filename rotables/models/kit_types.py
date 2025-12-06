"""Kit type definitions and helper mappings."""
from __future__ import annotations

from enum import Enum
from typing import ClassVar, Dict


class KitType(Enum):
    """Enumeration of kit types with static attributes."""

    A_FIRST_CLASS = ("first", 5.0, 200.0, 48)
    B_BUSINESS = ("business", 3.0, 150.0, 36)
    C_PREMIUM_ECONOMY = ("premiumEconomy", 2.5, 100.0, 24)
    D_ECONOMY = ("economy", 1.5, 50.0, 12)

    _passenger_key: str
    _weight_kg: float
    _kit_cost: float
    _replacement_lead_time_hours: int

    def __init__(self, passenger_key: str, weight_kg: float, kit_cost: float, replacement_lead_time_hours: int) -> None:
        self._passenger_key = passenger_key
        self._weight_kg = weight_kg
        self._kit_cost = kit_cost
        self._replacement_lead_time_hours = replacement_lead_time_hours

    @property
    def passenger_key(self) -> str:
        """Return the JSON passenger/class key used by the backend."""
        return self._passenger_key

    @property
    def weight_kg(self) -> float:
        return self._weight_kg

    @property
    def kit_cost(self) -> float:
        return self._kit_cost

    @property
    def replacement_lead_time_hours(self) -> int:
        return self._replacement_lead_time_hours

    @classmethod
    def from_passenger_key(cls, key: str) -> "KitType":
        """Map a passenger key from API payloads to a KitType."""
        try:
            return _PASSENGER_KEY_TO_TYPE[key]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unknown passenger key: {key}") from exc


_PASSENGER_KEY_TO_TYPE: Dict[str, KitType] = {kit.passenger_key: kit for kit in KitType}
PASSENGER_KEYS_BY_TYPE: Dict[KitType, str] = {kit: kit.passenger_key for kit in KitType}


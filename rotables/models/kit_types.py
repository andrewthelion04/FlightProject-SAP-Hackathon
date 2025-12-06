"""Kit type definitions mirroring the Java enum."""
from __future__ import annotations

from enum import Enum
from typing import Dict


class KitType(Enum):
    A_FIRST_CLASS = ("first", 5.0, 200.0, 48)
    B_BUSINESS = ("business", 3.0, 150.0, 36)
    C_PREMIUM_ECONOMY = ("premiumEconomy", 2.5, 100.0, 24)
    D_ECONOMY = ("economy", 1.5, 50.0, 12)

    def __init__(self, passenger_key: str, weight_kg: float, kit_cost: float, replacement_lead_time_hours: int):
        self.passenger_key = passenger_key
        self.weight_kg_value = weight_kg
        self.kit_cost_value = kit_cost
        self.replacement_lead_time_hours_value = replacement_lead_time_hours

    @property
    def weight_kg(self) -> float:
        return self.weight_kg_value

    @property
    def cost(self) -> float:
        return self.kit_cost_value

    @property
    def replacement_lead_time_hours(self) -> int:
        return self.replacement_lead_time_hours_value

    @classmethod
    def from_passenger_key(cls, key: str) -> "KitType":
        for kt in cls:
            if kt.passenger_key == key:
                return kt
        raise KeyError(f"Unknown passenger class key: {key}")

    @classmethod
    def passenger_key_map(cls) -> Dict[str, "KitType"]:
        return {kt.passenger_key: kt for kt in cls}

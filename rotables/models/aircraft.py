"""Aircraft type model and CSV loading utility."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from rotables.config import CSV_DELIMITER

from .kit_types import KitType


@dataclass
class AircraftType:
    code: str
    fuel_cost_per_kg_km: float
    passenger_capacity_per_class: Dict[KitType, int]
    kit_capacity_per_class: Dict[KitType, int]


def load_aircraft_types_from_csv(path: Path) -> Dict[str, AircraftType]:
    """Read aircraft_types.csv into AircraftType objects keyed by type code."""
    aircraft_types: Dict[str, AircraftType] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=CSV_DELIMITER)
        for row in reader:
            code = row["type_code"]
            fuel_cost = float(row.get("cost_per_kg_per_km", 0.0) or 0.0)

            def _to_int(value: str | None) -> int:
                return int(float(value)) if value not in (None, "", "null") else 0

            passenger_capacity_per_class = {
                KitType.A_FIRST_CLASS: _to_int(row.get("first_class_seats")),
                KitType.B_BUSINESS: _to_int(row.get("business_seats")),
                KitType.C_PREMIUM_ECONOMY: _to_int(row.get("premium_economy_seats")),
                KitType.D_ECONOMY: _to_int(row.get("economy_seats")),
            }
            kit_capacity_per_class = {
                KitType.A_FIRST_CLASS: _to_int(row.get("first_class_kits_capacity")),
                KitType.B_BUSINESS: _to_int(row.get("business_kits_capacity")),
                KitType.C_PREMIUM_ECONOMY: _to_int(row.get("premium_economy_kits_capacity")),
                KitType.D_ECONOMY: _to_int(row.get("economy_kits_capacity")),
            }
            aircraft_types[code] = AircraftType(
                code=code,
                fuel_cost_per_kg_km=fuel_cost,
                passenger_capacity_per_class=passenger_capacity_per_class,
                kit_capacity_per_class=kit_capacity_per_class,
            )
    return aircraft_types

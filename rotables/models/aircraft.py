"""Aircraft type model and CSV loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import pandas as pd

from config import CSV_DELIMITER
from .kit_types import KitType


@dataclass
class AircraftType:
    code: str
    fuel_cost_per_km: float
    passenger_capacity_per_class: Dict[KitType, int]
    kit_capacity_per_class: Dict[KitType, int]


def load_aircraft_types(csv_path: Path) -> Dict[str, AircraftType]:
    df = pd.read_csv(csv_path, delimiter=CSV_DELIMITER)
    aircraft: Dict[str, AircraftType] = {}
    for _, row in df.iterrows():
        code = str(row["type_code"])
        passenger_capacity = {
            KitType.A_FIRST_CLASS: int(row.get("first_class_seats", 0)),
            KitType.B_BUSINESS: int(row.get("business_seats", 0)),
            KitType.C_PREMIUM_ECONOMY: int(row.get("premium_economy_seats", 0)),
            KitType.D_ECONOMY: int(row.get("economy_seats", 0)),
        }
        kit_capacity = {
            KitType.A_FIRST_CLASS: int(row.get("first_class_kits_capacity", 0)),
            KitType.B_BUSINESS: int(row.get("business_kits_capacity", 0)),
            KitType.C_PREMIUM_ECONOMY: int(row.get("premium_economy_kits_capacity", 0)),
            KitType.D_ECONOMY: int(row.get("economy_kits_capacity", 0)),
        }

        aircraft[code] = AircraftType(
            code=code,
            fuel_cost_per_km=float(row.get("cost_per_kg_per_km", 0.0)),
            passenger_capacity_per_class=passenger_capacity,
            kit_capacity_per_class=kit_capacity,
        )
    return aircraft

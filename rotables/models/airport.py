"""Airport model and CSV loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import pandas as pd

from config import CSV_DELIMITER
from .kit_types import KitType

HUB_CODE = "HUB1"


@dataclass
class Airport:
    code: str
    is_hub: bool
    capacity_per_kit: Dict[KitType, int]
    initial_stock_per_kit: Dict[KitType, int]
    loading_cost_per_kit: Dict[KitType, float]
    processing_cost_per_kit: Dict[KitType, float]
    processing_time_hours: Dict[KitType, int]


def load_airports(csv_path: Path) -> Dict[str, Airport]:
    """Load airports from the provided CSV path."""
    df = pd.read_csv(csv_path, delimiter=CSV_DELIMITER)
    airports: Dict[str, Airport] = {}
    for _, row in df.iterrows():
        code = str(row["code"])
        is_hub = code.upper() == HUB_CODE
        capacity = {
            KitType.A_FIRST_CLASS: int(row.get("capacity_fc", 0)),
            KitType.B_BUSINESS: int(row.get("capacity_bc", 0)),
            KitType.C_PREMIUM_ECONOMY: int(row.get("capacity_pe", 0)),
            KitType.D_ECONOMY: int(row.get("capacity_ec", 0)),
        }
        initial_stock = {
            KitType.A_FIRST_CLASS: int(row.get("initial_fc_stock", 0)),
            KitType.B_BUSINESS: int(row.get("initial_bc_stock", 0)),
            KitType.C_PREMIUM_ECONOMY: int(row.get("initial_pe_stock", 0)),
            KitType.D_ECONOMY: int(row.get("initial_ec_stock", 0)),
        }
        loading_cost = {
            KitType.A_FIRST_CLASS: float(row.get("first_loading_cost", 0.0)),
            KitType.B_BUSINESS: float(row.get("business_loading_cost", 0.0)),
            KitType.C_PREMIUM_ECONOMY: float(row.get("premium_economy_loading_cost", 0.0)),
            KitType.D_ECONOMY: float(row.get("economy_loading_cost", 0.0)),
        }
        processing_cost = {
            KitType.A_FIRST_CLASS: float(row.get("first_processing_cost", 0.0)),
            KitType.B_BUSINESS: float(row.get("business_processing_cost", 0.0)),
            KitType.C_PREMIUM_ECONOMY: float(row.get("premium_economy_processing_cost", 0.0)),
            KitType.D_ECONOMY: float(row.get("economy_processing_cost", 0.0)),
        }
        processing_time = {
            KitType.A_FIRST_CLASS: int(row.get("first_processing_time", 0)),
            KitType.B_BUSINESS: int(row.get("business_processing_time", 0)),
            KitType.C_PREMIUM_ECONOMY: int(row.get("premium_economy_processing_time", 0)),
            KitType.D_ECONOMY: int(row.get("economy_processing_time", 0)),
        }

        airport = Airport(
            code=code,
            is_hub=is_hub,
            capacity_per_kit=capacity,
            initial_stock_per_kit=initial_stock,
            loading_cost_per_kit=loading_cost,
            processing_cost_per_kit=processing_cost,
            processing_time_hours=processing_time,
        )
        airports[code] = airport
    return airports

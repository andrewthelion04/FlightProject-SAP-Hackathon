"""Airport model and CSV loading utilities."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from rotables.config import CSV_DELIMITER

from .kit_types import KitType


COLUMN_MAP = {
    "processing_time": {
        KitType.A_FIRST_CLASS: "first_processing_time",
        KitType.B_BUSINESS: "business_processing_time",
        KitType.C_PREMIUM_ECONOMY: "premium_economy_processing_time",
        KitType.D_ECONOMY: "economy_processing_time",
    },
    "processing_cost": {
        KitType.A_FIRST_CLASS: "first_processing_cost",
        KitType.B_BUSINESS: "business_processing_cost",
        KitType.C_PREMIUM_ECONOMY: "premium_economy_processing_cost",
        KitType.D_ECONOMY: "economy_processing_cost",
    },
    "loading_cost": {
        KitType.A_FIRST_CLASS: "first_loading_cost",
        KitType.B_BUSINESS: "business_loading_cost",
        KitType.C_PREMIUM_ECONOMY: "premium_economy_loading_cost",
        KitType.D_ECONOMY: "economy_loading_cost",
    },
    "stock": {
        KitType.A_FIRST_CLASS: "initial_fc_stock",
        KitType.B_BUSINESS: "initial_bc_stock",
        KitType.C_PREMIUM_ECONOMY: "initial_pe_stock",
        KitType.D_ECONOMY: "initial_ec_stock",
    },
    "capacity": {
        KitType.A_FIRST_CLASS: "capacity_fc",
        KitType.B_BUSINESS: "capacity_bc",
        KitType.C_PREMIUM_ECONOMY: "capacity_pe",
        KitType.D_ECONOMY: "capacity_ec",
    },
}


@dataclass
class Airport:
    """Represents an airport with capacity, cost, and processing characteristics."""

    code: str
    name: str
    is_hub: bool
    capacity_per_kit: Dict[KitType, int]
    initial_stock_per_kit: Dict[KitType, int]
    loading_cost_per_kit: Dict[KitType, float]
    processing_cost_per_kit: Dict[KitType, float]
    processing_time_hours: Dict[KitType, int]


def _build_kit_map(row: Dict[str, str], section: str) -> Dict[KitType, float | int]:
    result: Dict[KitType, float | int] = {}

    def _to_number(value: str | None) -> float:
        if value in (None, "", "null"):
            return 0.0
        return float(value)

    column_mapping = COLUMN_MAP.get(section, {})
    for kit, column_name in column_mapping.items():
        value = row.get(column_name)
        if section in {"processing_time", "stock", "capacity"}:
            result[kit] = int(_to_number(value))
        else:
            result[kit] = float(_to_number(value))
    return result


def load_airports_from_csv(path: Path) -> Dict[str, Airport]:
    """Parse airports_with_stocks.csv into Airport objects keyed by airport code."""
    airports: Dict[str, Airport] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=CSV_DELIMITER)
        for row in reader:
            code = row["code"]
            name = row.get("name", code)
            is_hub = code.upper() == "HUB1"
            processing_time = _build_kit_map(row, "processing_time")
            processing_cost = _build_kit_map(row, "processing_cost")
            loading_cost = _build_kit_map(row, "loading_cost")
            initial_stock = _build_kit_map(row, "stock")
            capacity = _build_kit_map(row, "capacity")

            airport = Airport(
                code=code,
                name=name,
                is_hub=is_hub,
                capacity_per_kit={kit: int(capacity.get(kit, 0)) for kit in KitType},
                initial_stock_per_kit={kit: int(initial_stock.get(kit, 0)) for kit in KitType},
                loading_cost_per_kit={kit: float(loading_cost.get(kit, 0.0)) for kit in KitType},
                processing_cost_per_kit={kit: float(processing_cost.get(kit, 0.0)) for kit in KitType},
                processing_time_hours={kit: int(processing_time.get(kit, 0)) for kit in KitType},
            )
            airports[code] = airport
    return airports

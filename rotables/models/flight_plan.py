"""Flight plan entries parsed from CSV."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd

from config import CSV_DELIMITER


@dataclass
class FlightPlanEntry:
    origin: str
    destination: str
    scheduled_departure_hour: int
    scheduled_arrival_hour: int
    arrival_next_day: bool
    distance_km: float
    days_of_week: List[str]


def load_flight_plan(csv_path: Path) -> List[FlightPlanEntry]:
    df = pd.read_csv(csv_path, delimiter=CSV_DELIMITER)
    entries: List[FlightPlanEntry] = []
    for _, row in df.iterrows():
        days = []
        for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            try:
                if int(row.get(day, 0)) == 1:
                    days.append(day)
            except Exception:
                continue
        entries.append(
            FlightPlanEntry(
                origin=str(row["depart_code"]),
                destination=str(row["arrival_code"]),
                scheduled_departure_hour=int(row.get("scheduled_hour", 0)),
                scheduled_arrival_hour=int(row.get("scheduled_arrival_hour", 0)),
                arrival_next_day=bool(row.get("arrival_next_day", False)),
                distance_km=float(row.get("distance_km", 0.0)),
                days_of_week=days,
            )
        )
    return entries

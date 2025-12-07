"""Utility for reading static CSV datasets used by the simulator.

The loader always resolves file paths relative to the repository root, so it
works regardless of the current working directory or runner entrypoint.
"""

import csv
from pathlib import Path
from typing import Dict, List

from rotables_optimizer.domain.airport_profile import AirportProfile

# Use data colocated with this package so rotables is fully standalone.
DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


class DatasetLoader:
    def __init__(self, data_root: Path = DATA_ROOT):
        self.data_root = data_root

    # ------------------------------------------------------------
    # Airports
    # ------------------------------------------------------------
    def load_airport_profiles(self) -> List[AirportProfile]:
        """
        Parse the airport metadata including processing times, capacities, and
        starting stock. File is expected to be semicolon-delimited.
        """
        profiles: List[AirportProfile] = []
        with open(self.data_root / "airports_with_stocks.csv", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                profiles.append(
                    AirportProfile(
                        identifier=row["id"],
                        code=row["code"],
                        name=row["name"],
                        processing_time_first=int(row["first_processing_time"]),
                        processing_time_business=int(row["business_processing_time"]),
                        processing_time_premium=int(row["premium_economy_processing_time"]),
                        processing_time_economy=int(row["economy_processing_time"]),
                        processing_cost_first=float(row["first_processing_cost"]),
                        processing_cost_business=float(row["business_processing_cost"]),
                        processing_cost_premium=float(row["premium_economy_processing_cost"]),
                        processing_cost_economy=float(row["economy_processing_cost"]),
                        loading_cost_first=float(row["first_loading_cost"]),
                        loading_cost_business=float(row["business_loading_cost"]),
                        loading_cost_premium=float(row["premium_economy_loading_cost"]),
                        loading_cost_economy=float(row["economy_loading_cost"]),
                        starting_first=int(row["initial_fc_stock"]),
                        starting_business=int(row["initial_bc_stock"]),
                        starting_premium=int(row["initial_pe_stock"]),
                        starting_economy=int(row["initial_ec_stock"]),
                        capacity_first=int(row["capacity_fc"]),
                        capacity_business=int(row["capacity_bc"]),
                        capacity_premium=int(row["capacity_pe"]),
                        capacity_economy=int(row["capacity_ec"]),
                    )
                )
        return profiles

    # ------------------------------------------------------------
    # Aircraft capacities
    # ------------------------------------------------------------
    def load_aircraft_capacities(self) -> Dict[str, Dict[str, int]]:
        """Return a mapping from aircraft type code to per-cabin kit capacity."""
        capacities: Dict[str, Dict[str, int]] = {}
        with open(self.data_root / "aircraft_types.csv", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                capacities[row["type_code"]] = {
                    "first": int(row["first_class_kits_capacity"]),
                    "business": int(row["business_kits_capacity"]),
                    "premium": int(row["premium_economy_kits_capacity"]),
                    "economy": int(row["economy_kits_capacity"]),
                }
        return capacities

    # ------------------------------------------------------------
    # Flight plan stats (frequency / distance)
    # ------------------------------------------------------------
    def load_flight_plan_stats(self):
        """
        Parse flight_plan.csv to build lightweight priors:
        - freq_by_origin: weekly departures per origin
        - risk_by_origin: freq * avg_distance (proxy for penalty exposure)
        - route_distance: distance per (origin, dest)
        """
        freq_by_origin: Dict[str, int] = {}
        total_dist_by_origin: Dict[str, int] = {}
        route_distance: Dict[tuple, int] = {}

        path = self.data_root / "flight_plan.csv"
        if not path.exists():
            return {
                "freq_by_origin": freq_by_origin,
                "risk_by_origin": {},
                "route_distance": route_distance,
            }

        with open(path, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                origin = row["depart_code"]
                dest = row["arrival_code"]
                distance = int(float(row.get("distance_km", 0)))
                route_distance[(origin, dest)] = distance

                # Count departures per week based on day flags.
                weekly = sum(int(row.get(day, 0)) for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
                freq_by_origin[origin] = freq_by_origin.get(origin, 0) + weekly
                total_dist_by_origin[origin] = total_dist_by_origin.get(origin, 0) + weekly * distance

        risk_by_origin: Dict[str, float] = {}
        for origin, freq in freq_by_origin.items():
            if freq == 0:
                continue
            avg_dist = total_dist_by_origin.get(origin, 0) / freq
            risk_by_origin[origin] = avg_dist * freq  # proxy exposure

        return {
            "freq_by_origin": freq_by_origin,
            "risk_by_origin": risk_by_origin,
            "route_distance": route_distance,
        }

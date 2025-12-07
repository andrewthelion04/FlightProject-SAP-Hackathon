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

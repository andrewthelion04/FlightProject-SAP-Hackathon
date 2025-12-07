from dataclasses import dataclass


@dataclass
class AirportProfile:
    """
    Immutable snapshot of an airport's operational characteristics.

    The names are intentionally verbose so that later code reads naturally:
    - processing_*: time needed to refurbish kits by cabin
    - loading_*: cost metadata (kept for completeness)
    - capacity_*: maximum on-hand kits the airport can store per cabin
    """

    identifier: str
    code: str
    name: str

    processing_time_first: int
    processing_time_business: int
    processing_time_premium: int
    processing_time_economy: int

    processing_cost_first: float
    processing_cost_business: float
    processing_cost_premium: float
    processing_cost_economy: float

    loading_cost_first: float
    loading_cost_business: float
    loading_cost_premium: float
    loading_cost_economy: float

    starting_first: int
    starting_business: int
    starting_premium: int
    starting_economy: int

    capacity_first: int
    capacity_business: int
    capacity_premium: int
    capacity_economy: int

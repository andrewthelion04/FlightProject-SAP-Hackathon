"""Hyperparameters for the rotables strategy and tuning utilities."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict

from rotables.models.kit_types import KitType


def _default_ratio(value: float) -> Dict[KitType, float]:
    return {kit: value for kit in KitType}


@dataclass
class StrategyConfig:
    """
    Tunable knobs for the lookahead heuristic.

    These values are intentionally exposed so a closed-loop tuner can explore
    the space without rewriting the core decision logic.
    """

    # Time lookahead
    safety_buffer_hours: int = 12
    horizon_multiplier_first: float = 1.0
    horizon_multiplier_business: float = 1.0
    horizon_multiplier_premium: float = 1.0
    horizon_multiplier_economy: float = 1.0
    endgame_lookahead_hours: int = 48

    # Purchases
    min_purchase_threshold: int = 3
    purchase_safety_ratio: float = 0.05
    endgame_aggressive_purchase: bool = True

    # Repositioning
    allow_reposition: bool = True
    reposition_distance_threshold: float = 1200.0
    cost_dominated_factor: float = 1.1
    surplus_reserve_ratio: float = 0.15
    min_reserve_at_origin: int = 2
    safe_load_ratio: float = 0.35

    # Safety stock (per kit)
    safety_stock_ratio: Dict[KitType, float] = None

    def __post_init__(self) -> None:
        if self.safety_stock_ratio is None:
            self.safety_stock_ratio = _default_ratio(0.2)

    def asdict(self) -> Dict:
        data = asdict(self)
        data["safety_stock_ratio"] = {kit.name: val for kit, val in self.safety_stock_ratio.items()}
        return data

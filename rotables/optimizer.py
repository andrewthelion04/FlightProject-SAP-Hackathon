"""Closed-loop optimizer that tunes strategy hyperparameters based on backend penalties."""
from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional

from rotables.client import ApiClient
from rotables.runner import SessionRunner, DEFAULT_DATA_DIR
from rotables.strategy.config import StrategyConfig
from rotables.strategy.lookahead import LookaheadStrategy


STRUCTURAL_CODES = {
    "NEGATIVE_INVENTORY",
    "OVER_CAPACITY_STOCK",
    "FLIGHT_OVERLOAD",
    "INCORRECT_FLIGHT_LOAD",
    "EARLY_END_OF_GAME",
}


@dataclass
class PenaltyBreakdown:
    negative_inventory: float = 0.0
    over_capacity_stock: float = 0.0
    flight_overload: float = 0.0
    incorrect_flight_load: float = 0.0
    unfulfilled_kits: float = 0.0
    endgame_remaining_stock: float = 0.0
    endgame_pending_processing: float = 0.0
    endgame_unfulfilled_flights: float = 0.0
    early_end_of_game: float = 0.0

    @property
    def structural_penalty_sum(self) -> float:
        return (
            self.negative_inventory
            + self.over_capacity_stock
            + self.flight_overload
            + self.incorrect_flight_load
            + self.early_end_of_game
        )

    def to_dict(self) -> Dict[str, float]:
        return {
            "negative_inventory": self.negative_inventory,
            "over_capacity_stock": self.over_capacity_stock,
            "flight_overload": self.flight_overload,
            "incorrect_flight_load": self.incorrect_flight_load,
            "unfulfilled_kits": self.unfulfilled_kits,
            "endgame_remaining_stock": self.endgame_remaining_stock,
            "endgame_pending_processing": self.endgame_pending_processing,
            "endgame_unfulfilled_flights": self.endgame_unfulfilled_flights,
            "early_end_of_game": self.early_end_of_game,
        }


@dataclass
class ExperimentResult:
    config: StrategyConfig
    total_cost: float
    penalties: PenaltyBreakdown


def aggregate_penalties(raw_penalties: List[Dict]) -> PenaltyBreakdown:
    breakdown = PenaltyBreakdown()
    for entry in raw_penalties or []:
        code = str(entry.get("code", "")).upper()
        value = float(entry.get("penalty", 0.0) or 0.0)
        if code == "NEGATIVE_INVENTORY":
            breakdown.negative_inventory += value
        elif code == "OVER_CAPACITY_STOCK":
            breakdown.over_capacity_stock += value
        elif code == "FLIGHT_OVERLOAD":
            breakdown.flight_overload += value
        elif code == "INCORRECT_FLIGHT_LOAD":
            breakdown.incorrect_flight_load += value
        elif code in {"UNFULFILLED_KIT", "UNFULFILLED_FLIGHT_KIT", "UNFULFILLED_FLIGHT_KITS"}:
            breakdown.unfulfilled_kits += value
        elif code == "END_OF_GAME_REMAINING_STOCK":
            breakdown.endgame_remaining_stock += value
        elif code == "END_OF_GAME_PENDING_KIT_PROCESSING":
            breakdown.endgame_pending_processing += value
        elif code == "END_OF_GAME_UNFULFILLED_FLIGHT_KITS":
            breakdown.endgame_unfulfilled_flights += value
        elif code == "EARLY_END_OF_GAME":
            breakdown.early_end_of_game += value
    return breakdown


def run_single_session(
    config: StrategyConfig,
    data_dir: Path = DEFAULT_DATA_DIR,
    verbose: bool = True,
) -> ExperimentResult:
    """
    Run one full session with the given config and return the outcome.
    Relies on the existing SessionRunner and API client.
    """
    runner = SessionRunner(
        data_dir=data_dir,
        strategy=LookaheadStrategy(config),
        client=ApiClient(verbose=verbose),
    )
    runner.run()
    penalties = aggregate_penalties(runner.penalties_log)
    total_cost = float(runner.total_cost) if runner.total_cost is not None else float("inf")
    return ExperimentResult(config=config, total_cost=total_cost, penalties=penalties)


def log_experiment(result: ExperimentResult, path: Path = Path("experiments_log.csv")) -> None:
    """Append experiment results to a CSV with config and penalty breakdown."""
    path = path.resolve()
    header = None
    if not path.exists():
        header = True
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "total_cost",
                "negative_inventory",
                "over_capacity_stock",
                "flight_overload",
                "incorrect_flight_load",
                "unfulfilled_kits",
                "endgame_remaining_stock",
                "endgame_pending_processing",
                "endgame_unfulfilled_flights",
                "early_end_of_game",
            ]
            + list(result.config.asdict().keys()),
        )
        if header:
            writer.writeheader()
        row = {"total_cost": result.total_cost, **result.penalties.to_dict(), **result.config.asdict()}
        writer.writerow(row)


def generate_neighbor_configs(base: StrategyConfig, step_scale: float = 1.0) -> List[StrategyConfig]:
    """Simple coordinate perturbations around a base configuration."""
    neighbors: List[StrategyConfig] = []

    def clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    deltas = [
        ("reposition_distance_threshold", 100.0),
        ("cost_dominated_factor", 0.1),
        ("purchase_safety_ratio", 0.05),
        ("surplus_reserve_ratio", 0.05),
        ("horizon_multiplier_first", 0.25),
        ("horizon_multiplier_business", 0.25),
        ("horizon_multiplier_premium", 0.25),
        ("horizon_multiplier_economy", 0.25),
    ]

    for field, delta in deltas:
        current = getattr(base, field)
        for sign in (-1, 1):
            new_val = current + sign * delta * step_scale
            if "ratio" in field or "multiplier" in field or "factor" in field:
                new_val = clamp(new_val, 0.01, 5.0)
            if "distance" in field:
                new_val = clamp(new_val, 100.0, 10000.0)
            neighbors.append(replace(base, **{field: new_val}))

    # Adjust safety buffer hours
    for sign in (-1, 1):
        new_buffer = int(clamp(base.safety_buffer_hours + sign * 4 * step_scale, 0, 72))
        neighbors.append(replace(base, safety_buffer_hours=new_buffer))

    return neighbors


def auto_tune(base_config: StrategyConfig, max_iterations: int = 10) -> StrategyConfig:
    """
    Coordinate-descent style tuner:
    - Rejects any configuration that yields structural penalties.
    - Accepts lower total_cost as improvement.
    """
    best_config = base_config
    best_result = run_single_session(best_config)
    step_scale = 1.0

    for _ in range(max_iterations):
        improved = False
        for cfg in generate_neighbor_configs(best_config, step_scale):
            result = run_single_session(cfg)
            if result.penalties.structural_penalty_sum > 0:
                continue
            if result.total_cost < best_result.total_cost:
                best_result = result
                best_config = cfg
                improved = True
                log_experiment(result)
        if not improved:
            step_scale *= 0.5
            if step_scale < 0.1:
                break
    return best_config


if __name__ == "__main__":
    # Example driver for manual tuning; beware this will call the live backend.
    baseline = StrategyConfig()
    result = run_single_session(baseline, verbose=True)
    print("Total cost:", result.total_cost)

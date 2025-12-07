"""Entry point for the refactored rotables engine.

This script wires together the data loader, stock coordinator, strategy, and
API client. It is intentionally verbose to make the control flow easy to follow.
"""

import argparse
import sys
import types
from pathlib import Path

# Bootstrap: expose this folder (which has a hyphen in its name) as an importable
# package named "rotables_optimizer" and, for backward compatibility, "rotables".
PACKAGE_ROOT = Path(__file__).resolve().parent
for alias in ("rotables_optimizer", "rotables"):
    if alias not in sys.modules:
        module = types.ModuleType(alias)
        module.__path__ = [str(PACKAGE_ROOT)]
        sys.modules[alias] = module

# Ensure the parent directory is on sys.path so subpackages are discoverable.
REPO_ROOT = PACKAGE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rotables_optimizer.domain.contracts import RoundInstruction
from rotables_optimizer.infra.data_loader import DatasetLoader
from rotables_optimizer.infra.game_api import GameApiClient
from rotables_optimizer.engine.stock_coordinator import StockCoordinator
from rotables_optimizer.engine.simulation_state import SimulationState
from rotables_optimizer.engine.strategy import BalancedDispatchStrategy
from rotables_optimizer.engine.strategy_aggressive import AggressiveStrategy
from rotables_optimizer.engine.strategy_conservative import ConservativeStrategy
from rotables_optimizer.engine.strategy_capacity_guard import CapacityGuardStrategy
from rotables_optimizer.engine.strategy_hub_priority import HubPriorityStrategy
from rotables_optimizer.engine.strategy_outstation_support import OutstationSupportStrategy
from rotables_optimizer.engine.strategy_lean_buffers import LeanBuffersStrategy
from rotables_optimizer.engine.strategy_high_economy import HighEconomyStrategy
from rotables_optimizer.engine.strategy_no_overflow import NoOverflowStrategy
from rotables_optimizer.engine.strategy_no_purchase import NoPurchaseStrategy


STRATEGY_REGISTRY = {
    "balanced": BalancedDispatchStrategy,
    "aggressive": AggressiveStrategy,
    "conservative": ConservativeStrategy,
    "capacity_guard": CapacityGuardStrategy,
    "hub_priority": HubPriorityStrategy,
    "outstation_support": OutstationSupportStrategy,
    "lean_buffers": LeanBuffersStrategy,
    "high_economy": HighEconomyStrategy,
    "no_overflow": NoOverflowStrategy,
    "no_purchase": NoPurchaseStrategy,
}


def run(argv=None):
    parser = argparse.ArgumentParser(description="Run rotables optimizer with a selectable strategy.")
    parser.add_argument(
        "--strategy",
        default="balanced",
        choices=sorted(STRATEGY_REGISTRY.keys()),
        help="Which strategy to use for this session.",
    )
    args = parser.parse_args(argv)

    print("=== ROTABLES ENGINE START ===")
    print(f"[INFO] Using strategy: {args.strategy}")

    loader = DatasetLoader()
    airports = loader.load_airport_profiles()
    aircraft_caps = loader.load_aircraft_capacities()

    stock = StockCoordinator(airports)
    sim_state = SimulationState()
    sim_state.aircraft_capacities = aircraft_caps

    api = GameApiClient()
    strategy_cls = STRATEGY_REGISTRY[args.strategy]
    strategy = strategy_cls(stock, aircraft_caps)

    print("[INFO] Starting or resuming session...")
    api.start_session()

    day = 0
    hour = 0

    while True:
        instruction: RoundInstruction = strategy.plan_round(day, hour, sim_state)
        outcome = api.play_round(instruction)

        sim_state.ingest_backend_round(outcome)

        # Apply procurement to HUB inventory right away.
        purchase = instruction.procurement
        if purchase.first_class or purchase.business_class or purchase.premium_economy or purchase.economy:
            stock.receive_purchase_at_hub(purchase)

        # Landed flights return kits into processing.
        for event in outcome.flight_events:
            if event.event_type.value == "LANDED":
                used_kits = strategy.last_kits_per_flight.get(event.flight_id)
                if used_kits:
                    stock.enqueue_processing_after_landing(
                        airport_code=event.destination_airport,
                        used_kits=used_kits,
                        day=outcome.day,
                        hour=outcome.hour,
                    )
                strategy.last_kits_per_flight.pop(event.flight_id, None)

        print(f"[ITER] day={outcome.day} hour={outcome.hour} total_cost={outcome.total_cost}")

        if outcome.day == 29 and outcome.hour == 23:
            break

        hour += 1
        if hour == 24:
            hour = 0
            day += 1

    print("=== SIMULATION END ===")
    print("SESSION CLOSED BY BACKEND")


if __name__ == "__main__":
    run()

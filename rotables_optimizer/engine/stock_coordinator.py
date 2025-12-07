"""Inventory management primitives with explicit, self-documenting names."""

from collections import defaultdict
from typing import Dict, List

from rotables_optimizer.domain.airport_profile import AirportProfile
from rotables_optimizer.domain.contracts import CabinKits
from rotables_optimizer.engine.processing_queue import ProcessingTask
from rotables_optimizer.engine.stock import StockLevels


class StockCoordinator:
    """
    Keeps track of on-hand kits per airport and simulates refurbishment/processing.
    The naming is intentionally verbose so it is obvious which quantities are
    mutated and when processing completes.
    """

    def __init__(self, airport_profiles):
        self.airport_meta: Dict[str, AirportProfile] = {profile.code: profile for profile in airport_profiles}
        self.stock_by_airport: Dict[str, StockLevels] = {
            profile.code: StockLevels(
                first_class=profile.starting_first,
                business_class=profile.starting_business,
                premium_economy=profile.starting_premium,
                economy=profile.starting_economy,
            )
            for profile in airport_profiles
        }
        self.processing_queues: Dict[str, List[ProcessingTask]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------
    def snapshot(self, airport_code: str) -> StockLevels:
        """Return a direct reference to the stock object for an airport."""
        return self.stock_by_airport[airport_code]

    # ------------------------------------------------------------------
    # Stock movements
    # ------------------------------------------------------------------
    def consume_for_flight(self, airport_code: str, kits: CabinKits):
        """Remove kits from origin just before a flight departs."""
        stock = self.stock_by_airport[airport_code]
        stock.first_class = max(0, stock.first_class - kits.first_class)
        stock.business_class = max(0, stock.business_class - kits.business_class)
        stock.premium_economy = max(0, stock.premium_economy - kits.premium_economy)
        stock.economy = max(0, stock.economy - kits.economy)

    def receive_purchase_at_hub(self, kits: CabinKits, hub_code: str = "HUB1"):
        """All procurement is delivered to the designated hub."""
        stock = self.stock_by_airport[hub_code]
        stock.first_class += kits.first_class
        stock.business_class += kits.business_class
        stock.premium_economy += kits.premium_economy
        stock.economy += kits.economy

    # ------------------------------------------------------------------
    # Processing workflow
    # ------------------------------------------------------------------
    def _ready_time(self, day: int, hour: int, extra_hours: int):
        absolute = day * 24 + hour + extra_hours
        return absolute // 24, absolute % 24

    def enqueue_processing_after_landing(self, airport_code: str, used_kits: CabinKits, day: int, hour: int):
        meta = self.airport_meta[airport_code]

        if used_kits.first_class:
            rd, rh = self._ready_time(day, hour, meta.processing_time_first)
            self.processing_queues[airport_code].append(ProcessingTask("first", used_kits.first_class, rd, rh))
        if used_kits.business_class:
            rd, rh = self._ready_time(day, hour, meta.processing_time_business)
            self.processing_queues[airport_code].append(ProcessingTask("business", used_kits.business_class, rd, rh))
        if used_kits.premium_economy:
            rd, rh = self._ready_time(day, hour, meta.processing_time_premium)
            self.processing_queues[airport_code].append(ProcessingTask("premium_economy", used_kits.premium_economy, rd, rh))
        if used_kits.economy:
            rd, rh = self._ready_time(day, hour, meta.processing_time_economy)
            self.processing_queues[airport_code].append(ProcessingTask("economy", used_kits.economy, rd, rh))

    def advance_processing(self, day: int, hour: int):
        """Move completed processing tasks back into usable inventory."""
        for airport_code, queue in list(self.processing_queues.items()):
            remaining: List[ProcessingTask] = []
            stock = self.stock_by_airport[airport_code]

            for task in queue:
                ready = (day > task.ready_day) or (day == task.ready_day and hour >= task.ready_hour)
                if not ready:
                    remaining.append(task)
                    continue

                if task.cabin == "first":
                    stock.first_class += task.quantity
                elif task.cabin == "business":
                    stock.business_class += task.quantity
                elif task.cabin == "premium_economy":
                    stock.premium_economy += task.quantity
                elif task.cabin == "economy":
                    stock.economy += task.quantity

            self.processing_queues[airport_code] = remaining

"""Strategy variant: progressive ramp + outstation protection + cabin prioritization."""

from typing import Dict

from rotables_optimizer.domain.contracts import CabinKits, FlightLoadPlan, RoundInstruction
from rotables_optimizer.engine.simulation_state import SimulationState
from rotables_optimizer.engine.stock_coordinator import StockCoordinator


class ProgressiveOutstationStrategy:
    """
    - Early: lean purchases, conservative loads.
    - Late: ramps up purchases/loads via exponential factor.
    - Protects outstations with higher minima.
    - Prioritizes higher-penalty cabins when reserving/limiting stock.
    """

    def __init__(self, stock_coordinator: StockCoordinator, aircraft_capacities: Dict, flight_plan_stats=None):
        self.stock = stock_coordinator
        self.aircraft_capacities = aircraft_capacities
        self.last_kits_per_flight: Dict = {}
        # Importance derived mainly from kitCost (weight has minor influence):
        # first: 200 + 0.05*5 = 200.25, business: 150+0.05*3=150.15,
        # premium: 100+0.05*2.5=100.125, economy: 50+0.05*1.5=50.075
        # Normalize relative to economy (≈50) -> weights ~4.0, 3.0, 2.0, 1.0
        self.priority_weight = {
            "first": 4.0,
            "business": 3.0,
            "premium_economy": 2.0,
            "economy": 1.0,
        }
        self.flight_plan_stats = flight_plan_stats or {
            "freq_by_origin": {},
            "risk_by_origin": {},
            "route_distance": {},
        }

    def plan_round(self, day: int, hour: int, state: SimulationState) -> RoundInstruction:
        self.stock.advance_processing(day, hour)

        load_plans = []
        for flight_event in state.pull_pending_loads():
            plan = self._build_load_plan(flight_event, state, day, hour)
            load_plans.append(plan)
            self.last_kits_per_flight[flight_event.flight_id] = plan.planned_kits

            origin_stock = self.stock.snapshot(flight_event.origin_airport)
            consumed = CabinKits(
                first_class=min(plan.planned_kits.first_class, origin_stock.first_class),
                business_class=min(plan.planned_kits.business_class, origin_stock.business_class),
                premium_economy=min(plan.planned_kits.premium_economy, origin_stock.premium_economy),
                economy=min(plan.planned_kits.economy, origin_stock.economy),
            )
            self.stock.consume_for_flight(flight_event.origin_airport, consumed)

        procurement = self._decide_procurement(day, hour)

        return RoundInstruction(day=day, hour=hour, load_plans=load_plans, procurement=procurement)

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _progress_ratio(self, day: int, hour: int) -> float:
        total_hours = 30 * 24
        current = day * 24 + hour
        return max(0.0, min(1.0, current / total_hours))

    def _exp_ramp(self, day: int, hour: int, steepness: float = 3.0) -> float:
        import math

        p = self._progress_ratio(day, hour)
        num = math.exp(steepness * p) - 1.0
        den = math.exp(steepness) - 1.0
        return max(0.0, min(1.0, num / den))

    def _forecast_origin_demand(self, origin_airport: str, state: SimulationState, exclude_flight_id=None) -> CabinKits:
        demand = CabinKits()
        flights = getattr(state, "scheduled_flights", state.active_flights)
        for evt in flights.values():
            if evt.origin_airport != origin_airport:
                continue
            if exclude_flight_id is not None and evt.flight_id == exclude_flight_id:
                continue
            pax = evt.passengers
            demand.first_class += pax.first_class
            demand.business_class += pax.business_class
            demand.premium_economy += pax.premium_economy
            demand.economy += pax.economy
        return demand

    # ------------------------------------------------------------
    # Load decision
    # ------------------------------------------------------------
    def _build_load_plan(self, evt, state: SimulationState, day: int, hour: int) -> FlightLoadPlan:
        origin = evt.origin_airport
        destination = evt.destination_airport
        pax = evt.passengers
        capacity = self.aircraft_capacities[evt.aircraft_type]

        origin_stock = self.stock.snapshot(origin)
        destination_stock = self.stock.snapshot(destination)
        destination_meta = self.stock.airport_meta.get(destination)

        dest_cap_first = getattr(destination_meta, "capacity_first", 10**9)
        dest_cap_business = getattr(destination_meta, "capacity_business", 10**9)
        dest_cap_premium = getattr(destination_meta, "capacity_premium", 10**9)
        dest_cap_economy = getattr(destination_meta, "capacity_economy", 10**9)

        forecast = self._forecast_origin_demand(origin, state, exclude_flight_id=evt.flight_id)
        ramp = self._exp_ramp(day, hour, steepness=3.0)

        # Flight plan priors
        freq = self.flight_plan_stats.get("freq_by_origin", {}).get(origin, 0)
        risk = self.flight_plan_stats.get("risk_by_origin", {}).get(origin, 0.0)
        route_dist = self.flight_plan_stats.get("route_distance", {}).get((origin, destination), 0)

        reserve_scale_hub = 1.0 + 0.18 * ramp
        reserve_scale_out = 1.0 + 0.14 * ramp

        def apply_priority_guard(value: int, cabin: str, pax_for_cabin: int) -> int:
            # Higher weight and higher pax reduce the reserve to allow more loading.
            factor = 1.0 + 0.12 * self.priority_weight[cabin]
            pressure = min(0.5, 0.03 * pax_for_cabin)  # at most 50% cut from passenger pressure
            return max(0, int(value * (1 - pressure) / factor))

        if origin == "HUB1":
            reserve_first = apply_priority_guard(int(forecast.first_class * 1.1 * reserve_scale_hub), "first", pax.first_class)
            reserve_business = apply_priority_guard(int(forecast.business_class * 1.1 * reserve_scale_hub), "business", pax.business_class)
            reserve_premium = apply_priority_guard(int(forecast.premium_economy * 1.05 * reserve_scale_hub), "premium_economy", pax.premium_economy)
            reserve_economy = int(forecast.economy * 1.05 * reserve_scale_hub)
        else:
            freq_boost = 1.0 + min(0.5, freq / 14.0)  # more departures -> higher base
            base_first = min(max(5, int(origin_stock.first_class * 0.24 * freq_boost)), 85)
            base_business = min(max(7, int(origin_stock.business_class * 0.24 * freq_boost)), 105)
            base_premium = min(max(7, int(origin_stock.premium_economy * 0.24 * freq_boost)), 105)
            base_economy = min(max(60, int(origin_stock.economy * 0.36 * freq_boost)), 380)

            reserve_first = apply_priority_guard(max(base_first, int(forecast.first_class * (1.0 + 0.12 * ramp))), "first", pax.first_class)
            reserve_business = apply_priority_guard(max(base_business, int(forecast.business_class * (1.0 + 0.12 * ramp))), "business", pax.business_class)
            reserve_premium = apply_priority_guard(max(base_premium, int(forecast.premium_economy * (1.0 + 0.12 * ramp))), "premium_economy", pax.premium_economy)
            reserve_economy = max(base_economy, int(forecast.economy * (1.02 + 0.16 * ramp)))

        reserve_first = min(max(0, reserve_first), origin_stock.first_class)
        reserve_business = min(max(0, reserve_business), origin_stock.business_class)
        reserve_premium = min(max(0, reserve_premium), origin_stock.premium_economy)
        reserve_economy = min(max(0, reserve_economy), origin_stock.economy)

        available_first = max(0, origin_stock.first_class - reserve_first)
        available_business = max(0, origin_stock.business_class - reserve_business)
        available_premium = max(0, origin_stock.premium_economy - reserve_premium)
        available_economy = max(0, origin_stock.economy - reserve_economy)

        # Route priority based on distance (longer routes risk higher penalties)
        dist_factor = min(1.3, 1.0 + 0.00007 * route_dist) if route_dist else 1.0

        load_first = min(int(pax.first_class * dist_factor), available_first, capacity["first"])
        load_business = min(int(pax.business_class * dist_factor), available_business, capacity["business"])
        load_premium = min(int(pax.premium_economy * dist_factor), available_premium, capacity["premium"])
        load_economy = min(int(pax.economy * dist_factor), available_economy, capacity["economy"])

        base_margin = int(30 + 12 * ramp)

        def respect_destination_capacity(current, limit, proposed, cabin):
            margin = max(10, int(base_margin - 6 * self.priority_weight.get(cabin, 1.0)))
            free_space = limit - current - margin
            if free_space <= 0:
                return 0
            return min(proposed, free_space)

        load_first = respect_destination_capacity(destination_stock.first_class, dest_cap_first, load_first, "first")
        load_business = respect_destination_capacity(destination_stock.business_class, dest_cap_business, load_business, "business")
        load_premium = respect_destination_capacity(destination_stock.premium_economy, dest_cap_premium, load_premium, "premium_economy")
        load_economy = respect_destination_capacity(destination_stock.economy, dest_cap_economy, load_economy, "economy")

        load_first = max(0, min(load_first, origin_stock.first_class))
        load_business = max(0, min(load_business, origin_stock.business_class))
        load_premium = max(0, min(load_premium, origin_stock.premium_economy))
        load_economy = max(0, min(load_economy, origin_stock.economy))

        return FlightLoadPlan(
            evt.flight_id,
            CabinKits(
                first_class=int(load_first),
                business_class=int(load_business),
                premium_economy=int(load_premium),
                economy=int(load_economy),
            ),
        )

    # ------------------------------------------------------------
    # Procurement
    # ------------------------------------------------------------
    def _decide_procurement(self, day: int, hour: int) -> CabinKits:
        hub_code = "HUB1"
        hub_stock = self.stock.snapshot(hub_code)
        hub_meta = self.stock.airport_meta.get(hub_code)

        cap_first = getattr(hub_meta, "capacity_first", 10**9)
        cap_business = getattr(hub_meta, "capacity_business", 10**9)
        cap_premium = getattr(hub_meta, "capacity_premium", 10**9)
        cap_economy = getattr(hub_meta, "capacity_economy", 10**9)

        ramp = self._exp_ramp(day, hour, steepness=3.0)

        buy_first = buy_business = buy_premium = buy_economy = 0

        econ_low_ratio = 0.30 + 0.08 * ramp    # 0.30 -> 0.38
        econ_high_ratio = 0.55 + 0.10 * ramp   # 0.55 -> 0.65

        low_economy = int(cap_economy * econ_low_ratio)
        high_economy = int(cap_economy * econ_high_ratio)

        if hub_stock.economy < low_economy:
            desired = int(4500 + 7500 * ramp)  # slightly more to avoid shortages
            free_space = max(0, high_economy - hub_stock.economy)
            buy_economy = min(desired, free_space)

        # Adjust cabin thresholds using route/origin risk if available
        risk_boost = min(0.06, self.flight_plan_stats.get("risk_by_origin", {}).get("HUB1", 0) / 30000)  # coarse heuristic

        if hub_stock.first_class < 170 + int(80 * ramp):
            buy_first = min(140, max(0, cap_first - hub_stock.first_class - 10))

        if hub_stock.business_class < 250 + int(80 * ramp):
            buy_business = min(150, max(0, cap_business - hub_stock.business_class - 10))

        if hub_stock.premium_economy < 320 + int(80 * ramp):
            buy_premium = min(150, max(0, cap_premium - hub_stock.premium_economy - 10))

        return CabinKits(
            first_class=int(buy_first),
            business_class=int(buy_business),
            premium_economy=int(buy_premium),
            economy=int(buy_economy),
        )

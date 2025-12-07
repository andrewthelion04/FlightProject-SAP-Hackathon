"""Strategy variant: very frugal early, pushes hard in the last third of the timeline."""

from typing import Dict

from rotables_optimizer.domain.contracts import CabinKits, FlightLoadPlan, RoundInstruction
from rotables_optimizer.engine.simulation_state import SimulationState
from rotables_optimizer.engine.stock_coordinator import StockCoordinator


class LateGamePushStrategy:
    """
    Early (first 1/3): minimal purchases, modest loads.
    Mid (second 1/3): balanced.
    Late (final 1/3): aggressive loading and higher purchases.
    """

    def __init__(self, stock_coordinator: StockCoordinator, aircraft_capacities: Dict):
        self.stock = stock_coordinator
        self.aircraft_capacities = aircraft_capacities
        self.last_kits_per_flight: Dict = {}

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

    def _progress_ratio(self, day: int, hour: int) -> float:
        total_hours = 30 * 24
        current = day * 24 + hour
        return max(0.0, min(1.0, current / total_hours))

    def _phase(self, progress: float) -> str:
        if progress < 1 / 3:
            return "early"
        if progress < 2 / 3:
            return "mid"
        return "late"

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
        progress = self._progress_ratio(day, hour)
        phase = self._phase(progress)

        if phase == "early":
            load_factor = 0.6
            dest_margin = 50
            reserve_mult_hub = 1.05
            reserve_mult_out = 1.0
        elif phase == "mid":
            load_factor = 0.8
            dest_margin = 40
            reserve_mult_hub = 1.15
            reserve_mult_out = 1.05
        else:  # late
            load_factor = 1.0
            dest_margin = 30
            reserve_mult_hub = 1.25
            reserve_mult_out = 1.15

        if origin == "HUB1":
            reserve_first = int(forecast.first_class * reserve_mult_hub)
            reserve_business = int(forecast.business_class * reserve_mult_hub)
            reserve_premium = int(forecast.premium_economy * reserve_mult_hub)
            reserve_economy = int(forecast.economy * reserve_mult_hub)
        else:
            base_first = min(max(2, int(origin_stock.first_class * 0.18)), 55)
            base_business = min(max(3, int(origin_stock.business_class * 0.18)), 75)
            base_premium = min(max(3, int(origin_stock.premium_economy * 0.18)), 75)
            base_economy = min(max(40, int(origin_stock.economy * 0.30)), 280)

            reserve_first = max(base_first, int(forecast.first_class * reserve_mult_out))
            reserve_business = max(base_business, int(forecast.business_class * reserve_mult_out))
            reserve_premium = max(base_premium, int(forecast.premium_economy * reserve_mult_out))
            reserve_economy = max(base_economy, int(forecast.economy * reserve_mult_out))

        reserve_first = min(max(0, reserve_first), origin_stock.first_class)
        reserve_business = min(max(0, reserve_business), origin_stock.business_class)
        reserve_premium = min(max(0, reserve_premium), origin_stock.premium_economy)
        reserve_economy = min(max(0, reserve_economy), origin_stock.economy)

        available_first = max(0, origin_stock.first_class - reserve_first)
        available_business = max(0, origin_stock.business_class - reserve_business)
        available_premium = max(0, origin_stock.premium_economy - reserve_premium)
        available_economy = max(0, origin_stock.economy - reserve_economy)

        load_first = min(int(pax.first_class * load_factor), available_first, capacity["first"])
        load_business = min(int(pax.business_class * load_factor), available_business, capacity["business"])
        load_premium = min(int(pax.premium_economy * load_factor), available_premium, capacity["premium"])
        load_economy = min(int(pax.economy * load_factor), available_economy, capacity["economy"])

        safety_margin = dest_margin

        def respect_destination_capacity(current, limit, proposed):
            free_space = limit - current - safety_margin
            if free_space <= 0:
                return 0
            return min(proposed, free_space)

        load_first = respect_destination_capacity(destination_stock.first_class, dest_cap_first, load_first)
        load_business = respect_destination_capacity(destination_stock.business_class, dest_cap_business, load_business)
        load_premium = respect_destination_capacity(destination_stock.premium_economy, dest_cap_premium, load_premium)
        load_economy = respect_destination_capacity(destination_stock.economy, dest_cap_economy, load_economy)

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

    def _decide_procurement(self, day: int, hour: int) -> CabinKits:
        hub_code = "HUB1"
        hub_stock = self.stock.snapshot(hub_code)
        hub_meta = self.stock.airport_meta.get(hub_code)

        cap_first = getattr(hub_meta, "capacity_first", 10**9)
        cap_business = getattr(hub_meta, "capacity_business", 10**9)
        cap_premium = getattr(hub_meta, "capacity_premium", 10**9)
        cap_economy = getattr(hub_meta, "capacity_economy", 10**9)

        progress = self._progress_ratio(day, hour)
        phase = self._phase(progress)

        buy_first = buy_business = buy_premium = buy_economy = 0

        if phase == "early":
            econ_low = 0.22
            econ_high = 0.50
            econ_desired = 4000
            fc_thresh = 150
            bc_thresh = 220
            pe_thresh = 250
        elif phase == "mid":
            econ_low = 0.28
            econ_high = 0.60
            econ_desired = 7000
            fc_thresh = 200
            bc_thresh = 300
            pe_thresh = 340
        else:
            econ_low = 0.34
            econ_high = 0.70
            econ_desired = 10000
            fc_thresh = 240
            bc_thresh = 360
            pe_thresh = 400

        low_economy = int(cap_economy * econ_low)
        high_economy = int(cap_economy * econ_high)

        if hub_stock.economy < low_economy:
            free_space = max(0, high_economy - hub_stock.economy)
            buy_economy = min(econ_desired, free_space)

        if hub_stock.first_class < fc_thresh:
            buy_first = min(140, max(0, cap_first - hub_stock.first_class - 10))

        if hub_stock.business_class < bc_thresh:
            buy_business = min(170, max(0, cap_business - hub_stock.business_class - 10))

        if hub_stock.premium_economy < pe_thresh:
            buy_premium = min(170, max(0, cap_premium - hub_stock.premium_economy - 10))

        return CabinKits(
            first_class=int(buy_first),
            business_class=int(buy_business),
            premium_economy=int(buy_premium),
            economy=int(buy_economy),
        )

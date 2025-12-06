"""Greedy solver and game loop for the Flight Rotables Optimization challenge."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from client import ApiClient
from config import BUFFER_PASSENGERS, CARGO_TOPUP, CSV_DELIMITER, MIN_STOCK_THRESHOLD
from models import Airport, Flight, CLASS_KEYS

# Constants and defaults
HUB_CODE = "HUB1"
KIT_OUTPUT_NAMES = {
    "first": "FIRST",
    "business": "BUSINESS",
    "premiumEconomy": "PREMIUM_ECONOMY",
    "economy": "ECONOMY",
}
DEFAULT_PROCESSING_DELAY_HOURS = 2
MAX_HORIZON_HOURS = 2
HUB_REORDER_LEVEL = MIN_STOCK_THRESHOLD * 3
HUB_PURCHASE_BATCH = 200
MAX_DAY = 0
MAX_HOUR = 3

# Data locations (relative to repository root)
AIRPORTS_CSV = Path("eval-platform/src/main/resources/liquibase/data/airports_with_stocks.csv")
FLIGHT_PLAN_CSV = Path("eval-platform/src/main/resources/liquibase/data/flight_plan.csv")
AIRCRAFT_TYPES_CSV = Path("eval-platform/src/main/resources/liquibase/data/aircraft_types.csv")


def hours_since_zero(day: int, hour: int) -> int:
    return day * 24 + hour


def advance_time(day: int, hour: int) -> Tuple[int, int]:
    hour += 1
    if hour >= 24:
        day += 1
        hour = 0
    return day, hour


class GameState:
    def __init__(self) -> None:
        self.airports: Dict[str, Airport] = {}
        self.flight_plan: Dict[Tuple[str, str], Dict[str, int]] = {}
        self.aircraft_types: Dict[str, Dict[str, int]] = {}
        self.pending_departures: List[Dict] = []
        self.pending_arrivals: List[Dict] = []
        self.known_flights: Dict[str, Flight] = {}
        self.locked_flights: set[str] = set()
        self.current_day = 0
        self.current_hour = 0

    def ensure_airport(self, code: str) -> Airport:
        if code not in self.airports:
            self.airports[code] = Airport(code, {k: 0 for k in CLASS_KEYS})
        self.airports[code].ensure_keys()
        return self.airports[code]

    def load_airports(self, path: Path) -> None:
        df = pd.read_csv(path, delimiter=CSV_DELIMITER)
        for _, row in df.iterrows():
            stocks = {
                "first": int(row.get("initial_fc_stock", 0)),
                "business": int(row.get("initial_bc_stock", 0)),
                "premiumEconomy": int(row.get("initial_pe_stock", 0)),
                "economy": int(row.get("initial_ec_stock", 0)),
            }
            processing = {
                "first": int(row.get("first_processing_time", 0)),
                "business": int(row.get("business_processing_time", 0)),
                "premiumEconomy": int(row.get("premium_economy_processing_time", 0)),
                "economy": int(row.get("economy_processing_time", 0)),
            }
            capacities = {
                "first": int(row.get("capacity_fc", 0)),
                "business": int(row.get("capacity_bc", 0)),
                "premiumEconomy": int(row.get("capacity_pe", 0)),
                "economy": int(row.get("capacity_ec", 0)),
            }
            airport = Airport(code=row["code"], stocks=stocks, processing_times=processing, capacities=capacities)
            airport.ensure_keys()
            self.airports[airport.code] = airport

    def load_flight_plan(self, path: Path) -> None:
        if not path.exists():
            return
        df = pd.read_csv(path, delimiter=CSV_DELIMITER)
        for _, row in df.iterrows():
            self.flight_plan[(row["depart_code"], row["arrival_code"])] = {
                "scheduled_hour": int(row.get("scheduled_hour", 0)),
                "arrival_next_day": bool(row.get("arrival_next_day", False)),
            }

    def load_aircraft_types(self, path: Path) -> None:
        if not path.exists():
            return
        df = pd.read_csv(path, delimiter=CSV_DELIMITER)
        for _, row in df.iterrows():
            self.aircraft_types[str(row["type_code"])] = {
                "first": int(row.get("first_class_kits_capacity", 0)),
                "business": int(row.get("business_kits_capacity", 0)),
                "premiumEconomy": int(row.get("premium_economy_kits_capacity", 0)),
                "economy": int(row.get("economy_kits_capacity", 0)),
            }

    def capacity_for(self, aircraft_type: str) -> Dict[str, int]:
        if not aircraft_type:
            return {}
        return self.aircraft_types.get(str(aircraft_type), {})

    def estimate_departure(self, flight: Flight) -> Tuple[int, int]:
        dep_hour = flight.scheduled_hour
        dep_day = flight.scheduled_day if flight.scheduled_day is not None else self.current_day

        if dep_hour is None:
            plan = self.flight_plan.get((flight.origin, flight.destination))
            if plan:
                dep_hour = plan.get("scheduled_hour")

        if dep_hour is None:
            dep_hour = self.current_hour + 1
            dep_day = self.current_day

        while dep_hour >= 24:
            dep_hour -= 24
            dep_day += 1

        now_idx = hours_since_zero(self.current_day, self.current_hour)
        dep_idx = hours_since_zero(dep_day, dep_hour)
        if dep_idx < now_idx:
            dep_day, dep_hour = self.current_day, self.current_hour

        return dep_day, dep_hour

    def estimate_arrival_delay(self, destination: str) -> int:
        airport = self.airports.get(destination)
        if airport and airport.processing_times:
            max_minutes = max(airport.processing_times.values())
            delay_hours = max(1, int(round(max_minutes / 60))) if max_minutes else 1
            return delay_hours
        return DEFAULT_PROCESSING_DELAY_HOURS

    def register_departure(self, flight: Flight, kits: Dict[str, int], dep_day: int, dep_hour: int, arrival_delay: int):
        if flight.id in self.locked_flights:
            return
        self.locked_flights.add(flight.id)
        depart_idx = hours_since_zero(dep_day, dep_hour)
        self.pending_departures.append(
            {
                "flightId": flight.id,
                "origin": flight.origin,
                "destination": flight.destination,
                "kits": kits,
                "depart_at": depart_idx,
                "arrival_delay": arrival_delay,
            }
        )

    def process_departures(self) -> None:
        now_idx = hours_since_zero(self.current_day, self.current_hour)
        remaining = []
        for item in self.pending_departures:
            if item["depart_at"] <= now_idx:
                origin = self.airports.get(item["origin"])
                if origin:
                    origin.commit_departure(item["kits"])
                if item["flightId"] in self.locked_flights:
                    self.locked_flights.remove(item["flightId"])
                self.pending_arrivals.append(
                    {
                        "airport": item["destination"],
                        "kits": item["kits"],
                        "deliver_at": item["depart_at"] + item["arrival_delay"],
                    }
                )
            else:
                remaining.append(item)
        self.pending_departures = remaining

    def process_arrivals(self) -> None:
        now_idx = hours_since_zero(self.current_day, self.current_hour)
        remaining = []
        for item in self.pending_arrivals:
            if item["deliver_at"] <= now_idx:
                airport = self.ensure_airport(item["airport"])
                for cls, qty in item["kits"].items():
                    airport.update_stock(cls, qty)
            else:
                remaining.append(item)
        self.pending_arrivals = remaining

    def tick(self) -> None:
        self.process_departures()
        self.process_arrivals()


def hours_until(target_day: int, target_hour: int, current_day: int, current_hour: int) -> int:
    return hours_since_zero(target_day, target_hour) - hours_since_zero(current_day, current_hour)


def decide_loads(state: GameState, flights: List[Flight]) -> Dict:
    flight_commands = []
    flight_loads = []

    for flight in flights:
        if not flight.origin or not flight.destination:
            continue
        if flight.id in state.locked_flights:
            continue
        dep_day, dep_hour = state.estimate_departure(flight)
        if hours_until(dep_day, dep_hour, state.current_day, state.current_hour) > MAX_HORIZON_HOURS:
            continue

        origin = state.ensure_airport(flight.origin)
        destination = state.ensure_airport(flight.destination)
        capacity = state.capacity_for(flight.aircraft_type)

        kits_map: Dict[str, int] = {}
        for cls in CLASS_KEYS:
            passengers = flight.passengers.get(cls, 0)
            cargo_topup = CARGO_TOPUP if destination.available(cls) < MIN_STOCK_THRESHOLD else 0
            desired = passengers + BUFFER_PASSENGERS + cargo_topup
            cap_limit = capacity.get(cls)
            if cap_limit:
                desired = min(desired, cap_limit)

            available = origin.available(cls)
            load_qty = min(desired, available)
            if load_qty < passengers and available > passengers:
                load_qty = min(available, passengers)

            reserved = origin.reserve(cls, load_qty)
            if reserved > 0:
                kits_map[cls] = reserved

        if kits_map:
            arrival_delay = state.estimate_arrival_delay(flight.destination)
            state.register_departure(flight, kits_map, dep_day, dep_hour, arrival_delay)

            flight_commands.append(
                {
                    "flightId": flight.id,
                    "kits": [{"type": KIT_OUTPUT_NAMES[k], "quantity": v} for k, v in kits_map.items()],
                }
            )
            flight_loads.append(
                {
                    "flightId": flight.id,
                    "loadedKits": {
                        "first": kits_map.get("first", 0),
                        "business": kits_map.get("business", 0),
                        "premiumEconomy": kits_map.get("premiumEconomy", 0),
                        "economy": kits_map.get("economy", 0),
                    },
                }
            )

    return {"flightCommands": flight_commands, "flightLoads": flight_loads}


def build_purchase_orders(state: GameState) -> Tuple[Dict[str, int], List[Dict]]:
    hub = state.airports.get(HUB_CODE)
    if not hub:
        return {}, []

    per_class = {}
    detailed = []
    for cls in CLASS_KEYS:
        if hub.available(cls) < HUB_REORDER_LEVEL:
            per_class[cls] = HUB_PURCHASE_BATCH
            detailed.append({"airport": HUB_CODE, "type": KIT_OUTPUT_NAMES[cls], "quantity": HUB_PURCHASE_BATCH})
        else:
            per_class[cls] = 0

    if all(v == 0 for v in per_class.values()):
        return {}, []
    return per_class, detailed


def build_payload(state: GameState, flights: List[Flight]) -> Dict:
    loads = decide_loads(state, flights)
    purchase_map, purchase_list = build_purchase_orders(state)

    payload = {
        "flightCommands": loads["flightCommands"],
        "purchaseOrders": purchase_list,
        "flightLoads": [
            {"flightId": item["flightId"], "loadedKits": item["loadedKits"]} for item in loads["flightLoads"]
        ],
        "kitPurchasingOrders": purchase_map if purchase_map else None,
    }
    return payload


def dump_json(label: str, obj: Dict) -> None:
    print(f"\n========== {label} ==========")
    try:
        print(json.dumps(obj, indent=2, sort_keys=True))
    except Exception:
        print(obj)
    print(f"======== End {label} ========\n")


def print_local_state(state: GameState) -> None:
    print("\n========== Local state ==========")
    print(f"Time: day={state.current_day} hour={state.current_hour}")
    print(f"Airports tracked: {len(state.airports)}")
    for code, ap in state.airports.items():
        print(f"  {code}: stocks={ap.stocks} | reserved={ap.reserved}")
    flights_list = [f"{f.flight_number}({f.id})" for f in state.known_flights.values()]
    print(f"Known flights: {len(state.known_flights)} -> {flights_list}")
    print(f"Pending departures: {len(state.pending_departures)} -> {state.pending_departures}")
    print(f"Pending arrivals: {len(state.pending_arrivals)} -> {state.pending_arrivals}")
    print("======== End Local state ========\n")


def print_round_header(day: int, hour: int) -> None:
    print(f"\n================ Round day={day} hour={hour} ================\n")


def run_game_loop() -> None:
    state = GameState()
    state.load_airports(AIRPORTS_CSV)
    state.load_flight_plan(FLIGHT_PLAN_CSV)
    state.load_aircraft_types(AIRCRAFT_TYPES_CSV)

    client = ApiClient()
    session_id = client.start_session()
    if not session_id:
        print("Failed to start session. Check API key and backend availability.")
        return

    day, hour = 0, 0

    try:
        while True:
            if day > MAX_DAY or (day == MAX_DAY and hour > MAX_HOUR):
                break
            print_round_header(day, hour)
            state.current_day, state.current_hour = day, hour
            state.tick()

            flights = list(state.known_flights.values())
            payload = build_payload(state, flights)
            response = client.play_round(day, hour, payload) or {}
            dump_json("API response (raw)", response)

            for update in response.get("flightUpdates", []):
                flight = Flight.from_json(update)
                if not flight or not flight.origin or not flight.destination:
                    continue
                if str(update.get("eventType", "")).upper() == "LANDED":
                    state.known_flights.pop(flight.id, None)
                else:
                    state.known_flights[flight.id] = flight

            print_local_state(state)

            day, hour = advance_time(day, hour)
    except KeyboardInterrupt:
        print("Stopping game loop by user request.")
    except Exception as exc:  # keep running in degraded mode
        print(f"Unexpected error: {exc}")
    finally:
        client.end_session()


if __name__ == "__main__":
    run_game_loop()

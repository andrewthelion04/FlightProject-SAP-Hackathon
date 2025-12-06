"""Strategy interface and decision dataclasses."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Protocol, Tuple

from rotables.models.flight import FlightInstance
from rotables.models.kit_types import KitType
from rotables.state.matrix_state import MatrixState


@dataclass
class KitLoadDecision:
    flight_id: str
    kits_per_type: Dict[KitType, int]


@dataclass
class PurchaseDecision:
    kit_type: KitType
    quantity: int


class Strategy(Protocol):
    def decide(
        self,
        current_day: int,
        current_hour: int,
        flights_now: List[FlightInstance],
        matrix: MatrixState,
        all_flights: List[FlightInstance],
    ) -> Tuple[List[KitLoadDecision], List[PurchaseDecision]]:
        ...


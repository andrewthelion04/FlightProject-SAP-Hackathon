"""Movement edges between inventory nodes."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from rotables.models.kit_types import KitType


class EdgeType(Enum):
    STORAGE = "storage"
    FLIGHT = "flight"
    PROCESSING = "processing"
    PURCHASE = "purchase"


@dataclass
class KitMovement:
    edge_type: EdgeType
    origin_airport: str
    origin_hour: int
    destination_airport: str
    destination_hour: int
    kit_type: KitType
    quantity: int
    flight_id: Optional[str] = None
    reason: Optional[str] = None

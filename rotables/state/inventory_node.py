"""Inventory node for the time-expanded network."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from rotables.models.airport import Airport
from rotables.models.kit_types import KitType


@dataclass
class InventoryNode:
    """
    Represents the clean kit inventory for an airport at the start of a given hour.

    Convention: movements with destination_hour == this node's hour have already been
    applied, and movements originating from this node's hour will deduct stock.
    """

    airport: Airport
    global_hour: int
    available_kits: Dict[KitType, int] = field(default_factory=dict)


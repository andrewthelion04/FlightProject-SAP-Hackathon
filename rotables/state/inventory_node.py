"""Inventory node represents stock at an airport at a given hour."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from rotables.models.airport import Airport
from rotables.models.kit_types import KitType


@dataclass
class InventoryNode:
    airport: Airport
    global_hour: int
    available_kits: Dict[KitType, int] = field(default_factory=dict)

    def copy(self, new_hour: int) -> "InventoryNode":
        return InventoryNode(
            airport=self.airport,
            global_hour=new_hour,
            available_kits=dict(self.available_kits),
        )

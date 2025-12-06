"""Utilities for translating between (day, hour) and a global hour index."""
from __future__ import annotations

from typing import Tuple

MAX_DAY = 30
# Last playable global hour index (0-based). Day 0..29, hour 0..23 -> 0..719.
MAX_HOUR = MAX_DAY * 24 - 1


def to_global_hour(day: int, hour: int) -> int:
    """Convert (day, hour) into a single global hour index."""
    return day * 24 + hour


def from_global_hour(global_hour: int) -> Tuple[int, int]:
    """Convert a global hour index back into (day, hour)."""
    day = global_hour // 24
    hour = global_hour % 24
    return day, hour

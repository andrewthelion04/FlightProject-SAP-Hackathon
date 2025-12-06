"""Utility helpers for time indexing."""
from __future__ import annotations

MAX_DAY = 30
MAX_HOUR = MAX_DAY * 24


def to_global_hour(day: int, hour: int) -> int:
    return day * 24 + hour


def from_global_hour(t: int) -> tuple[int, int]:
    day = t // 24
    hour = t % 24
    return day, hour

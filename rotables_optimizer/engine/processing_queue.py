from dataclasses import dataclass


@dataclass
class ProcessingTask:
    """Represents kits undergoing cleaning/processing before returning to stock."""

    cabin: str
    quantity: int
    ready_day: int
    ready_hour: int

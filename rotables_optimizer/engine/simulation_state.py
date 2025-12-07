"""In-memory representation of the world as seen by the strategy layer."""

from dataclasses import dataclass, field
from typing import Dict, List
from uuid import UUID

from rotables_optimizer.domain.contracts import (
    RoundOutcome,
    FlightUpdate,
    FlightEventKind,
)


@dataclass
class SimulationState:
    """
    Tracks flight timelines and cost history so the strategy can make informed
    decisions without touching IO or networking.
    """

    aircraft_capacities: Dict[str, Dict] = field(default_factory=dict)

    active_flights: Dict[UUID, FlightUpdate] = field(default_factory=dict)
    scheduled_flights: Dict[UUID, FlightUpdate] = field(default_factory=dict)

    pending_loads: List[FlightUpdate] = field(default_factory=list)
    recent_landings: List[FlightUpdate] = field(default_factory=list)

    cost_timeline: List[Dict] = field(default_factory=list)

    def ingest_backend_round(self, outcome: RoundOutcome) -> None:
        """Update internal indices based on backend response for the current hour."""
        self.pending_loads = []
        self.recent_landings = []

        for event in outcome.flight_events:
            # Maintain scheduled list for forecasting.
            if event.event_type in (FlightEventKind.SCHEDULED, FlightEventKind.CHECKED_IN):
                self.scheduled_flights[event.flight_id] = event
            elif event.event_type == FlightEventKind.LANDED:
                self.scheduled_flights.pop(event.flight_id, None)

            # Track active flights requiring immediate load decisions.
            if event.event_type == FlightEventKind.CHECKED_IN:
                self.active_flights[event.flight_id] = event
                self.pending_loads.append(event)
            elif event.event_type == FlightEventKind.LANDED:
                self.active_flights.pop(event.flight_id, None)
                self.recent_landings.append(event)

        self.cost_timeline.append(
            {
                "day": outcome.day,
                "hour": outcome.hour,
                "total_cost": outcome.total_cost,
            }
        )

    def pull_pending_loads(self) -> List[FlightUpdate]:
        """Return the list of flights needing a load decision this hour."""
        return list(self.pending_loads)

    def pull_recent_landings(self) -> List[FlightUpdate]:
        """Return flights that just landed this hour."""
        return list(self.recent_landings)

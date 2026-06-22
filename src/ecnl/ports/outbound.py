"""Outbound ports — interfaces the application layer depends on.

These are the contracts that driven adapters must satisfy. The application
layer only imports these protocols; it never references concrete
implementations. This is what makes the hexagonal boundary testable and
swappable (real HTTP adapter vs. an in-memory stub).
"""

from typing import Protocol

from ..domain.models import (
    Club,
    Event,
    EventOverview,
    Match,
    Standings,
    Team,
)


class DiscoveryPort(Protocol):
    """Contract for resolving human queries to events.

    There is no public event-list endpoint, so discovery walks the league/gender
    org club lists to enumerate events and classifies each by name.
    """

    async def find_events(
        self,
        league: str | None = None,
        gender: str | None = None,
        season: str | None = None,
    ) -> list[Event]:
        """Return events matching the given filters (None means "any")."""
        ...


class ECNLAPIPort(Protocol):
    """Contract for the upstream ECNL data source (AthleteOne API)."""

    async def get_event(self, event_id: int) -> Event:
        """Return event metadata (name, location, dates) by event ID.

        Raises:
            ECNLNotFoundError: If no event with that ID exists.
        """
        ...

    async def get_event_overview(self, event_id: int) -> EventOverview:
        """Return the division/flight navigation tree for an event.

        Raises:
            ECNLNotFoundError: If no event with that ID exists.
        """
        ...

    async def get_standings(self, event_id: int, division_id: int, flight_id: int) -> Standings:
        """Return the standings table for a flight."""
        ...

    async def get_schedule(self, event_id: int, flight_id: int) -> list[Match]:
        """Return all matches for a flight, in source order."""
        ...

    async def get_team_schedule(self, event_id: int, team_id: int) -> list[Match]:
        """Return all matches for a single team within an event."""
        ...

    async def get_flight_teams(self, flight_id: int) -> list[Team]:
        """Return the teams competing in a flight."""
        ...

    async def get_event_teams(self, event_id: int) -> list[Team]:
        """Return every team registered for an event."""
        ...

    async def get_clubs(self, event_id: int) -> list[Club]:
        """Return the clubs participating in an event."""
        ...

    async def get_match(self, match_token: str) -> dict:
        """Return raw match-detail / box-score data for a match token.

        The detail payload is highly variable, so it is returned as the decoded
        JSON ``data`` object rather than a fixed domain model.
        """
        ...

    async def get_brackets(self, event_id: int, flight_id: int) -> dict:
        """Return raw playoff-bracket data for a flight.

        Brackets are tree-shaped and event-specific, so the decoded ``data``
        object is returned directly.
        """
        ...

    async def get_org_club_events(self, org_id: int) -> list[int]:
        """Return the distinct active event IDs across an org's clubs.

        Used by discovery to enumerate the events for a league/gender org
        without a dedicated event-list endpoint.
        """
        ...

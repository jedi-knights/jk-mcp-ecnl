"""Outbound adapter — translates domain calls into AthleteOne API HTTP requests.

This is the only place in the codebase that knows about:
- The AthleteOne API host and URL structure
- The ``{"result": "success", "data": ...}`` response envelope
- How to translate non-2xx responses and error envelopes into domain errors

All endpoints are public read-only JSON; no authentication header is required
(verified — the site's own HTTP interceptor attaches none for public calls).
The wire-format -> domain-model mapping lives in athleteone_parsers.py.
"""

import asyncio
import logging
from typing import Any

import httpx

from ...domain.exceptions import ECNLNotFoundError, UpstreamAPIError
from ...domain.models import Club, Event, EventOverview, Match, Standings, Team
from .athleteone_parsers import (
    parse_club,
    parse_division_with_flights,
    parse_event,
    parse_match,
    parse_standing_row,
    parse_team,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.athleteone.com"
_API = "/api"


class AthleteOneAdapter:
    """Calls the AthleteOne (Total Global Sports) public API for ECNL/ECRL data.

    The underlying httpx.AsyncClient is created once at construction and reused
    for all requests so the TCP connection pool is retained across calls —
    avoiding a fresh TCP+TLS handshake on every API call.
    """

    def __init__(self, base_url: str = _DEFAULT_BASE_URL, client: httpx.AsyncClient | None = None) -> None:
        """Initialize the adapter with an optional HTTP client.

        Args:
            base_url: Base URL of the AthleteOne API. Defaults to
                https://api.athleteone.com.
            client: An httpx.AsyncClient to reuse across all requests. Inject a
                pre-configured mock in tests.
        """
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def _get(self, path: str) -> Any:
        """Execute a GET request and return the unwrapped ``data`` payload.

        Args:
            path: URL path relative to base_url (including the ``/api`` prefix).

        Returns:
            The value of the response's ``data`` field.

        Raises:
            ECNLNotFoundError: If the server returns HTTP 404.
            UpstreamAPIError: For any other non-2xx status or an error envelope.
        """
        logger.debug("GET %s", path)
        try:
            response = await self._client.get(path)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ECNLNotFoundError(f"Not found: {path}") from exc
            raise UpstreamAPIError(f"Upstream error {exc.response.status_code}: {path}") from exc
        except httpx.HTTPError as exc:
            raise UpstreamAPIError(f"Request failed: {path}: {exc}") from exc
        return _unwrap(response.json(), path)

    async def get_event(self, event_id: int) -> Event:
        """Return event metadata by event ID."""
        data = await self._get(f"{_API}/team/get-event-details-by-eventid/{event_id}")
        if not data:
            raise ECNLNotFoundError(f"Event not found: {event_id}")
        return parse_event(data)

    async def get_event_overview(self, event_id: int) -> EventOverview:
        """Return the division/flight navigation tree plus event metadata.

        Fetches event details and the schedule-or-standings index concurrently
        and merges them into a single overview.
        """
        event, tree = await asyncio.gather(
            self.get_event(event_id),
            self._get(f"{_API}/Event/get-event-schedule-or-standings/{event_id}"),
        )
        divisions = [parse_division_with_flights(d, "girls") for d in (tree or {}).get("girlsDivAndFlightList", [])] + [
            parse_division_with_flights(d, "boys") for d in (tree or {}).get("boysDivAndFlightList", [])
        ]
        return EventOverview(event=event, divisions=divisions)

    async def get_standings(self, event_id: int, division_id: int, flight_id: int) -> Standings:
        """Return the standings table for a flight.

        The feed groups standings into one or more flight groups; rows from all
        groups are flattened in source order.
        """
        data = await self._get(f"{_API}/Event/get-standings-by-div-and-flight/{division_id}/{flight_id}/{event_id}")
        rows = [parse_standing_row(row) for group in (data or []) for row in group.get("teamStandings", [])]
        return Standings(event_id=event_id, division_id=division_id, flight_id=flight_id, rows=rows)

    async def get_schedule(self, event_id: int, flight_id: int) -> list[Match]:
        """Return all matches for a flight (complexID segment is fixed at 0)."""
        data = await self._get(f"{_API}/Event/get-schedules-by-flight/{event_id}/{flight_id}/0")
        return [parse_match(m) for m in (data or [])]

    async def get_team_schedule(self, event_id: int, team_id: int) -> list[Match]:
        """Return all matches for a single team within an event."""
        data = await self._get(f"{_API}/Event/get-game-list-by-eventID-and-teamID/{event_id}/{team_id}")
        return [parse_match(m) for m in (data or [])]

    async def get_flight_teams(self, flight_id: int) -> list[Team]:
        """Return the teams competing in a flight."""
        data = await self._get(f"{_API}/Event/get-team-list-by-flight/{flight_id}")
        return [parse_team(t) for t in (data or [])]

    async def get_event_teams(self, event_id: int) -> list[Team]:
        """Return every team registered for an event."""
        data = await self._get(f"{_API}/Event/get-team-list/{event_id}")
        return [parse_team(t) for t in (data or [])]

    async def get_clubs(self, event_id: int) -> list[Club]:
        """Return the clubs participating in an event."""
        data = await self._get(f"{_API}/Event/get-org-club-list-by-event/{event_id}")
        return [parse_club(c) for c in (data or [])]

    async def get_match(self, match_token: str) -> dict:
        """Return raw match-detail data for a match token."""
        data = await self._get(f"{_API}/Event/get-match-detail-by-token/{match_token}")
        return data or {}

    async def get_brackets(self, event_id: int, flight_id: int) -> dict:
        """Return raw playoff-bracket data for a flight."""
        data = await self._get(f"{_API}/Event/get-flight-brackets-by-flight/{event_id}/{flight_id}")
        return data or {}

    async def get_org_club_events(self, org_id: int) -> list[int]:
        """Return distinct active event IDs across an org's clubs.

        Each club entry carries an ``eventID`` (0 when the club has no active
        event); the distinct non-zero values are the org's current events.
        """
        data = await self._get(f"{_API}/Event/get-org-club-list-by-orgID/{org_id}")
        event_ids = {eid for club in (data or []) if (eid := club.get("eventID"))}
        return sorted(event_ids)


def _unwrap(payload: Any, path: str) -> Any:
    """Return the ``data`` field of a TGS envelope, raising on error envelopes.

    The API returns ``{"result": "success", "data": ...}`` on success and a
    ``{"result": "error", ...}`` (sometimes with HTTP 200) on failure.

    Raises:
        UpstreamAPIError: If the envelope reports an error or is malformed.
    """
    if not isinstance(payload, dict):
        raise UpstreamAPIError(f"Unexpected response shape from {path}")
    result = str(payload.get("result", payload.get("Result", ""))).lower()
    if result and result != "success":
        message = payload.get("message") or payload.get("Message") or "error"
        raise UpstreamAPIError(f"Upstream error from {path}: {message}")
    return payload.get("data")

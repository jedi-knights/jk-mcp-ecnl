"""Application service — the core of the hexagonal architecture.

Orchestrates work by delegating to outbound ports. It knows nothing about MCP,
HTTP, or JSON — those are adapter concerns. RPI math lives in the pure ``_rpi``
module; this service only extracts results and hands them off.
"""

import time
from collections import OrderedDict
from collections.abc import Callable

from ..domain.exceptions import ECNLNotFoundError
from ..domain.models import (
    Club,
    Event,
    EventOverview,
    Match,
    MatchResult,
    Standings,
    Team,
    TeamRPI,
)
from ..ports.outbound import DiscoveryPort, ECNLAPIPort
from ._rpi import compute_rpi

_VALID_LEAGUES = ("ECNL", "ECRL")
_VALID_GENDERS = ("girls", "boys")


def _validate_enum(value: str | None, valid: tuple[str, ...], label: str) -> str | None:
    """Normalize and validate an optional enum-like argument.

    Returns the normalized value, or None when ``value`` is None.

    Raises:
        ValueError: If a non-None value is not in ``valid``.
    """
    if value is None:
        return None
    normalized = value.strip().upper() if label == "league" else value.strip().lower()
    if normalized not in valid:
        raise ValueError(f"Invalid {label}={value!r}. Must be one of: {', '.join(valid)}")
    return normalized


class ECNLService:
    """Coordinates ECNL/ECRL data lookups through the outbound ports.

    Two driven ports are injected: ``repo`` (the AthleteOne data feed) and
    ``discovery`` (resolves league/gender/season queries to events).
    """

    def __init__(
        self,
        repo: ECNLAPIPort,
        discovery: DiscoveryPort,
        now: Callable[[], float] = time.monotonic,
        rpi_ttl_seconds: float = 60.0,
        rpi_cache_size: int = 32,
    ) -> None:
        """Initialize the service.

        Args:
            repo: The AthleteOne data port.
            discovery: The event-discovery port.
            now: Monotonic clock for the RPI table memo. Injectable for testing.
            rpi_ttl_seconds: TTL of a memoized RPI table — matches the schedule
                cache lifetime, since the table is a pure transform of the schedule.
            rpi_cache_size: Max distinct (event, flight, tie_weight) tables retained.
        """
        self._repo = repo
        self._discovery = discovery
        self._now = now
        self._rpi_ttl = rpi_ttl_seconds
        self._rpi_cache_size = rpi_cache_size
        # LRU + TTL memo so get_rpi and get_team_rpi share one computation per
        # (event, flight, tie_weight) instead of rebuilding the table per call.
        self._rpi_cache: OrderedDict[tuple[int, int, float], tuple[float, list[TeamRPI]]] = OrderedDict()

    # -- discovery & navigation --------------------------------------------

    async def find_events(
        self,
        league: str | None = None,
        gender: str | None = None,
        season: str | None = None,
    ) -> list[Event]:
        """Find ECNL/ECRL events by league, gender, and/or season."""
        league_n = _validate_enum(league, _VALID_LEAGUES, "league")
        gender_n = _validate_enum(gender, _VALID_GENDERS, "gender")
        return await self._discovery.find_events(league_n, gender_n, season)

    async def get_event_overview(self, event_id: int) -> EventOverview:
        """Return the division/flight tree and metadata for an event."""
        return await self._repo.get_event_overview(event_id)

    # -- standings & schedule ----------------------------------------------

    async def get_standings(self, event_id: int, division_id: int, flight_id: int) -> Standings:
        """Return the standings table for a flight."""
        return await self._repo.get_standings(event_id, division_id, flight_id)

    async def get_schedule(self, event_id: int, flight_id: int) -> list[Match]:
        """Return all matches for a flight."""
        return await self._repo.get_schedule(event_id, flight_id)

    async def get_team_schedule(self, event_id: int, team_id: int) -> list[Match]:
        """Return all matches for a single team within an event."""
        return await self._repo.get_team_schedule(event_id, team_id)

    # -- teams, clubs, matches, brackets -----------------------------------

    async def get_teams(self, flight_id: int) -> list[Team]:
        """Return the teams competing in a flight."""
        return await self._repo.get_flight_teams(flight_id)

    async def get_clubs(self, event_id: int) -> list[Club]:
        """Return the clubs participating in an event."""
        return await self._repo.get_clubs(event_id)

    async def get_match(self, match_token: str) -> dict:
        """Return raw match-detail data for a match token."""
        return await self._repo.get_match(match_token)

    async def get_brackets(self, event_id: int, flight_id: int) -> dict:
        """Return raw playoff-bracket data for a flight."""
        return await self._repo.get_brackets(event_id, flight_id)

    # -- analytics: results & RPI ------------------------------------------

    async def get_results(self, event_id: int, flight_id: int) -> list[MatchResult]:
        """Return completed match results for a flight (played games only).

        This is the raw feed RPI builds on, exposed on its own because "what are
        the final scores so far?" is a common question.
        """
        schedule = await self._repo.get_schedule(event_id, flight_id)
        return [
            MatchResult(
                home_team=m.home_team,
                away_team=m.away_team,
                home_score=m.home_score,  # type: ignore[arg-type]
                away_score=m.away_score,  # type: ignore[arg-type]
            )
            for m in schedule
            if m.is_played
        ]

    async def get_rpi(self, event_id: int, flight_id: int, tie_weight: float = 1 / 3) -> list[TeamRPI]:
        """Return the RPI ranking for every team in a flight.

        Args:
            event_id: The event the flight belongs to.
            flight_id: The flight (conference tier) to rate.
            tie_weight: WP tie weight — 1/3 (2024 convention) or 1/2 (pre-2024).

        The rating pool is the flight: opponents and their opponents are taken
        from the flight's own completed games. The computed table is memoized
        (see ``_rpi_table``), so repeat calls within the TTL are free.
        """
        return await self._rpi_table(event_id, flight_id, tie_weight)

    async def get_team_rpi(self, event_id: int, flight_id: int, team: str, tie_weight: float = 1 / 3) -> TeamRPI:
        """Return one team's RPI with its component breakdown.

        Reuses the memoized flight table — OWP/OOWP need the whole graph, so the
        table is computed once and shared rather than rebuilt per team.

        Args:
            team: Team name (case-insensitive substring match against the flight's teams).

        Raises:
            ECNLNotFoundError: If no team in the flight matches ``team``.
        """
        table = await self._rpi_table(event_id, flight_id, tie_weight)
        needle = team.strip().lower()
        for row in table:
            if needle in row.team.lower():
                return row
        raise ECNLNotFoundError(f"No team matching {team!r} in flight {flight_id}")

    async def _rpi_table(self, event_id: int, flight_id: int, tie_weight: float) -> list[TeamRPI]:
        """Return the (memoized) RPI table for a flight.

        The table is a pure transform of the flight schedule, which the outbound
        cache already keeps for the same lifetime; memoizing the transform avoids
        recomputing it across get_rpi/get_team_rpi calls. Bounded by an LRU cap
        and a TTL, so the cache cannot grow without limit.
        """
        key = (event_id, flight_id, tie_weight)
        cached = self._rpi_cache.get(key)
        if cached is not None and self._now() < cached[0]:
            self._rpi_cache.move_to_end(key)
            return cached[1]

        results = await self.get_results(event_id, flight_id)
        table = compute_rpi(results, wp_tie_weight=tie_weight)
        self._rpi_cache[key] = (self._now() + self._rpi_ttl, table)
        self._rpi_cache.move_to_end(key)
        if len(self._rpi_cache) > self._rpi_cache_size:
            self._rpi_cache.popitem(last=False)
        return table

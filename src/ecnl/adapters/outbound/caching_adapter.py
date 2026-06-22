"""CachingAdapter — transparent TTL-cache decorator for ECNLAPIPort.

Wraps any ECNLAPIPort implementation and caches successful results in a plain
dict keyed by method name plus arguments. The clock is injectable so tests can
control expiry without sleeping.

Two TTLs: event structure (divisions, flights, teams, clubs, org events) changes
rarely and uses the long TTL; standings and schedules move during match days and
use a short TTL.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from ...domain.models import Club, Event, EventOverview, Match, Standings, Team
from ...ports.outbound import ECNLAPIPort

logger = logging.getLogger(__name__)


def _cache_key(method: str, args: tuple[Any, ...]) -> str:
    """Build a deterministic cache key from a method name and its arguments."""
    return json.dumps({"method": method, "args": args}, sort_keys=True, default=str)


class CachingAdapter:
    """Decorates an ECNLAPIPort with a TTL-based in-memory cache."""

    def __init__(
        self,
        inner: ECNLAPIPort,
        ttl_seconds: float = 300.0,
        live_ttl_seconds: float = 60.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the caching adapter.

        Args:
            inner: The ECNLAPIPort implementation to wrap.
            ttl_seconds: Default TTL for stable structural data.
            live_ttl_seconds: Shorter TTL for standings/schedules (live during matches).
            now: Callable returning the current monotonic time. Injectable for testing.
        """
        self._inner = inner
        self._ttl = ttl_seconds
        self._live_ttl = live_ttl_seconds
        self._now = now
        self._cache: dict[str, tuple[float, Any]] = {}

    async def _get_or_fetch(self, method_name: str, ttl: float, *args: Any) -> Any:
        """Return a cached result or fetch from the inner adapter and cache it."""
        key = _cache_key(method_name, args)
        entry = self._cache.get(key)
        if entry is not None:
            expiry, result = entry
            if self._now() < expiry:
                logger.debug("Cache hit for %s", method_name)
                return result
            del self._cache[key]

        logger.debug("Cache miss for %s, fetching from inner adapter", method_name)
        method = getattr(self._inner, method_name)
        result = await method(*args)
        self._cache[key] = (self._now() + ttl, result)
        return result

    async def get_event(self, event_id: int) -> Event:
        return await self._get_or_fetch("get_event", self._ttl, event_id)

    async def get_event_overview(self, event_id: int) -> EventOverview:
        return await self._get_or_fetch("get_event_overview", self._ttl, event_id)

    async def get_standings(self, event_id: int, division_id: int, flight_id: int) -> Standings:
        return await self._get_or_fetch("get_standings", self._live_ttl, event_id, division_id, flight_id)

    async def get_schedule(self, event_id: int, flight_id: int) -> list[Match]:
        return await self._get_or_fetch("get_schedule", self._live_ttl, event_id, flight_id)

    async def get_team_schedule(self, event_id: int, team_id: int) -> list[Match]:
        return await self._get_or_fetch("get_team_schedule", self._live_ttl, event_id, team_id)

    async def get_flight_teams(self, flight_id: int) -> list[Team]:
        return await self._get_or_fetch("get_flight_teams", self._ttl, flight_id)

    async def get_event_teams(self, event_id: int) -> list[Team]:
        return await self._get_or_fetch("get_event_teams", self._ttl, event_id)

    async def get_clubs(self, event_id: int) -> list[Club]:
        return await self._get_or_fetch("get_clubs", self._ttl, event_id)

    async def get_match(self, match_token: str) -> dict:
        return await self._get_or_fetch("get_match", self._live_ttl, match_token)

    async def get_brackets(self, event_id: int, flight_id: int) -> dict:
        return await self._get_or_fetch("get_brackets", self._live_ttl, event_id, flight_id)

    async def get_org_club_events(self, org_id: int) -> list[int]:
        return await self._get_or_fetch("get_org_club_events", self._ttl, org_id)

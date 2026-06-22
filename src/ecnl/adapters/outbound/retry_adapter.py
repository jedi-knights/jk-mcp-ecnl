"""RetryingAdapter — transparent retry decorator for ECNLAPIPort.

Wraps any ECNLAPIPort implementation and retries on UpstreamAPIError using
exponential backoff. ECNLNotFoundError is not retried because a 404 is a
definitive answer, not a transient failure.

The sleep callable is injectable so tests can assert on backoff timing without
actually sleeping.
"""

import asyncio
import logging
from collections.abc import Callable

from ...domain.exceptions import ECNLNotFoundError, UpstreamAPIError
from ...domain.models import Club, Event, EventOverview, Match, Standings, Team
from ...ports.outbound import ECNLAPIPort

logger = logging.getLogger(__name__)


class RetryingAdapter:
    """Decorates an ECNLAPIPort with exponential-backoff retry on UpstreamAPIError.

    ECNLNotFoundError propagates immediately — a 404 will not become a 200 on retry.
    """

    def __init__(
        self,
        inner: ECNLAPIPort,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        """Initialize the retrying adapter.

        Args:
            inner: The ECNLAPIPort implementation to wrap.
            max_attempts: Total attempts before giving up (minimum 1).
            delay_seconds: Base delay in seconds; doubled on each retry.
            sleep: Async callable used to wait between retries. Injectable for testing.
        """
        self._inner = inner
        self._max_attempts = max(1, max_attempts)
        self._delay_seconds = delay_seconds
        self._sleep = sleep

    async def _retry(self, method_name: str, *args: object) -> object:
        """Execute an inner port method with retry on UpstreamAPIError.

        Args:
            method_name: Name of the method on the inner adapter to call.
            *args: Positional arguments forwarded to the method.

        Raises:
            ECNLNotFoundError: Immediately, without retrying.
            UpstreamAPIError: After all attempts are exhausted.
        """
        method = getattr(self._inner, method_name)
        last_error: UpstreamAPIError | None = None
        for attempt in range(self._max_attempts):
            try:
                return await method(*args)
            except ECNLNotFoundError:
                raise
            except UpstreamAPIError as exc:
                last_error = exc
                if attempt < self._max_attempts - 1:
                    delay = self._delay_seconds * (2**attempt)
                    logger.warning(
                        "Attempt %d/%d failed for %s, retrying in %.1fs: %s",
                        attempt + 1,
                        self._max_attempts,
                        method_name,
                        delay,
                        exc,
                    )
                    await self._sleep(delay)
        raise last_error  # type: ignore[misc]

    async def get_event(self, event_id: int) -> Event:
        return await self._retry("get_event", event_id)  # type: ignore[return-value]

    async def get_event_overview(self, event_id: int) -> EventOverview:
        return await self._retry("get_event_overview", event_id)  # type: ignore[return-value]

    async def get_standings(self, event_id: int, division_id: int, flight_id: int) -> Standings:
        return await self._retry("get_standings", event_id, division_id, flight_id)  # type: ignore[return-value]

    async def get_schedule(self, event_id: int, flight_id: int) -> list[Match]:
        return await self._retry("get_schedule", event_id, flight_id)  # type: ignore[return-value]

    async def get_team_schedule(self, event_id: int, team_id: int) -> list[Match]:
        return await self._retry("get_team_schedule", event_id, team_id)  # type: ignore[return-value]

    async def get_flight_teams(self, flight_id: int) -> list[Team]:
        return await self._retry("get_flight_teams", flight_id)  # type: ignore[return-value]

    async def get_event_teams(self, event_id: int) -> list[Team]:
        return await self._retry("get_event_teams", event_id)  # type: ignore[return-value]

    async def get_clubs(self, event_id: int) -> list[Club]:
        return await self._retry("get_clubs", event_id)  # type: ignore[return-value]

    async def get_match(self, match_token: str) -> dict:
        return await self._retry("get_match", match_token)  # type: ignore[return-value]

    async def get_brackets(self, event_id: int, flight_id: int) -> dict:
        return await self._retry("get_brackets", event_id, flight_id)  # type: ignore[return-value]

    async def get_org_club_events(self, org_id: int) -> list[int]:
        return await self._retry("get_org_club_events", org_id)  # type: ignore[return-value]

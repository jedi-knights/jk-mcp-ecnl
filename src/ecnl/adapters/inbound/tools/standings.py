"""Standings tool."""

import logging

from mcp.server.fastmcp import FastMCP

from ....application.service import ECNLService
from ..formatters import _fmt_standings
from ._base import _READ_ANNOTATIONS, _safe_call

logger = logging.getLogger(__name__)


def register_standings_tools(mcp: FastMCP, service: ECNLService) -> None:
    """Register the standings tool on ``mcp``."""

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_standings(event_id: int, division_id: int, flight_id: int) -> str:
        """Get the standings table for a flight.

        Returns each team's W-L-D record, points, and points-per-game ordered as
        the league publishes them. Get the division and flight IDs from
        get_event_overview.

        Args:
            event_id: Numeric event ID (e.g. 3933).
            division_id: Age-group division ID from get_event_overview.
            flight_id: Flight ID from get_event_overview.
        """
        logger.info("tool=get_standings event_id=%r division_id=%r flight_id=%r", event_id, division_id, flight_id)
        return await _safe_call(service.get_standings(event_id, division_id, flight_id), _fmt_standings)

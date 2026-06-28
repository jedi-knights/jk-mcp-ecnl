"""Event discovery and overview tools."""

import logging

from mcp.server.fastmcp import FastMCP

from ....application.service import ECNLService
from ....ports.inbound import Authorizer
from ..formatters import _fmt_event_overview, _fmt_events
from ._base import _READ_ANNOTATIONS, _safe_call_authorized

logger = logging.getLogger(__name__)


def register_event_tools(mcp: FastMCP, service: ECNLService, authorizer: Authorizer) -> None:
    """Register the event discovery/overview tools on ``mcp``."""

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def find_events(league: str | None = None, gender: str | None = None, season: str | None = None) -> str:
        """Find ECNL or ECRL events (conferences) and their event IDs.

        This is the starting point: it maps a human description to the numeric
        event IDs every other tool needs. Filter by any combination of league,
        gender, and season. With no arguments it returns all current events.

        Args:
            league: "ECNL" or "ECRL" (the ECNL Regional League). Omit for both.
            gender: "girls" or "boys". Omit for both.
            season: Season label like "2025-26". Omit for all seasons present.
        """
        logger.info("tool=find_events league=%r gender=%r season=%r", league, gender, season)
        return await _safe_call_authorized(
            authorizer, "find_events", service.find_events(league, gender, season), _fmt_events
        )

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_event_overview(event_id: int) -> str:
        """Get the divisions and flights for an event.

        Returns each age-group division and its flights, with the flight ID,
        flight tier (ECNL/ECRL), and team count. Use the flight ID with
        get_standings, get_schedule, get_teams, and the RPI tools.

        Args:
            event_id: Numeric event ID from find_events (e.g. 3933).
        """
        logger.info("tool=get_event_overview event_id=%r", event_id)
        return await _safe_call_authorized(
            authorizer, "get_event_overview", service.get_event_overview(event_id), _fmt_event_overview
        )

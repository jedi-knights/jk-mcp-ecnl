"""Schedule tools."""

import logging

from mcp.server.fastmcp import FastMCP

from ....application.service import ECNLService
from ....ports.inbound import Authorizer
from ..formatters import _fmt_schedule
from ._base import _READ_ANNOTATIONS, _safe_call_authorized

logger = logging.getLogger(__name__)


def register_schedule_tools(mcp: FastMCP, service: ECNLService, authorizer: Authorizer) -> None:
    """Register the schedule tools on ``mcp``."""

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_schedule(event_id: int, flight_id: int) -> str:
        """Get all matches for a flight.

        Returns each match's date, time, venue, teams, and score (if played).
        Get the flight ID from get_event_overview.

        Args:
            event_id: Numeric event ID (e.g. 3933).
            flight_id: Flight ID from get_event_overview.
        """
        logger.info("tool=get_schedule event_id=%r flight_id=%r", event_id, flight_id)
        return await _safe_call_authorized(
            authorizer, "get_schedule", service.get_schedule(event_id, flight_id), _fmt_schedule
        )

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_team_schedule(event_id: int, team_id: int) -> str:
        """Get all matches for one team within an event.

        Returns the team's full slate — date, opponent, venue, and score.

        Args:
            event_id: Numeric event ID (e.g. 3933).
            team_id: Team ID from get_teams or the standings table.
        """
        logger.info("tool=get_team_schedule event_id=%r team_id=%r", event_id, team_id)
        return await _safe_call_authorized(
            authorizer, "get_team_schedule", service.get_team_schedule(event_id, team_id), _fmt_schedule
        )

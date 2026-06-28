"""Team and club tools."""

import logging

from mcp.server.fastmcp import FastMCP

from ....application.service import ECNLService
from ....ports.inbound import Authorizer
from ..formatters import _fmt_clubs, _fmt_teams
from ._base import _READ_ANNOTATIONS, _safe_call_authorized

logger = logging.getLogger(__name__)


def register_team_tools(mcp: FastMCP, service: ECNLService, authorizer: Authorizer) -> None:
    """Register the team/club tools on ``mcp``."""

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_teams(flight_id: int) -> str:
        """Get the teams competing in a flight.

        Returns each team's ID, name, and head coach. Use a team ID with
        get_team_schedule. Get the flight ID from get_event_overview.

        Args:
            flight_id: Flight ID from get_event_overview.
        """
        logger.info("tool=get_teams flight_id=%r", flight_id)
        return await _safe_call_authorized(authorizer, "get_teams", service.get_teams(flight_id), _fmt_teams)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_clubs(event_id: int) -> str:
        """Get the clubs participating in an event.

        Returns each club's ID, name, and location.

        Args:
            event_id: Numeric event ID (e.g. 3933).
        """
        logger.info("tool=get_clubs event_id=%r", event_id)
        return await _safe_call_authorized(authorizer, "get_clubs", service.get_clubs(event_id), _fmt_clubs)

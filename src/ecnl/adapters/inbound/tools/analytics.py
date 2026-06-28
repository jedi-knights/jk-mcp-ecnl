"""Analytics tools — extracted results and RPI."""

import logging

from mcp.server.fastmcp import FastMCP

from ....application.service import ECNLService
from ....ports.inbound import Authorizer
from ..formatters import _fmt_results, _fmt_rpi, _fmt_team_rpi
from ._base import _READ_ANNOTATIONS, _safe_call_authorized

logger = logging.getLogger(__name__)


def register_analytics_tools(mcp: FastMCP, service: ECNLService, authorizer: Authorizer) -> None:
    """Register the results and RPI tools on ``mcp``."""

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_results(event_id: int, flight_id: int) -> str:
        """Get the completed match results for a flight.

        Returns only games that have been played, with final scores. This is the
        raw data the RPI tools build on.

        Args:
            event_id: Numeric event ID (e.g. 3933).
            flight_id: Flight ID from get_event_overview.
        """
        logger.info("tool=get_results event_id=%r flight_id=%r", event_id, flight_id)
        return await _safe_call_authorized(
            authorizer, "get_results", service.get_results(event_id, flight_id), _fmt_results
        )

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_rpi(event_id: int, flight_id: int, tie_weight: float = 1 / 3) -> str:
        """Compute the RPI ranking for every team in a flight.

        RPI = 0.25·WP + 0.50·OWP + 0.25·OOWP, computed from the flight's
        completed games. Returns each team's WP/OWP/OOWP components and final RPI,
        ranked. Early in a season, sparse results make RPI noisy.

        Args:
            event_id: Numeric event ID (e.g. 3933).
            flight_id: Flight ID from get_event_overview.
            tie_weight: Tie value in the winning-percentage element — 1/3 (the
                2024 convention, default) or 0.5 (pre-2024).
        """
        logger.info("tool=get_rpi event_id=%r flight_id=%r tie_weight=%r", event_id, flight_id, tie_weight)
        return await _safe_call_authorized(
            authorizer, "get_rpi", service.get_rpi(event_id, flight_id, tie_weight), _fmt_rpi
        )

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_team_rpi(event_id: int, flight_id: int, team: str, tie_weight: float = 1 / 3) -> str:
        """Compute one team's RPI with its component breakdown.

        Args:
            event_id: Numeric event ID (e.g. 3933).
            flight_id: Flight ID from get_event_overview.
            team: Team name (or a distinctive part of it), case-insensitive.
            tie_weight: WP tie value — 1/3 (default) or 0.5 (pre-2024).
        """
        logger.info("tool=get_team_rpi event_id=%r flight_id=%r team=%r", event_id, flight_id, team)
        return await _safe_call_authorized(
            authorizer, "get_team_rpi", service.get_team_rpi(event_id, flight_id, team, tie_weight), _fmt_team_rpi
        )

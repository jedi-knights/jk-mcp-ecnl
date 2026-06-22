"""Match-detail and bracket tools.

These return the upstream payload as pretty-printed JSON because match detail
and bracket shapes vary by event and are not normalized into domain models.
"""

import logging

from mcp.server.fastmcp import FastMCP

from ....application.service import ECNLService
from ..formatters import _fmt_raw
from ._base import _READ_ANNOTATIONS, _safe_call

logger = logging.getLogger(__name__)


def register_match_tools(mcp: FastMCP, service: ECNLService) -> None:
    """Register the match-detail and bracket tools on ``mcp``."""

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_match(match_token: str) -> str:
        """Get detailed information for a single match by its token.

        Returns the match-detail / box-score payload (teams, score, events) as
        JSON. The match token comes from a schedule entry's match data.

        Args:
            match_token: The match's token/ID string.
        """
        logger.info("tool=get_match match_token=%r", match_token)
        return await _safe_call(service.get_match(match_token), _fmt_raw)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_brackets(event_id: int, flight_id: int) -> str:
        """Get the playoff bracket for a flight, if one exists.

        Returns the bracket structure as JSON. Many regular-season flights have
        no bracket; in that case the payload is empty.

        Args:
            event_id: Numeric event ID (e.g. 3933).
            flight_id: Flight ID from get_event_overview.
        """
        logger.info("tool=get_brackets event_id=%r flight_id=%r", event_id, flight_id)
        return await _safe_call(service.get_brackets(event_id, flight_id), _fmt_raw)

"""Shared infrastructure for inbound MCP tool modules.

``_safe_call`` translates domain exceptions raised by the application service
into readable error strings the LLM can present. ``_READ_ANNOTATIONS`` flags
tools as read-only / idempotent so MCP clients can reason about them.
"""

import logging
from collections.abc import Awaitable, Callable

from mcp.types import ToolAnnotations

from ....domain.exceptions import ECNLNotFoundError, UpstreamAPIError

logger = logging.getLogger(__name__)

_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
"""Annotation for tools that make read-only, idempotent calls to upstream APIs."""


async def _safe_call[T](coro: Awaitable[T], fmt: Callable[[T], str]) -> str:
    """Await coro, format the result, and convert domain exceptions to error strings.

    Args:
        coro: An awaitable returning the raw domain result.
        fmt: A callable converting the domain result to a formatted string.

    Returns:
        The formatted string, or an error message if a domain exception was raised.
    """
    try:
        return fmt(await coro)
    except ECNLNotFoundError as exc:
        logger.warning("Not found: %s", exc)
        return f"Not found: {exc}"
    except UpstreamAPIError as exc:
        logger.error("Upstream API error: %s", exc)
        return f"Upstream error: {exc}"
    except ValueError as exc:
        logger.warning("Invalid request: %s", exc)
        return f"Invalid request: {exc}"

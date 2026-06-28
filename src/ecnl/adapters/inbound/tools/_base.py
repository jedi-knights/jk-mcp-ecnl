"""Shared infrastructure for inbound MCP tool modules.

`_safe_call` translates domain exceptions raised by the application service
into readable error strings the LLM can present. `_READ_ANNOTATIONS` flags
tools as read-only / idempotent so MCP clients can reason about them.
`_authorize_tool` consults the wired :class:`ecnl.ports.inbound.Authorizer`
before any tool dispatch — wired by the composition root in
:mod:`ecnl.server` per the architecture roadmap's authorization port.
"""

import logging
from collections.abc import Awaitable, Callable

from mcp.types import ToolAnnotations

from ....domain.exceptions import ECNLNotFoundError, UpstreamAPIError
from ....ports.inbound import AuthorizationRequest, Authorizer

logger = logging.getLogger(__name__)

_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
"""Annotation for tools that make read-only, idempotent calls to upstream APIs."""


async def _safe_call[T](coro: Awaitable[T], fmt: Callable[[T], str]) -> str:
    """Await coro, apply fmt to the result, and convert domain exceptions to error strings.

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


async def _safe_call_authorized[T](
    authorizer: Authorizer,
    tool_name: str,
    coro: Awaitable[T],
    fmt: Callable[[T], str],
) -> str:
    """Authorize the call, then run :func:`_safe_call`.

    Single dispatcher shared by every tool handler so the
    "authorize → execute → format" pipeline stays consistent across the
    20+ tools without each one repeating the wiring. A denial
    short-circuits before the coroutine runs — no upstream fetch
    happens for a forbidden call, which matters for both cost and
    audit attribution.
    """
    denied = await _authorize_tool(authorizer, tool_name)
    if denied is not None:
        # Closing the coroutine releases anything it was holding (e.g.
        # an async generator) so the upstream call never starts.
        coro.close() if hasattr(coro, "close") else None
        return denied
    return await _safe_call(coro, fmt)


async def _authorize_tool(authorizer: Authorizer, tool_name: str) -> str | None:
    """Consult the authorizer for a tool dispatch.

    Returns ``None`` when the call is allowed; the caller proceeds to
    :func:`_safe_call`. Returns a "Forbidden: <reason>" string when
    denied; the tool handler returns that string to the LLM so the
    model can recover or surface the rejection to the user.

    The caller's identity comes from the streamable-http transport's
    AccessToken (set by the :class:`JWKSTokenVerifier` from
    :mod:`ecnl.security`). The token's scopes carry the ADR-0015
    ``actor_type``, ``agent_id``, and ``sub`` claims as
    ``actor_type:<value>`` etc. — we parse them back into the
    AuthorizationRequest here so the application layer doesn't see
    the encoding.
    """
    actor = _read_actor()
    decision = await authorizer.authorize(
        AuthorizationRequest(
            actor_type=actor["actor_type"],
            agent_id=actor["agent_id"],
            subject=actor["sub"],
            client_id=actor["client_id"],
            tool_name=tool_name,
        )
    )
    if decision.allowed:
        return None
    logger.info(
        "authz deny: tool=%s reason=%s actor=%s", tool_name, decision.reason, actor.get("actor_type") or "anonymous"
    )
    return f"Forbidden: {decision.reason}"


def _read_actor() -> dict[str, str]:
    """Pull the bearer-token-derived actor identity from the current request context.

    Reads the AccessToken set by the mcp SDK's AuthenticationMiddleware,
    parses the ``actor_type:`` / ``agent_id:`` / ``sub:`` scope
    encodings the :class:`JWKSTokenVerifier` produces, and returns
    them as a plain dict. Missing or unset values become empty strings
    so downstream code can treat them uniformly — the stdio transport
    and the streamable-http transport without auth both end up here
    with empty fields, which the PassThroughAuthorizer happily allows.
    """
    actor = {"actor_type": "", "agent_id": "", "sub": "", "client_id": ""}
    token = _current_access_token()
    if token is None:
        return actor
    actor["client_id"] = token.client_id or ""
    _merge_scope_claims(actor, token.scopes or [])
    return actor


def _current_access_token():
    """Return the AccessToken for the in-flight request, or None.

    Wraps the mcp SDK import so a stdio-only build that omits the
    auth subpackage degrades gracefully instead of failing the
    import. The function is its own helper so the gocyclo-style
    counter on :func:`_read_actor` stays within the project's
    cyclomatic-complexity cap.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
    except ImportError:
        return None
    return get_access_token()


def _merge_scope_claims(actor: dict[str, str], scopes: list[str]) -> None:
    """Mutate ``actor`` in place with the ``key:value`` scope encodings.

    Scopes without a colon are ignored (those are the conventional
    OAuth scope values like ``read`` or ``write``). Scopes whose key
    is not one of the four known actor fields are also ignored so
    unrelated scope conventions cannot accidentally overwrite
    identity fields.
    """
    for scope in scopes:
        if ":" not in scope:
            continue
        key, _, value = scope.partition(":")
        if key in actor:
            actor[key] = value

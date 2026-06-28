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

_READ_ANNOTATIONS_BASE = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
"""Standard MCP hints. Kept separately for tools that need only the
spec-defined fields without the architecture-roadmap extensions."""


# ---------------------------------------------------------------------------
# Extended annotations (architecture/docs/agentic-posture.md — sensitivity,
# cost_class, rate_limit_class)
# ---------------------------------------------------------------------------


# Sensitivity classifications surfaced to MCP clients (LLM gateways,
# audit aggregators, policy engines). The values are intentionally
# coarse — adding a class is cheap; partitioning an existing one is a
# behaviour change for every consumer that branched on it.
SENSITIVITY_PUBLIC = "public"
"""Data is freely available to anyone with access to the upstream API.
Default for the ECNL tools that wrap AthleteOne's public endpoints."""
SENSITIVITY_INTERNAL = "internal"
"""Data is not personally identifiable but the deployment treats it
as confidential (rate-limited per-tenant, behind a private gateway,
etc.). Reserved for future tools that surface enriched analytics."""
SENSITIVITY_PII = "pii"
"""Tool returns personally identifiable information. Reserved — no
ECNL tool exposes PII today; the class is registered up-front so a
future addition does not require coordinating a rename."""


# Cost classifications. A consumer can use these to throttle, batch, or
# defer expensive tool calls without inspecting per-call latency.
COST_FREE = "free"
"""Tool is a no-op cache lookup; safe to invoke at any rate. Reserved
for future static-content tools."""
COST_METERED = "metered"
"""Tool calls an upstream API that the operator pays for per request.
Default for every ECNL tool — AthleteOne, season-discovery are all
metered upstreams."""
COST_BILLABLE = "billable"
"""Tool triggers downstream charges that flow through Lago (ADR-0019).
Reserved for tools that explicitly emit billing events; today every
ECNL tool is read-only so this is unused but registered for the
identity-platform side of the portfolio."""


# Rate-limit classifications. These pair with the per-deployment rate
# limiter — the actual ceilings live in operator config, not here.
RATE_LIMIT_LOW = "low"
"""Tool participates in a slow / cheap bucket — e.g. one call per
second per agent. Reserved for the analytics endpoints once we
introduce per-class buckets."""
RATE_LIMIT_STANDARD = "standard"
"""Tool participates in the default rate-limit bucket. Today every
ECNL tool falls here."""
RATE_LIMIT_PREMIUM = "premium"
"""Tool participates in a high-throughput bucket reserved for clients
that pay for elevated limits. Reserved."""


def read_annotations(
    *,
    sensitivity: str = SENSITIVITY_PUBLIC,
    cost_class: str = COST_METERED,
    rate_limit_class: str = RATE_LIMIT_STANDARD,
    title: str | None = None,
) -> ToolAnnotations:
    """Build a read-only ToolAnnotations extended with the
    architecture-roadmap fields (``sensitivity``, ``cost_class``,
    ``rate_limit_class``).

    The MCP SDK's ToolAnnotations Pydantic model is configured with
    ``extra="allow"`` so the extension fields land on the wire next to
    the standard hints — clients that don't know about them ignore
    them per RFC-style forward compatibility, while RAR-aware policy
    engines can route on them.

    Defaults match the dominant pattern for the ECNL tools (public
    soccer data, metered upstream, standard rate bucket). Stricter
    tools override per-field.
    """
    extras: dict[str, str] = {
        "sensitivity": sensitivity,
        "cost_class": cost_class,
        "rate_limit_class": rate_limit_class,
    }
    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
        **extras,
    )


_READ_ANNOTATIONS = read_annotations()
"""Default read-only annotation set surfaced to every ECNL tool.

Every ECNL tool today wraps a read-only public soccer-data endpoint
so the default sensitivity/cost/rate-limit classifications are
correct. Tools with different characteristics override by calling
:func:`read_annotations` directly with explicit values.
"""


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

    The tool's architecture-roadmap annotations (sensitivity,
    cost_class, rate_limit_class) are looked up from
    :data:`_TOOL_ANNOTATIONS_REGISTRY` so the policy engine can branch
    on the bucket without a separate catalog call. Missing entries
    fall back to the public/metered/standard defaults.
    """
    actor = _read_actor()
    annotations = _TOOL_ANNOTATIONS_REGISTRY.get(tool_name, _DEFAULT_TOOL_ANNOTATIONS_TUPLE)
    decision = await authorizer.authorize(
        AuthorizationRequest(
            actor_type=actor["actor_type"],
            agent_id=actor["agent_id"],
            subject=actor["sub"],
            client_id=actor["client_id"],
            tool_name=tool_name,
            sensitivity=annotations[0],
            cost_class=annotations[1],
            rate_limit_class=annotations[2],
        )
    )
    if decision.allowed:
        return None
    logger.info(
        "authz deny: tool=%s reason=%s actor=%s", tool_name, decision.reason, actor.get("actor_type") or "anonymous"
    )
    return f"Forbidden: {decision.reason}"


# Per-tool annotation map populated at registration time. Keys are the
# tool name (the @mcp.tool function name); values are the
# (sensitivity, cost_class, rate_limit_class) triple. Default entries
# are seeded lazily on first access via [register_tool_annotations].
_TOOL_ANNOTATIONS_REGISTRY: dict[str, tuple[str, str, str]] = {}
_DEFAULT_TOOL_ANNOTATIONS_TUPLE: tuple[str, str, str] = (
    SENSITIVITY_PUBLIC,
    COST_METERED,
    RATE_LIMIT_STANDARD,
)


def register_tool_annotations(
    tool_name: str,
    *,
    sensitivity: str = SENSITIVITY_PUBLIC,
    cost_class: str = COST_METERED,
    rate_limit_class: str = RATE_LIMIT_STANDARD,
) -> None:
    """Record the architecture-roadmap annotations for a tool.

    Called from each ``register_*_tools`` function alongside the
    ``@mcp.tool(annotations=...)`` decorator so the wire-level
    surface (visible to MCP clients) and the policy-port surface
    (visible to the :func:`_authorize_tool` lookup) stay aligned.
    Calling with the defaults is a no-op — the registry only stores
    overrides, so unannotated tools fall through to the constant
    defaults at authorize time.
    """
    if (sensitivity, cost_class, rate_limit_class) == _DEFAULT_TOOL_ANNOTATIONS_TUPLE:
        # Skip the dict write so the registry only carries overrides;
        # the lookup falls back to the defaults via .get's default.
        return
    _TOOL_ANNOTATIONS_REGISTRY[tool_name] = (sensitivity, cost_class, rate_limit_class)


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

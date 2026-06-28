"""Inbound ports the application service expects.

The MCP server's inbound surface is the tool dispatch path: a tool
handler reads the caller's identity from the bearer token, asks the
:class:`Authorizer` whether the call may proceed, and only then invokes
the application service. The port lives here so the adapter side can
provide either a pass-through (local dev) or a policy-service-backed
implementation without the application layer having to know which is
wired.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class DecisionKind(StrEnum):
    """Result of an authorization check.

    A string-backed Enum keeps log messages and audit envelopes
    readable without an extra translation step.
    """

    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class Decision:
    """The authorizer's verdict on a single tool call.

    ``reason`` is surfaced verbatim to the caller when the decision is
    :class:`DecisionKind.DENY`. Per RFC 6749 §5.2 we don't want to leak
    operational detail in error messages — implementations should
    return a short, stable string the caller can show a user without
    triggering an enumeration probe (e.g. "tool not allowed for
    actor"), not the raw policy lookup result.
    """

    kind: DecisionKind
    reason: str = ""

    @classmethod
    def allow(cls) -> Decision:
        return cls(DecisionKind.ALLOW)

    @classmethod
    def deny(cls, reason: str = "tool call not permitted") -> Decision:
        return cls(DecisionKind.DENY, reason)

    @property
    def allowed(self) -> bool:
        return self.kind is DecisionKind.ALLOW


@dataclass(frozen=True)
class AuthorizationRequest:
    """The full input to an authorization check.

    Bundling the fields into a value object keeps the protocol stable
    when new attributes ship (per-tool sensitivity, cost class, RAR
    `authorization_details`) — adapter implementations can pick the
    fields they care about without breaking signature changes
    cascading through every caller.
    """

    actor_type: str
    """One of "user", "service", "agent" per ADR-0015. Empty when
    ``MCP_AUTH_ENABLED=false`` and no token was presented."""

    agent_id: str
    """Stable agent identifier per ADR-0015. Empty for non-agent
    actors and for unauthenticated calls."""

    subject: str
    """The ``sub`` claim from the bearer token — typically the
    human-readable user id, or the agent's own id when the agent
    acts on its own behalf."""

    client_id: str
    """The ``client_id`` claim, which doubles as the OAuth client
    identifier for audit / metering attribution."""

    tool_name: str
    """The name of the MCP tool being invoked, e.g. ``get_standings``."""


class Authorizer(Protocol):
    """Inbound authorization port.

    Implementations are async because the production adapter calls
    :mod:`authorization-policy-service` over HTTP; the pass-through is
    still async to keep call sites identical regardless of which
    implementation is wired.
    """

    async def authorize(self, req: AuthorizationRequest) -> Decision:
        """Decide whether the supplied tool call may proceed."""
        ...

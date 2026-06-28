"""Tests for the _safe_call_authorized dispatcher.

The dispatcher is the bridge between every tool handler and the
application service: authorize → execute → format. The tests verify
that a denial short-circuits before the coroutine is awaited (so the
upstream call never happens) and that an allow proceeds to the
normal _safe_call path.
"""

from __future__ import annotations

import pytest

from ecnl.adapters.inbound.tools._base import _safe_call_authorized
from ecnl.ports.inbound import AuthorizationRequest, Authorizer, Decision


class _DenyAll:
    """Authorizer that denies every request with a known reason."""

    async def authorize(self, req: AuthorizationRequest) -> Decision:  # noqa: ARG002
        return Decision.deny("computer says no")


class _AllowAll:
    """Authorizer that allows every request."""

    async def authorize(self, req: AuthorizationRequest) -> Decision:  # noqa: ARG002
        return Decision.allow()


@pytest.mark.asyncio
async def test_dispatch_returns_forbidden_when_denied() -> None:
    called = False

    async def upstream() -> int:
        nonlocal called
        called = True
        return 42

    result = await _safe_call_authorized(_DenyAll(), "get_standings", upstream(), str)
    assert result.startswith("Forbidden:")
    assert "computer says no" in result
    assert called is False, "upstream coroutine must not run when denied"


@pytest.mark.asyncio
async def test_dispatch_runs_upstream_when_allowed() -> None:
    async def upstream() -> int:
        return 42

    result = await _safe_call_authorized(_AllowAll(), "get_standings", upstream(), lambda v: f"value={v}")
    assert result == "value=42"


@pytest.mark.asyncio
async def test_dispatch_handles_domain_exceptions_after_allow() -> None:
    from ecnl.domain.exceptions import ECNLNotFoundError

    async def upstream() -> int:
        raise ECNLNotFoundError("team 999 not found")

    result = await _safe_call_authorized(_AllowAll(), "get_team", upstream(), str)
    assert "Not found" in result


@pytest.mark.asyncio
async def test_dispatch_authorizer_protocol_accepts_any_implementation() -> None:
    # The Authorizer protocol is duck-typed; an implementation that
    # doesn't subclass anything still satisfies it.
    class Custom:
        async def authorize(self, req: AuthorizationRequest) -> Decision:  # noqa: ARG002
            return Decision.allow()

    a: Authorizer = Custom()
    result = await _safe_call_authorized(a, "x", _coro(1), str)
    assert result == "1"


async def _coro(v: int) -> int:
    return v

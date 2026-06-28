"""Tests for the extended tool annotations.

The annotations land on the MCP wire (visible to clients) and on the
authorization-port path (used by policy engines that branch on
sensitivity / cost / rate-limit bucket). Both surfaces are covered.
"""

from __future__ import annotations

import pytest

from ecnl.adapters.inbound.tools._base import (
    _DEFAULT_TOOL_ANNOTATIONS_TUPLE,
    _TOOL_ANNOTATIONS_REGISTRY,
    COST_BILLABLE,
    COST_METERED,
    RATE_LIMIT_LOW,
    RATE_LIMIT_STANDARD,
    SENSITIVITY_INTERNAL,
    SENSITIVITY_PUBLIC,
    _authorize_tool,
    read_annotations,
    register_tool_annotations,
)
from ecnl.ports.inbound import AuthorizationRequest, Decision


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    """Each test gets a clean per-tool override map."""
    _TOOL_ANNOTATIONS_REGISTRY.clear()


# ---------------------------------------------------------------------------
# read_annotations — surface to MCP clients
# ---------------------------------------------------------------------------


def test_read_annotations_defaults_are_public_metered_standard() -> None:
    a = read_annotations()
    # readOnlyHint et al. preserved.
    assert a.readOnlyHint is True
    assert a.idempotentHint is True
    # Architecture-roadmap extras land via Pydantic's extra="allow".
    dumped = a.model_dump(exclude_none=True)
    assert dumped["sensitivity"] == SENSITIVITY_PUBLIC
    assert dumped["cost_class"] == COST_METERED
    assert dumped["rate_limit_class"] == RATE_LIMIT_STANDARD


def test_read_annotations_overrides_propagate_to_wire() -> None:
    a = read_annotations(sensitivity=SENSITIVITY_INTERNAL, cost_class=COST_BILLABLE)
    dumped = a.model_dump(exclude_none=True)
    assert dumped["sensitivity"] == SENSITIVITY_INTERNAL
    assert dumped["cost_class"] == COST_BILLABLE
    # Rate limit retained its default — overrides are per-field, not all-or-nothing.
    assert dumped["rate_limit_class"] == RATE_LIMIT_STANDARD


def test_read_annotations_carries_title_when_set() -> None:
    a = read_annotations(title="Get ECNL Standings")
    assert a.title == "Get ECNL Standings"


# ---------------------------------------------------------------------------
# register_tool_annotations — registry semantics
# ---------------------------------------------------------------------------


def test_register_tool_annotations_default_values_are_not_stored() -> None:
    # Storing the defaults would waste memory and complicate audit
    # diffs; the lookup falls back to the constant tuple instead.
    register_tool_annotations("get_teams")
    assert "get_teams" not in _TOOL_ANNOTATIONS_REGISTRY


def test_register_tool_annotations_stores_overrides() -> None:
    register_tool_annotations(
        "get_team_rpi",
        sensitivity=SENSITIVITY_INTERNAL,
        cost_class=COST_BILLABLE,
        rate_limit_class=RATE_LIMIT_LOW,
    )
    assert _TOOL_ANNOTATIONS_REGISTRY["get_team_rpi"] == (
        SENSITIVITY_INTERNAL,
        COST_BILLABLE,
        RATE_LIMIT_LOW,
    )


def test_default_tuple_matches_constants() -> None:
    # Drift in the defaults silently changes the policy-port input
    # shape — pin it so any change is intentional.
    assert _DEFAULT_TOOL_ANNOTATIONS_TUPLE == (SENSITIVITY_PUBLIC, COST_METERED, RATE_LIMIT_STANDARD)


# ---------------------------------------------------------------------------
# _authorize_tool — surface to the policy port
# ---------------------------------------------------------------------------


class _CapturingAuthorizer:
    """Authorizer that records the last AuthorizationRequest."""

    def __init__(self) -> None:
        self.captured: AuthorizationRequest | None = None

    async def authorize(self, req: AuthorizationRequest) -> Decision:
        self.captured = req
        return Decision.allow()


@pytest.mark.asyncio
async def test_authorize_tool_forwards_default_annotations_when_unregistered() -> None:
    a = _CapturingAuthorizer()
    result = await _authorize_tool(a, "unregistered_tool")
    assert result is None  # allowed
    assert a.captured is not None
    assert a.captured.sensitivity == SENSITIVITY_PUBLIC
    assert a.captured.cost_class == COST_METERED
    assert a.captured.rate_limit_class == RATE_LIMIT_STANDARD


@pytest.mark.asyncio
async def test_authorize_tool_forwards_registered_overrides() -> None:
    register_tool_annotations(
        "get_team_rpi",
        sensitivity=SENSITIVITY_INTERNAL,
        cost_class=COST_BILLABLE,
        rate_limit_class=RATE_LIMIT_LOW,
    )
    a = _CapturingAuthorizer()
    result = await _authorize_tool(a, "get_team_rpi")
    assert result is None
    assert a.captured is not None
    assert a.captured.sensitivity == SENSITIVITY_INTERNAL
    assert a.captured.cost_class == COST_BILLABLE
    assert a.captured.rate_limit_class == RATE_LIMIT_LOW

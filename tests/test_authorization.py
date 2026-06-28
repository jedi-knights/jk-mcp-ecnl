"""Tests for the inbound authorization port and adapter.

The port is consulted on every tool dispatch, so its correctness is
load-bearing: a misconfigured fail-closed default is the difference
between "tool refuses with a clear error" and "tool runs without a
policy check." The tests cover every decision branch and every
configuration knob.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from ecnl.adapters.inbound.authorization import (
    PassThroughAuthorizer,
    PolicyServiceAuthorizer,
    build_authorizer,
)
from ecnl.ports.inbound import AuthorizationRequest, Decision, DecisionKind


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "MCP_AUTHZ_URL",
        "MCP_AUTHZ_SERVER_NAME",
        "MCP_AUTHZ_TIMEOUT_SECONDS",
        "MCP_AUTHZ_FAIL_OPEN",
    ]:
        monkeypatch.delenv(name, raising=False)


def _req(tool: str = "get_standings", actor: str = "agent") -> AuthorizationRequest:
    return AuthorizationRequest(
        actor_type=actor,
        agent_id="agent-claude",
        subject="user-omar",
        client_id="client-A",
        tool_name=tool,
    )


# ---------------------------------------------------------------------------
# Decision value-object
# ---------------------------------------------------------------------------


def test_decision_allow_factory_is_allowed() -> None:
    d = Decision.allow()
    assert d.allowed
    assert d.kind is DecisionKind.ALLOW
    assert d.reason == ""


def test_decision_deny_factory_uses_default_reason() -> None:
    d = Decision.deny()
    assert not d.allowed
    assert d.kind is DecisionKind.DENY
    assert d.reason == "tool call not permitted"


def test_decision_deny_carries_custom_reason() -> None:
    d = Decision.deny("scope insufficient")
    assert d.reason == "scope insufficient"


# ---------------------------------------------------------------------------
# PassThroughAuthorizer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passthrough_allows_every_call() -> None:
    a = PassThroughAuthorizer()
    assert (await a.authorize(_req())).allowed
    assert (await a.authorize(_req(tool="anything", actor=""))).allowed


# ---------------------------------------------------------------------------
# PolicyServiceAuthorizer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_authorizer_translates_to_evaluate_payload() -> None:
    captured: dict = {}

    async def fake_post(self, url, json=None, **kwargs):  # noqa: ARG001
        captured["url"] = url
        captured["json"] = json
        return _FakeResp(200, {"allowed": True})

    with patch("httpx.AsyncClient.post", new=fake_post):
        a = PolicyServiceAuthorizer(base_url="http://policy.test/", server_name="jk-mcp-ecnl")
        assert (await a.authorize(_req(tool="get_standings"))).allowed

    assert captured["url"] == "http://policy.test/evaluate"
    assert captured["json"] == {
        "subject_id": "user-omar",
        "resource": "mcp:jk-mcp-ecnl:get_standings",
        "action": "invoke",
    }


@pytest.mark.asyncio
async def test_policy_authorizer_returns_deny_on_explicit_deny() -> None:
    async def fake_post(self, url, json=None, **kwargs):  # noqa: ARG001
        return _FakeResp(200, {"allowed": False, "reason": "subject lacks role"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        a = PolicyServiceAuthorizer(base_url="http://policy.test", server_name="jk-mcp-ecnl")
        d = await a.authorize(_req())
    assert not d.allowed
    assert d.reason == "subject lacks role"


@pytest.mark.asyncio
async def test_policy_authorizer_falls_back_to_client_id_when_subject_empty() -> None:
    captured: dict = {}

    async def fake_post(self, url, json=None, **kwargs):  # noqa: ARG001
        captured["json"] = json
        return _FakeResp(200, {"allowed": True})

    req = AuthorizationRequest(actor_type="", agent_id="", subject="", client_id="client-only", tool_name="t")
    with patch("httpx.AsyncClient.post", new=fake_post):
        a = PolicyServiceAuthorizer(base_url="http://policy.test", server_name="jk-mcp-ecnl")
        await a.authorize(req)
    assert captured["json"]["subject_id"] == "client-only"


@pytest.mark.asyncio
async def test_policy_authorizer_fail_closed_on_http_error() -> None:
    async def fake_post(self, url, json=None, **kwargs):  # noqa: ARG001
        raise httpx.ConnectError("policy service down")

    with patch("httpx.AsyncClient.post", new=fake_post):
        a = PolicyServiceAuthorizer(base_url="http://policy.test", server_name="jk-mcp-ecnl")
        d = await a.authorize(_req())
    assert not d.allowed
    assert d.reason == "authorization unavailable"


@pytest.mark.asyncio
async def test_policy_authorizer_fail_open_returns_allow_on_error() -> None:
    async def fake_post(self, url, json=None, **kwargs):  # noqa: ARG001
        raise httpx.ConnectError("policy service down")

    with patch("httpx.AsyncClient.post", new=fake_post):
        a = PolicyServiceAuthorizer(
            base_url="http://policy.test",
            server_name="jk-mcp-ecnl",
            fail_closed=False,
        )
        d = await a.authorize(_req())
    assert d.allowed


@pytest.mark.asyncio
async def test_policy_authorizer_fail_closed_on_non_2xx() -> None:
    async def fake_post(self, url, json=None, **kwargs):  # noqa: ARG001
        return _FakeResp(500, {"error": "internal"})

    with patch("httpx.AsyncClient.post", new=fake_post):
        a = PolicyServiceAuthorizer(base_url="http://policy.test", server_name="jk-mcp-ecnl")
        d = await a.authorize(_req())
    assert not d.allowed


def test_policy_authorizer_trims_trailing_slash() -> None:
    a = PolicyServiceAuthorizer(base_url="http://policy.test/", server_name="x")
    assert a.base_url == "http://policy.test"


# ---------------------------------------------------------------------------
# build_authorizer — env-driven construction
# ---------------------------------------------------------------------------


def test_build_authorizer_default_is_pass_through() -> None:
    assert isinstance(build_authorizer(), PassThroughAuthorizer)


def test_build_authorizer_constructs_policy_service_when_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTHZ_URL", "http://policy.test")
    a = build_authorizer()
    assert isinstance(a, PolicyServiceAuthorizer)
    assert a.base_url == "http://policy.test"
    assert a.server_name == "jk-mcp-ecnl"
    assert a.fail_closed is True


def test_build_authorizer_honors_server_name_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTHZ_URL", "http://policy.test")
    monkeypatch.setenv("MCP_AUTHZ_SERVER_NAME", "nwsl-custom")
    a = build_authorizer()
    assert isinstance(a, PolicyServiceAuthorizer)
    assert a.server_name == "nwsl-custom"


def test_build_authorizer_honors_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTHZ_URL", "http://policy.test")
    monkeypatch.setenv("MCP_AUTHZ_TIMEOUT_SECONDS", "0.5")
    a = build_authorizer()
    assert isinstance(a, PolicyServiceAuthorizer)
    assert a.timeout_seconds == 0.5


def test_build_authorizer_bad_timeout_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTHZ_URL", "http://policy.test")
    monkeypatch.setenv("MCP_AUTHZ_TIMEOUT_SECONDS", "not-a-number")
    a = build_authorizer()
    assert isinstance(a, PolicyServiceAuthorizer)
    assert a.timeout_seconds == 1.5


def test_build_authorizer_fail_open_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_AUTHZ_URL", "http://policy.test")
    monkeypatch.setenv("MCP_AUTHZ_FAIL_OPEN", "true")
    a = build_authorizer()
    assert isinstance(a, PolicyServiceAuthorizer)
    assert a.fail_closed is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResp:
    """Minimal stand-in for the slice of httpx.Response the adapter uses."""

    def __init__(self, status: int, payload: dict) -> None:
        self.status_code = status
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "policy service returned non-2xx",
                request=None,  # type: ignore[arg-type]
                response=None,  # type: ignore[arg-type]
            )

    def json(self) -> dict:
        return self._payload

"""End-to-end scenario replay against an MCP server.

One pytest parameter per scenario file under
``tests/evals/scenarios/``. Each scenario passes when every
``expected_contains`` substring appears in the joined tool outputs and
no per-step tool call raised. Failures point at either:

* a missing substring — the formatter changed shape or the upstream
  stub no longer produces the expected data, or
* an exception — the tool dispatch path itself broke.

Two transport modes share one parametrize:

* **Stub mode (default)** — in-process FastMCP instance whose outbound
  ports are stubs (see :mod:`tests.evals.conftest`). Hermetic and
  appropriate for every PR run.
* **Live mode** — set ``MCP_EVAL_REMOTE_URL`` (and, if the deployment
  enforces auth, ``MCP_EVAL_BEARER_TOKEN``) to dial a deployed Fly
  instance over Streamable HTTP. Only scenarios with ``live: true``
  participate, since the others depend on stub-specific values.

Each test spins the connected server-and-client pair inline rather
than via a fixture — the mcp SDK's session manager is an async
context manager built on anyio cancel scopes, which do not tolerate
entering and exiting in different tasks (the pattern a yield-style
async fixture creates). Inlining keeps the entire context inside one
task and sidesteps the issue.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.memory import create_connected_server_and_client_session

from ecnl.adapters.inbound.mcp_adapter import create_mcp_server
from ecnl.application.service import ECNLService
from tests.evals import load_scenarios, run_scenario
from tests.evals.conftest import _StubDiscovery, _StubRepo
from tests.evals.scenario_loader import Scenario

_REMOTE_URL = os.environ.get("MCP_EVAL_REMOTE_URL") or None
_BEARER_TOKEN = os.environ.get("MCP_EVAL_BEARER_TOKEN") or None


def _select_scenarios() -> list[Scenario]:
    all_scenarios = load_scenarios()
    if _REMOTE_URL is None:
        return all_scenarios
    # In live mode, scenarios whose expectations depend on stub data
    # cannot meaningfully replay against real upstreams — they opt in
    # by setting ``live: true`` in their YAML.
    return [s for s in all_scenarios if s.live]


_SCENARIOS = _select_scenarios()


def _ids(s: Scenario) -> str:
    return s.name


@asynccontextmanager
async def _open_session() -> AsyncIterator[ClientSession]:
    if _REMOTE_URL is None:
        service = ECNLService(repo=_StubRepo(), discovery=_StubDiscovery())
        server = create_mcp_server(service)
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            yield session
        return
    headers = {"Authorization": f"Bearer {_BEARER_TOKEN}"} if _BEARER_TOKEN else None
    async with (
        streamablehttp_client(_REMOTE_URL, headers=headers) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


@pytest.mark.skipif(
    _REMOTE_URL is not None and not _SCENARIOS,
    reason=f"live mode active ({_REMOTE_URL}) but no scenarios opted in via live: true",
)
@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", _SCENARIOS, ids=_ids)
async def test_scenario(scenario: Scenario) -> None:
    async with _open_session() as client:
        result = await run_scenario(scenario, client)
    assert not result.errors, f"errors during scenario {scenario.name}: {result.errors}\noutput:\n{result.output}"
    assert result.passed, (
        f"scenario {scenario.name} failed; missing substrings: {result.missing}\noutput:\n{result.output}"
    )


def test_loader_finds_at_least_one_scenario() -> None:
    # If the suite ever shrinks to zero scenarios the parametrize above
    # silently produces zero tests; this guard fails loudly instead.
    # Uses the unfiltered loader so the guard fires on a truly empty
    # scenarios directory, not on a live-mode filter rejecting all.
    assert len(load_scenarios()) >= 1

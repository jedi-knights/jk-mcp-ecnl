"""End-to-end scenario replay against the in-process MCP server.

One pytest parameter per scenario file under
``tests/evals/scenarios/``. Each scenario passes when every
``expected_contains`` substring appears in the joined tool outputs and
no per-step tool call raised. Failures point at either:

* a missing substring — the formatter changed shape or the upstream
  stub no longer produces the expected data, or
* an exception — the tool dispatch path itself broke.

Each test spins the connected server-and-client pair inline rather
than via a fixture — the mcp SDK's session manager is an async
context manager built on anyio cancel scopes, which do not tolerate
entering and exiting in different tasks (the pattern a yield-style
async fixture creates). Inlining keeps the entire context inside one
task and sidesteps the issue.
"""

from __future__ import annotations

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from ecnl.adapters.inbound.mcp_adapter import create_mcp_server
from ecnl.application.service import ECNLService
from tests.evals import load_scenarios, run_scenario
from tests.evals.conftest import _StubDiscovery, _StubRepo
from tests.evals.scenario_loader import Scenario

_SCENARIOS = load_scenarios()


def _ids(s: Scenario) -> str:
    return s.name


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", _SCENARIOS, ids=_ids)
async def test_scenario(scenario: Scenario) -> None:
    service = ECNLService(repo=_StubRepo(), discovery=_StubDiscovery())
    server = create_mcp_server(service)
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        result = await run_scenario(scenario, client)
    assert not result.errors, f"errors during scenario {scenario.name}: {result.errors}\noutput:\n{result.output}"
    assert result.passed, (
        f"scenario {scenario.name} failed; missing substrings: {result.missing}\noutput:\n{result.output}"
    )


def test_loader_finds_at_least_one_scenario() -> None:
    # If the suite ever shrinks to zero scenarios the parametrize above
    # silently produces zero tests; this guard fails loudly instead.
    assert len(_SCENARIOS) >= 1

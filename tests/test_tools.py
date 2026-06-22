"""Tests that exercise the MCP tool wrappers end-to-end via the FastMCP server.

Each tool is invoked through ``call_tool`` against a service backed by configured
mock ports, so the tool bodies, formatters, and ``_safe_call`` success path are
all covered. ``_safe_call`` error branches are tested directly.
"""

import pytest

from ecnl.adapters.inbound.mcp_adapter import create_mcp_server
from ecnl.adapters.inbound.tools._base import _safe_call
from ecnl.application.service import ECNLService
from ecnl.domain.exceptions import ECNLNotFoundError, UpstreamAPIError


@pytest.fixture
def wired_mcp(mock_repo, mock_discovery, sample_event, sample_overview, sample_standings, sample_schedule, sample_team):
    """A FastMCP server backed by mocks returning real domain objects."""
    mock_discovery.find_events.return_value = [sample_event]
    mock_repo.get_event_overview.return_value = sample_overview
    mock_repo.get_standings.return_value = sample_standings
    mock_repo.get_schedule.return_value = sample_schedule
    mock_repo.get_team_schedule.return_value = sample_schedule
    mock_repo.get_flight_teams.return_value = [sample_team]
    mock_repo.get_clubs.return_value = []
    mock_repo.get_match.return_value = {"matchID": 1}
    mock_repo.get_brackets.return_value = {}
    return create_mcp_server(ECNLService(repo=mock_repo, discovery=mock_discovery))


async def _call(mcp, name: str, **arguments) -> str:
    """Invoke a tool and return its concatenated text output."""
    result = await mcp.call_tool(name, arguments)
    content = result[0] if isinstance(result, tuple) else result
    return "\n".join(getattr(block, "text", "") for block in content)


@pytest.mark.parametrize(
    ("name", "args", "expected"),
    [
        ("find_events", {"league": "ECNL"}, "ECNL girls"),
        ("get_event_overview", {"event_id": 3933}, "Southwest"),
        ("get_standings", {"event_id": 3933, "division_id": 18755, "flight_id": 32928}, "Slammers"),
        ("get_schedule", {"event_id": 3933, "flight_id": 32928}, "Slammers"),
        ("get_team_schedule", {"event_id": 3933, "team_id": 1}, "Beach FC"),
        ("get_teams", {"flight_id": 32928}, "Slammers"),
        ("get_clubs", {"event_id": 3933}, "No clubs"),
        ("get_match", {"match_token": "abc"}, "matchID"),
        ("get_brackets", {"event_id": 3933, "flight_id": 32928}, "No data"),
        ("get_results", {"event_id": 3933, "flight_id": 32928}, "Slammers 2-1 Beach FC"),
        ("get_rpi", {"event_id": 3933, "flight_id": 32928}, "RPI"),
        ("get_team_rpi", {"event_id": 3933, "flight_id": 32928, "team": "Slammers"}, "Slammers"),
    ],
)
async def test_tool_invocations(wired_mcp, name, args, expected):
    # Arrange / Act
    out = await _call(wired_mcp, name, **args)

    # Assert
    assert expected in out


async def test_tool_translates_not_found(mock_repo, mock_discovery):
    # Arrange — overview raises NotFound; the tool should report it, not crash.
    mock_repo.get_event_overview.side_effect = ECNLNotFoundError("event 1 missing")
    mcp = create_mcp_server(ECNLService(repo=mock_repo, discovery=mock_discovery))

    # Act
    out = await _call(mcp, "get_event_overview", event_id=1)

    # Assert
    assert "Not found" in out


async def test_safe_call_success():
    # Arrange / Act
    async def coro():
        return 21

    # Assert
    assert await _safe_call(coro(), lambda n: str(n * 2)) == "42"


async def test_safe_call_upstream_error():
    # Arrange
    async def coro():
        raise UpstreamAPIError("down")

    # Act / Assert
    assert "Upstream error" in await _safe_call(coro(), str)


async def test_safe_call_value_error():
    # Arrange
    async def coro():
        raise ValueError("bad arg")

    # Act / Assert
    assert "Invalid request" in await _safe_call(coro(), str)

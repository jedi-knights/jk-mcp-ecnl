"""Tests for the composition root and MCP server wiring."""

import pytest

from ecnl.adapters.inbound.mcp_adapter import create_mcp_server
from ecnl.application.service import ECNLService
from ecnl.server import build_server


def test_build_server_returns_named_instance():
    # Arrange / Act
    server = build_server()

    # Assert
    assert server.name == "ecnl"


async def test_all_tools_registered(service: ECNLService):
    # Arrange
    mcp = create_mcp_server(service)

    # Act
    tools = await mcp.list_tools()
    names = {t.name for t in tools}

    # Assert — every planned tool is present.
    assert names == {
        "find_events",
        "get_event_overview",
        "get_standings",
        "get_schedule",
        "get_team_schedule",
        "get_teams",
        "get_clubs",
        "get_match",
        "get_brackets",
        "get_results",
        "get_rpi",
        "get_team_rpi",
    }


async def test_tools_are_read_only(service: ECNLService):
    # Arrange
    mcp = create_mcp_server(service)

    # Act
    tools = await mcp.list_tools()

    # Assert
    assert all(t.annotations.readOnlyHint for t in tools)


def test_main_rejects_invalid_transport(monkeypatch: pytest.MonkeyPatch):
    # Arrange
    monkeypatch.setenv("MCP_TRANSPORT", "carrier-pigeon")
    from ecnl import server

    # Act / Assert
    with pytest.raises(ValueError, match="Invalid MCP_TRANSPORT"):
        server.main()

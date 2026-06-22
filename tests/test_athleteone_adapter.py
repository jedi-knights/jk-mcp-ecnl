"""Tests for AthleteOneAdapter — URL construction, envelope handling, parsing."""

from typing import Any

import httpx
import pytest
from pytest_mock import MockerFixture

from ecnl.adapters.outbound.athleteone_adapter import AthleteOneAdapter
from ecnl.domain.exceptions import ECNLNotFoundError, UpstreamAPIError


class _Resp:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)


def _adapter(mocker: MockerFixture, payload: Any, status: int = 200) -> tuple[AthleteOneAdapter, Any]:
    client = mocker.AsyncMock()
    client.get = mocker.AsyncMock(return_value=_Resp(payload, status))
    return AthleteOneAdapter(client=client), client


async def test_get_event_parses_and_classifies(mocker: MockerFixture):
    # Arrange
    payload = {"result": "success", "data": {"eventID": 3933, "name": "ECNL Girls Southwest 2025-26"}}
    adapter, client = _adapter(mocker, payload)

    # Act
    event = await adapter.get_event(3933)

    # Assert
    assert event.event_id == 3933
    assert (event.league, event.gender, event.conference) == ("ECNL", "girls", "Southwest")
    client.get.assert_awaited_once_with("/api/team/get-event-details-by-eventid/3933")


async def test_get_standings_flattens_groups(mocker: MockerFixture):
    # Arrange
    payload = {
        "result": "success",
        "data": [
            {
                "teamStandings": [
                    {
                        "teamID": 1,
                        "name": "Slammers",
                        "wins": 13,
                        "losses": 1,
                        "draws": 2,
                        "standingpoints": 41,
                        "ppg": 2.56,
                        "rank": 1,
                    }
                ]
            }
        ],
    }
    adapter, client = _adapter(mocker, payload)

    # Act
    standings = await adapter.get_standings(3933, 18755, 32928)

    # Assert
    assert len(standings.rows) == 1
    assert standings.rows[0].team_name == "Slammers"
    assert standings.rows[0].points == 41
    client.get.assert_awaited_once_with("/api/Event/get-standings-by-div-and-flight/18755/32928/3933")


async def test_get_schedule_parses_scores(mocker: MockerFixture):
    # Arrange
    payload = {
        "result": "success",
        "data": [
            {
                "matchID": 1,
                "homeTeam": "A",
                "awayTeam": "B",
                "hometeamscore": 2,
                "awayteamscore": 1,
                "gameDate": "2025-09-06",
            }
        ],
    }
    adapter, _ = _adapter(mocker, payload)

    # Act
    matches = await adapter.get_schedule(3933, 32928)

    # Assert
    assert matches[0].home_score == 2
    assert matches[0].away_score == 1
    assert matches[0].is_played


async def test_get_org_club_events_returns_distinct_nonzero(mocker: MockerFixture):
    # Arrange
    payload = {"result": "success", "data": [{"eventID": 3932}, {"eventID": 0}, {"eventID": 3932}, {"eventID": 3933}]}
    adapter, _ = _adapter(mocker, payload)

    # Act
    ids = await adapter.get_org_club_events(9)

    # Assert
    assert ids == [3932, 3933]


async def test_404_becomes_not_found(mocker: MockerFixture):
    # Arrange
    adapter, _ = _adapter(mocker, payload=None, status=404)

    # Act / Assert
    with pytest.raises(ECNLNotFoundError):
        await adapter.get_event(999999)


async def test_error_envelope_becomes_upstream_error(mocker: MockerFixture):
    # Arrange — HTTP 200 but the body reports an error.
    adapter, _ = _adapter(mocker, payload={"result": "error", "message": "boom"})

    # Act / Assert
    with pytest.raises(UpstreamAPIError, match="boom"):
        await adapter.get_schedule(3933, 32928)


async def test_500_becomes_upstream_error(mocker: MockerFixture):
    # Arrange
    adapter, _ = _adapter(mocker, payload=None, status=500)

    # Act / Assert
    with pytest.raises(UpstreamAPIError):
        await adapter.get_clubs(3933)

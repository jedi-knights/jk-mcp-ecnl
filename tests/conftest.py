"""Shared fixtures for the ECNL test suite.

These wire real domain models and mock ports together, mirroring the dependency
injection used in the production server.py composition root.
"""

from unittest.mock import AsyncMock

import pytest
from pytest_mock import MockerFixture

from ecnl.application.service import ECNLService
from ecnl.domain.models import (
    Division,
    Event,
    EventOverview,
    Flight,
    Match,
    StandingRow,
    Standings,
    Team,
)
from ecnl.ports.outbound import DiscoveryPort, ECNLAPIPort


@pytest.fixture
def sample_event() -> Event:
    """An ECNL girls event."""
    return Event(
        event_id=3933,
        name="ECNL Girls Southwest 2025-26",
        league="ECNL",
        gender="girls",
        conference="Southwest",
        season="2025-26",
        location="Henrico, Virginia",
    )


@pytest.fixture
def sample_overview(sample_event: Event) -> EventOverview:
    """An event overview with one division and one ECNL flight."""
    flight = Flight(flight_id=32928, division_id=18755, division_name="G2008/2007", name="ECNL", teams_count=17)
    division = Division(division_id=18755, name="G2008/2007", gender="girls", flights=[flight])
    return EventOverview(event=sample_event, divisions=[division])


@pytest.fixture
def sample_standings() -> Standings:
    """A two-row standings table."""
    return Standings(
        event_id=3933,
        division_id=18755,
        flight_id=32928,
        rows=[
            StandingRow(
                team_id=1, team_name="Slammers", wins=13, losses=1, draws=2, points=41, points_per_game=2.56, rank=1
            ),
            StandingRow(
                team_id=2, team_name="Beach FC", wins=12, losses=2, draws=2, points=38, points_per_game=2.38, rank=2
            ),
        ],
    )


@pytest.fixture
def sample_schedule() -> list[Match]:
    """A schedule with one played and one unplayed match."""
    return [
        Match(
            match_id=1,
            date="2025-09-06",
            time="08:00",
            home_team_id=1,
            home_team="Slammers",
            away_team_id=2,
            away_team="Beach FC",
            home_score=2,
            away_score=1,
            venue="Field 5",
        ),
        Match(
            match_id=2,
            date="2025-10-01",
            time="10:00",
            home_team_id=2,
            home_team="Beach FC",
            away_team_id=1,
            away_team="Slammers",
        ),
    ]


@pytest.fixture
def sample_team() -> Team:
    """A single team."""
    return Team(team_id=1, name="Slammers", club_id=1656, head_coach="Jane Coach")


@pytest.fixture
def mock_repo(mocker: MockerFixture) -> AsyncMock:
    """AsyncMock satisfying the ECNLAPIPort protocol."""
    return mocker.AsyncMock(spec=ECNLAPIPort)


@pytest.fixture
def mock_discovery(mocker: MockerFixture) -> AsyncMock:
    """AsyncMock satisfying the DiscoveryPort protocol."""
    return mocker.AsyncMock(spec=DiscoveryPort)


@pytest.fixture
def service(mock_repo: AsyncMock, mock_discovery: AsyncMock) -> ECNLService:
    """ECNLService wired with mock ports — the primary DI seam for service tests."""
    return ECNLService(repo=mock_repo, discovery=mock_discovery)

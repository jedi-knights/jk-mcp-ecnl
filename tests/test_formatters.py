"""Tests for the output formatters."""

from ecnl.adapters.inbound.formatters import (
    _fmt_clubs,
    _fmt_event_overview,
    _fmt_events,
    _fmt_raw,
    _fmt_results,
    _fmt_rpi,
    _fmt_schedule,
    _fmt_standings,
    _fmt_team_rpi,
    _fmt_teams,
)
from ecnl.domain.models import Club, MatchResult, Standings, Team, TeamRPI


def test_fmt_events(sample_event):
    # Arrange / Act
    out = _fmt_events([sample_event])

    # Assert
    assert "3933" in out
    assert "ECNL girls" in out
    assert "Southwest" in out


def test_fmt_events_empty():
    # Arrange / Act / Assert
    assert "No matching events" in _fmt_events([])


def test_fmt_event_overview(sample_overview):
    # Arrange / Act
    out = _fmt_event_overview(sample_overview)

    # Assert
    assert "ECNL Girls Southwest 2025-26" in out
    assert "32928" in out
    assert "17 teams" in out


def test_fmt_standings(sample_standings: Standings):
    # Arrange / Act
    out = _fmt_standings(sample_standings)

    # Assert
    assert "Slammers" in out
    assert "13-1-2" in out
    assert "41" in out


def test_fmt_standings_empty():
    # Arrange / Act / Assert
    assert "No standings" in _fmt_standings(Standings(event_id=1, division_id=2, flight_id=3))


def test_fmt_schedule(sample_schedule):
    # Arrange / Act
    out = _fmt_schedule(sample_schedule)

    # Assert — played match shows score, unplayed shows "vs".
    assert "Slammers 2-1 Beach FC" in out
    assert "Beach FC vs Slammers" in out


def test_fmt_schedule_empty():
    # Arrange / Act / Assert
    assert "No matches" in _fmt_schedule([])


def test_fmt_teams(sample_team: Team):
    # Arrange / Act
    out = _fmt_teams([sample_team])

    # Assert
    assert "Slammers" in out
    assert "Jane Coach" in out


def test_fmt_clubs():
    # Arrange / Act
    out = _fmt_clubs([Club(club_id=1656, name="Slammers FC", city="Newport Beach", state_code="CA")])

    # Assert
    assert "Slammers FC" in out
    assert "Newport Beach, CA" in out


def test_fmt_results():
    # Arrange / Act
    out = _fmt_results([MatchResult(home_team="A", away_team="B", home_score=2, away_score=1)])

    # Assert
    assert "A 2-1 B" in out


def test_fmt_rpi_and_team_rpi():
    # Arrange
    row = TeamRPI(team="A", wins=2, losses=0, draws=0, wp=1.0, owp=0.75, oowp=0.625, rpi=0.7813, rank=1)

    # Act
    table_out = _fmt_rpi([row])
    team_out = _fmt_team_rpi(row)

    # Assert
    assert "RPI" in table_out and "0.781" in table_out
    assert "rank 1" in team_out
    assert "0.7500" in team_out  # OWP component


def test_fmt_rpi_empty():
    # Arrange / Act / Assert
    assert "cannot be computed" in _fmt_rpi([])


def test_fmt_raw_roundtrips_and_handles_empty():
    # Arrange / Act / Assert
    assert "No data" in _fmt_raw({})
    assert '"a": 1' in _fmt_raw({"a": 1})

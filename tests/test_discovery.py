"""Tests for DiscoveryAdapter — org walking and classification filtering."""

from unittest.mock import AsyncMock

from ecnl.adapters.outbound.discovery import DiscoveryAdapter
from ecnl.domain.models import Event


def _event(event_id: int, league: str, gender: str, conf: str, season: str = "2025-26") -> Event:
    return Event(
        event_id=event_id,
        name=f"{league} {gender} {conf}",
        league=league,
        gender=gender,
        conference=conf,
        season=season,
    )


async def test_find_events_filters_to_requested_org(mock_repo: AsyncMock):
    # Arrange — only the ECNL-girls org (9) should be walked.
    mock_repo.get_org_club_events.return_value = [3932, 3933]
    mock_repo.get_event.side_effect = [
        _event(3932, "ECNL", "girls", "Southeast"),
        _event(3933, "ECNL", "girls", "Southwest"),
    ]
    discovery = DiscoveryAdapter(mock_repo)

    # Act
    events = await discovery.find_events(league="ECNL", gender="girls")

    # Assert
    mock_repo.get_org_club_events.assert_awaited_once_with(9)
    assert {e.event_id for e in events} == {3932, 3933}
    assert [e.conference for e in events] == ["Southeast", "Southwest"]  # sorted by conference


async def test_find_events_applies_season_filter(mock_repo: AsyncMock):
    # Arrange
    mock_repo.get_org_club_events.return_value = [1, 2]
    mock_repo.get_event.side_effect = [
        _event(1, "ECNL", "boys", "A", season="2024-25"),
        _event(2, "ECNL", "boys", "B", season="2025-26"),
    ]
    discovery = DiscoveryAdapter(mock_repo)

    # Act
    events = await discovery.find_events(league="ECNL", gender="boys", season="2025-26")

    # Assert
    assert [e.event_id for e in events] == [2]


async def test_find_events_unknown_org_returns_empty(mock_repo: AsyncMock):
    # Arrange — no org seeded for this combination would ever be hit; force empty map.
    discovery = DiscoveryAdapter(mock_repo, org_ids={})

    # Act
    events = await discovery.find_events(league="ECNL", gender="girls")

    # Assert
    assert events == []
    mock_repo.get_org_club_events.assert_not_awaited()

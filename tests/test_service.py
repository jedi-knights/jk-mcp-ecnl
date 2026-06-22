"""Tests for ECNLService orchestration."""

from unittest.mock import AsyncMock

import pytest

from ecnl.application.service import ECNLService
from ecnl.domain.exceptions import ECNLNotFoundError


async def test_find_events_normalizes_and_delegates(service: ECNLService, mock_discovery: AsyncMock):
    # Arrange
    mock_discovery.find_events.return_value = []

    # Act
    await service.find_events(league="ecnl", gender="Girls", season="2025-26")

    # Assert — normalized to canonical casing before reaching discovery.
    mock_discovery.find_events.assert_awaited_once_with("ECNL", "girls", "2025-26")


async def test_find_events_rejects_invalid_league(service: ECNLService):
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="Invalid league"):
        await service.find_events(league="MLS")


async def test_find_events_rejects_invalid_gender(service: ECNLService):
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="Invalid gender"):
        await service.find_events(gender="mixed")


async def test_get_results_keeps_only_played(service: ECNLService, mock_repo: AsyncMock, sample_schedule):
    # Arrange
    mock_repo.get_schedule.return_value = sample_schedule

    # Act
    results = await service.get_results(3933, 32928)

    # Assert — only the one completed match survives.
    assert len(results) == 1
    assert results[0].home_team == "Slammers"
    assert results[0].home_score == 2


async def test_get_rpi_computes_from_results(service: ECNLService, mock_repo: AsyncMock, sample_schedule):
    # Arrange
    mock_repo.get_schedule.return_value = sample_schedule

    # Act
    table = await service.get_rpi(3933, 32928)

    # Assert — two teams appear, ranked.
    assert {r.team for r in table} == {"Slammers", "Beach FC"}
    assert table[0].rank == 1


async def test_get_team_rpi_matches_by_substring(service: ECNLService, mock_repo: AsyncMock, sample_schedule):
    # Arrange
    mock_repo.get_schedule.return_value = sample_schedule

    # Act
    row = await service.get_team_rpi(3933, 32928, team="slammer")

    # Assert
    assert row.team == "Slammers"


async def test_get_team_rpi_raises_when_absent(service: ECNLService, mock_repo: AsyncMock, sample_schedule):
    # Arrange
    mock_repo.get_schedule.return_value = sample_schedule

    # Act / Assert
    with pytest.raises(ECNLNotFoundError):
        await service.get_team_rpi(3933, 32928, team="nonexistent")


async def test_rpi_table_is_memoized_across_calls(mock_repo: AsyncMock, mock_discovery: AsyncMock, sample_schedule):
    # Arrange — fixed clock so the memo never expires.
    mock_repo.get_schedule.return_value = sample_schedule
    svc = ECNLService(repo=mock_repo, discovery=mock_discovery, now=lambda: 0.0)

    # Act — a full-table call followed by a per-team call for the same flight.
    await svc.get_rpi(3933, 32928)
    await svc.get_team_rpi(3933, 32928, team="Slammers")

    # Assert — the schedule (hence the computation) is fetched only once.
    assert mock_repo.get_schedule.await_count == 1


async def test_rpi_table_expires_after_ttl(mock_repo: AsyncMock, mock_discovery: AsyncMock, sample_schedule):
    # Arrange — advancing clock crosses the TTL between calls.
    mock_repo.get_schedule.return_value = sample_schedule
    clock = {"t": 0.0}
    svc = ECNLService(repo=mock_repo, discovery=mock_discovery, now=lambda: clock["t"], rpi_ttl_seconds=60.0)

    # Act
    await svc.get_rpi(3933, 32928)
    clock["t"] = 120.0
    await svc.get_rpi(3933, 32928)

    # Assert — stale table is recomputed.
    assert mock_repo.get_schedule.await_count == 2


async def test_rpi_cache_is_bounded(mock_repo: AsyncMock, mock_discovery: AsyncMock, sample_schedule):
    # Arrange — cap of 1 entry; two distinct flights must not both be retained.
    mock_repo.get_schedule.return_value = sample_schedule
    svc = ECNLService(repo=mock_repo, discovery=mock_discovery, now=lambda: 0.0, rpi_cache_size=1)

    # Act — populate flight A, evict it with flight B, then re-request A.
    await svc.get_rpi(3933, 111)
    await svc.get_rpi(3933, 222)
    await svc.get_rpi(3933, 111)

    # Assert — flight A was evicted, so it is fetched twice (1st + after eviction).
    assert mock_repo.get_schedule.await_count == 3


async def test_passthrough_methods_delegate(service: ECNLService, mock_repo: AsyncMock):
    # Arrange / Act
    await service.get_event_overview(3933)
    await service.get_standings(3933, 18755, 32928)
    await service.get_teams(32928)
    await service.get_clubs(3933)
    await service.get_match("tok")
    await service.get_brackets(3933, 32928)
    await service.get_team_schedule(3933, 1)

    # Assert
    mock_repo.get_event_overview.assert_awaited_once_with(3933)
    mock_repo.get_standings.assert_awaited_once_with(3933, 18755, 32928)
    mock_repo.get_flight_teams.assert_awaited_once_with(32928)
    mock_repo.get_clubs.assert_awaited_once_with(3933)
    mock_repo.get_match.assert_awaited_once_with("tok")
    mock_repo.get_brackets.assert_awaited_once_with(3933, 32928)
    mock_repo.get_team_schedule.assert_awaited_once_with(3933, 1)

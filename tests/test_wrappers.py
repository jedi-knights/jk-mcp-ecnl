"""Tests for the retry and caching cross-cutting adapters."""

from unittest.mock import AsyncMock

import pytest

from ecnl.adapters.outbound.caching_adapter import CachingAdapter
from ecnl.adapters.outbound.retry_adapter import RetryingAdapter
from ecnl.domain.exceptions import ECNLNotFoundError, UpstreamAPIError

# ---- RetryingAdapter -------------------------------------------------------


async def test_retry_succeeds_after_transient_error(mock_repo: AsyncMock):
    # Arrange — first call fails, second succeeds.
    mock_repo.get_standings.side_effect = [UpstreamAPIError("flaky"), "ok"]
    sleeps: list[float] = []
    adapter = RetryingAdapter(mock_repo, sleep=lambda d: sleeps.append(d) or _noop())

    # Act
    result = await adapter.get_standings(3933, 18755, 32928)

    # Assert
    assert result == "ok"
    assert mock_repo.get_standings.await_count == 2
    assert sleeps == [1.0]


async def test_retry_does_not_retry_not_found(mock_repo: AsyncMock):
    # Arrange
    mock_repo.get_event.side_effect = ECNLNotFoundError("nope")
    adapter = RetryingAdapter(mock_repo)

    # Act / Assert
    with pytest.raises(ECNLNotFoundError):
        await adapter.get_event(1)
    assert mock_repo.get_event.await_count == 1


async def test_retry_exhausts_attempts(mock_repo: AsyncMock):
    # Arrange
    mock_repo.get_schedule.side_effect = UpstreamAPIError("always")
    adapter = RetryingAdapter(mock_repo, max_attempts=3, sleep=lambda d: _noop())

    # Act / Assert
    with pytest.raises(UpstreamAPIError):
        await adapter.get_schedule(3933, 32928)
    assert mock_repo.get_schedule.await_count == 3


async def _noop():
    return None


# ---- CachingAdapter --------------------------------------------------------


async def test_cache_hit_avoids_second_call(mock_repo: AsyncMock, sample_event):
    # Arrange — fixed clock so the entry never expires.
    mock_repo.get_event.return_value = sample_event
    adapter = CachingAdapter(mock_repo, now=lambda: 0.0)

    # Act
    await adapter.get_event(3933)
    await adapter.get_event(3933)

    # Assert
    assert mock_repo.get_event.await_count == 1


async def test_cache_expiry_refetches(mock_repo: AsyncMock, sample_event):
    # Arrange — advancing clock pushes past the TTL between calls.
    mock_repo.get_event.return_value = sample_event
    clock = {"t": 0.0}
    adapter = CachingAdapter(mock_repo, ttl_seconds=10.0, now=lambda: clock["t"])

    # Act
    await adapter.get_event(3933)
    clock["t"] = 100.0
    await adapter.get_event(3933)

    # Assert
    assert mock_repo.get_event.await_count == 2


async def test_cache_keys_distinguish_arguments(mock_repo: AsyncMock, sample_standings):
    # Arrange
    mock_repo.get_standings.return_value = sample_standings
    adapter = CachingAdapter(mock_repo, now=lambda: 0.0)

    # Act
    await adapter.get_standings(3933, 18755, 32928)
    await adapter.get_standings(3933, 18755, 99999)

    # Assert — different flight IDs are cached separately.
    assert mock_repo.get_standings.await_count == 2

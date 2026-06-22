"""Tests for event-name classification."""

import pytest

from ecnl.domain.classification import classify_event_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ECNL Girls Southwest 2025-26", ("ECNL", "girls", "Southwest", "2025-26")),
        ("ECNL Boys Northern Cal 2025-26", ("ECNL", "boys", "Northern Cal", "2025-26")),
        ("ECNL RL Girls STXCL 2025-26", ("ECRL", "girls", "STXCL", "2025-26")),
        ("ECNL RL Boys Golden State 2025-26", ("ECRL", "boys", "Golden State", "2025-26")),
    ],
)
def test_classify_known_events(name, expected):
    # Arrange / Act
    result = classify_event_name(name)

    # Assert
    assert result == expected


def test_classify_unknown_name_falls_back_to_empty_parts():
    # Arrange / Act
    league, gender, conference, season = classify_event_name("Some Showcase Tournament")

    # Assert — league defaults to ECNL, the rest are empty rather than raising.
    assert league == "ECNL"
    assert gender == ""
    assert season == ""


def test_classify_handles_four_digit_season():
    # Arrange / Act
    _, _, _, season = classify_event_name("ECNL Girls Southeast 2025-2026")

    # Assert
    assert season == "2025-2026"

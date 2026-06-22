"""Tests for the RPI engine, verified against hand-computed fixtures.

The four-team graph below is fully worked out by hand in the comments so the
expected WP/OWP/OOWP/RPI values are auditable, including the opponent-exclusion
rule and the skip-when-no-other-games case (team D).
"""

import pytest

from ecnl.application._rpi import compute_rpi, winning_pct
from ecnl.domain.models import MatchResult

# Four teams, deliberately unbalanced so OWP/OOWP differ between teams:
#   A beats B, A beats C, B beats C, C beats D
# Records:  A 2-0-0 | B 1-1-0 | C 1-2-0 | D 0-1-0
_GRAPH = [
    MatchResult(home_team="A", away_team="B", home_score=1, away_score=0),
    MatchResult(home_team="A", away_team="C", home_score=1, away_score=0),
    MatchResult(home_team="B", away_team="C", home_score=1, away_score=0),
    MatchResult(home_team="C", away_team="D", home_score=1, away_score=0),
]


def _by_team(rows):
    return {r.team: r for r in rows}


def test_winning_pct_handles_ties_by_weight():
    # Arrange / Act / Assert — 1 win, 1 loss, 2 ties.
    assert winning_pct(1, 1, 2, tie_weight=1 / 3) == pytest.approx((1 + (1 / 3) * 2) / 4)
    assert winning_pct(1, 1, 2, tie_weight=0.5) == pytest.approx((1 + 0.5 * 2) / 4)


def test_winning_pct_zero_games_is_zero():
    # Arrange / Act / Assert
    assert winning_pct(0, 0, 0, tie_weight=0.5) == 0.0


def test_rpi_components_match_hand_computation():
    # Arrange / Act
    rows = _by_team(compute_rpi(_GRAPH, digits=6))

    # Assert — values hand-derived in the module docstring of the test.
    # A: WP=1.0   OWP=0.75  OOWP=0.625
    assert rows["A"].wp == pytest.approx(1.0)
    assert rows["A"].owp == pytest.approx(0.75)
    assert rows["A"].oowp == pytest.approx(0.625)
    assert rows["A"].rpi == pytest.approx(0.25 * 1.0 + 0.5 * 0.75 + 0.25 * 0.625)

    # C: WP=1/3  OWP=0.5  OOWP=0.5  (D is skipped from C's OWP — no other games)
    assert rows["C"].wp == pytest.approx(1 / 3)
    assert rows["C"].owp == pytest.approx(0.5)
    assert rows["C"].oowp == pytest.approx(0.5)

    # D: only opponent is C; C's adjusted WP excluding D is 0/2 = 0.0
    assert rows["D"].owp == pytest.approx(0.0)
    assert rows["D"].oowp == pytest.approx(0.5)


def test_rpi_ranks_descending():
    # Arrange / Act
    rows = compute_rpi(_GRAPH)

    # Assert
    assert [r.team for r in rows] == ["A", "B", "C", "D"]
    assert [r.rank for r in rows] == [1, 2, 3, 4]
    assert rows[0].rpi >= rows[1].rpi >= rows[2].rpi >= rows[3].rpi


def test_rpi_tie_weight_changes_wp_only():
    # Arrange — A ties B, the only game for each.
    results = [MatchResult(home_team="A", away_team="B", home_score=1, away_score=1)]

    # Act
    third = _by_team(compute_rpi(results, wp_tie_weight=1 / 3, digits=6))
    half = _by_team(compute_rpi(results, wp_tie_weight=0.5, digits=6))

    # Assert — WP reflects the chosen tie weight; OWP/OOWP collapse to 0 (no other games).
    assert third["A"].wp == pytest.approx(1 / 3)
    assert half["A"].wp == pytest.approx(0.5)
    assert third["A"].owp == 0.0


def test_rpi_empty_results_is_empty():
    # Arrange / Act / Assert
    assert compute_rpi([]) == []

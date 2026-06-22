"""RPI (Rating Percentage Index) — pure, framework-free computation.

Formula (sites.google.com/site/rpifordivisioniwomenssoccer/rpi-formula),
standard NCAA structure ``(E1 + 2*E2 + E3) / 4`` == ``0.25*WP + 0.50*OWP + 0.25*OOWP``:

  - E1 WP   = (W + wp_tie_weight*T) / (W + L + T)
  - E2 OWP  = mean over each game's opponent of that opponent's winning pct with
              the game(s) against the rated team removed, ties scored at
              ``owp_tie_weight``
  - E3 OOWP = mean over each game's opponent of that opponent's OWP (no exclusion)

``wp_tie_weight`` defaults to 1/3 (2024 convention); pass 1/2 for the pre-2024
convention. ``owp_tie_weight`` defaults to 1/2 per the source.

Design lineage: modeled on the ``ratings`` repo's match-based stats, corrected
to handle ties in WP per the formula above and rebuilt to compute every team in
a single O(V + E) pass (V teams, E game-sides) instead of re-deriving each
opponent's record per lookup.
"""

from collections import defaultdict

from ..domain.models import MatchResult, TeamRPI

# Outcome codes from the rated team's perspective.
_WIN, _LOSS, _TIE = "W", "L", "T"


def _mean(values: list[float]) -> float:
    """Return the arithmetic mean, or 0.0 for an empty list."""
    return sum(values) / len(values) if values else 0.0


def _outcomes(home_score: int, away_score: int) -> tuple[str, str]:
    """Return (home_outcome, away_outcome) codes for a final score."""
    if home_score > away_score:
        return _WIN, _LOSS
    if home_score < away_score:
        return _LOSS, _WIN
    return _TIE, _TIE


def build_graph(results: list[MatchResult]) -> tuple[dict[str, list[int]], dict[str, list[tuple[str, str]]]]:
    """Build the opponent graph from completed match results.

    Returns:
        A ``(record, games)`` pair where ``record[team] == [wins, losses, ties]``
        over all games and ``games[team]`` is the list of ``(opponent, outcome)``
        tuples — one per game played, so repeat opponents appear multiple times.
    """
    record: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    games: dict[str, list[tuple[str, str]]] = defaultdict(list)
    index = {_WIN: 0, _LOSS: 1, _TIE: 2}
    for match in results:
        home_outcome, away_outcome = _outcomes(match.home_score, match.away_score)
        record[match.home_team][index[home_outcome]] += 1
        record[match.away_team][index[away_outcome]] += 1
        games[match.home_team].append((match.away_team, home_outcome))
        games[match.away_team].append((match.home_team, away_outcome))
    return record, games


def winning_pct(wins: int, losses: int, ties: int, tie_weight: float) -> float:
    """Return (W + tie_weight*T) / (W + L + T), or 0.0 when no games played."""
    played = wins + losses + ties
    if played == 0:
        return 0.0
    return (wins + tie_weight * ties) / played


def _opponent_wp_excluding(record: list[int], outcome: str, tie_weight: float) -> float | None:
    """Return an opponent's WP with one game (vs the rated team) removed.

    Args:
        record: The opponent's full ``[wins, losses, ties]``.
        outcome: The rated team's outcome in the game being excluded; the
            opponent's mirror result is subtracted.
        tie_weight: Tie weight for the opponent WP (OWP convention).

    Returns:
        The adjusted winning percentage, or None if the opponent has no other games.
    """
    wins, losses, ties = record
    if outcome == _WIN:  # rated team won -> opponent lost this game
        losses -= 1
    elif outcome == _LOSS:  # rated team lost -> opponent won this game
        wins -= 1
    else:
        ties -= 1
    played = wins + losses + ties
    if played <= 0:
        return None
    return (wins + tie_weight * ties) / played


def _owp(team: str, record: dict[str, list[int]], games: dict[str, list[tuple[str, str]]], tie_weight: float) -> float:
    """Compute a team's opponents' winning percentage (E2)."""
    values = [
        wp
        for opponent, outcome in games[team]
        if (wp := _opponent_wp_excluding(record[opponent], outcome, tie_weight)) is not None
    ]
    return _mean(values)


def compute_rpi(
    results: list[MatchResult],
    wp_tie_weight: float = 1 / 3,
    owp_tie_weight: float = 0.5,
    digits: int = 4,
) -> list[TeamRPI]:
    """Compute RPI for every team appearing in ``results``.

    Args:
        results: Completed matches (team names + integer scores).
        wp_tie_weight: Tie weight for the team's own WP (E1). 1/3 (2024) or 1/2 (pre-2024).
        owp_tie_weight: Tie weight for opponent WP in E2/E3. 1/2 per the source.
        digits: Rounding precision for the reported component and RPI values.

    Returns:
        TeamRPI rows sorted by RPI descending, with 1-based ranks assigned.

    Complexity:
        O(V + E) — single graph build, OWP cached per team before OOWP averages it.
    """
    record, games = build_graph(results)
    teams = list(record)

    owp_values = {team: _owp(team, record, games, owp_tie_weight) for team in teams}

    rows: list[TeamRPI] = []
    for team in teams:
        wins, losses, ties = record[team]
        wp = winning_pct(wins, losses, ties, wp_tie_weight)
        owp = owp_values[team]
        oowp = _mean([owp_values[opponent] for opponent, _ in games[team]])
        rpi = 0.25 * wp + 0.50 * owp + 0.25 * oowp
        rows.append(
            TeamRPI(
                team=team,
                wins=wins,
                losses=losses,
                draws=ties,
                wp=round(wp, digits),
                owp=round(owp, digits),
                oowp=round(oowp, digits),
                rpi=round(rpi, digits),
            )
        )

    rows.sort(key=lambda r: r.rpi, reverse=True)
    for rank, row in enumerate(rows, start=1):
        row.rank = rank
    return rows

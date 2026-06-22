"""Formatters — domain models -> human/LLM-readable strings.

Each ``_fmt_*`` takes a domain result and returns a compact text block. Keeping
formatting here (out of the tool functions) means the tool bodies stay one line
and the wire format is consistent across tools.
"""

import json
from typing import Any

from ...domain.models import (
    Club,
    Event,
    EventOverview,
    Match,
    MatchResult,
    Standings,
    Team,
    TeamRPI,
)


def _fmt_events(events: list[Event]) -> str:
    """Format a list of discovered events."""
    if not events:
        return "No matching events found."
    lines = [f"{len(events)} event(s):"]
    for e in events:
        loc = f" — {e.location}" if e.location else ""
        lines.append(f"  [{e.event_id}] {e.league} {e.gender} · {e.conference} · {e.season}{loc}")
    return "\n".join(lines)


def _fmt_event_overview(overview: EventOverview) -> str:
    """Format an event's division/flight tree."""
    e = overview.event
    lines = [
        f"{e.name}  [event {e.event_id}]",
        f"  league={e.league} gender={e.gender} conference={e.conference} season={e.season}",
    ]
    if not overview.divisions:
        lines.append("  (no divisions published)")
    for d in overview.divisions:
        lines.append(f"  Division {d.name} [{d.division_id}] ({d.gender}):")
        for f in d.flights:
            sched = "schedule active" if f.has_active_schedule else "no schedule yet"
            lines.append(f"    flight [{f.flight_id}] {f.name} — {f.teams_count} teams, {sched}")
    return "\n".join(lines)


def _fmt_standings(standings: Standings) -> str:
    """Format a flight standings table."""
    if not standings.rows:
        return f"No standings available for flight {standings.flight_id}."
    lines = [
        f"Standings — event {standings.event_id}, division {standings.division_id}, flight {standings.flight_id}:",
        f"  {'#':>2}  {'Team':<34} {'W-L-D':>8} {'Pts':>4} {'PPG':>5}",
    ]
    for i, r in enumerate(standings.rows, start=1):
        rank = r.rank if r.rank is not None else i
        record = f"{r.wins}-{r.losses}-{r.draws}"
        lines.append(f"  {rank:>2}  {r.team_name[:34]:<34} {record:>8} {r.points:>4} {r.points_per_game:>5.2f}")
    return "\n".join(lines)


def _fmt_match_line(m: Match) -> str:
    """Format a single match as one line."""
    when = " ".join(x for x in (m.date, m.time) if x) or "TBD"
    score = f"{m.home_score}-{m.away_score}" if m.is_played else "vs"
    venue = f" @ {m.venue}" if m.venue else ""
    return f"  {when}: {m.home_team} {score} {m.away_team}{venue}"


def _fmt_schedule(matches: list[Match]) -> str:
    """Format a flight or team schedule."""
    if not matches:
        return "No matches scheduled."
    return "\n".join([f"{len(matches)} match(es):", *(_fmt_match_line(m) for m in matches)])


def _fmt_teams(teams: list[Team]) -> str:
    """Format a team list."""
    if not teams:
        return "No teams found."
    lines = [f"{len(teams)} team(s):"]
    for t in teams:
        coach = f" — coach {t.head_coach}" if t.head_coach else ""
        lines.append(f"  [{t.team_id}] {t.name}{coach}")
    return "\n".join(lines)


def _fmt_clubs(clubs: list[Club]) -> str:
    """Format a club list."""
    if not clubs:
        return "No clubs found."
    lines = [f"{len(clubs)} club(s):"]
    for c in clubs:
        where = ", ".join(x for x in (c.city, c.state_code) if x)
        where = f" ({where})" if where else ""
        lines.append(f"  [{c.club_id}] {c.name}{where}")
    return "\n".join(lines)


def _fmt_results(results: list[MatchResult]) -> str:
    """Format extracted completed results."""
    if not results:
        return "No completed matches yet."
    lines = [f"{len(results)} completed match(es):"]
    for r in results:
        lines.append(f"  {r.home_team} {r.home_score}-{r.away_score} {r.away_team}")
    return "\n".join(lines)


def _fmt_rpi(table: list[TeamRPI]) -> str:
    """Format a full RPI table."""
    if not table:
        return "No completed matches — RPI cannot be computed yet."
    lines = [
        "RPI = 0.25·WP + 0.50·OWP + 0.25·OOWP",
        f"  {'#':>2}  {'Team':<34} {'W-L-D':>8} {'WP':>6} {'OWP':>6} {'OOWP':>6} {'RPI':>6}",
    ]
    for r in table:
        record = f"{r.wins}-{r.losses}-{r.draws}"
        lines.append(
            f"  {r.rank:>2}  {r.team[:34]:<34} {record:>8} {r.wp:>6.3f} {r.owp:>6.3f} {r.oowp:>6.3f} {r.rpi:>6.3f}"
        )
    return "\n".join(lines)


def _fmt_team_rpi(r: TeamRPI) -> str:
    """Format a single team's RPI breakdown."""
    return (
        f"{r.team} — RPI {r.rpi:.4f} (rank {r.rank})\n"
        f"  record: {r.wins}-{r.losses}-{r.draws}\n"
        f"  WP   (0.25): {r.wp:.4f}\n"
        f"  OWP  (0.50): {r.owp:.4f}\n"
        f"  OOWP (0.25): {r.oowp:.4f}"
    )


def _fmt_raw(data: Any) -> str:
    """Format an unstructured payload (match detail, brackets) as pretty JSON."""
    if not data:
        return "No data available."
    return json.dumps(data, indent=2, default=str)

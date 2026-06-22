"""Wire-format -> domain-model parsers for the AthleteOne API.

Kept separate from the HTTP adapter so that module stays focused on transport.
Each ``_parse_*`` function takes one raw JSON object (already unwrapped from the
``{"result": "success", "data": ...}`` envelope) and returns a domain model.

The feed is permissive with field presence and casing, so parsers use ``.get``
with sensible fallbacks rather than assuming keys exist.
"""

from typing import Any

from ...domain.classification import classify_event_name
from ...domain.models import (
    Club,
    Division,
    Event,
    Flight,
    Match,
    StandingRow,
    Team,
)


def _to_int(value: Any) -> int | None:
    """Coerce a feed value to int, returning None when it isn't numeric."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int0(value: Any) -> int:
    """Coerce a feed value to int, defaulting to 0 for missing/non-numeric input."""
    return _to_int(value) or 0


def _standing_ppg(raw: dict[str, Any], points: int, played: int) -> float:
    """Return points-per-game from the feed, or derive it from points/games played."""
    ppg = raw.get("ppg")
    if ppg is not None:
        return float(ppg)
    return round(points / played, 4) if played else 0.0


def parse_event(raw: dict[str, Any]) -> Event:
    """Parse an event-details ``data`` object into an Event.

    Classifies league/gender/conference/season from the event name.
    """
    name = raw.get("name", "")
    league, gender, conference, season = classify_event_name(name)
    return Event(
        event_id=_to_int(raw.get("eventID")) or 0,
        name=name,
        league=league,
        gender=gender,
        conference=conference,
        season=season,
        location=raw.get("location") or raw.get("city"),
        start_date=raw.get("startDate"),
        end_date=raw.get("endDate"),
    )


def _parse_flight(raw: dict[str, Any], division_name: str) -> Flight:
    """Parse one flight entry from a division's ``flightList``."""
    return Flight(
        flight_id=_to_int(raw.get("flightID")) or 0,
        division_id=_to_int(raw.get("divisionID")) or 0,
        division_name=division_name,
        name=raw.get("flightName", ""),
        teams_count=_to_int(raw.get("teamsCount")) or 0,
        has_active_schedule=bool(raw.get("hasActiveSchedule", False)),
    )


def parse_division_with_flights(raw: dict[str, Any], gender: str) -> Division:
    """Parse one entry from ``girlsDivAndFlightList`` / ``boysDivAndFlightList``."""
    name = raw.get("divisionName", "")
    flights = [_parse_flight(f, name) for f in raw.get("flightList", [])]
    return Division(
        division_id=_to_int(raw.get("divisionID")) or 0,
        name=name,
        gender=gender,
        flights=flights,
    )


def parse_standing_row(raw: dict[str, Any]) -> StandingRow:
    """Parse one team row from a standings ``teamStandings`` list."""
    wins, losses, draws = _int0(raw.get("wins")), _int0(raw.get("losses")), _int0(raw.get("draws"))
    points = _to_int(raw.get("standingpoints"))
    if points is None:
        points = wins * 3 + draws
    played = wins + losses + draws
    return StandingRow(
        team_id=_int0(raw.get("teamID")),
        team_name=raw.get("name", ""),
        wins=wins,
        losses=losses,
        draws=draws,
        points=points,
        points_per_game=_standing_ppg(raw, points, played),
        goals_for=_to_int(raw.get("goalsfor")),
        goals_against=_to_int(raw.get("goalsagainst")),
        goal_differential=_to_int(raw.get("goaldifferential")),
        rank=_to_int(raw.get("rank")),
        club_logo=raw.get("clublogo") or raw.get("clubLogo"),
    )


def parse_match(raw: dict[str, Any]) -> Match:
    """Parse one match entry from a flight schedule."""
    return Match(
        match_id=_to_int(raw.get("matchID")) or 0,
        date=raw.get("gameDate"),
        time=raw.get("gameTime"),
        home_team_id=_to_int(raw.get("hometeamID")),
        home_team=raw.get("homeTeam") or raw.get("hometeam") or "",
        away_team_id=_to_int(raw.get("awayteamID")),
        away_team=raw.get("awayTeam") or raw.get("awayteam") or "",
        home_score=_to_int(raw.get("hometeamscore")),
        away_score=_to_int(raw.get("awayteamscore")),
        venue=raw.get("venue"),
        complex=raw.get("complex"),
        flight_id=_to_int(raw.get("flightID")),
        division=raw.get("division"),
        status=raw.get("type"),
    )


def parse_team(raw: dict[str, Any]) -> Team:
    """Parse one team entry from a flight/event team list."""
    return Team(
        team_id=_to_int(raw.get("teamID")) or 0,
        name=raw.get("name", ""),
        club_id=_to_int(raw.get("clubID")),
        club_logo=raw.get("clubLogo"),
        head_coach=raw.get("headCoach"),
    )


def parse_club(raw: dict[str, Any]) -> Club:
    """Parse one club entry from an org/event club list."""
    return Club(
        club_id=_to_int(raw.get("clubID")) or 0,
        name=raw.get("clubName") or raw.get("clubFullName") or "",
        city=raw.get("city"),
        state_code=raw.get("stateCode"),
        logo=raw.get("clubLogo"),
    )

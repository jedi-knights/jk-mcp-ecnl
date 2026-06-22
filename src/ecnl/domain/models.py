"""Domain models for the ECNL MCP server.

Pure Python dataclasses with zero framework dependencies. Adapters translate
to/from these types from the AthleteOne API wire format.

Vocabulary (see docs/decisions/0001-data-source-athleteone-api.md):
  - league:     "ECNL" or "ECRL" (the API spells ECRL as "ECNL RL")
  - gender:     "girls" or "boys"
  - event:      one league x gender x conference x season (has an ``event_id``)
  - division:   an age group within an event (e.g. "G2008/2007")
  - flight:     a competition grouping within a division; standings and
                schedules are keyed by ``flight_id``
"""

from dataclasses import dataclass, field

# League/gender are kept as plain strings (not enums) so they serialize cleanly
# through MCP tool arguments and the JSON cache key. Validated at the boundary.
type League = str  # "ECNL" | "ECRL"
type Gender = str  # "girls" | "boys"


@dataclass(slots=True)
class Event:
    """A single ECNL/ECRL competition: one league x gender x conference x season.

    ``conference`` and ``season`` are parsed from the event name (e.g.
    "ECNL Girls Southeast 2025-26" -> league=ECNL, gender=girls,
    conference="Southeast", season="2025-26").
    """

    event_id: int
    name: str
    league: League
    gender: Gender
    conference: str
    season: str
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None


@dataclass(slots=True)
class Flight:
    """A competition grouping within a division.

    ``name`` is the flight label from the feed — typically "ECNL" or "ECRL" —
    which is how a single event can carry both league tiers. Standings and
    schedules are addressed by ``flight_id``.
    """

    flight_id: int
    division_id: int
    division_name: str
    name: str
    teams_count: int
    has_active_schedule: bool = False


@dataclass(slots=True)
class Division:
    """An age group within an event, with its flights."""

    division_id: int
    name: str
    gender: Gender
    flights: list[Flight] = field(default_factory=list)


@dataclass(slots=True)
class EventOverview:
    """Full navigation tree for an event: the event plus its divisions/flights.

    Divisions are split by gender at the source; this model keeps a single
    flattened list and each division carries its own ``gender``.
    """

    event: Event
    divisions: list[Division] = field(default_factory=list)


@dataclass(slots=True)
class Team:
    """A team competing in a flight or event."""

    team_id: int
    name: str
    club_id: int | None = None
    club_logo: str | None = None
    head_coach: str | None = None


@dataclass(slots=True)
class Club:
    """A club participating in an event."""

    club_id: int
    name: str
    city: str | None = None
    state_code: str | None = None
    logo: str | None = None


@dataclass(slots=True)
class StandingRow:
    """A single team's row in a flight standings table."""

    team_id: int
    team_name: str
    wins: int
    losses: int
    draws: int
    points: int
    points_per_game: float
    goals_for: int | None = None
    goals_against: int | None = None
    goal_differential: int | None = None
    rank: int | None = None
    club_logo: str | None = None


@dataclass(slots=True)
class Standings:
    """A flight's standings table, ordered as returned by the source."""

    event_id: int
    division_id: int
    flight_id: int
    rows: list[StandingRow] = field(default_factory=list)


@dataclass(slots=True)
class Match:
    """A single scheduled or completed match within a flight.

    ``home_score``/``away_score`` are None until the match is played. ``status``
    carries the source's free-text status / game type (e.g. "Group Play").
    """

    match_id: int
    date: str | None
    time: str | None
    home_team_id: int | None
    home_team: str
    away_team_id: int | None
    away_team: str
    home_score: int | None = None
    away_score: int | None = None
    venue: str | None = None
    complex: str | None = None
    flight_id: int | None = None
    division: str | None = None
    status: str | None = None

    @property
    def is_played(self) -> bool:
        """True when both scores are present (the match has a final result)."""
        return self.home_score is not None and self.away_score is not None


@dataclass(slots=True)
class MatchResult:
    """A completed match reduced to the fields RPI needs.

    Team identity is the team *name* because the RPI opponent graph is built by
    matching team names across a flight's full schedule.
    """

    home_team: str
    away_team: str
    home_score: int
    away_score: int


@dataclass(slots=True)
class TeamRPI:
    """A team's RPI with its three weighted components and its raw record.

    ``rpi = wp_weight*wp + owp_weight*owp + oowp_weight*oowp`` (NCAA 25/50/25).
    ``wp``/``owp``/``oowp`` are the winning-percentage, opponents' winning-
    percentage, and opponents' opponents' winning-percentage elements.
    """

    team: str
    wins: int
    losses: int
    draws: int
    wp: float
    owp: float
    oowp: float
    rpi: float
    rank: int | None = None

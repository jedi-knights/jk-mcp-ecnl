"""DiscoveryAdapter — resolves league/gender/season queries to events.

The AthleteOne feed has no "list all events for a season" endpoint. It does,
however, expose each league/gender *organization*'s club list, and every club
entry carries the ``eventID`` of the event it currently competes in. So
discovery works as:

    (league, gender) -> orgID (seed map below)
    orgID            -> get_org_club_events -> distinct event IDs
    event ID         -> get_event -> Event classified by name (conference/season)

Only the four org IDs are seeded; everything else is derived live. The IDs are
stable identifiers, not data — see docs/decisions/0001-data-source-athleteone-api.md
for how they were resolved and how to re-derive them if the league restructures.
"""

import asyncio
import logging
from collections.abc import Callable

from ...domain.models import Event
from ...ports.outbound import ECNLAPIPort

logger = logging.getLogger(__name__)


def _norm(value: str | None, transform: Callable[[str], str]) -> str | None:
    """Apply ``transform`` to a non-empty value, returning None otherwise."""
    return transform(value) if value else None


# (league, gender) -> AthleteOne organization ID. ECRL is "ECNL RL" in the feed.
_ORG_IDS: dict[tuple[str, str], int] = {
    ("ECNL", "girls"): 9,
    ("ECNL", "boys"): 12,
    ("ECRL", "girls"): 13,
    ("ECRL", "boys"): 16,
}


class DiscoveryAdapter:
    """Enumerates and classifies events by walking org club lists."""

    def __init__(self, repo: ECNLAPIPort, org_ids: dict[tuple[str, str], int] | None = None) -> None:
        """Initialize discovery over an ECNLAPIPort.

        Args:
            repo: The data port used to fetch org club lists and event details.
            org_ids: Override for the (league, gender) -> orgID seed map.
        """
        self._repo = repo
        # `is not None` (not truthiness) so an explicit empty override is honored.
        self._org_ids = org_ids if org_ids is not None else dict(_ORG_IDS)

    async def find_events(
        self,
        league: str | None = None,
        gender: str | None = None,
        season: str | None = None,
    ) -> list[Event]:
        """Return events matching the given filters.

        Args:
            league: "ECNL" or "ECRL" (case-insensitive), or None for both.
            gender: "girls" or "boys" (case-insensitive), or None for both.
            season: Season label like "2025-26", or None for all seasons present.

        Returns:
            Events sorted by league, gender, then conference.
        """
        league_n = _norm(league, str.upper)
        gender_n = _norm(gender, str.lower)

        orgs = [org_id for key, org_id in self._org_ids.items() if _org_matches(key, league_n, gender_n)]
        if not orgs:
            return []

        events = await self._gather_events(orgs)
        results = [e for e in events if _event_matches(e, league_n, gender_n, season)]
        results.sort(key=lambda e: (e.league, e.gender, e.conference))
        return results

    async def _gather_events(self, orgs: list[int]) -> list[Event]:
        """Fan out across orgs to collect every distinct event, then fetch each.

        Bounded by the number of conferences per org (~10-20), so this stays small.
        """
        event_id_lists = await asyncio.gather(*(self._repo.get_org_club_events(o) for o in orgs))
        event_ids = sorted({eid for ids in event_id_lists for eid in ids})
        return list(await asyncio.gather(*(self._repo.get_event(eid) for eid in event_ids)))


def _org_matches(key: tuple[str, str], league: str | None, gender: str | None) -> bool:
    """Return True if an org's (league, gender) key passes the optional filters."""
    org_league, org_gender = key
    return (league is None or org_league == league) and (gender is None or org_gender == gender)


def _event_matches(event: Event, league: str | None, gender: str | None, season: str | None) -> bool:
    """Return True if a classified event passes the optional league/gender/season filters."""
    return (
        (league is None or event.league == league)
        and (gender is None or event.gender == gender)
        and (season is None or event.season == season)
    )

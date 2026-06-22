"""Event-name classification — pure domain logic.

The AthleteOne feed has no field that says "this event is ECNL girls in the
Southeast conference for 2025-26". That information is encoded in the event
*name*, e.g.:

    "ECNL Girls Southeast 2025-26"      -> ECNL  / girls / Southeast   / 2025-26
    "ECNL Boys Northern Cal 2025-26"    -> ECNL  / boys  / Northern Cal / 2025-26
    "ECNL RL Girls STXCL 2025-26"       -> ECRL  / girls / STXCL        / 2025-26
    "ECNL RL Boys Golden State 2025-26" -> ECRL  / boys  / Golden State / 2025-26

ECRL is spelled "ECNL RL" in the source. This module is the single place that
understands that convention; both the outbound adapter and discovery rely on it.
"""

import re

# Trailing season token like "2025-26" or "2025-2026".
_SEASON_RE = re.compile(r"\b(\d{4}-\d{2,4})\b")


def classify_event_name(name: str) -> tuple[str, str, str, str]:
    """Parse an event name into (league, gender, conference, season).

    Args:
        name: The raw event name from the feed.

    Returns:
        A ``(league, gender, conference, season)`` tuple. ``league`` is "ECNL"
        or "ECRL"; ``gender`` is "girls" or "boys". ``conference`` and ``season``
        fall back to "" when they cannot be parsed, so callers always get four
        strings and can decide how to treat an unrecognized name.
    """
    text = name.strip()
    league = "ECRL" if re.search(r"\bECNL\s+RL\b", text, re.IGNORECASE) else "ECNL"

    lowered = text.lower()
    if "girls" in lowered:
        gender = "girls"
    elif "boys" in lowered:
        gender = "boys"
    else:
        gender = ""

    season_match = _SEASON_RE.search(text)
    season = season_match.group(1) if season_match else ""

    conference = _extract_conference(text, gender, season)
    return league, gender, conference, season


def _extract_conference(text: str, gender: str, season: str) -> str:
    """Return the conference slice between the gender token and the season."""
    remainder = text
    if gender:
        # Cut everything up to and including the gender word (Girls/Boys).
        match = re.search(gender, remainder, re.IGNORECASE)
        if match:
            remainder = remainder[match.end() :]
    if season:
        remainder = remainder.replace(season, "")
    return remainder.strip()

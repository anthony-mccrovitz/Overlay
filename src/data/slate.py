"""Slate-date filtering for odds-fed sports.

The Odds API returns the next N *upcoming* events for a sport regardless of
date. On sparse playoff slates the "next game" can be days away, so a naive
"keep everything that hasn't started" filter leaks future games onto today's
card. This module keeps only events whose *local* game date matches the slate
date, so an off-day correctly yields an empty slate instead of a future pick.

MLB doesn't need this — it builds its slate from the MLB Stats API by date —
but NBA and NHL fetch their slates straight from the odds feed and do.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def _to_date(game_date: date | str) -> date:
    """Accept a date or a YYYYMMDD / YYYY-MM-DD string."""
    if isinstance(game_date, date):
        return game_date
    s = str(game_date).replace("-", "")
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def event_local_date(commence: str, tz: str = "America/New_York") -> date | None:
    """Local calendar date of an ISO commence_time, or None if unparseable."""
    if not commence:
        return None
    try:
        dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(tz)).date()
    except (ValueError, TypeError):
        return None


def filter_to_slate(
    events: list[dict],
    game_date: date | str,
    tz: str = "America/New_York",
    commence_key: str = "commence_time",
) -> list[dict]:
    """Keep only events whose local (default ET) game date equals game_date.

    Late tip-offs cross into the next UTC day, so we compare in local time
    rather than on the raw UTC date string. Events with a missing/malformed
    commence time are dropped — we can't confirm they belong to this slate.
    """
    target = _to_date(game_date)
    return [
        e
        for e in events
        if event_local_date(e.get(commence_key, ""), tz) == target
    ]

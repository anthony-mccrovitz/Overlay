"""Slate-date filtering for odds-fed sports.

The Odds API returns the next N *upcoming* events for a sport regardless of
date. On sparse playoff slates the "next game" can be days away, so a naive
"keep everything that hasn't started" filter leaks future games onto today's
card. This module keeps only events whose *local* game date matches the slate
date, so an off-day correctly yields an empty slate instead of a future pick.

MLB needs this too, despite building its slate from the MLB Stats API by
date: predictions are joined to odds rows by *team name* (value_bets.py),
and during a series the same two teams sit on the odds board for consecutive
days — without a slate filter the join happily prices today's prediction
with yesterday's (or tomorrow's) line. That exact miss produced the
2026-07-12 phantom-edge card.
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


def filter_df_to_slate(
    odds_df,
    game_date: date | str,
    tz: str = "America/New_York",
    commence_col: str = "CommenceTime",
):
    """DataFrame twin of filter_to_slate for odds_api.fetch_odds() output.

    Keeps only rows whose local game date equals game_date. Rows with a
    missing/unparseable commence time are dropped — a row we can't place on
    the slate can't be safely priced against it.
    """
    if odds_df.empty or commence_col not in odds_df.columns:
        return odds_df
    target = _to_date(game_date)
    mask = odds_df[commence_col].map(
        lambda c: event_local_date(str(c or ""), tz) == target
    )
    dropped = int((~mask).sum())
    if dropped:
        n_games = odds_df.loc[~mask, "GameID"].nunique() if "GameID" in odds_df.columns else "?"
        print(f"  [slate] Dropped {dropped} odds row(s) ({n_games} game(s)) not on the {target} slate.")
    return odds_df[mask]

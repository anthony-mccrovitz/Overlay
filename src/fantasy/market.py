"""
market.py — team context for the whole board, priced by the betting market.

WHY THIS EXISTS
───────────────
`valuation.py` projects every player from his own 2025 box score. It has no
team-level features at all: no offensive line, no target competition, no scheme,
no pace. Its docstring is honest about this — modelling team change is hard and
doing it badly is worse than not doing it.

But the market already does it, continuously and for free. When Myles Garrett
left Cleveland, the Browns' win total moved within hours. A game's total and
spread are a live, money-backed estimate of how many points each offense will
score, and they price every roster move, injury and coaching change the moment
it becomes public. So rather than build team features and lose to the market,
this module reads the market and hands the board the one thing it is missing.

The quantity is the IMPLIED TEAM TOTAL — how many points a team is expected to
score in a specific game:

    home = (total - home_spread) / 2      away = (total + home_spread) / 2

A 40.5 total with the home team laying 3 means 21.75 / 18.75.

WHAT IT FIXES, AND WHAT IT DOES NOT
───────────────────────────────────
It fixes TEAM context. It does NOT fix ROLE. A receiver who changed teams still
carries last season's target share from his old offense, and no amount of market
data tells you how the new coordinator will use him. Treat a market-adjusted
number for a player who moved as "the right team, the wrong role" — better than
before, still not trustworthy. `TeamWeek.note` flags this where it can.

Defense is the exception, and the reason this module was written. A DST's
fantasy points are almost entirely a function of the offense it faces, and its
"player id" in Sleeper is the team code — so `valuation.py` is projecting the
FRANCHISE's 2025 box score forward and personnel change is invisible by
construction. For DST the market does not adjust the projection, it REPLACES it.

MISSING LINES ARE NOT A GREEN LIGHT
───────────────────────────────────
This repo's recurring bug is "couldn't check" rendering as "all clear". If the
book has not posted a week yet, every function here returns empty and says so.
Nothing silently falls back to the stale projection, because a stale projection
that looks market-adjusted is worse than one that admits it isn't.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

import pandas as pd

ODDS_SPORT = "americanfootball_nfl"

# The Odds API returns full club names; Sleeper keys everything by abbreviation,
# including DST player ids. This join is the only reason the map exists.
TEAM_ABBR: dict[str, str] = {
    "Arizona Cardinals": "ARI",      "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",       "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",      "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",     "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",         "Denver Broncos": "DEN",
    "Detroit Lions": "DET",          "Green Bay Packers": "GB",
    "Houston Texans": "HOU",         "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",   "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV",       "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR",       "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",      "New England Patriots": "NE",
    "New Orleans Saints": "NO",      "New York Giants": "NYG",
    "New York Jets": "NYJ",          "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",       "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",       "Washington Commanders": "WAS",
}

# How much of a team's scoring swing reaches an individual skill player.
#
# A team projected for 27 instead of 21 does not make its WR1 score 29% more.
# Receptions and yardage accrue on volume regardless of whether drives finish,
# and a trailing team throws MORE — so the correlation is real but well under
# one, and part of it runs backwards.
#
# This constant is a JUDGMENT CALL, NOT A FITTED COEFFICIENT. Fitting it needs
# weekly fantasy points joined to historical weekly closing totals, and this repo
# has no NFL odds history — the NFL lanes were wired 2026-07-31, pre-season. It
# is set deliberately low so the adjustment breaks ties rather than overturning
# the projection. If NFL odds history accumulates, fit this and delete the note.
SKILL_PASS_THROUGH = 0.50

# Kickers score when their own offense moves the ball but stalls, so team total
# is the signal — but field goals come from the drives that DON'T finish, which
# is why this is damped even harder than skill players.
KICKER_PASS_THROUGH = 0.30

# Positions whose fantasy value is driven by the OPPONENT rather than by their
# own team. Only one, but naming it beats a magic string.
OPPONENT_DRIVEN = ("DEF",)


@dataclass
class TeamWeek:
    """One team's market-implied context for one week."""
    team: str                 # Sleeper abbreviation
    opponent: str
    is_home: bool
    game_total: float
    implied_total: float      # points this team is expected to SCORE
    opp_implied_total: float  # points this team is expected to ALLOW
    books: int = 0

    @property
    def note(self) -> str:
        return f"{'vs' if self.is_home else '@'} {self.opponent}"


def _schedule(week: int, season: int) -> list[tuple[str, str]]:
    """(away, home) for every game in `week`, straight from Sleeper.

    Sleeper is authoritative for who plays whom and already speaks in the
    abbreviations the rest of the fantasy package uses, so the odds feed is only
    ever asked for prices — never for matchups.
    """
    url = f"https://api.sleeper.app/schedule/nfl/regular/{season}"
    with urllib.request.urlopen(url, timeout=30) as fh:
        games = json.load(fh)
    return [(g["away"], g["home"]) for g in games if g.get("week") == week]


def week_market(week: int, season: int = 2026,
                odds_df: pd.DataFrame | None = None) -> dict[str, TeamWeek]:
    """Market-implied context for all 32 teams in `week`.

    Returns {} — not a partial or a guess — when the book has not posted the
    week. Callers must treat empty as "unknown", never as "no adjustment".
    """
    if odds_df is None:
        from src.data.odds_api import fetch_odds
        odds_df = fetch_odds(sport=ODDS_SPORT, markets="spreads,totals")
    if odds_df is None or odds_df.empty:
        return {}

    need = {"HomeTeam", "AwayTeam", "HomeSpread", "Total", "Sportsbook"}
    if not need.issubset(odds_df.columns):
        return {}

    # Consensus across books: median is the right centre here because a single
    # stale or off-market book should not move the number.
    df = odds_df.dropna(subset=["HomeSpread", "Total"])
    if df.empty:
        return {}
    lines = df.groupby(["HomeTeam", "AwayTeam"]).agg(
        total=("Total", "median"),
        home_spread=("HomeSpread", "median"),
        books=("Sportsbook", "nunique"),
    ).reset_index()

    priced: dict[tuple[str, str], tuple[float, float, int]] = {}
    for row in lines.itertuples(index=False):
        home = TEAM_ABBR.get(row.HomeTeam)
        away = TEAM_ABBR.get(row.AwayTeam)
        if home and away:
            priced[(away, home)] = (row.total, row.home_spread, row.books)

    out: dict[str, TeamWeek] = {}
    for away, home in _schedule(week, season):
        hit = priced.get((away, home))
        if hit is None:
            continue                      # unpriced game — omit, never invent
        total, home_spread, books = hit
        home_itt = (total - home_spread) / 2
        away_itt = (total + home_spread) / 2
        out[home] = TeamWeek(home, away, True,  total, home_itt, away_itt, books)
        out[away] = TeamWeek(away, home, False, total, away_itt, home_itt, books)
    return out


def league_average(market: dict[str, TeamWeek]) -> float:
    """Mean implied team total across the priced slate — the context baseline."""
    if not market:
        return 0.0
    return sum(tw.implied_total for tw in market.values()) / len(market)


def context_multiplier(position: str, team: str,
                       market: dict[str, TeamWeek]) -> float | None:
    """How much to scale a weekly projection for market context. None = unknown.

    None is a first-class answer and means the game is not priced. It is
    deliberately not 1.0: a caller that cannot tell "no adjustment" from "no
    data" is the bug this repo keeps rediscovering.
    """
    tw = market.get(team)
    if tw is None:
        return None
    avg = league_average(market)
    if avg <= 0:
        return None

    if position in OPPONENT_DRIVEN:
        # A defense gets better as its opponent gets worse, so the ratio inverts.
        return avg / tw.opp_implied_total if tw.opp_implied_total > 0 else None

    damping = KICKER_PASS_THROUGH if position == "K" else SKILL_PASS_THROUGH
    return 1.0 + damping * (tw.implied_total / avg - 1.0)


def rank_defenses(market: dict[str, TeamWeek],
                  exclude: set[str] | None = None) -> list[TeamWeek]:
    """Defenses best-to-worst for the week: lowest opponent implied total first.

    This is the whole DST model. It carries no 2025 production term at all,
    because a defense's player id is its team code and last year's box score
    describes a roster that may no longer exist.
    """
    gone = exclude or set()
    return sorted((tw for tm, tw in market.items() if tm not in gone),
                  key=lambda tw: tw.opp_implied_total)

"""
schedule.py — bye weeks and position-specific strength of schedule.

Two things that decide leagues and that almost nobody in a casual league checks.

BYE WEEKS. Drafting three running backs who all rest in week 7 is an entirely
avoidable way to lose a game. The schedule gives this exactly — a team missing
from a week is on bye — so there is no excuse for guessing.

PLAYOFF SCHEDULE. This league's playoffs start in week 15 and pay six teams. A
season's work is decided across weeks 15-17, and the players who win it are the
ones facing defenses that cannot stop their position. Sleeper publishes
`fan_pts_allow_rb / _wr / _qb / _te` per defense, so this is a measured quantity
rather than a vibe: we can say how many fantasy points a defense actually gave up
to running backs last year, and who Anthony's candidates play in December.

The caveat that applies to all of it: defenses change between seasons more than
offenses do — personnel, coordinators, injuries. Last year's numbers are the best
public estimate available and still only an estimate, so SOS is a tiebreaker
between close players, never a reason to move someone rounds up the board.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from src.fantasy import sleeper

SCHEDULE_URL = "https://api.sleeper.app/schedule/nfl/regular/{season}"
CACHE = Path("data/cache/sleeper")

REGULAR_WEEKS = 18


def schedule(season: int = 2026) -> list[dict]:
    """All regular-season games: {week, home, away, date}."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"schedule_{season}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            pass
    req = urllib.request.Request(SCHEDULE_URL.format(season=season),
                                 headers={"User-Agent": "overlay-fantasy/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read())
    path.write_text(json.dumps(data))
    return data


def bye_weeks(season: int = 2026) -> dict[str, int]:
    """{team: bye_week}. A team absent from a week is on bye that week."""
    games = schedule(season)
    playing: dict[int, set[str]] = {}
    teams: set[str] = set()
    for g in games:
        w = g.get("week")
        if not isinstance(w, int):
            continue
        for side in ("home", "away"):
            t = g.get(side)
            if t:
                playing.setdefault(w, set()).add(t)
                teams.add(t)
    out: dict[str, int] = {}
    for w in sorted(playing):
        for t in teams - playing[w]:
            out.setdefault(t, w)
    return out


def opponents(season: int = 2026) -> dict[str, dict[int, str]]:
    """{team: {week: opponent}}."""
    out: dict[str, dict[int, str]] = {}
    for g in schedule(season):
        w, h, a = g.get("week"), g.get("home"), g.get("away")
        if not (isinstance(w, int) and h and a):
            continue
        out.setdefault(h, {})[w] = a
        out.setdefault(a, {})[w] = h
    return out


# ─────────────────────────── defensive strength ──────────────────────────────

POS_ALLOW_KEY = {
    "QB": "fan_pts_allow_qb",
    "RB": "fan_pts_allow_rb",
    "WR": "fan_pts_allow_wr",
    "TE": "fan_pts_allow_te",
}


def points_allowed(season: int = 2025) -> dict[str, dict[str, float]]:
    """{team: {position: fantasy points allowed per game}}.

    Measured, not inferred: Sleeper tracks what each defense actually gave up to
    each position. Normalised per game so a team that played 17 isn't penalised
    against one that played 16.
    """
    stats = sleeper.season_stats(season)
    out: dict[str, dict[str, float]] = {}
    for pid, st in stats.items():
        # Team defense rows are keyed by the team abbreviation.
        if not (isinstance(st, dict) and len(pid) <= 3 and pid.isupper()):
            continue
        gp = float(st.get("gp") or 0) or 17.0
        row = {}
        for pos, key in POS_ALLOW_KEY.items():
            v = st.get(key)
            if isinstance(v, (int, float)):
                row[pos] = round(float(v) / gp, 2)
        if row:
            out[pid] = row
    return out


@dataclass
class ScheduleView:
    byes: dict[str, int]
    opp: dict[str, dict[int, str]]
    allowed: dict[str, dict[str, float]]
    league_avg: dict[str, float] = field(default_factory=dict)

    def sos(self, team: str, position: str,
            weeks: range | list[int] | None = None) -> float | None:
        """Fantasy points a player's opponents allow to his position, per game,
        relative to league average. >1.0 is an easy schedule.
        """
        if team not in self.opp or position not in POS_ALLOW_KEY:
            return None
        wk = list(weeks) if weeks is not None else list(range(1, REGULAR_WEEKS + 1))
        vals = []
        for w in wk:
            o = self.opp[team].get(w)
            if not o:
                continue                       # bye
            v = (self.allowed.get(o) or {}).get(position)
            if v is not None:
                vals.append(v)
        if not vals:
            return None
        avg = self.league_avg.get(position)
        mean = sum(vals) / len(vals)
        return round(mean / avg, 3) if avg else round(mean, 2)

    def playoff_sos(self, team: str, position: str,
                    start_week: int = 15, end_week: int = 17) -> float | None:
        """SOS across the weeks that actually decide the championship."""
        return self.sos(team, position, range(start_week, end_week + 1))

    def playoff_opponents(self, team: str,
                          start_week: int = 15, end_week: int = 17) -> list[str]:
        return [self.opp.get(team, {}).get(w, "BYE")
                for w in range(start_week, end_week + 1)]


def load_view(season: int = 2026, stats_season: int = 2025) -> ScheduleView:
    allowed = points_allowed(stats_season)
    avg: dict[str, float] = {}
    for pos in POS_ALLOW_KEY:
        vals = [row[pos] for row in allowed.values() if pos in row]
        if vals:
            avg[pos] = sum(vals) / len(vals)
    return ScheduleView(byes=bye_weeks(season), opp=opponents(season),
                        allowed=allowed, league_avg=avg)

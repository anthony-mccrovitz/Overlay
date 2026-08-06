"""
sleeper.py — read-only client for the Sleeper API.

Sleeper publishes everything this tool needs without auth: the player database,
current ADP, historical stats, league scoring settings, and — during the draft —
live picks. That last one is what makes a live draft assistant possible rather
than a static cheat sheet.

Endpoints are cached to disk because the player database is ~12k rows and the
draft loop polls every few seconds; re-fetching it each tick would be both slow
and rude to a free public API.

Nothing here writes to Sleeper. The tool never touches the league.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://api.sleeper.app"
CACHE_DIR = Path("data/cache/sleeper")

# Player DB and season stats change rarely; ADP moves daily in preseason; draft
# picks change every few seconds while a draft is live.
TTL = {
    "players": 24 * 3600,
    "stats":   12 * 3600,
    "adp":     3600,
    "league":  600,
    "draft":   5,
}


class SleeperError(RuntimeError):
    pass


def _fetch(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "overlay-fantasy/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as err:                       # network, 404, bad JSON
        raise SleeperError(f"{url}: {err}") from err


def _cached(name: str, url: str, ttl: int) -> Any:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{name}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl:
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            pass                                    # corrupt cache → refetch
    data = _fetch(url)
    path.write_text(json.dumps(data))
    return data


# ─────────────────────────── reference data ──────────────────────────────────

def state() -> dict:
    return _fetch(f"{BASE}/v1/state/nfl")


def players() -> dict:
    """{player_id: {...}} — the full NFL player database (~12k rows)."""
    return _cached("players", f"{BASE}/v1/players/nfl", TTL["players"])


def season_stats(season: int) -> dict:
    """{player_id: {stat: value}} for a completed regular season."""
    return _cached(f"stats_{season}",
                   f"{BASE}/v1/stats/nfl/regular/{season}", TTL["stats"])


def adp(season: int, week: int = 1) -> dict[str, float]:
    """{player_id: adp} using Sleeper's PPR dynasty-draft ADP.

    Preseason "projections" carry ADP and nothing else — real stat projections
    only populate near week 1. ADP is the useful half anyway: it is what the
    other eleven managers in the league are drafting from.
    """
    raw = _cached(f"adp_{season}_{week}",
                  f"{BASE}/v1/projections/nfl/regular/{season}/{week}", TTL["adp"])
    out: dict[str, float] = {}
    for pid, row in (raw or {}).items():
        if not isinstance(row, dict):
            continue
        v = row.get("adp_dd_ppr")
        # 1000.0 is Sleeper's "undrafted" sentinel, not a 1000th-pick estimate.
        if isinstance(v, (int, float)) and v < 1000:
            out[pid] = float(v)
    return out


# ─────────────────────────── league + draft ──────────────────────────────────

def league(league_id: str) -> dict:
    return _cached(f"league_{league_id}",
                   f"{BASE}/v1/league/{league_id}", TTL["league"])


def league_users(league_id: str) -> list[dict]:
    return _fetch(f"{BASE}/v1/league/{league_id}/users")


def league_drafts(league_id: str) -> list[dict]:
    return _fetch(f"{BASE}/v1/league/{league_id}/drafts")


def league_rosters(league_id: str) -> list[dict]:
    """Post-draft rosters. Uncached — waiver moves land between requests."""
    return _fetch(f"{BASE}/v1/league/{league_id}/rosters")


def draft(draft_id: str) -> dict:
    return _fetch(f"{BASE}/v1/draft/{draft_id}")


def draft_picks(draft_id: str) -> list[dict]:
    """Picks made so far. Polled live during the draft — deliberately uncached."""
    return _fetch(f"{BASE}/v1/draft/{draft_id}/picks")


def user(username: str) -> dict:
    return _fetch(f"{BASE}/v1/user/{username}")


def user_leagues(user_id: str, season: int) -> list[dict]:
    return _fetch(f"{BASE}/v1/user/{user_id}/leagues/nfl/{season}")


# ─────────────────────────── helpers ─────────────────────────────────────────

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


def display_name(p: dict) -> str:
    """Readable name for any roster entry.

    Team defenses carry no `full_name` — they are stored as first/last
    ("Houston" / "Texans"). Reading full_name blindly KeyErrors on all 32 of
    them, which is the kind of thing that surfaces mid-draft.
    """
    return (p.get("full_name")
            or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
            or p.get("player_id", "?"))


def fantasy_players(players_db: dict | None = None) -> dict:
    """Active players on an NFL roster at a fantasy-scoring position.

    Sleeper's DB includes retired players, practice-squad bodies and every
    position on the field; drafting from the unfiltered list is how a board ends
    up recommending a long-snapper.
    """
    db = players_db if players_db is not None else players()
    return {
        pid: p for pid, p in db.items()
        if isinstance(p, dict)
        and p.get("active")
        and p.get("team")
        and p.get("position") in FANTASY_POSITIONS
    }

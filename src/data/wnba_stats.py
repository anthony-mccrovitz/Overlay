"""
WNBA Stats client — mirrors nba_stats.py but targets WNBA (league_id="10").

Key differences from NBA:
  - 40-minute games (not 48)
  - Pace ~75-78 possessions per 40 min (vs NBA ~100)
  - Scoring ~80 pts/game per team → totals ~160 (vs NBA ~114 per team)
  - Home court advantage ~2.0 pts (vs NBA ~3.0)
  - Season format: "2026" (not "2025-26")
  - Smaller rosters (12 vs 15) → bench depth matters less
"""
from __future__ import annotations

import json
import time
from pathlib import Path

CACHE_DIR = Path("data/cache/wnba")

# League-average baselines — 2026 WNBA season
# ORtg/DRtg are per-100-possessions, pace is per 40 min
LG_AVG_ORTG  = 102.0   # pts per 100 possessions (WNBA is lower than NBA)
LG_AVG_DRTG  = 102.0
LG_AVG_PACE  = 98.0    # nba_api per-48-min normalized (real ~82 per 40 min after scaling)
HOME_COURT   = 2.0     # home court advantage in spread points

SEASON = "2026"
LEAGUE_ID = "10"


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _load_cache(key: str, max_age_s: int = 21600) -> list | None:
    path = _cache_path(key)
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_s:
        with open(path) as f:
            return json.load(f)
    return None


def _save_cache(key: str, data: list) -> None:
    with open(_cache_path(key), "w") as f:
        json.dump(data, f)


def fetch_team_ratings(refresh: bool = False) -> list[dict]:
    """
    Fetch all WNBA teams with OFF_RATING, DEF_RATING, NET_RATING, PACE, W_PCT.
    Cached 6 hours.
    """
    cache_key = f"wnba_team_advanced_{SEASON}"
    cached = _load_cache(cache_key)
    if cached and not refresh:
        return cached

    try:
        from nba_api.stats.endpoints import leaguedashteamstats
        resp = leaguedashteamstats.LeagueDashTeamStats(
            season=SEASON,
            league_id_nullable=LEAGUE_ID,
            measure_type_detailed_defense="Advanced",
            timeout=30,
        )
        df = resp.get_data_frames()[0]
        teams = df.to_dict("records")
        _save_cache(cache_key, teams)
        return teams
    except Exception as e:
        print(f"  [wnba_stats] team ratings: {e}")
        path = _cache_path(cache_key)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return _default_teams()


def _default_teams() -> list[dict]:
    """Fallback with league-average stats when API is unavailable."""
    wnba_teams = [
        "Atlanta Dream", "Chicago Sky", "Connecticut Sun", "Dallas Wings",
        "Indiana Fever", "Las Vegas Aces", "Los Angeles Sparks",
        "Minnesota Lynx", "New York Liberty", "Phoenix Mercury",
        "Seattle Storm", "Washington Mystics",
    ]
    return [
        {
            "TEAM_NAME": name,
            "OFF_RATING": LG_AVG_ORTG,
            "DEF_RATING": LG_AVG_DRTG,
            "NET_RATING": 0.0,
            "PACE": LG_AVG_PACE,
            "W_PCT": 0.500,
        }
        for name in wnba_teams
    ]


def get_team_ratings(team_name: str, all_teams: list[dict] | None = None) -> dict:
    """Return ratings dict for a single WNBA team (fuzzy match)."""
    if all_teams is None:
        all_teams = fetch_team_ratings()

    name_lower = team_name.lower()
    for t in all_teams:
        if t.get("TEAM_NAME", "").lower() == name_lower:
            return t
    for t in all_teams:
        tname = t.get("TEAM_NAME", "").lower()
        for word in name_lower.split():
            if len(word) > 3 and word in tname:
                return t
    return {
        "TEAM_NAME": team_name,
        "OFF_RATING": LG_AVG_ORTG,
        "DEF_RATING": LG_AVG_DRTG,
        "NET_RATING": 0.0,
        "PACE": LG_AVG_PACE,
        "W_PCT": 0.500,
    }


def fetch_player_stats(refresh: bool = False) -> list[dict]:
    """All WNBA players — PTS, REB, AST per game. Cached 6 hours."""
    cache_key = f"wnba_player_base_{SEASON}"
    cached = _load_cache(cache_key)
    if cached and not refresh:
        return cached

    try:
        from nba_api.stats.endpoints import leaguedashplayerstats
        resp = leaguedashplayerstats.LeagueDashPlayerStats(
            season=SEASON,
            league_id_nullable=LEAGUE_ID,
            per_mode_detailed="PerGame",
            timeout=30,
        )
        df = resp.get_data_frames()[0]
        players = df.to_dict("records")
        _save_cache(cache_key, players)
        return players
    except Exception as e:
        print(f"  [wnba_stats] player stats: {e}")
        path = _cache_path(cache_key)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return []

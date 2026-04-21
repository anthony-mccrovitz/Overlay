"""
NBA Stats client using nba_api (pip install nba_api).

Fetches real 2025-26 season team efficiency ratings and player averages
from stats.nba.com via the nba_api library which handles headers/rate-limiting.

All results are cached to data/cache/nba/ with a 6-hour TTL.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

CACHE_DIR = Path("data/cache/nba")

# League average baselines (2025-26 season)
LG_AVG_ORTG  = 114.0
LG_AVG_DRTG  = 114.0
LG_AVG_PACE  = 100.2
HOME_COURT   = 3.0   # home court advantage in spread points


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


# ─────────────────────────── Team Stats ─────────────────────────────────────

def fetch_team_ratings(refresh: bool = False) -> list[dict]:
    """
    Return all 30 teams with OFF_RATING, DEF_RATING, NET_RATING, PACE, W_PCT.
    Cached 6 hours.
    """
    cached = _load_cache("team_advanced_2025_26")
    if cached and not refresh:
        return cached

    try:
        from nba_api.stats.endpoints import leaguedashteamstats
        resp = leaguedashteamstats.LeagueDashTeamStats(
            season="2025-26",
            measure_type_detailed_defense="Advanced",
            timeout=30,
        )
        df = resp.get_data_frames()[0]
        teams = df.to_dict("records")
        _save_cache("team_advanced_2025_26", teams)
        return teams
    except Exception as e:
        print(f"  [nba_stats] team ratings: {e}")
        # Fall back to cached even if stale
        path = _cache_path("team_advanced_2025_26")
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return []


def get_team_ratings(team_name: str, all_teams: list[dict] | None = None) -> dict:
    """
    Return ratings dict for a single team by name (fuzzy match).
    Falls back to league-average defaults if team not found.
    """
    if all_teams is None:
        all_teams = fetch_team_ratings()

    name_lower = team_name.lower()
    for t in all_teams:
        if t.get("TEAM_NAME", "").lower() == name_lower:
            return t
    # Partial — city or mascot
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


# ─────────────────────────── Player Stats ────────────────────────────────────

def fetch_player_stats(refresh: bool = False) -> list[dict]:
    """
    All players — PTS, REB, AST, STL, BLK, FG3M per game.
    Cached 6 hours.
    """
    cached = _load_cache("player_base_2025_26")
    if cached and not refresh:
        return cached

    try:
        from nba_api.stats.endpoints import leaguedashplayerstats
        resp = leaguedashplayerstats.LeagueDashPlayerStats(
            season="2025-26",
            per_mode_detailed="PerGame",
            timeout=30,
        )
        df = resp.get_data_frames()[0]
        players = df.to_dict("records")
        _save_cache("player_base_2025_26", players)
        return players
    except Exception as e:
        print(f"  [nba_stats] player stats: {e}")
        path = _cache_path("player_base_2025_26")
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return []


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _normalize_name(name: str) -> str:
    """Lowercase, strip trailing generational suffixes and punctuation."""
    parts = name.lower().replace(".", "").split()
    while parts and parts[-1] in _NAME_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def get_player_stats(player_name: str, all_players: list[dict] | None = None) -> dict | None:
    """Return season stats dict for a player by name (fuzzy, suffix-aware)."""
    if all_players is None:
        all_players = fetch_player_stats()

    name_lower = player_name.lower().strip()

    # 1. Exact match (case-insensitive, ignoring trailing period)
    for p in all_players:
        if p.get("PLAYER_NAME", "").lower().rstrip(".") == name_lower:
            return p

    # 2. Normalized match — strip Jr/Sr/II/III from both sides
    norm_query = _normalize_name(player_name)
    for p in all_players:
        if _normalize_name(p.get("PLAYER_NAME", "")) == norm_query:
            return p

    # 3. Full name substring (query is subset of stored name or vice versa)
    for p in all_players:
        pn = p.get("PLAYER_NAME", "").lower()
        if norm_query and (norm_query in pn or pn.startswith(norm_query)):
            return p

    # 4. Last-name only — skip suffix tokens, require first-initial match
    parts = name_lower.split()
    meaningful = [w for w in parts if w not in _NAME_SUFFIXES and len(w) > 1]
    if len(meaningful) >= 2:
        first_init = meaningful[0][0]
        last_word  = meaningful[-1]
        candidates = [
            p for p in all_players
            if last_word in p.get("PLAYER_NAME", "").lower()
            and p.get("PLAYER_NAME", "").lower().startswith(first_init)
        ]
        if len(candidates) == 1:
            return candidates[0]

    return None


# ─────────────────────────── Opponent Defense ────────────────────────────────

def fetch_opp_position_defense(refresh: bool = False) -> list[dict]:
    """
    Team opponent stats — pts allowed, opp FG%, etc.
    Used to adjust player prop projections.
    """
    cached = _load_cache("opp_defense_2025_26")
    if cached and not refresh:
        return cached

    try:
        from nba_api.stats.endpoints import leaguedashteamstats
        resp = leaguedashteamstats.LeagueDashTeamStats(
            season="2025-26",
            measure_type_detailed_defense="Opponent",
            timeout=30,
        )
        df = resp.get_data_frames()[0]
        teams = df.to_dict("records")
        _save_cache("opp_defense_2025_26", teams)
        return teams
    except Exception as e:
        print(f"  [nba_stats] opp defense: {e}")
        path = _cache_path("opp_defense_2025_26")
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return []


def get_team_opp_pts_allowed(team_name: str, opp_stats: list[dict] | None = None) -> float:
    """
    Return opponent points per game allowed by this team (lower = better defense).
    Uses DEF_RATING (per-100-possessions) from advanced stats as the primary source.
    OPP_PTS from the Opponent measure type is a season total, not per-game.
    """
    # Use DEF_RATING from advanced stats — already per-100-possessions calibrated
    adv = get_team_ratings(team_name)
    return float(adv.get("DEF_RATING", LG_AVG_DRTG))

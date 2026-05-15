"""
NHL Stats client — fetches team and goalie stats from api.nhle.com (free, no key).

Team ratings: GF/game, GA/game, shots for/against, PP%, PK%
Goalie stats: SV%, GAA for starting goalies
Schedule: today's games with team IDs

All results cached to data/cache/nhl/ with configurable TTL.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

CACHE_DIR = Path("data/cache/nhl")
API_BASE = "https://api.nhle.com/stats/rest/en"
SCHEDULE_BASE = "https://api-web.nhle.com/v1"

# 2025-26 season ID
SEASON_ID = 20252026

# League averages (2025-26 regular season baseline)
LG_AVG_GF_PER_GAME = 3.05
LG_AVG_GA_PER_GAME = 3.05
LG_AVG_SV_PCT = 0.898
HOME_GOALS_ADJ = 0.15   # home ice advantage in expected goals


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _load_cache(key: str, max_age_s: int = 21600) -> list | dict | None:
    path = _cache_path(key)
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_s:
        with open(path) as f:
            return json.load(f)
    return None


def _save_cache(key: str, data: list | dict) -> None:
    with open(_cache_path(key), "w") as f:
        json.dump(data, f)


def fetch_team_stats(game_type: int = 2, refresh: bool = False) -> list[dict]:
    """
    Return all teams with GF/game, GA/game, shots, PP%, PK%, point%.
    game_type: 2=regular season, 3=playoffs
    """
    cache_key = f"team_summary_{SEASON_ID}_type{game_type}"
    cached = _load_cache(cache_key)
    if cached and not refresh:
        return cached

    try:
        url = f"{API_BASE}/team/summary"
        params = {
            "cayenneExp": f"seasonId={SEASON_ID} and gameTypeId={game_type}",
            "limit": -1,
        }
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        _save_cache(cache_key, data)
        return data
    except Exception as e:
        print(f"  [nhl_stats] team stats error: {e}")
        path = _cache_path(cache_key)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return []


def fetch_goalie_stats(game_type: int = 3, refresh: bool = False) -> list[dict]:
    """
    Return playoff goalie stats: SV%, GAA, gamesStarted.
    Sorted by gamesStarted desc so starters appear first.
    """
    cache_key = f"goalie_summary_{SEASON_ID}_type{game_type}"
    cached = _load_cache(cache_key, max_age_s=3600)
    if cached and not refresh:
        return cached

    try:
        url = f"{API_BASE}/goalie/summary"
        params = {
            "cayenneExp": f"seasonId={SEASON_ID} and gameTypeId={game_type}",
            "limit": -1,
        }
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        # Sort by gamesStarted descending (starters first)
        data.sort(key=lambda g: g.get("gamesStarted", 0), reverse=True)
        _save_cache(cache_key, data)
        return data
    except Exception as e:
        print(f"  [nhl_stats] goalie stats error: {e}")
        path = _cache_path(cache_key)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return []


def fetch_final_scores(game_date: date | None = None) -> list[dict]:
    """
    Return completed NHL games for game_date with final scores.
    Each entry: {id, away_team, home_team, away_abbrev, home_abbrev,
                 away_score, home_score, total, winner, state}.
    Uses the api-web.nhle.com /score/{date} endpoint (no auth).
    """
    d = game_date or date.today()
    cache_key = f"scores_{d.isoformat()}"
    cached = _load_cache(cache_key, max_age_s=600)
    if cached:
        return cached

    try:
        resp = requests.get(f"{SCHEDULE_BASE}/score/{d.isoformat()}", timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        print(f"  [nhl_stats] scores error: {e}")
        return []

    games = []
    for g in raw.get("games", []):
        state = g.get("gameState", "")
        if state not in ("OFF", "FINAL"):
            continue
        away = (
            g["awayTeam"].get("placeName", {}).get("default", "")
            + " " + g["awayTeam"].get("commonName", {}).get("default", "")
        ).strip()
        home = (
            g["homeTeam"].get("placeName", {}).get("default", "")
            + " " + g["homeTeam"].get("commonName", {}).get("default", "")
        ).strip()
        away_score = int(g["awayTeam"].get("score", 0) or 0)
        home_score = int(g["homeTeam"].get("score", 0) or 0)
        winner = away if away_score > home_score else home
        games.append({
            "id":           g.get("id"),
            "away_team":    away,
            "home_team":    home,
            "away_abbrev":  g["awayTeam"].get("abbrev", ""),
            "home_abbrev":  g["homeTeam"].get("abbrev", ""),
            "away_score":   away_score,
            "home_score":   home_score,
            "total":        away_score + home_score,
            "margin":       abs(away_score - home_score),
            "winner":       winner,
            "state":        "Final",
        })
    _save_cache(cache_key, games)
    return games


def fetch_today_schedule(game_date: date | None = None) -> list[dict]:
    """
    Return today's games: [{id, home_team, away_team, start_utc}]
    """
    d = game_date or date.today()
    cache_key = f"schedule_{d.isoformat()}"
    cached = _load_cache(cache_key, max_age_s=1800)
    if cached:
        return cached

    try:
        resp = requests.get(f"{SCHEDULE_BASE}/schedule/{d.isoformat()}", timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        games = []
        for day in raw.get("gameWeek", []):
            if day.get("date", "") != d.isoformat():
                continue
            for g in day.get("games", []):
                away = (
                    g["awayTeam"].get("placeName", {}).get("default", "")
                    + " "
                    + g["awayTeam"].get("commonName", {}).get("default", "")
                ).strip()
                home = (
                    g["homeTeam"].get("placeName", {}).get("default", "")
                    + " "
                    + g["homeTeam"].get("commonName", {}).get("default", "")
                ).strip()
                games.append({
                    "id": g.get("id"),
                    "away_team": away,
                    "away_abbrev": g["awayTeam"].get("abbrev", ""),
                    "home_team": home,
                    "home_abbrev": g["homeTeam"].get("abbrev", ""),
                    "start_utc": g.get("startTimeUTC", ""),
                })
        _save_cache(cache_key, games)
        return games
    except Exception as e:
        print(f"  [nhl_stats] schedule error: {e}")
        return []


# ─────────────────── Lookup helpers ────────────────────────────────────────

# Common NHL team name aliases to match odds-api names to NHL API names
_TEAM_ALIASES: dict[str, list[str]] = {
    "Boston Bruins":         ["Boston", "Bruins"],
    "Buffalo Sabres":        ["Buffalo", "Sabres"],
    "Calgary Flames":        ["Calgary", "Flames"],
    "Carolina Hurricanes":   ["Carolina", "Hurricanes"],
    "Chicago Blackhawks":    ["Chicago", "Blackhawks"],
    "Colorado Avalanche":    ["Colorado", "Avalanche"],
    "Columbus Blue Jackets": ["Columbus", "Blue Jackets"],
    "Dallas Stars":          ["Dallas", "Stars"],
    "Detroit Red Wings":     ["Detroit", "Red Wings"],
    "Edmonton Oilers":       ["Edmonton", "Oilers"],
    "Florida Panthers":      ["Florida", "Panthers"],
    "Los Angeles Kings":     ["Los Angeles", "Kings", "LA Kings"],
    "Minnesota Wild":        ["Minnesota", "Wild"],
    "Montreal Canadiens":    ["Montreal", "Canadiens", "Montréal"],
    "Nashville Predators":   ["Nashville", "Predators"],
    "New Jersey Devils":     ["New Jersey", "Devils"],
    "New York Islanders":    ["New York Islanders", "NY Islanders", "Islanders"],
    "New York Rangers":      ["New York Rangers", "NY Rangers", "Rangers"],
    "Ottawa Senators":       ["Ottawa", "Senators"],
    "Philadelphia Flyers":   ["Philadelphia", "Flyers"],
    "Pittsburgh Penguins":   ["Pittsburgh", "Penguins"],
    "San Jose Sharks":       ["San Jose", "Sharks"],
    "Seattle Kraken":        ["Seattle", "Kraken"],
    "St. Louis Blues":       ["St. Louis", "Blues", "Saint Louis"],
    "Tampa Bay Lightning":   ["Tampa Bay", "Lightning"],
    "Toronto Maple Leafs":   ["Toronto", "Maple Leafs"],
    "Utah Mammoth":          ["Utah", "Mammoth"],
    "Vancouver Canucks":     ["Vancouver", "Canucks"],
    "Vegas Golden Knights":  ["Vegas", "Golden Knights"],
    "Washington Capitals":   ["Washington", "Capitals"],
    "Winnipeg Jets":         ["Winnipeg", "Jets"],
    "Anaheim Ducks":         ["Anaheim", "Ducks"],
}


def _blend_team_stats(playoff: dict, regular: dict, po_weight: float = 0.25) -> dict:
    """Blend playoff and regular season stats. Playoff sample too small alone."""
    blended = dict(playoff)
    for key in ("goalsForPerGame", "goalsAgainstPerGame", "shotsForPerGame",
                "shotsAgainstPerGame", "powerPlayPct", "penaltyKillPct"):
        pv = playoff.get(key)
        rv = regular.get(key)
        if pv is not None and rv is not None:
            blended[key] = pv * po_weight + rv * (1 - po_weight)
        elif rv is not None:
            blended[key] = rv
    return blended


def get_team_stats(
    team_name: str,
    all_teams: list[dict] | None = None,
    game_type: int = 3,
) -> dict:
    """
    Return stats dict for a team. Blends playoff (25%) + regular season (75%)
    to avoid small-sample distortion in early playoff rounds.
    Falls back to league-average defaults if not found.
    """
    if all_teams is None:
        all_teams = fetch_team_stats(game_type=game_type)

    # Always fetch regular season for blending
    reg_teams = fetch_team_stats(game_type=2)

    name_lower = team_name.lower()
    best_match = None
    best_score = 0

    for t in all_teams:
        full = t.get("teamFullName", "")
        score = 0
        if full.lower() == name_lower:
            score = 100
        elif full.lower() in name_lower or name_lower in full.lower():
            score = 80
        else:
            # Check aliases
            for canonical, aliases in _TEAM_ALIASES.items():
                if any(a.lower() in name_lower for a in aliases):
                    if canonical.lower() in full.lower() or full.lower() in canonical.lower():
                        score = 70
                        break
            # Partial word match
            if score == 0:
                words = name_lower.split()
                for w in words:
                    if len(w) > 3 and w in full.lower():
                        score = max(score, 50)

        if score > best_score:
            best_score = score
            best_match = t

    if best_match and best_score >= 50:
        # Blend with regular season stats to smooth small playoff samples
        reg_match = None
        reg_score = 0
        for t in (reg_teams or []):
            full = t.get("teamFullName", "")
            s = 100 if full.lower() == name_lower else (80 if name_lower in full.lower() or full.lower() in name_lower else 0)
            if s > reg_score:
                reg_score = s
                reg_match = t
        if reg_match and reg_score >= 50:
            return _blend_team_stats(best_match, reg_match)
        return best_match

    # Not in playoffs — use regular season only
    if reg_teams:
        for t in reg_teams:
            full = t.get("teamFullName", "")
            if full.lower() == name_lower or name_lower in full.lower() or full.lower() in name_lower:
                return t

    # Default to league averages
    return {
        "teamFullName": team_name,
        "goalsForPerGame": LG_AVG_GF_PER_GAME,
        "goalsAgainstPerGame": LG_AVG_GA_PER_GAME,
        "shotsForPerGame": 30.0,
        "shotsAgainstPerGame": 30.0,
        "powerPlayPct": 0.200,
        "penaltyKillPct": 0.800,
        "pointPct": 0.500,
        "gamesPlayed": 0,
    }


def get_team_goalie(team_abbrev: str, all_goalies: list[dict] | None = None) -> dict | None:
    """Return the most-used goalie for a team in playoffs. Returns None if not found."""
    if all_goalies is None:
        all_goalies = fetch_goalie_stats(game_type=3)

    abbrev_upper = team_abbrev.upper()
    matches = [
        g for g in all_goalies
        if abbrev_upper in (g.get("teamAbbrevs") or "").upper().split(",")
    ]
    if not matches:
        return None
    # Most games started = presumed starter
    return max(matches, key=lambda g: g.get("gamesStarted", 0))

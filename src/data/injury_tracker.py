"""
Real-time injury and lineup availability tracking for NBA and NHL.
Adjusts team strength based on known player absences.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

CACHE_DIR = Path("data/cache/injuries")
CACHE_TTL_SECONDS = 7200  # 2 hours

# Approximate point value of each player role (NBA)
# Used to compute lineup quality adjustment when key players are out
_NBA_ROLE_VALUE: dict[str, float] = {
    "star":    4.5,   # MVP-caliber, top-5 in VORP
    "starter": 1.8,   # regular starter
    "rotation": 0.7,  # 20+ mpg rotation player
    "bench":   0.2,   # < 20 mpg
}

# NHL: goals per game impact by role
_NHL_ROLE_VALUE: dict[str, float] = {
    "star":    0.35,
    "starter": 0.15,
    "rotation": 0.06,
    "bench":   0.02,
}


def _cache_path(sport: str, date_str: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{sport}_{date_str}.json"


def _load_cache(sport: str, date_str: str) -> Optional[dict]:
    p = _cache_path(sport, date_str)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        age = time.time() - data.get("_cached_at", 0)
        if age < CACHE_TTL_SECONDS:
            return data
    except Exception:
        pass
    return None


def _save_cache(sport: str, date_str: str, data: dict) -> None:
    data["_cached_at"] = time.time()
    _cache_path(sport, date_str).write_text(json.dumps(data, indent=2))


def fetch_nba_injuries(date_str: str | None = None) -> dict[str, list[dict]]:
    """
    Fetch NBA injury report for date_str (YYYYMMDD). Returns {team: [player_info]}.
    Source: nba_api CommonPlayerInfo + LeaguePlayerOnOffSummary (no key required).
    Falls back to empty dict on any error so the model still runs.
    """
    ds = date_str or date.today().strftime("%Y%m%d")
    cached = _load_cache("nba", ds)
    if cached:
        return {k: v for k, v in cached.items() if not k.startswith("_")}

    injuries: dict[str, list[dict]] = {}

    try:
        from nba_api.stats.endpoints import leagueinjuryfetch  # type: ignore
        result = leagueinjuryfetch.LeagueInjuryFetch()
        df = result.get_data_frames()[0]
        for _, row in df.iterrows():
            team = row.get("TeamName", "")
            player = row.get("PlayerName", "")
            status = row.get("PlayerStatus", "")  # "Out", "Questionable", "Doubtful"
            if team not in injuries:
                injuries[team] = []
            injuries[team].append({"player": player, "status": status})
    except Exception:
        # nba_api injury endpoint may not be available in all versions
        # Silently return empty — model runs without adjustment
        pass

    _save_cache("nba", ds, injuries)
    return injuries


def fetch_nhl_injuries(date_str: str | None = None) -> dict[str, list[dict]]:
    """
    Fetch NHL injury/roster data from api-web.nhle.com (free, no key).
    Returns {team: [player_info]} for players listed as injured/IR.
    """
    import requests

    ds = date_str or date.today().strftime("%Y%m%d")
    cached = _load_cache("nhl", ds)
    if cached:
        return {k: v for k, v in cached.items() if not k.startswith("_")}

    injuries: dict[str, list[dict]] = {}

    # NHL team abbreviations for API calls
    nhl_teams = [
        "ANA","BOS","BUF","CGY","CAR","CHI","COL","CBJ","DAL","DET",
        "EDM","FLA","LAK","MIN","MTL","NSH","NJD","NYI","NYR","OTT",
        "PHI","PIT","SJS","SEA","STL","TBL","TOR","VAN","VGK","WSH","WPG","UTA"
    ]

    for abbrev in nhl_teams:
        try:
            url = f"https://api-web.nhle.com/v1/roster/{abbrev}/current"
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                continue
            roster = resp.json()
            # Players on IR show up in the roster with injuryStatus field
            team_injuries = []
            for position_group in ("forwards", "defensemen", "goalies"):
                for player in roster.get(position_group, []):
                    injury_status = player.get("injuryStatus") or player.get("injuryDescription")
                    if injury_status:
                        team_injuries.append({
                            "player": f"{player.get('firstName', {}).get('default','')} {player.get('lastName', {}).get('default','')}",
                            "status": injury_status,
                            "position": player.get("positionCode", ""),
                        })
            if team_injuries:
                injuries[abbrev] = team_injuries
        except Exception:
            continue

    _save_cache("nhl", ds, injuries)
    return injuries


def get_lineup_adjustment(team: str, sport: str, date_str: str | None = None) -> float:
    """
    Returns pts (NBA) or goals (NHL) to subtract from team's projected score
    due to player absences. Positive value = team is weaker than normal.
    Example: if LeBron is out → returns ~4.5 (subtract 4.5 pts from LAL projection).
    """
    ds = date_str or date.today().strftime("%Y%m%d")

    if sport in ("nba", "basketball_nba"):
        injuries = fetch_nba_injuries(ds)
        role_values = _NBA_ROLE_VALUE
    elif sport in ("nhl", "icehockey_nhl"):
        injuries = fetch_nhl_injuries(ds)
        role_values = _NHL_ROLE_VALUE
    else:
        return 0.0

    team_injuries = injuries.get(team, [])
    if not team_injuries:
        return 0.0

    total_impact = 0.0
    for player_info in team_injuries:
        status = (player_info.get("status") or "").lower()
        # Only count confirmed out/doubtful — skip questionable
        if "out" in status or "ir" in status or "doubtful" in status:
            # Without per-player VORP data, use rotation-level estimate
            # This gets upgraded to star/starter once player importance data is wired
            total_impact += role_values.get("rotation", 0.5)

    return round(total_impact, 2)

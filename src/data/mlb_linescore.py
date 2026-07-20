"""
MLB inning-by-inning linescore data from statsapi.mlb.com.

Used for:
  - NRFI (No Run First Inning) predictions: pitcher & team 1st-inning performance
  - First 5 innings models: starter-only outcomes
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests

API_BASE = "https://statsapi.mlb.com/api/v1"
CACHE_DIR = Path("data/cache/mlb_linescore")


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _cached_get(key: str, url: str, params: dict | None = None, max_age_s: int = 86400) -> dict:
    cache = _cache_path(key)
    if cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < max_age_s:
            with open(cache) as f:
                return json.load(f)

    resp = requests.get(url, params=params or {}, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    with open(cache, "w") as f:
        json.dump(data, f)
    return data


def fetch_game_linescore(game_pk: int) -> dict | None:
    """
    Fetch inning-by-inning linescore for a completed game.

    Returns dict with:
        innings: list of {inning, home_runs, away_runs}
        home_pitcher_id: int
        away_pitcher_id: int
        home_team_id: int
        away_team_id: int
        home_1st_inning_runs: int
        away_1st_inning_runs: int
        nrfi: bool (True if both teams scored 0 in 1st inning)
    """
    try:
        data = _cached_get(
            f"linescore_{game_pk}",
            f"{API_BASE}/game/{game_pk}/linescore",
            max_age_s=86400 * 30,  # cache for 30 days (historical data)
        )
    except Exception:
        return None

    innings = data.get("innings", [])
    if not innings:
        return None

    first = innings[0] if innings else {}
    home_1st = first.get("home", {}).get("runs", 0) or 0
    away_1st = first.get("away", {}).get("runs", 0) or 0

    parsed_innings = []
    for inn in innings:
        parsed_innings.append({
            "inning": inn.get("num", 0),
            "home_runs": inn.get("home", {}).get("runs", 0) or 0,
            "away_runs": inn.get("away", {}).get("runs", 0) or 0,
            "home_hits": inn.get("home", {}).get("hits", 0) or 0,
            "away_hits": inn.get("away", {}).get("hits", 0) or 0,
        })

    f5_home = sum(i.get("home_runs", 0) for i in parsed_innings[:5])
    f5_away = sum(i.get("away_runs", 0) for i in parsed_innings[:5])

    return {
        "game_pk": game_pk,
        "innings": parsed_innings,
        "home_1st_inning_runs": home_1st,
        "away_1st_inning_runs": away_1st,
        "nrfi": (home_1st == 0 and away_1st == 0),
        "f5_home_runs": f5_home,
        "f5_away_runs": f5_away,
        "total_innings": len(parsed_innings),
    }


def fetch_season_linescores(season: int, verbose: bool = True) -> list[dict]:
    """
    Fetch all linescores for a season by first getting the schedule,
    then fetching each game's linescore.

    Returns list of enriched game dicts with linescore + pitcher data.
    """
    if verbose:
        print(f"  Fetching {season} schedule for linescores...")

    start = f"{season}-03-20"
    end = f"{season}-10-05"
    schedule_data = _cached_get(
        f"schedule_full_{season}",
        f"{API_BASE}/schedule",
        {
            "sportId": 1,
            "startDate": start,
            "endDate": end,
            "gameType": "R",
            "hydrate": "probablePitcher,linescore",
        },
        max_age_s=86400 * 7,
    )

    results = []
    total = 0
    for date_entry in schedule_data.get("dates", []):
        for game in date_entry.get("games", []):
            state = game.get("status", {}).get("abstractGameState", "")
            if state != "Final":
                continue

            game_pk = game.get("gamePk")
            home_info = game.get("teams", {}).get("home", {})
            away_info = game.get("teams", {}).get("away", {})

            hp = home_info.get("probablePitcher", {})
            ap = away_info.get("probablePitcher", {})

            linescore_data = game.get("linescore", {})
            innings = linescore_data.get("innings", [])

            if not innings:
                # Fetch individually if not hydrated
                ls = fetch_game_linescore(game_pk)
                if ls is None:
                    continue
                innings_parsed = ls["innings"]
                home_1st = ls["home_1st_inning_runs"]
                away_1st = ls["away_1st_inning_runs"]
                nrfi = ls["nrfi"]
                f5_home = ls["f5_home_runs"]
                f5_away = ls["f5_away_runs"]
            else:
                first = innings[0] if innings else {}
                home_1st = first.get("home", {}).get("runs", 0) or 0
                away_1st = first.get("away", {}).get("runs", 0) or 0
                nrfi = (home_1st == 0 and away_1st == 0)

                innings_parsed = []
                for inn in innings:
                    innings_parsed.append({
                        "inning": inn.get("num", 0),
                        "home_runs": inn.get("home", {}).get("runs", 0) or 0,
                        "away_runs": inn.get("away", {}).get("runs", 0) or 0,
                    })

                f5_home = sum(i["home_runs"] for i in innings_parsed[:5])
                f5_away = sum(i["away_runs"] for i in innings_parsed[:5])

            home_id = home_info.get("team", {}).get("id")
            away_id = away_info.get("team", {}).get("id")
            home_score = home_info.get("score", 0) or 0
            away_score = away_info.get("score", 0) or 0

            results.append({
                "game_pk": game_pk,
                "season": season,
                "date": game.get("gameDate", "")[:10],
                "home_id": home_id,
                "away_id": away_id,
                "home_name": home_info.get("team", {}).get("name", ""),
                "away_name": away_info.get("team", {}).get("name", ""),
                "home_score": home_score,
                "away_score": away_score,
                "home_pitcher_id": hp.get("id"),
                "away_pitcher_id": ap.get("id"),
                "home_pitcher_name": hp.get("fullName", ""),
                "away_pitcher_name": ap.get("fullName", ""),
                "home_1st_inning_runs": home_1st,
                "away_1st_inning_runs": away_1st,
                "nrfi": nrfi,
                "f5_home_runs": f5_home,
                "f5_away_runs": f5_away,
            })
            total += 1

    if verbose:
        nrfi_count = sum(1 for r in results if r["nrfi"])
        rate = nrfi_count / max(total, 1)
        print(f"  {season}: {total} games, NRFI rate: {rate:.1%} ({nrfi_count}/{total})")

    return results



"""
MLB recent form tracker.

Fetches completed 2026 game results from MLB Stats API and computes
rolling win % for last 5, 10, and 20 games per team.

Results are cached to data/cache/mlb/recent_form_YYYYMMDD.json for 12 hours.
Call get_recent_form() at the start of each morning run to get fresh data.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from datetime import date, timedelta
from pathlib import Path

import requests

_CACHE_DIR = Path("data/cache/mlb")
_CACHE_TTL = 12 * 60 * 60  # 12 hours
_MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"

# Season start — only fetch from here forward
_SEASON_START = "2026-03-27"


def _cache_path(today: str) -> Path:
    return _CACHE_DIR / f"recent_form_{today}.json"


def _fetch_results(start_date: str, end_date: str) -> list[dict]:
    """Fetch all Final game results in the date range from MLB Stats API."""
    try:
        resp = requests.get(
            _MLB_SCHEDULE_URL,
            params={
                "sportId": 1,
                "startDate": start_date,
                "endDate": end_date,
                "gameType": "R",
                "fields": (
                    "dates,date,games,gamePk,status,abstractGameState,"
                    "teams,home,away,team,name,score,officialDate"
                ),
            },
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  [recent_form] API error: {e}")
        return []

    games = []
    for date_block in resp.json().get("dates", []):
        for game in date_block.get("games", []):
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue
            try:
                ht = game["teams"]["home"]["team"]["name"]
                at = game["teams"]["away"]["team"]["name"]
                hs = game["teams"]["home"].get("score") or 0
                as_ = game["teams"]["away"].get("score") or 0
                gdate = game.get("officialDate") or date_block["date"]
                games.append({
                    "date": gdate,
                    "home": ht,
                    "away": at,
                    "home_score": int(hs),
                    "away_score": int(as_),
                })
            except (KeyError, TypeError):
                continue

    return sorted(games, key=lambda g: g["date"])


def _compute_form(games: list[dict]) -> dict[str, dict]:
    """
    Given a sorted list of completed games, compute per-team rolling stats.

    Returns:
        {team_name: {last5_pct, last10_pct, last20_pct, momentum, games_played}}
    """
    recent5: dict[str, deque] = defaultdict(lambda: deque(maxlen=5))
    recent10: dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
    recent20: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
    played: dict[str, int] = defaultdict(int)

    for g in games:
        home_won = g["home_score"] > g["away_score"]
        for team, won in [(g["home"], home_won), (g["away"], not home_won)]:
            recent5[team].append(int(won))
            recent10[team].append(int(won))
            recent20[team].append(int(won))
            played[team] += 1

    form: dict[str, dict] = {}
    all_teams = set(recent10.keys())
    for team in all_teams:
        r5  = list(recent5[team])
        r10 = list(recent10[team])
        r20 = list(recent20[team])
        l5  = sum(r5)  / max(len(r5),  1) if r5  else 0.5
        l10 = sum(r10) / max(len(r10), 1) if r10 else 0.5
        l20 = sum(r20) / max(len(r20), 1) if r20 else 0.5
        form[team] = {
            "last5_pct":   round(l5, 4),
            "last10_pct":  round(l10, 4),
            "last20_pct":  round(l20, 4),
            "momentum":    round(l5 - l10, 4),
            "games_played": played[team],
        }
    return form


def get_recent_form(today: date | None = None) -> dict[str, dict]:
    """
    Return recent-form dict for all MLB teams.

    {team_name: {last5_pct, last10_pct, last20_pct, momentum, games_played}}

    Uses a 12-hour cache keyed by today's date. Falls back to stale cache or
    empty dict on API failure — never raises, never blocks the prediction flow.
    """
    if today is None:
        today = date.today()
    today_str = today.strftime("%Y%m%d")

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(today_str)

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            if time.time() - cached.get("_cached_at", 0) < _CACHE_TTL:
                return cached.get("form", {})
        except Exception:
            pass

    end_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    games = _fetch_results(_SEASON_START, end_date)

    if not games:
        # Try returning stale cache rather than empty
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text()).get("form", {})
            except Exception:
                pass
        return {}

    form = _compute_form(games)

    try:
        cache_file.write_text(json.dumps({
            "_cached_at": time.time(),
            "_date": today_str,
            "_games_fetched": len(games),
            "form": form,
        }, indent=2))
    except Exception:
        pass

    return form


def inject_form(stats: dict, team_name: str, form: dict[str, dict]) -> dict:
    """
    Inject recent-form features into a stats dict.
    Falls back to 0.5 if team not found (e.g. first week of season).
    """
    tf = form.get(team_name, {})
    return {
        **stats,
        "last5_pct":  tf.get("last5_pct",  0.5),
        "last10_pct": tf.get("last10_pct", 0.5),
        "last20_pct": tf.get("last20_pct", 0.5),
        "momentum":   tf.get("momentum",   0.0),
    }

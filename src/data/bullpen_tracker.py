"""
Bullpen depletion tracker.

Fetches the last 2 days of completed MLB games and computes a
"bullpen fatigue score" for each team — the total relief innings pitched
in that window. Books underweight bullpen depletion because they price
starters, not bullpen depth. A tired bullpen leaks runs in innings 6-9.

Usage:
    from src.data.bullpen_tracker import get_bullpen_adjustment
    runs_adj = get_bullpen_adjustment("New York Yankees", game_date)
    # Positive = expect MORE runs (tired bullpen); subtract from total projection
    # when the team is pitching, add when they're batting.

API: MLB Stats API (free, no key) — schedule + boxscore endpoints.
Cache: data/cache/bullpen/{date}.json — refreshed once per day.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

CACHE_DIR = Path("data/cache/bullpen")
MLB_API   = "https://statsapi.mlb.com/api/v1"

# Historical average: ~5 IP from starter, ~4 IP from bullpen per 9-inning game.
# Each inning of bullpen usage per game = roughly +0.15 runs in expected total
# (based on bullpen ERA ~4.5 vs starter ERA ~4.0, difference × per-inning exposure).
RUNS_PER_BULLPEN_IP = 0.15

# Fatigue threshold: if a team's bullpen has thrown > 8 IP in last 2 days,
# they're depleted. Apply the adjustment above that baseline.
BASELINE_IP     = 3.0   # normal bullpen load over 2 days
FATIGUE_SCALE   = 0.12  # additional runs per IP above baseline


def _fetch_json(url: str, params: dict | None = None) -> dict | list | None:
    try:
        import requests
        r = requests.get(url, params=params or {}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _get_completed_game_ids(game_date: date) -> list[str]:
    """Return game PKs for completed games on game_date."""
    data = _fetch_json(
        f"{MLB_API}/schedule",
        {"sportId": 1, "date": game_date.strftime("%Y-%m-%d"), "gameType": "R,P"},
    )
    if not data:
        return []
    ids = []
    for day in data.get("dates", []):
        for game in day.get("games", []):
            if game.get("status", {}).get("abstractGameState") == "Final":
                ids.append(str(game["gamePk"]))
    return ids


def _get_relief_innings(game_pk: str, team_name: str) -> float:
    """
    Parse boxscore for one game and return total IP thrown by relievers
    for team_name. Returns 0.0 if team not in game or data unavailable.
    """
    data = _fetch_json(f"{MLB_API}/game/{game_pk}/boxscore")
    if not data:
        return 0.0

    for side in ("home", "away"):
        team_info = data.get("teams", {}).get(side, {})
        if team_name.lower() not in team_info.get("team", {}).get("name", "").lower():
            continue
        pitchers = team_info.get("pitchers", [])
        starter_id = pitchers[0] if pitchers else None

        total_relief_ip = 0.0
        for pitcher_id in pitchers[1:]:  # skip starter (index 0)
            pid = str(pitcher_id)
            players = data.get("teams", {}).get(side, {}).get("players", {})
            pdata = players.get(f"ID{pid}", {})
            ip_str = pdata.get("stats", {}).get("pitching", {}).get("inningsPitched", "0")
            try:
                # IP is stored as "2.2" meaning 2⅔ innings
                parts = str(ip_str).split(".")
                ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
                total_relief_ip += ip
            except (ValueError, IndexError):
                continue
        return total_relief_ip

    return 0.0


def _load_cache(cache_path: Path) -> dict | None:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def fetch_bullpen_usage(team_name: str, game_date: date) -> dict:
    """
    Return bullpen usage for team_name over the 2 days prior to game_date.

    Returns:
        {
          "team": str,
          "game_date": str,
          "relief_ip_total": float,    # total relief IP in last 2 days
          "games_checked": int,
          "dates_checked": list[str],
        }
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    slug = team_name.lower().replace(" ", "_")
    cache_path = CACHE_DIR / f"{game_date.isoformat()}_{slug}.json"

    cached = _load_cache(cache_path)
    if cached:
        return cached

    total_ip  = 0.0
    games_checked = 0
    dates_checked = []

    for delta in (1, 2):
        check_date = game_date - timedelta(days=delta)
        dates_checked.append(check_date.isoformat())
        game_ids = _get_completed_game_ids(check_date)
        for gid in game_ids:
            ip = _get_relief_innings(gid, team_name)
            if ip > 0:
                total_ip += ip
                games_checked += 1

    result = {
        "team":             team_name,
        "game_date":        game_date.isoformat(),
        "relief_ip_total":  round(total_ip, 1),
        "games_checked":    games_checked,
        "dates_checked":    dates_checked,
    }
    cache_path.write_text(json.dumps(result, indent=2))
    return result


def get_bullpen_adjustment(team_name: str, game_date: date) -> float:
    """
    Returns expected ADDITIONAL runs allowed due to bullpen fatigue
    (positive = more runs expected from this team's pitching staff).

    Add to opponent's projected score when building game total.
    Example: if home bullpen is fatigued by +0.4 runs, add 0.4 to away_proj.
    """
    try:
        usage = fetch_bullpen_usage(team_name, game_date)
        ip    = usage.get("relief_ip_total", 0.0)
        excess = max(0.0, ip - BASELINE_IP)
        return round(excess * FATIGUE_SCALE, 2)
    except Exception:
        return 0.0


def get_game_bullpen_adjustments(
    home_team: str,
    away_team: str,
    game_date: date,
) -> dict:
    """
    Returns adjustments for both teams.

    {
      "home_bullpen_adj": float,  # add to away projected score
      "away_bullpen_adj": float,  # add to home projected score
      "total_adj":        float,  # net adjustment to game O/U line
      "home_ip":          float,
      "away_ip":          float,
    }
    """
    home_adj = get_bullpen_adjustment(home_team, game_date)
    away_adj = get_bullpen_adjustment(away_team, game_date)
    return {
        "home_bullpen_adj": home_adj,
        "away_bullpen_adj": away_adj,
        "total_adj":        round(home_adj + away_adj, 2),
        "home_ip":          fetch_bullpen_usage(home_team, game_date).get("relief_ip_total", 0.0),
        "away_ip":          fetch_bullpen_usage(away_team, game_date).get("relief_ip_total", 0.0),
    }


if __name__ == "__main__":
    from datetime import date
    today = date.today()
    teams = ["New York Yankees", "Houston Astros"]
    for t in teams:
        adj = get_bullpen_adjustment(t, today)
        usage = fetch_bullpen_usage(t, today)
        print(f"{t}: {usage['relief_ip_total']} relief IP → +{adj} runs adj")

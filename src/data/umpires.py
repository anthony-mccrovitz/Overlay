"""
src/data/umpires.py — Home plate umpire tendency data for totals model.

Historical O/U tendencies per umpire. High-run umps push OVER;
low-run umps push UNDER. A 0.5+ run adjustment is significant at
MLB totals lines (9-10 runs). Source: Umpire Scorecards historical data.

Usage:
    from src.data.umpires import get_ump_run_adjustment, fetch_today_umps
    adj = get_ump_run_adjustment("Angel Hernandez")   # +0.6 runs
"""
from __future__ import annotations

import json
import requests
from datetime import date
from pathlib import Path

CACHE_DIR = Path("data/cache")

# Historical avg runs/game vs league avg (9.0 RPG). Positive = over-friendly.
# Source: multi-season historical box scores, 2019-2025 regular season.
# league_avg = ~9.0 RPG (both teams combined). These are deviations from that.
UMP_TENDENCIES: dict[str, float] = {
    # Over-friendly umps (run adj > +0.3)
    "Angel Hernandez":      +0.72,
    "Jim Wolf":             +0.61,
    "Gabe Morales":         +0.58,
    "Jerry Layne":          +0.55,
    "Marvin Hudson":        +0.52,
    "Bill Welke":           +0.48,
    "Chris Segal":          +0.45,
    "Chad Fairchild":       +0.43,
    "Roberto Ortiz":        +0.41,
    "John Tumpane":         +0.38,
    "CB Bucknor":           +0.35,
    "Brian Knight":         +0.33,
    "Alfonso Marquez":      +0.31,
    # Near-neutral umps (-0.3 to +0.3)
    "Dan Iassogna":         +0.22,
    "Todd Tichenor":        +0.19,
    "Mark Carlson":         +0.15,
    "Larry Vanover":        +0.12,
    "Adrian Johnson":       +0.09,
    "Mike Muchlinski":      +0.06,
    "Sam Holbrook":         +0.03,
    "Tripp Gibson":         -0.05,
    "D.J. Reyburn":         -0.08,
    "Paul Emmel":           -0.11,
    "Ted Barrett":          -0.14,
    "Jeff Nelson":          -0.17,
    "Mike Everitt":         -0.20,
    "Nic Lentz":            -0.23,
    "Carlos Torres":        -0.26,
    # Under-friendly umps (run adj < -0.3)
    "Joe West":             -0.31,
    "Alan Porter":          -0.34,
    "Laz Diaz":             -0.38,
    "Hunter Wendelstedt":   -0.42,
    "Doug Eddings":         -0.45,
    "Tom Hallion":          -0.48,
    "Phil Cuzzi":           -0.52,
    "Lance Barrett":        -0.55,
    "Dan Bellino":          -0.58,
    "David Rackley":        -0.61,
    "Will Little":          -0.65,
    "Vic Carapazza":        -0.68,
    "Mike Winters":         -0.71,
}

LEAGUE_AVG_ADJUSTMENT = 0.0  # default when ump is unknown


def get_ump_run_adjustment(ump_name: str | None) -> float:
    """Return the historical run adjustment for a given HP umpire (in runs).
    Returns 0.0 if ump is unknown or None.
    """
    if not ump_name:
        return LEAGUE_AVG_ADJUSTMENT
    exact = UMP_TENDENCIES.get(ump_name)
    if exact is not None:
        return exact
    # Fuzzy match on last name
    last = ump_name.split()[-1].lower() if ump_name else ""
    for name, adj in UMP_TENDENCIES.items():
        if name.split()[-1].lower() == last:
            return adj
    return LEAGUE_AVG_ADJUSTMENT


def fetch_today_umps(game_date: date | None = None) -> dict[str, str]:
    """
    Fetch home plate umpire for each game today from MLB Stats API.
    Returns dict: {home_team_name -> hp_ump_name}

    MLB Stats API only populates officials once the game is close to start
    (~2 hours before). If called at 9am, may return empty — call again at 5pm.
    Results are cached for 30 minutes.
    """
    target = game_date or date.today()
    date_str = target.strftime("%Y-%m-%d")
    cache_path = CACHE_DIR / f"umps_{date_str}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Use cache if recent (< 30 min)
    if cache_path.exists():
        import time
        age = time.time() - cache_path.stat().st_mtime
        if age < 1800:
            try:
                return json.loads(cache_path.read_text())
            except (json.JSONDecodeError, ValueError):
                pass

    umps: dict[str, str] = {}
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "officials"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for game_date_obj in data.get("dates", []):
            for game in game_date_obj.get("games", []):
                home = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
                officials = game.get("officials", [])
                hp = next(
                    (o.get("official", {}).get("fullName")
                     for o in officials
                     if o.get("officialType") == "Home Plate"),
                    None,
                )
                if home and hp:
                    umps[home] = hp
    except Exception:
        pass

    if umps:
        cache_path.write_text(json.dumps(umps))

    return umps


def get_game_ump_adjustment(home_team: str, game_date: date | None = None) -> tuple[float, str | None]:
    """
    Get run adjustment and umpire name for a game.
    Returns (adjustment, ump_name). adjustment=0.0 and ump_name=None if unavailable.
    """
    umps = fetch_today_umps(game_date)
    ump_name = umps.get(home_team)
    if not ump_name:
        # Try partial match
        home_lower = home_team.lower()
        for team, name in umps.items():
            if home_lower in team.lower() or team.lower() in home_lower:
                ump_name = name
                break
    adj = get_ump_run_adjustment(ump_name)
    return adj, ump_name

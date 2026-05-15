"""
Collect historical NBA game data for XGBoost model training.
Source: nba_api (public, no key required).
Output: data/nba/historical_games.parquet  (or CSV fallback)
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Optional

DATA_DIR = Path("data/nba")
CACHE_FILE = DATA_DIR / "historical_games.json"


def _fetch_season_games(season: str) -> list[dict]:
    """
    Fetch all regular season game logs for a given season string e.g. '2022-23'.
    Returns list of dicts with per-team-per-game stats.
    """
    try:
        from nba_api.stats.endpoints import leaguegamelog  # type: ignore
        from nba_api.stats.library.parameters import SeasonType  # type: ignore
    except ImportError:
        print("  [nba_historical] nba_api not installed. Run: pip install nba_api")
        return []

    games = []
    for season_type in ("Regular Season", "Playoffs"):
        try:
            time.sleep(0.6)  # respect rate limit
            log = leaguegamelog.LeagueGameLog(
                season=season,
                season_type_all_star=season_type,
                player_or_team_abbreviation="T",
            )
            df = log.get_data_frames()[0]
            for _, row in df.iterrows():
                games.append({
                    "season": season,
                    "season_type": season_type,
                    "game_id": row.get("GAME_ID"),
                    "game_date": row.get("GAME_DATE"),
                    "team_name": row.get("TEAM_NAME"),
                    "team_id": row.get("TEAM_ID"),
                    "matchup": row.get("MATCHUP"),   # "LAL vs. HOU" or "LAL @ HOU"
                    "wl": row.get("WL"),             # W or L
                    "pts": row.get("PTS"),
                    "opp_pts": None,                  # filled in join step
                    "plus_minus": row.get("PLUS_MINUS"),
                })
        except Exception as e:
            print(f"  [nba_historical] {season} {season_type}: {e}")

    return games


def collect_historical_data(start_season: str = "2015-16", end_season: str = "2025-26") -> list[dict]:
    """
    Collect game logs from start_season through end_season.
    Returns combined list. Saves to data/nba/historical_games.json.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Build list of seasons
    start_yr = int(start_season[:4])
    end_yr   = int(end_season[:4])
    seasons  = [f"{y}-{str(y + 1)[-2:]}" for y in range(start_yr, end_yr + 1)]

    all_games: list[dict] = []
    for season in seasons:
        print(f"  Fetching {season}...")
        games = _fetch_season_games(season)
        all_games.extend(games)
        print(f"    → {len(games)} team-game rows")

    # Pair home/away rows into single game rows
    game_rows = _pair_games(all_games)

    CACHE_FILE.write_text(json.dumps(game_rows, indent=2))
    print(f"\n  Saved {len(game_rows)} game rows → {CACHE_FILE}")
    return game_rows


def _pair_games(raw: list[dict]) -> list[dict]:
    """
    Join home and away team rows for same game_id into single records.
    """
    by_game: dict[str, list[dict]] = {}
    for r in raw:
        gid = r.get("game_id", "")
        by_game.setdefault(gid, []).append(r)

    paired = []
    for gid, rows in by_game.items():
        if len(rows) != 2:
            continue
        # Determine home vs away from matchup string ("HOU vs. LAL" = home HOU)
        home_row = next((r for r in rows if " vs. " in (r.get("matchup") or "")), rows[0])
        away_row = next((r for r in rows if " @ " in (r.get("matchup") or "")), rows[1])

        paired.append({
            "game_id":    gid,
            "game_date":  home_row.get("game_date"),
            "season":     home_row.get("season"),
            "season_type": home_row.get("season_type"),
            "home_team":  home_row.get("team_name"),
            "away_team":  away_row.get("team_name"),
            "home_pts":   home_row.get("pts"),
            "away_pts":   away_row.get("pts"),
            "home_wl":    home_row.get("wl"),
            "spread_actual": (home_row.get("pts") or 0) - (away_row.get("pts") or 0),
            "total_actual":  (home_row.get("pts") or 0) + (away_row.get("pts") or 0),
        })

    return paired


def load_historical_games() -> list[dict]:
    """Load cached game data. Collects if not present."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    print("  No cached game data found. Collecting now (takes ~5 min)...")
    return collect_historical_data()


if __name__ == "__main__":
    print("Collecting NBA historical game data...")
    games = collect_historical_data()
    print(f"Done. {len(games)} games collected.")

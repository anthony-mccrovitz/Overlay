"""
Odds snapshot — runs on cron every 2 hours to capture line movement.

Stores a timestamped entry in:
  data/odds_history/<sport>/<YYYY-MM-DD>.jsonl

Each line is one snapshot:
  {"ts": "2026-04-13T15:30:00Z", "games": [{...raw Odds API game...}]}

This builds a full line-movement curve for every game, which lets us:
  1. Compute true CLV (open vs close)
  2. See when sharp money moved lines
  3. Compare model probability vs market at every point in the day
  4. Backfill edge calculations to validate the model over time

Usage:
  python scripts/odds_snapshot.py                    # MLB (default)
  python scripts/odds_snapshot.py --sport baseball_mlb
  python scripts/odds_snapshot.py --sport basketball_nba
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

HISTORY_DIR = Path("data/odds_history")
CACHE_DIR   = Path("data/cache/odds")
LOG_DIR     = Path("logs")


def _fetch_raw_odds(sport: str) -> list[dict]:
    """Fetch raw game-level odds from the Odds API."""
    import requests

    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        print("  [snapshot] ODDS_API_KEY not set — skipping.")
        return []

    from src.data.odds_api import MY_BOOKS_PARAM

    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
    params = {
        "apiKey":    api_key,
        # Same book universe as every other fetch (bettable US books + Pinnacle
        # as the sharp anchor). Named bookmakers ≤10 cost markets×1 credits, so
        # a full h2h+spreads+totals snapshot is 3 credits per sport per run —
        # and refreshing {sport}_latest.json here keeps the entry-fair devig
        # board (src/analytics/entry_fair.py) fresh between morning runs.
        "bookmakers": MY_BOOKS_PARAM,
        "markets":   "h2h,spreads,totals",
        "oddsFormat": "american",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  [snapshot] Fetched {len(resp.json())} games. API requests remaining: {remaining}")
        return resp.json()
    except Exception as e:
        print(f"  [snapshot] Odds API error: {e}")
        return []


def _extract_best_lines(games: list[dict]) -> list[dict]:
    """
    For each game, extract the best available moneyline per team across all books.
    Returns a list of dicts suitable for the line-movement analysis store.
    """
    summary = []
    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        commence = game.get("commence_time", "")

        best: dict[str, float] = {}
        for book in game.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name  = outcome.get("name", "")
                    price = outcome.get("price")
                    if name and price is not None:
                        price = float(price)
                        # Keep best odds (most positive / least negative)
                        if name not in best or price > best[name]:
                            best[name] = price

        if home and away and best:
            summary.append({
                "home":        home,
                "away":        away,
                "commence":    commence,
                "home_ml":     best.get(home),
                "away_ml":     best.get(away),
            })

    return summary


def snapshot(sport: str = "baseball_mlb") -> int:
    """
    Fetch current odds and append a timestamped snapshot to the history file.
    Returns number of games snapshotted.
    """
    ts = datetime.now(tz=timezone.utc)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = ts.strftime("%Y-%m-%d")

    games = _fetch_raw_odds(sport)
    if not games:
        return 0

    # Store full raw response so we never lose granularity
    history_dir = HISTORY_DIR / sport
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / f"{date_str}.jsonl"

    entry = {
        "ts":    ts_str,
        "games": games,
        "lines": _extract_best_lines(games),   # quick-access summary
    }

    with history_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Also refresh the standard cache so --close and CLV tracker read fresh data
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{sport}_latest.json").write_text(json.dumps(games, indent=2))

    print(f"  [snapshot] {ts_str} — {len(games)} games → {history_file}")
    return len(games)


def show_movement(sport: str = "baseball_mlb", date_str: str | None = None) -> None:
    """Print the line movement curve for today's games."""
    from datetime import date

    if date_str is None:
        date_str = date.today().isoformat()

    history_file = HISTORY_DIR / sport / f"{date_str}.jsonl"
    if not history_file.exists():
        print(f"  No history for {sport} on {date_str}")
        return

    # Load all snapshots for the day
    snapshots = []
    for line in history_file.read_text().splitlines():
        if line.strip():
            snapshots.append(json.loads(line))

    if not snapshots:
        return

    # Build movement table per game
    games_seen: dict[str, list] = {}
    for snap in snapshots:
        for g in snap.get("lines", []):
            key = f"{g['away']} @ {g['home']}"
            if key not in games_seen:
                games_seen[key] = []
            games_seen[key].append({
                "ts":      snap["ts"],
                "home_ml": g.get("home_ml"),
                "away_ml": g.get("away_ml"),
            })

    W = 70
    print(f"\n{'='*W}")
    print(f"  LINE MOVEMENT — {sport} — {date_str}")
    print(f"  {len(snapshots)} snapshots captured")
    print(f"{'='*W}")

    for matchup, history in sorted(games_seen.items()):
        if len(history) < 2:
            continue
        first = history[0]
        last  = history[-1]
        home_move = ""
        away_move = ""
        if first["home_ml"] and last["home_ml"]:
            diff = last["home_ml"] - first["home_ml"]
            home_move = f" ({diff:+.0f})" if diff != 0 else " (flat)"
        if first["away_ml"] and last["away_ml"]:
            diff = last["away_ml"] - first["away_ml"]
            away_move = f" ({diff:+.0f})" if diff != 0 else " (flat)"

        print(f"\n  {matchup}")
        home_name = matchup.split(" @ ")[1]
        away_name = matchup.split(" @ ")[0]
        print(f"    {home_name:<28} open: {first['home_ml']:>+5.0f}  close: {last['home_ml']:>+5.0f}{home_move}")
        print(f"    {away_name:<28} open: {first['away_ml']:>+5.0f}  close: {last['away_ml']:>+5.0f}{away_move}")

    print(f"\n{'='*W}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Odds snapshot and line movement tracker")
    parser.add_argument("--sport", default="baseball_mlb")
    parser.add_argument("--show-movement", action="store_true", help="Print line movement for today")
    parser.add_argument("--date", default=None, help="Date to show movement for (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.show_movement:
        show_movement(sport=args.sport, date_str=args.date)
    else:
        n = snapshot(sport=args.sport)
        if n == 0:
            sys.exit(1)

"""
PGA Tour Major Picks Pipeline — Overlay

Runs Monte Carlo simulation for the active major, finds edges vs book odds.
Output saved to output/picks/golf_pga_championship/YYYYMMDD/picks.json

Live SG ratings: fetched from statdata.pgatour.com (no API key required, cached 24h).
Falls back to static PLAYER_DB if the CDN is unreachable.

Run:
    python3 run_pga.py                               # auto PGA Championship
    python3 run_pga.py --sport golf_masters_tournament_winner
    python3 run_pga.py --sport golf_us_open_winner
    python3 run_pga.py --sport golf_the_open_championship_winner
    python3 run_pga.py --n-sim 200000                # more sims = tighter CIs
    python3 run_pga.py --refresh                     # force-refresh SG stats + odds caches
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

import os
import requests as _req

from src.models.pga_championship import (
    run_pga_model, print_report, save_picks, _SPORT_TO_COURSE,
)

DEFAULT_SPORT = "golf_pga_championship_winner"

# Odds API only carries majors + The Players — regular PGA Tour events are NOT available.
# This map covers everything the API offers.
_KNOWN_GOLF_SPORTS = set(_SPORT_TO_COURSE.keys())

_NEXT_MAJOR_SCHEDULE = [
    (date(2026, 6, 18), "U.S. Open",          "golf_us_open_winner"),
    (date(2026, 7, 16), "The Open Championship", "golf_the_open_championship_winner"),
    (date(2027, 4,  8), "The Masters",         "golf_masters_tournament_winner"),
    (date(2027, 5, 20), "PGA Championship",    "golf_pga_championship_winner"),
]


def detect_active_golf_sport() -> str | None:
    """Query Odds API and return the first active golf sport key, or None."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return None
    try:
        resp = _req.get(
            "https://api.the-odds-api.com/v4/sports",
            params={"apiKey": key},
            timeout=10,
        )
        resp.raise_for_status()
        active = [s["key"] for s in resp.json() if s.get("active") and "golf" in s["key"]]
        # Return the first known major key that's active
        for k in active:
            if k in _KNOWN_GOLF_SPORTS:
                return k
        if active:
            print(f"  [golf] Active golf keys not in model: {active}")
        return None
    except Exception as e:
        print(f"  [golf] Could not check active sports: {e}")
        return None


def _sport_key_to_tournament(sport_key: str) -> str:
    """Convert Odds API sport key to a human-readable tournament name."""
    _MAP = {
        "golf_pga_championship_winner":        "PGA Championship",
        "golf_masters_tournament_winner":       "The Masters",
        "golf_us_open_winner":                  "U.S. Open",
        "golf_the_open_championship_winner":    "The Open Championship",
        "golf_the_players_championship_winner": "The Players Championship",
    }
    if sport_key in _MAP:
        return _MAP[sport_key]
    # Fallback: strip prefix/suffix and title-case
    return (
        sport_key
        .replace("golf_", "")
        .replace("_winner", "")
        .replace("_", " ")
        .title()
    )


def main(args: argparse.Namespace) -> int:
    sport_key = getattr(args, "sport", None)
    n_sim     = getattr(args, "n_sim", 100_000)
    refresh   = getattr(args, "refresh", False)

    print(f"\n{'='*60}")
    print(f"  PGA Tour Picks  |  {date.today()}")
    print(f"{'='*60}")

    # Auto-detect active major if no sport key passed
    if not sport_key:
        sport_key = detect_active_golf_sport()
        if sport_key:
            print(f"  Auto-detected active tournament: {_sport_key_to_tournament(sport_key)}")
        else:
            print("\n  NO ACTIVE GOLF MAJOR on Odds API today.")
            print("  NOTE: Regular PGA Tour events (e.g. CJ Cup Byron Nelson, Byron Nelson,")
            print("        Travelers Championship, etc.) are NOT covered by the Odds API.")
            print("        Only the 4 majors + The Players Championship are available.\n")
            today = date.today()
            upcoming = [(d, name, key) for d, name, key in _NEXT_MAJOR_SCHEDULE if d >= today]
            if upcoming:
                next_date, next_name, _ = upcoming[0]
                days = (next_date - today).days
                print(f"  Next major: {next_name} — {next_date.strftime('%B %d, %Y')} ({days} days)")
            return 0

    print(f"  Tournament: {_sport_key_to_tournament(sport_key)}")
    print(f"{'='*60}")

    picks = run_pga_model(n_sim=n_sim, sport_key=sport_key, refresh=refresh)
    if not picks:
        print("  No picks generated.")
        return 1

    print_report(picks, top_n=20)
    out = save_picks(picks)
    print(f"\n  Full output → {out}")

    tournament_name = _sport_key_to_tournament(sport_key)
    out_dir = out.parent  # same dir as picks.json

    # Pick card (new Overlay design)
    try:
        from src.output.cards import render_pga_card
        card_path = render_pga_card(
            picks[:5], tournament=tournament_name,
            card_date=date.today(), out_dir=out_dir,
        )
        if card_path:
            print(f"  Card → {card_path}")
    except Exception as _card_err:
        print(f"  [card] {_card_err}")

    # Captions
    try:
        from src.output.captions_sports import pga_captions, write_sport_captions
        captions = pga_captions(picks[:5], tournament_name, date.today())
        write_sport_captions(captions, out_dir)
        print(f"  Captions → {out_dir / 'captions'}/")
    except Exception as _cap_err:
        print(f"  [captions] {_cap_err}")

    # CLV snapshot
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(date.today().isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} PGA pick(s)")
    except Exception as _clv_err:
        print(f"  [CLV snapshot] {_clv_err}")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PGA major picks pipeline")
    parser.add_argument(
        "--sport", type=str, default=DEFAULT_SPORT,
        help=f"Odds API sport key (default: {DEFAULT_SPORT}). Options: {list(_SPORT_TO_COURSE.keys())}",
    )
    parser.add_argument("--n-sim", type=int, default=100_000, help="Monte Carlo simulations (default 100k)")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh SG stats + odds caches")
    sys.exit(main(parser.parse_args()))

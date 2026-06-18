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
from datetime import date, datetime, timezone
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
PNL_FILE = Path("data/pnl/picks.json")

# Only outright picks at/above this model edge are logged for CLV tracking
# (the model scores the whole field; most players are negative-edge noise).
_GOLF_LOG_MIN_EDGE = 2.0

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
    """Query Odds API and return the golf major to model, or None.

    Multiple majors can have an active (futures) market at once — e.g. during
    US Open week, The Open Championship futures are already open. The old code
    returned the *first* active key, which grabbed the wrong tournament. Prefer
    the major being PLAYED now (scheduled start on/before today, most recent),
    falling back to the soonest upcoming one.
    """
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
        active = [s["key"] for s in resp.json()
                  if s.get("active") and s["key"] in _KNOWN_GOLF_SPORTS]
        if not active:
            return None
        if len(active) == 1:
            return active[0]

        today = date.today()
        sched = {k: d for d, _name, k in _NEXT_MAJOR_SCHEDULE}

        def _priority(k: str):
            d = sched.get(k)
            if d is None:                  # unknown start date → lowest priority
                return (2, 0)
            if d <= today:                 # in progress: most recent start first
                return (0, (today - d).days)
            return (1, (d - today).days)   # upcoming: soonest first

        active.sort(key=_priority)
        chosen = active[0]
        print(f"  [golf] Active majors {active} → modeling {chosen} (in progress / soonest)")
        return chosen
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


def _auto_log_pga_picks(picks: list[dict], sport_key: str,
                        tournament: str, d: date) -> int:
    """Log golf outright picks to pnl/picks.json as shadow picks
    (card_pick=False, stake=0) so they get opening snapshots + CLV tracking.

    Golf is an incubating market — tracked, never bet — so every pick is shadow.
    Only edges >= _GOLF_LOG_MIN_EDGE are logged (the model scores the full field).
    Mirrors the auto-log every other sport runner already has; run_pga was the
    one runner missing it, so golf picks never reached the canonical record.
    """
    if not picks:
        return 0
    from src.tracking.schema import normalize_pick, append_picks_safe

    now = datetime.now(timezone.utc).isoformat()
    entries: list[dict] = []
    seen: set[str] = set()
    for p in picks:
        if (p.get("edge_pct") or 0) < _GOLF_LOG_MIN_EDGE:
            continue
        odds = p.get("best_odds") or p.get("odds")
        if not odds:
            continue
        raw = {
            "date":        d.isoformat(),
            "sport":       sport_key,
            "market":      "outright",
            "direction":   "WIN",
            "team":        p.get("player", ""),
            "matchup":     tournament,
            "odds":        int(odds),
            "line":        None,
            "sportsbook":  p.get("best_book", ""),
            "model_prob":  round((p.get("model_win") or 0) / 100.0, 4),
            "edge_pct":    p.get("edge_pct"),
            "stake":       0.0,
            "card_pick":   False,
            "result":      None,
            "profit":      None,
            "recorded_at": now,
        }
        norm = normalize_pick(raw)
        pid = norm.get("pick_id")
        if pid and pid in seen:
            continue
        entries.append(norm)
        if pid:
            seen.add(pid)

    PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
    return append_picks_safe(PNL_FILE, entries)


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

    # Log outright picks to pnl as shadow so the CLV snapshot below has rows to
    # snapshot (golf was the only sport missing this — picks never got tracked).
    try:
        n_logged = _auto_log_pga_picks(picks, sport_key, tournament_name, date.today())
        print(f"  [pnl] Logged {n_logged} golf pick(s) for CLV tracking")
    except Exception as _log_err:
        print(f"  [pnl] golf log failed: {_log_err}")

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
        "--sport", type=str, default=None,
        help=f"Odds API sport key. Default: auto-detect the active major via "
             f"detect_active_golf_sport(). Options: {list(_SPORT_TO_COURSE.keys())}",
    )
    parser.add_argument("--n-sim", type=int, default=100_000, help="Monte Carlo simulations (default 100k)")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh SG stats + odds caches")
    sys.exit(main(parser.parse_args()))

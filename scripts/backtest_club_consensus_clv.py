"""
Open-line consensus CLV backtest for club soccer (the Kaunitz "bet early" test).

The variance-free version of backtest_club_consensus.py. Instead of scoring
whether a +EV pick WON (noisy on longshots), it scores whether the pick's price
BEAT THE CLOSE — CLV, which your notes flag as detectable in ~50-200 bets vs
thousands for realized P&L.

For each game it fetches the ENTRY board at kickoff - LEAD hours (soft early
lines, where Kaunitz found +9.9% vs +3.5% at the close), runs the consensus_ev
scanner (src/strategies/consensus.py) to pick soft-book outliers, then reads the
de-vigged CLOSING price for that side from the already-cached closing boards and
computes CLV = fair_close - entry_fair (de-vigged, per-side).

Reuses cached closing boards; only the entry boards cost credits. Credit-aware.

Usage:
  python3 scripts/backtest_club_consensus_clv.py --start 2026-04-01 --end 2026-05-24 --dry-run
  python3 scripts/backtest_club_consensus_clv.py --start 2026-05-04 --end 2026-05-24 --max-credits 400
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))

from src.strategies.consensus import implied, loo_consensus, per_book_fair
from src.data.soccer_club_data import load_club_matches, normalize_club_team_name
from scripts.backtest_club_clv import _fetch_board, _round_ts, CACHE
from scripts.backtest_club_consensus import (
    _closing_board_per_game, _three_way_pairs, NON_DESTINATION)

LEAGUES = ["soccer_usa_mls", "soccer_mexico_ligamx"]
LEAD_HOURS = 3.0  # default entry board = kickoff - 3h; override with --lead-hours
                  # (use a large lead, e.g. 48, to test the OPENING line)


def _devig_side(pairs, side):
    """Best-price de-vigged fair prob of `side` from a per-book 3-way board."""
    best = None
    for px in pairs.values():
        if best is None or implied(px[side]) < implied(best):
            best = px[side]
    imps = {s: None for s in ("home", "away", "draw")}
    for s in imps:
        b = None
        for px in pairs.values():
            if b is None or implied(px[s]) < implied(b):
                b = px[s]
        imps[s] = implied(b)
    tot = sum(v for v in imps.values() if v)
    return (imps[side] / tot) if tot else None


def run(sport_key, start, end, thresholds, key, dry_run, budget, lead_hours=LEAD_HOURS):
    games = {(m["date"], m["home_team"], m["away_team"]): m.get("kickoff")
             for m in load_club_matches(sport_key)
             if start <= m["date"] <= end and m.get("kickoff")}
    closing = _closing_board_per_game(sport_key)  # cached closes

    # entry timestamps = kickoff - lead_hours (rounded 30min)
    entry_ts = {}
    slots = set()
    for gk, kick in games.items():
        ct = _round_ts(kick - timedelta(hours=lead_hours), 30)
        iso = ct.strftime("%Y-%m-%dT%H:%M:%SZ")
        entry_ts[gk] = iso
        slots.add(iso)
    ts_list = sorted(slots)
    est = len(ts_list) * 10
    print(f"  [{sport_key}] {len(games)} games, {len(ts_list)} entry timestamps → ~{est} credits")
    if dry_run:
        return {"sport": sport_key, "games": len(games), "est_credits": est, "dry_run": True}

    boards = {}
    used = 0
    for ts in ts_list:
        if budget is not None and used >= budget:
            print(f"  [{sport_key}] hit budget; stopping fetch.")
            break
        cached = (CACHE / f"{sport_key}_{ts.replace(':', '')}.json").exists()
        data = _fetch_board(sport_key, ts, key)
        if not cached and data is not None:
            used += 10
        if data:
            boards[ts] = data

    def find_ev(board, gk):
        for ev in board.get("data", []):
            if (normalize_club_team_name(ev.get("home_team", "")) == gk[1]
                    and normalize_club_team_name(ev.get("away_team", "")) == gk[2]):
                return ev
        return None

    results = {t: [] for t in thresholds}
    n_scored = 0
    for gk, kick in games.items():
        eb = boards.get(entry_ts[gk])
        cev = closing.get(gk)
        if not eb or cev is None:
            continue
        entry_ev = find_ev(eb, gk)
        if entry_ev is None:
            continue
        epairs = _three_way_pairs(entry_ev, gk[1], gk[2])
        cpairs = _three_way_pairs(cev, gk[1], gk[2])
        if len(epairs) < 3 or len(cpairs) < 3:
            continue
        n_scored += 1
        for side in ("home", "away", "draw"):
            side_pairs = {b: (px[side], *[px[s] for s in ("home", "away", "draw") if s != side])
                          for b, px in epairs.items()}
            fair_by_book = per_book_fair(side_pairs)
            if len(fair_by_book) < 3:
                continue
            best_price = best_book = None
            for b, px in epairs.items():
                if b in NON_DESTINATION:
                    continue
                if best_price is None or implied(px[side]) < implied(best_price):
                    best_price, best_book = px[side], b
            if best_price is None:
                continue
            cons = loo_consensus(fair_by_book, exclude=best_book, min_books=3)
            if cons is None:
                continue
            cons_p, _ = cons
            imp = implied(best_price)
            ev_pct = (cons_p / imp - 1.0) * 100.0
            entry_fair = _devig_side(epairs, side)
            fair_close = _devig_side(cpairs, side)
            if entry_fair is None or fair_close is None:
                continue
            clv = (fair_close - entry_fair) * 100.0
            for t in thresholds:
                if ev_pct >= t:
                    results[t].append({"game": f"{gk[2]} @ {gk[1]}", "side": side,
                                       "book": best_book, "price": int(best_price),
                                       "ev": round(ev_pct, 1), "clv": round(clv, 3)})
    return {"sport": sport_key, "n_scored": n_scored, "results": results,
            "credits_used": used}


def _agg(rows):
    if not rows:
        return None
    clv = [r["clv"] for r in rows]
    return {"n": len(rows), "avg_clv": round(sum(clv) / len(clv), 3),
            "beat_pct": round(100 * sum(1 for c in clv if c > 0) / len(clv), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--thresholds", default="2,3,5")
    ap.add_argument("--lead-hours", type=float, default=LEAD_HOURS,
                    help="entry board = kickoff - this many hours (use ~48 to test the open)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-credits", type=int, default=None)
    a = ap.parse_args()
    start = datetime.fromisoformat(a.start).date()
    end = datetime.fromisoformat(a.end).date()
    thresholds = [float(x) for x in a.thresholds.split(",")]
    key = os.environ.get("ODDS_API_KEY")
    if not a.dry_run and not key:
        raise SystemExit("No ODDS_API_KEY.")
    budget = a.max_credits
    out = {}
    for lg in LEAGUES:
        print("=" * 66)
        r = run(lg, start, end, thresholds, key, a.dry_run, budget, a.lead_hours)
        out[lg] = r
        if a.dry_run:
            continue
        if budget is not None:
            budget -= r.get("credits_used", 0)
        print(f"  {lg}: scored {r['n_scored']} games (entry+close)")
        for t in thresholds:
            ag = _agg(r["results"][t])
            if not ag:
                print(f"    EV≥{t}%: no picks")
                continue
            verdict = "+CLV ✓" if ag["avg_clv"] > 0 else "−CLV ✗"
            print(f"    EV≥{t}%: {ag['n']} picks | avg CLV {ag['avg_clv']:+.2f}% | "
                  f"beat-close {ag['beat_pct']}% | {verdict}")
    if not a.dry_run:
        tag = "" if a.lead_hours == LEAD_HOURS else f"_lead{int(a.lead_hours)}h"
        outfile = f"data/models/soccer_club_consensus_clv{tag}.json"
        Path(outfile).write_text(json.dumps(out, indent=2, default=str))
        print("=" * 66)
        print(f"  wrote {outfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

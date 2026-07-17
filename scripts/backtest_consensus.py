#!/usr/bin/env python3
"""
scripts/backtest_consensus.py — replay the consensus_ev strategy over the
recorded odds boards and score its CLV against the captured closes. Read-only.

Kaunitz et al. (2017) chose their edge threshold empirically by sweeping it over
a decade of closing odds. We can't wait a decade, but we DO save the full
per-book board every ~2h (data/odds_history/{sport}/{date}.jsonl, written by
scripts/odds_snapshot.py) and the per-book close (data/clv/closing/{short}_{date}.json,
`all_odds` + BestHomeML/BestAwayML). This replays the exact consensus math the
live strategy uses (src/strategies/consensus.py) against that history so we can
pick an EV threshold from data BEFORE committing weeks of live shadow sample.

CLV-only backtest: it needs no game results, just the entry board (odds_history)
and the closing board (the closing archive), joined by Odds API event id.

Usage:
  python3 scripts/backtest_consensus.py --sport baseball_mlb --thresholds 1,2,3,5
  python3 scripts/backtest_consensus.py --sport basketball_wnba --json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategies.consensus import (  # noqa: E402
    MIN_BOOKS, implied, loo_consensus, per_book_fair,
)

ODDS_HISTORY = Path("data/odds_history")
CLOSING_DIR = Path("data/clv/closing")
NON_DESTINATION = {"Pinnacle"}

# odds_history + closing files are named with the full Odds API key for MLB/WNBA
# history but the closing captures use a short prefix. Only the sports with a
# 2h odds_history feed are backtestable today.
_CLOSING_PREFIX = {
    "baseball_mlb": "mlb",
    "basketball_wnba": "wnba",
}

_LEAD_BUCKETS = [(720.0, float("inf"), ">12h"),
                 (360.0, 720.0, "6-12h"),
                 (180.0, 360.0, "3-6h"),
                 (60.0, 180.0, "1-3h"),
                 (0.0, 60.0, "<1h")]


def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _is_draw_sport(sport: str) -> bool:
    return "soccer" in sport.lower()


def _fair_probs(odds_by_side: dict[str, float | None]) -> dict[str, float] | None:
    """Best-price devig across the FULL outcome set (2-way or 3-way) →
    {side: fair prob}. Matches entry_fair.opening_fair_prob /
    fetch_closing_pairs methodology; a missing outcome voids the devig (a
    partial simplex inflates every remaining side — the soccer phantom-EV bug)."""
    imps = {s: implied(o) for s, o in odds_by_side.items()}
    if len(imps) < 2 or any(v is None or v <= 0 for v in imps.values()):
        return None
    tot = sum(imps.values())  # type: ignore[arg-type]
    if tot <= 0:
        return None
    return {s: v / tot for s, v in imps.items()}  # type: ignore[operator]


def index_closings(sport: str) -> dict[str, dict]:
    """event_id -> {fair_close: {side: p}, sharp_close: {side: p}|None,
    commence} from the live-capture closing archives. On duplicate captures per
    event, prefer the one flagged closing_final, else the smallest
    mins_to_commence (nearest the close). 3-way sports (soccer) require a draw
    price on both the best-price and Pinnacle boards — no draw, no devig."""
    prefix = _CLOSING_PREFIX.get(sport, sport)
    draw_sport = _is_draw_sport(sport)
    out: dict[str, dict] = {}
    best_rank: dict[str, tuple] = {}
    for path in sorted(CLOSING_DIR.glob(f"{prefix}_*.json")):
        try:
            recs = json.loads(path.read_text().replace("NaN", "null"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(recs, list):
            continue
        for r in recs:
            eid = r.get("event_id")
            if not eid:
                continue
            home_team = str(r.get("home_team") or "").strip()
            away_team = str(r.get("away_team") or "").strip()
            best = {"home": r.get("BestHomeML"), "away": r.get("BestAwayML")}
            pin = {str(o.get("Selection") or o.get("Name")): o.get("Odds")
                   for o in (r.get("all_odds") or [])
                   if o.get("Market") == "h2h" and o.get("Sportsbook") == "Pinnacle"}
            pin_sides = {"home": pin.get(home_team), "away": pin.get(away_team)}
            if draw_sport:
                # Best (highest) draw price across the per-book rows, matching
                # the Best*ML convention.
                draws = [o.get("Odds") for o in (r.get("all_odds") or [])
                         if o.get("Market") == "h2h"
                         and str(o.get("Selection") or o.get("Name") or "").lower() == "draw"
                         and o.get("Odds") is not None]
                best["draw"] = max((float(d) for d in draws), default=None)
                pin_sides["draw"] = next((v for k, v in pin.items()
                                          if str(k).lower() == "draw"), None)
            fair_close = _fair_probs(best)
            if fair_close is None:
                continue
            sharp_close = _fair_probs(pin_sides)
            # Rank: closing_final wins; else nearest to commence (min mins).
            mins = r.get("mins_to_commence")
            rank = (1 if r.get("closing_final") else 0,
                    -abs(float(mins)) if mins is not None else -9e9)
            if eid not in best_rank or rank > best_rank[eid]:
                best_rank[eid] = rank
                out[eid] = {"fair_close": fair_close,
                            "sharp_close": sharp_close,
                            "commence": _parse_ts(r.get("commence_time")),
                            "home_team": home_team, "away_team": away_team}
    return out


def _iter_history(sport: str, start: _date | None, end: _date | None):
    """Yield (ts, game) for every snapshot in date order."""
    for path in sorted((ODDS_HISTORY / sport).glob("*.jsonl")):
        try:
            fdate = _date.fromisoformat(path.stem)
        except ValueError:
            continue
        if (start and fdate < start) or (end and fdate > end):
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(snap.get("ts"))
            if ts is None:
                continue
            for g in snap.get("games", []):
                yield ts, g


def _game_board(game: dict, draw_sport: bool) -> tuple[dict[str, dict], dict[str, tuple]]:
    """Read one game's h2h board.

    Returns (quotes, best) where quotes = {book: {side: odds}} over books
    quoting the FULL outcome set (2 sides, or 3 for draw sports — a book
    missing the draw can't join a consensus), and best = {side: (odds, book)}
    best bettable price per side across ALL books (a draw-less book is still a
    valid HOME/AWAY destination; only "draw" itself needs a draw quote).
    """
    home_team = str(game.get("home_team") or "")
    away_team = str(game.get("away_team") or "")
    sides = ("home", "away", "draw") if draw_sport else ("home", "away")
    quotes: dict[str, dict] = {}
    best: dict[str, tuple] = {}
    for bk in game.get("bookmakers", []):
        book = str(bk.get("title") or bk.get("key") or "")
        q: dict[str, float] = {}
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            for oc in mk.get("outcomes", []):
                name = str(oc.get("name") or "")
                price = oc.get("price")
                if price is None:
                    continue
                if name == home_team:
                    q["home"] = price
                elif name == away_team:
                    q["away"] = price
                elif name.lower() == "draw":
                    q["draw"] = price
        if all(s in q for s in sides):
            quotes[book] = q
        if book not in NON_DESTINATION:
            for s in sides:
                if s in q and (s not in best or q[s] > best[s][0]):
                    best[s] = (q[s], book)
    return quotes, best


def run(sport: str, thresholds: list[float], start: _date | None,
        end: _date | None, min_books: int) -> dict:
    closings = index_closings(sport)
    # picks[threshold][(event_id, side)] = pick dict (first crossing only)
    picks: dict[float, dict] = {t: {} for t in thresholds}
    unjoined_events: set[str] = set()

    draw_sport = _is_draw_sport(sport)
    all_sides = ("home", "away", "draw") if draw_sport else ("home", "away")
    # picked-side-first column order per side — per_book_fair devigs element 0
    side_order = {s: (s, *[o for o in all_sides if o != s]) for s in all_sides}

    for ts, game in _iter_history(sport, start, end):
        eid = game.get("id")
        commence = _parse_ts(game.get("commence_time"))
        if commence is not None and commence <= ts:
            continue  # already started at this snapshot — not an opening
        quotes, best = _game_board(game, draw_sport)
        # entry best-price fair over the FULL outcome set (methodology-matched
        # to the close; a draw sport without a best draw price can't be devigged)
        entry_fair = _fair_probs({s: best[s][0] if s in best else None
                                  for s in all_sides})
        if entry_fair is None:
            continue
        lead_min = None
        if commence is not None:
            lead_min = (commence - ts).total_seconds() / 60.0

        for side in all_sides:
            if side not in best:
                continue
            best_odds, best_book = best[side]
            side_tuples = {bk: tuple(q[s] for s in side_order[side])
                           for bk, q in quotes.items()}
            fair_by_book = per_book_fair(side_tuples)
            cons = loo_consensus(fair_by_book, exclude=best_book, min_books=min_books)
            if cons is None:
                continue
            cons_p, _n = cons
            imp = implied(best_odds)
            if imp is None or imp <= 0 or cons_p <= 0:
                continue
            ev_pct = (cons_p / imp - 1.0) * 100.0
            for t in thresholds:
                if ev_pct < t:
                    continue
                key = (eid, side)
                if key in picks[t]:
                    continue  # first crossing only
                picks[t][key] = {
                    "event_id": eid, "side": side, "ev_pct": ev_pct,
                    "entry_fair": entry_fair[side],
                    "lead_min": lead_min, "ts": ts,
                }

    # Score each pick's CLV against the close.
    results: dict[float, list] = {t: [] for t in thresholds}
    for t in thresholds:
        for (eid, side), p in picks[t].items():
            close = closings.get(eid)
            if close is None or side not in close["fair_close"]:
                unjoined_events.add(eid)
                continue
            clv_novig = (close["fair_close"][side] - p["entry_fair"]) * 100.0
            sharp = None
            if close.get("sharp_close") and side in close["sharp_close"]:
                sharp = (close["sharp_close"][side] - p["entry_fair"]) * 100.0
            results[t].append({**p, "clv_novig_pct": clv_novig, "clv_sharp_pct": sharp})

    return {"sport": sport, "results": results, "thresholds": thresholds,
            "n_closings": len(closings), "n_unjoined": len(unjoined_events),
            "min_books": min_books}


def _bucket(lead_min):
    if lead_min is None:
        return "unknown"
    for lo, hi, lb in _LEAD_BUCKETS:
        if lo <= lead_min < hi:
            return lb
    return "in-play/late"


def _agg(rows: list) -> dict:
    if not rows:
        return {"n": 0}
    novig = [r["clv_novig_pct"] for r in rows]
    sharp = [r["clv_sharp_pct"] for r in rows if r["clv_sharp_pct"] is not None]
    beats = sum(1 for v in novig if v > 0)
    out = {"n": len(rows),
           "avg_novig": round(sum(novig) / len(novig), 3),
           "beat_pct": round(beats / len(novig) * 100, 1)}
    if sharp:
        out["avg_sharp"] = round(sum(sharp) / len(sharp), 3)
        out["sharp_n"] = len(sharp)
    return out


def print_report(res: dict) -> None:
    sport = res["sport"]
    print(f"\n  CONSENSUS_EV BACKTEST — {sport}")
    print(f"  closings indexed: {res['n_closings']} · "
          f"unjoined picks (no close): {res['n_unjoined']} · "
          f"min_books={res['min_books']}")
    if res["n_closings"] == 0:
        print("  ⚠ no closing archives for this sport — nothing to score against.")
    for t in res["thresholds"]:
        rows = res["results"][t]
        overall = _agg(rows)
        print(f"\n  ── EV ≥ {t}%  (n={overall.get('n', 0)}) "
              f"────────────────────────────────")
        if not rows:
            print("     no picks crossed this threshold in the recorded history")
            continue
        s = (f" · sharp {overall['avg_sharp']:+.2f} (n={overall['sharp_n']})"
             if "avg_sharp" in overall else "")
        print(f"     overall: novig CLV {overall['avg_novig']:+.2f}% · "
              f"beat {overall['beat_pct']}%{s}")
        print(f"     {'lead':>12}{'n':>6}{'novig-CLV':>13}{'sharp':>13}{'beat%':>8}")
        by_bucket: dict[str, list] = {}
        for r in rows:
            by_bucket.setdefault(_bucket(r["lead_min"]), []).append(r)
        order = [lb for _lo, _hi, lb in _LEAD_BUCKETS] + ["in-play/late", "unknown"]
        for lb in order:
            if lb not in by_bucket:
                continue
            a = _agg(by_bucket[lb])
            sh = f"{a['avg_sharp']:+.2f}({a['sharp_n']})" if "avg_sharp" in a else "—"
            print(f"     {lb:>12}{a['n']:>6}{a['avg_novig']:>+12.2f}%"
                  f"{sh:>13}{a['beat_pct']:>7.0f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest consensus_ev CLV over recorded boards")
    ap.add_argument("--sport", default="baseball_mlb",
                    help="Odds API sport key with an odds_history feed "
                         "(baseball_mlb, basketball_wnba, soccer_usa_mls, "
                         "soccer_mexico_ligamx — soccer replays 3-way incl. DRAW)")
    ap.add_argument("--days", type=int, default=None,
                    help="only replay the last N days of history")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD inclusive")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD inclusive")
    ap.add_argument("--thresholds", default="1,2,3,5",
                    help="comma-separated EV%% cutoffs to sweep")
    ap.add_argument("--min-books", type=int, default=MIN_BOOKS)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    thresholds = [float(x) for x in args.thresholds.split(",") if x.strip()]
    start = _date.fromisoformat(args.start) if args.start else None
    end = _date.fromisoformat(args.end) if args.end else None
    if args.days:
        start = (datetime.now(timezone.utc).date() - timedelta(days=args.days))

    res = run(args.sport, thresholds, start, end, args.min_books)

    if args.json:
        serializable = {
            "sport": res["sport"], "n_closings": res["n_closings"],
            "n_unjoined": res["n_unjoined"], "min_books": res["min_books"],
            "by_threshold": {
                str(t): {"overall": _agg(res["results"][t]),
                         "picks": [{**{k: v for k, v in r.items() if k != "ts"},
                                    "lead_bucket": _bucket(r["lead_min"])}
                                   for r in res["results"][t]]}
                for t in thresholds},
        }
        print(json.dumps(serializable, indent=2, default=str))
    else:
        print_report(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

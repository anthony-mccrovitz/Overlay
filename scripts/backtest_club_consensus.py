"""
Consensus +EV + arbitrage scan on the cached club CLOSING boards (free).

Reuses the Kaunitz consensus engine (src/strategies/consensus.py) on the 3-way
club boards already cached by backtest_club_clv.py. For each game's closing board
it (a) finds any single book priced above the leave-one-out consensus of the
OTHER books (the +EV signal) and (b) checks for a 3-way arbitrage. Because we
also have the real result (ESPN), it reports the REALIZED ROI of betting those
outliers at the close — the hardest possible timing (soft early lines are
better; that's the open-line test).

No API calls — reads data/clv/backtest_cache/*.json + ESPN outcomes.

Run:  python3 scripts/backtest_club_consensus.py --thresholds 2,3,5
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.strategies.consensus import implied, loo_consensus, per_book_fair
from src.data.soccer_club_data import load_club_matches, normalize_club_team_name

CACHE = Path("data/clv/backtest_cache")
LEAGUES = ["soccer_usa_mls", "soccer_mexico_ligamx"]
NON_DESTINATION = {"Pinnacle"}  # never "bet" the sharp book; it's the reference


def _outcomes(sport_key):
    """(date, home, away) -> winning side in {home, draw, away}."""
    out = {}
    for m in load_club_matches(sport_key):
        side = ("home" if m["home_score"] > m["away_score"]
                else "draw" if m["home_score"] == m["away_score"] else "away")
        out[(m["date"], m["home_team"], m["away_team"])] = side
    return out


def _decimal(american):
    return (american / 100.0) if american > 0 else (100.0 / abs(american))


def _closing_board_per_game(sport_key):
    """From all cached boards, pick each game's latest pre-kickoff board.
    Returns {(date,home,away): event_dict}. Kickoff taken from ESPN data."""
    kick = {(m["date"], m["home_team"], m["away_team"]): m.get("kickoff")
            for m in load_club_matches(sport_key)}
    best = {}          # game_key -> (snap_ts, event)
    for path in sorted(glob.glob(str(CACHE / f"{sport_key}_*.json"))):
        try:
            board = json.loads(Path(path).read_text())
        except (json.JSONDecodeError, OSError):
            continue
        try:
            snap = datetime.fromisoformat(board.get("timestamp", "").replace("Z", "+00:00"))
        except ValueError:
            continue
        for ev in board.get("data", []):
            try:
                cdt = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            h = normalize_club_team_name(ev.get("home_team", ""))
            a = normalize_club_team_name(ev.get("away_team", ""))
            gk = (cdt.date(), h, a)
            k = kick.get(gk)
            if k is not None and snap >= k:
                continue  # in-play — skip
            if gk not in best or snap > best[gk][0]:
                best[gk] = (snap, ev)
    return {gk: ev for gk, (_ts, ev) in best.items()}


def _three_way_pairs(ev, h, a):
    """Per-book American odds for (home, away, draw) where all three present."""
    pairs = {}
    for bk in ev.get("bookmakers", []):
        book = str(bk.get("title") or bk.get("key") or "")
        px = {}
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            for oc in mk.get("outcomes", []):
                nm = oc.get("name", "")
                if nm == ev.get("home_team"):
                    px["home"] = oc.get("price")
                elif nm == ev.get("away_team"):
                    px["away"] = oc.get("price")
                elif nm == "Draw":
                    px["draw"] = oc.get("price")
        if all(k in px and px[k] is not None for k in ("home", "away", "draw")):
            pairs[book] = px
    return pairs


def scan(sport_key, thresholds, min_books):
    outcomes = _outcomes(sport_key)
    boards = _closing_board_per_game(sport_key)
    picks = {t: [] for t in thresholds}
    arbs = []
    n_games = 0

    for gk, ev in boards.items():
        result = outcomes.get(gk)
        if result is None:
            continue
        n_games += 1
        pairs = _three_way_pairs(ev, gk[1], gk[2])
        if len(pairs) < min_books:
            continue

        best_imp_sum = 0.0
        for side in ("home", "away", "draw"):
            # per-book fair prob of this side (side first, others after)
            side_pairs = {b: (px[side], *[px[s] for s in ("home", "away", "draw") if s != side])
                          for b, px in pairs.items()}
            fair_by_book = per_book_fair(side_pairs)
            if len(fair_by_book) < min_books:
                continue
            # best (longest) price for this side among non-sharp books
            best_price = best_book = None
            for b, px in pairs.items():
                if b in NON_DESTINATION:
                    continue
                p = px[side]
                if best_price is None or implied(p) < implied(best_price):
                    best_price, best_book = p, b
            if best_price is None:
                continue
            best_imp_sum += implied(best_price)
            cons = loo_consensus(fair_by_book, exclude=best_book, min_books=min_books)
            if cons is None:
                continue
            cons_p, _n = cons
            imp = implied(best_price)
            if imp <= 0:
                continue
            ev_pct = (cons_p / imp - 1.0) * 100.0
            won = (side == result)
            profit = (_decimal(best_price) if won else -1.0)
            for t in thresholds:
                if ev_pct >= t:
                    picks[t].append({"game": f"{gk[2]} @ {gk[1]}", "side": side,
                                     "book": best_book, "price": int(best_price),
                                     "ev": round(ev_pct, 1), "won": won,
                                     "profit": round(profit, 3)})
        # 3-way arb: best price each side, summed implied < 1 → guaranteed
        if best_imp_sum and best_imp_sum < 1.0:
            arbs.append({"game": f"{gk[1]} v {gk[2]}", "margin_pct": round((1 - best_imp_sum) * 100, 2)})
    return {"sport": sport_key, "n_games": n_games, "picks": picks, "arbs": arbs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thresholds", default="2,3,5")
    ap.add_argument("--min-books", type=int, default=3)
    a = ap.parse_args()
    thresholds = [float(x) for x in a.thresholds.split(",")]
    out = {}
    for lg in LEAGUES:
        r = scan(lg, thresholds, a.min_books)
        out[lg] = r
        print("=" * 66)
        print(f"  {lg} — {r['n_games']} games with a closing board")
        for t in thresholds:
            ps = r["picks"][t]
            if not ps:
                print(f"    EV≥{t}%: no +EV outliers")
                continue
            tot = sum(p["profit"] for p in ps)
            wr = sum(p["won"] for p in ps) / len(ps)
            print(f"    EV≥{t}%: {len(ps)} bets @close | realized ROI {100*tot/len(ps):+.1f}% "
                  f"({tot:+.2f}u, win {wr:.2f})")
        print(f"    arbs at close: {len(r['arbs'])}"
              + (f" (best {max(x['margin_pct'] for x in r['arbs']):.2f}%)" if r["arbs"] else ""))
        # show a few EV≥2 picks
        for p in sorted(r["picks"][thresholds[0]], key=lambda x: -x["ev"])[:5]:
            print(f"      {p['game']:34s} {p['side']:5s} {p['book']:14s} @{p['price']:+d} "
                  f"EV{p['ev']:+.1f}% {'W' if p['won'] else 'L'} {p['profit']:+.2f}u")
    Path("data/models/soccer_club_consensus_close.json").write_text(json.dumps(out, indent=2, default=str))
    print("=" * 66)
    print("  wrote data/models/soccer_club_consensus_close.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

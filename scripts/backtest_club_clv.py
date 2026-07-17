"""
Closing-line backtest for the club soccer models (MLS, Liga MX).

The definitive "do we beat the book?" test. For each historical club game in a
window it:

  1. Prices the game with the model using CAUSAL ratings (only prior matches) and
     params fit only on data BEFORE the window — no training-set lookahead.
  2. Fetches the real CLOSING odds board (~kickoff) from The Odds API historical
     endpoint, de-vigs the 3-way market.
  3. Scores two things:
       • ACCURACY vs the closing line — model log-loss/Brier vs the closing
         line's own implied-probability log-loss/Brier on the same games. If the
         model is more accurate than the sharpest available line, it has genuine
         edge (CLV is just a proxy for this).
       • PROFIT at the close — simulate flat-betting the model's anchored
         moneyline edges AT THE CLOSING price (the worst price you'd ever get)
         and compute ROI from actual results. Profit here ⇒ profit earlier.

Closing boards only ⇒ ~half the credits of a full open+close CLV run. Historical
calls cost 10 credits each; boards are cached, and the run is credit-capped.

Usage:
    python3 scripts/backtest_club_clv.py --start 2026-05-04 --end 2026-05-24 --dry-run
    python3 scripts/backtest_club_clv.py --start 2026-05-04 --end 2026-05-24 --max-credits 400
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(str(Path(__file__).resolve().parents[1] / ".env"))

from src.data.soccer_club_data import load_club_matches, normalize_club_team_name
from src.models.soccer_club_model import SoccerClubModel
from src.models.soccer_model_v2 import _american_to_imp

API_BASE = "https://api.the-odds-api.com/v4"
CACHE = Path("data/clv/backtest_cache")
EDGE_THRESHOLD = 3.0   # anchored moneyline edge % to "bet" in the simulation
CLOSE_MIN_BEFORE = 20  # minutes before kickoff = "closing" board


def _round_ts(dt: datetime, minutes: int = 30) -> datetime:
    """Round down to a `minutes` grid so nearby kickoffs share one board call."""
    m = (dt.minute // minutes) * minutes
    return dt.replace(minute=m, second=0, microsecond=0)


def _fetch_board(sport_key: str, iso_ts: str, key: str) -> dict | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{sport_key}_{iso_ts.replace(':', '')}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    r = requests.get(f"{API_BASE}/historical/sports/{sport_key}/odds",
                     params={"apiKey": key, "date": iso_ts, "regions": "us",
                             "markets": "h2h", "oddsFormat": "american"}, timeout=30)
    if r.status_code != 200:
        print(f"    [api] {sport_key} @ {iso_ts} -> {r.status_code}")
        return None
    data = r.json()
    cache.write_text(json.dumps(data))
    return data


def _novig_3way(outcomes: list[dict], home: str, away: str):
    """De-vig a 3-way h2h market → {home,away,'Draw': prob} and picked prices."""
    prices = {}
    for o in outcomes:
        prices[o.get("name", "")] = float(o.get("price", 0))
    keys = [home, away, "Draw"]
    if not all(k in prices and prices[k] for k in keys):
        return None, None
    imps = {k: _american_to_imp(prices[k]) for k in keys}
    tot = sum(imps.values())
    if tot <= 0:
        return None, None
    return {k: imps[k] / tot for k in keys}, prices


def _build_causal(sport_key: str, window_start, window_end):
    """Fit params on pre-window matches, then price each in-window game from its
    causal rolling snapshot. Returns {(date,home,away): (probs, outcome, exp_total)}."""
    allm = sorted(load_club_matches(sport_key), key=lambda x: x["date"])
    train = [m for m in allm if m["date"] < window_start]
    if len(train) < 200:
        raise SystemExit(f"Not enough pre-window data for {sport_key} ({len(train)}).")
    m = SoccerClubModel(sport_key)
    m.fit(verbose=False, _matches=train)

    m2 = SoccerClubModel(sport_key)
    m2.k_factor, m2.xg_sot, m2.xg_off = m.k_factor, m.xg_sot, m.xg_off
    snaps = m2._compute_rolling_elo(allm)
    for a in ("mu", "alpha", "beta", "delta", "gamma", "c_alt", "c_travel",
              "c_rest", "rho", "temperature", "tempo_shrink", "league_avg"):
        setattr(m2, a, getattr(m, a))

    priced = {}
    for i, mt in enumerate(allm):
        if not (window_start <= mt["date"] <= window_end):
            continue
        eh, ea, ah, da, aa, dh, *_ = snaps[i]
        h, a = mt["home_team"], mt["away_team"]
        m2.elo_ratings[h], m2.elo_ratings[a] = eh, ea
        m2.atk_ratings[h], m2.dfn_ratings[h] = ah, dh
        m2.atk_ratings[a], m2.dfn_ratings[a] = aa, da
        r = m2.matchup(h, a, neutral=False)
        o = 0 if mt["home_score"] > mt["away_score"] else (
            1 if mt["home_score"] == mt["away_score"] else 2)
        priced[(mt["date"], h, a)] = ({h: r["home_win"], "Draw": r["draw"],
                                       a: r["away_win"]}, o, r["exp_total"],
                                      mt.get("kickoff"))
    return priced, m2.ANCHOR_MODEL_WEIGHT


def run(sport_key: str, start, end, key, dry_run, credit_budget):
    priced, w = _build_causal(sport_key, start, end)
    print(f"  [{sport_key}] {len(priced)} in-window games priced (causal).")

    # Target the true PRE-GAME closing board per game: the board at
    # kickoff - 30min (floored to a 30-min grid so nearby kickoffs share a call).
    # Guessing the time instead captures IN-PLAY odds (extreme prices, artificially
    # low log-loss) — the bug this replaced.
    close_ts: dict[tuple, str] = {}
    slots: set[str] = set()
    for gkey, (_mp, _o, _et, kick) in priced.items():
        if kick is None:
            continue
        ct = _round_ts(kick - timedelta(minutes=30), 30)
        iso = ct.strftime("%Y-%m-%dT%H:%M:%SZ")
        close_ts[gkey] = iso
        slots.add(iso)
    ts_list = sorted(slots)
    est_credits = len(ts_list) * 10
    print(f"  [{sport_key}] {len(ts_list)} pre-game closing timestamps → ~{est_credits} credits")
    if dry_run:
        return {"sport": sport_key, "games": len(priced), "timestamps": len(ts_list),
                "est_credits": est_credits, "dry_run": True}

    # Fetch each closing board (credit-capped, cached).
    board_by_ts: dict[str, dict] = {}
    used = 0
    for ts in ts_list:
        if credit_budget is not None and used >= credit_budget:
            print(f"  [{sport_key}] hit credit budget ({credit_budget}); stopping fetch.")
            break
        was_cached = (CACHE / f"{sport_key}_{ts.replace(':', '')}.json").exists()
        data = _fetch_board(sport_key, ts, key)
        if not was_cached and data is not None:
            used += 10  # only real API calls (cache miss) cost credits
        if data:
            board_by_ts[ts] = data

    def _find_event(data, h, a):
        for ev in data.get("data", []):
            if (normalize_club_team_name(ev.get("home_team", "")) == h
                    and normalize_club_team_name(ev.get("away_team", "")) == a):
                return ev
        return None

    # Score.
    n = 0
    ll_m = ll_k = 0.0
    bri_m = bri_k = 0.0
    picks = []
    for (d, h, a), (mp, o, _et, kick) in priced.items():
        iso = close_ts.get((d, h, a))
        data = board_by_ts.get(iso) if iso else None
        if not data:
            continue
        # Guard: the snapshot must be pre-kickoff (else it's in-play).
        try:
            snap_dt = datetime.fromisoformat(data.get("timestamp", "").replace("Z", "+00:00"))
            if kick is not None and snap_dt >= kick:
                continue
        except (ValueError, AttributeError):
            pass
        ev = _find_event(data, h, a)
        if ev is None:
            continue
        # pick the h2h market from the first book that has all 3 (per-book de-vig
        # is standard; we then take the best price across books for the bet side)
        market_probs = None
        best_price = {h: None, a: None, "Draw": None}
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                nv, prices = _novig_3way(mk.get("outcomes", []), h, a)
                if nv is None:
                    continue
                if market_probs is None:
                    market_probs = {k: [] for k in (h, a, "Draw")}
                for k in (h, a, "Draw"):
                    market_probs[k].append(nv[k])
                    p = prices[k]
                    if best_price[k] is None or _american_to_imp(p) < _american_to_imp(best_price[k]):
                        best_price[k] = p  # best (longest) price for the bettor
        if not market_probs:
            continue
        # consensus market prob = mean across books
        mk_prob = {k: sum(v) / len(v) for k, v in market_probs.items()}
        n += 1
        # accuracy: model vs closing-line (consensus) as predictors
        outc = (h, "Draw", a)[o]
        ll_m += -math.log(max(mp[outc], 1e-12))
        ll_k += -math.log(max(mk_prob[outc], 1e-12))
        bri_m += sum((mp[k] - (1 if k == outc else 0)) ** 2 for k in (h, a, "Draw"))
        bri_k += sum((mk_prob[k] - (1 if k == outc else 0)) ** 2 for k in (h, a, "Draw"))
        # simulate anchored edges at the CLOSING price
        for side in (h, a, "Draw"):
            anchored = w * mp[side] + (1 - w) * mk_prob[side]
            edge = (anchored - mk_prob[side]) * 100
            price = best_price[side]
            # Sanity: ignore absurd prices (data errors / any in-play remnant).
            if edge >= EDGE_THRESHOLD and price and abs(price) <= 5000:
                won = (side == outc)
                dec = (price / 100.0) if price > 0 else (100.0 / abs(price))
                profit = dec if won else -1.0
                picks.append({"game": f"{a} @ {h}", "side": side, "edge": round(edge, 1),
                              "price": int(price), "won": won, "profit": round(profit, 3)})

    res = {"sport": sport_key, "games_scored": n, "n_picks": len(picks)}
    if n:
        res.update(model_logloss=round(ll_m / n, 4), close_logloss=round(ll_k / n, 4),
                   model_brier=round(bri_m / n, 4), close_brier=round(bri_k / n, 4))
    if picks:
        tot = sum(p["profit"] for p in picks)
        res.update(units_staked=len(picks), units_profit=round(tot, 2),
                   roi_pct=round(100 * tot / len(picks), 2),
                   win_rate=round(sum(p["won"] for p in picks) / len(picks), 3))
    res["credits_used"] = used
    res["_picks"] = picks
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-credits", type=int, default=None)
    ap.add_argument("--leagues", default="soccer_usa_mls,soccer_mexico_ligamx")
    a = ap.parse_args()
    start = datetime.fromisoformat(a.start).date()
    end = datetime.fromisoformat(a.end).date()
    key = os.environ.get("ODDS_API_KEY")
    if not a.dry_run and not key:
        raise SystemExit("No ODDS_API_KEY — cannot fetch historical odds.")

    out = {}
    budget = a.max_credits
    for lg in a.leagues.split(","):
        print("=" * 66)
        r = run(lg, start, end, key, a.dry_run, budget)
        if budget is not None and "credits_used" in r:
            budget -= r["credits_used"]
        out[lg] = r
        if not a.dry_run:
            picks = r.pop("_picks", [])
            print(f"  [{lg}] scored {r.get('games_scored',0)} games | "
                  f"model logloss {r.get('model_logloss','–')} vs close {r.get('close_logloss','–')}")
            if r.get("n_picks"):
                print(f"    SIM: {r['n_picks']} bets @close, ROI {r['roi_pct']}%  "
                      f"({r['units_profit']:+}u, win {r['win_rate']})")
                for p in sorted(picks, key=lambda x: -x['edge'])[:8]:
                    print(f"      {p['game']:34s} {p['side']:20s} edge {p['edge']:+.1f}% "
                          f"@{p['price']:+d}  {'W' if p['won'] else 'L'} {p['profit']:+.2f}u")
        else:
            print(f"  [{lg}] DRY: {r['games']} games, {r['timestamps']} calls, ~{r['est_credits']} credits")

    if not a.dry_run:
        Path("data/models/soccer_club_backtest.json").write_text(json.dumps(out, indent=2, default=str))
        print("=" * 66)
        print("  wrote data/models/soccer_club_backtest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

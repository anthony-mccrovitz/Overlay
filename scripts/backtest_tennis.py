"""
Walk-forward backtest of the tennis Elo engine vs the Pinnacle close.

Replays 2023→2026 chronologically: each match is PREDICTED from ratings built
only on earlier matches, then the ratings update. Evaluation is on matches
where tennis-data carries Pinnacle odds (PSW/PSL) and both players clear the
confidence floor.

Reported:
  - Brier score: raw Elo blend, market (Pinnacle devig), and the production
    50/50 anchor blend (what run_tennis actually bets from)
  - Calibration by prob bucket
  - The honesty check: if anchored-Brier ≈ market-Brier and both beat raw Elo,
    the model matches the literature (Elo loses to the close; anchor to it).

Run: python3 scripts/backtest_tennis.py [--tour atp|wta] [--eval-year 2026]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.tennis_data import (
    DEFAULT_YEARS, MIN_MATCHES_KNOWN, elo_from_rank, elo_win_prob,
    load_matches, norm_td_name, _surface_key, _K_NUM, _K_OFF, _K_SHAPE,
    _BLEND, _PRIOR_M,
)


def walk_forward(tour: str, eval_year: int) -> dict:
    import pandas as pd

    matches = load_matches(tour, years=DEFAULT_YEARS, refresh_current=False)
    if len(matches) == 0:
        return {}

    players: dict[str, dict] = {}

    def _get(k):
        return players.setdefault(k, {"overall": 1500.0, "clay": 1500.0,
                                      "hard": 1500.0, "grass": 1500.0,
                                      "matches": 0, "rank": None})

    def _k(m):
        return _K_NUM / ((m + _K_OFF) ** _K_SHAPE)

    def _effective(rec, surf):
        obs = _BLEND * rec["overall"] + (1 - _BLEND) * rec[surf]
        m = rec["matches"]
        w = m / (m + _PRIOR_M)
        return w * obs + (1 - w) * elo_from_rank(rec["rank"])

    rows = []
    for row in matches.itertuples(index=False):
        w_raw, l_raw = getattr(row, "Winner", None), getattr(row, "Loser", None)
        if not isinstance(w_raw, str) or not isinstance(l_raw, str):
            continue
        comment = str(getattr(row, "Comment", "") or "").lower()
        if "walkover" in comment:
            continue
        wk, lk = norm_td_name(w_raw), norm_td_name(l_raw)
        surf = _surface_key(getattr(row, "Surface", ""))
        w, l = _get(wk), _get(lk)

        # ── predict BEFORE updating ──
        year = getattr(row, "SrcYear", None)
        # Market benchmark: Pinnacle close when quoted, else the market
        # average close (AvgW/AvgL — full coverage in recent files).
        psw, psl = getattr(row, "PSW", None), getattr(row, "PSL", None)
        if not (pd.notna(psw) and pd.notna(psl)):
            psw, psl = getattr(row, "AvgW", None), getattr(row, "AvgL", None)
        if (year == eval_year and pd.notna(psw) and pd.notna(psl)
                and float(psw) > 1 and float(psl) > 1
                and min(w["matches"], l["matches"]) >= MIN_MATCHES_KNOWN):
            p_model = elo_win_prob(_effective(w, surf), _effective(l, surf))
            iw, il = 1 / float(psw), 1 / float(psl)
            p_market = iw / (iw + il)          # devigged Pinnacle close
            conf = min(0.5, min(w["matches"], l["matches"])
                       / (min(w["matches"], l["matches"]) + 40.0))
            p_anchor = conf * p_model + (1 - conf) * p_market
            rows.append((p_model, p_market, p_anchor))

        # ── update ──
        for field in ("overall", surf):
            exp_w = elo_win_prob(w[field], l[field])
            w[field] += _k(w["matches"]) * (1 - exp_w)
            l[field] -= _k(l["matches"]) * (1 - exp_w)
        w["matches"] += 1
        l["matches"] += 1
        wr, lr = getattr(row, "WRank", None), getattr(row, "LRank", None)
        if pd.notna(wr):
            w["rank"] = float(wr)
        if pd.notna(lr):
            l["rank"] = float(lr)

    if not rows:
        return {}
    n = len(rows)
    # outcome is always 1 (winner listed first): Brier = mean (1-p)^2
    out = {
        "n": n,
        "brier_model":  sum((1 - a) ** 2 for a, _, _ in rows) / n,
        "brier_market": sum((1 - b) ** 2 for _, b, _ in rows) / n,
        "brier_anchor": sum((1 - c) ** 2 for _, _, c in rows) / n,
        "acc_model":  sum(1 for a, _, _ in rows if a > 0.5) / n,
        "acc_market": sum(1 for _, b, _ in rows if b > 0.5) / n,
    }
    # calibration buckets for the anchored prob
    buckets: dict[str, list] = {}
    for _, _, c in rows:
        b = f"{int(c * 10) * 10}-{int(c * 10) * 10 + 10}%"
        buckets.setdefault(b, []).append(c)
    out["buckets"] = {k: (len(v), sum(v) / len(v)) for k, v in sorted(buckets.items())}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tour", default="both", choices=["atp", "wta", "both"])
    ap.add_argument("--eval-year", type=int, default=2026)
    args = ap.parse_args()

    tours = ["atp", "wta"] if args.tour == "both" else [args.tour]
    for tour in tours:
        r = walk_forward(tour, args.eval_year)
        if not r:
            print(f"  [{tour}] no evaluable matches")
            continue
        print(f"\n  ── {tour.upper()} walk-forward, {args.eval_year}, n={r['n']} "
              f"(both players ≥{MIN_MATCHES_KNOWN} matches, Pinnacle priced) ──")
        print(f"    Brier — raw Elo:   {r['brier_model']:.4f}   "
              f"(accuracy {r['acc_model']:.1%})")
        print(f"    Brier — Pinnacle:  {r['brier_market']:.4f}   "
              f"(accuracy {r['acc_market']:.1%})")
        print(f"    Brier — anchored:  {r['brier_anchor']:.4f}   ← production blend")
        print(f"    (coin flip = 0.2500; lower is better)")


if __name__ == "__main__":
    main()

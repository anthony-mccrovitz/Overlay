"""
Validate the NRFI v2 rebuild (offense-aware) against v1 (ERA/K9-only).

Builds a real historical dataset from MLB Stats API — for each completed game:
the first-inning outcome (from the linescore) + both starters' season ERA/K9 +
both teams' season OPS. Fits v2's coefficients on a temporal TRAIN split, then
compares v1 vs v2 on the held-out TEST split with the same test the tuning
ledger uses: does higher predicted P(NRFI) actually mean a higher NRFI rate?
(v1 failed this — its confidence was inverted.)

Usage: python3 scripts/validate_nrfi_v2.py [--days 30]
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.mlb_stats import (
    _cached_get, API_BASE, fetch_team_stats, fetch_pitcher_stats,
)
from src.data import nrfi as N


def _collect(days: int) -> list[dict]:
    """One row per completed game: features + NRFI outcome."""
    rows: list[dict] = []
    team_ops_cache: dict[int, dict[int, float]] = {}
    pit_cache: dict[int, tuple[float, float]] = {}
    today = date.today()
    for off in range(2, 2 + days):
        d = (today - timedelta(days=off)).isoformat()
        data = _cached_get(f"nrfi_hist_{d}", f"{API_BASE}/schedule",
                           {"sportId": 1, "date": d,
                            "hydrate": "linescore,probablePitcher,team"},
                           max_age_s=999999)
        season = int(d[:4])
        if season not in team_ops_cache:
            team_ops_cache[season] = {
                tid: ts.ops for tid, ts in fetch_team_stats(season).items()}
        team_ops = team_ops_cache[season]

        for day in data.get("dates", []):
            for g in day.get("games", []):
                ls = g.get("linescore", {})
                innings = ls.get("innings", [])
                if not innings:
                    continue
                first = innings[0]
                a1 = first.get("away", {}).get("runs")
                h1 = first.get("home", {}).get("runs")
                if a1 is None or h1 is None:
                    continue
                nrfi = 1 if (a1 == 0 and h1 == 0) else 0

                home, away = g["teams"]["home"], g["teams"]["away"]
                hp = home.get("probablePitcher", {}) or {}
                ap = away.get("probablePitcher", {}) or {}
                if not hp.get("id") or not ap.get("id"):
                    continue

                def _pit(pid):
                    if pid not in pit_cache:
                        ps = fetch_pitcher_stats(pid, season)
                        era = ps.era if ps and ps.era else N._LEAGUE_AVG_ERA
                        k9 = ps.k_per_9 if ps and ps.k_per_9 else N._LEAGUE_AVG_K9
                        pit_cache[pid] = (era, k9)
                    return pit_cache[pid]

                h_era, h_k9 = _pit(hp["id"])
                a_era, a_k9 = _pit(ap["id"])
                h_ops = team_ops.get(home["team"]["id"], N._LEAGUE_AVG_OPS) or N._LEAGUE_AVG_OPS
                a_ops = team_ops.get(away["team"]["id"], N._LEAGUE_AVG_OPS) or N._LEAGUE_AVG_OPS
                rows.append({
                    "date": d, "h_era": h_era, "h_k9": h_k9, "a_era": a_era,
                    "a_k9": a_k9, "h_ops": h_ops, "a_ops": a_ops, "nrfi": nrfi,
                })
    rows.sort(key=lambda r: r["date"])
    return rows


def _logloss(rows, params) -> float:
    tot = 0.0
    for r in rows:
        p = N.project_nrfi_v2(r["h_era"], r["h_k9"], r["a_era"], r["a_k9"],
                              r["h_ops"], r["a_ops"], params=params)
        p = min(max(p, 1e-6), 1 - 1e-6)
        tot += -(r["nrfi"] * math.log(p) + (1 - r["nrfi"]) * math.log(1 - p))
    return tot / len(rows)


def _fit(rows) -> dict:
    """Fit v2 coefficients by minimizing NRFI log-loss (scipy L-BFGS-B)."""
    from scipy.optimize import minimize
    keys = ["base_lambda", "era_coef", "k9_coef", "off_gamma"]
    x0 = [N._V2[k] for k in keys]
    bounds = [(0.05, 0.5), (0.0, 0.2), (0.0, 0.1), (0.0, 3.0)]

    def obj(x):
        p = dict(N._V2, **{k: v for k, v in zip(keys, x)})
        return _logloss(rows, p)

    res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds)
    return dict(N._V2, **{k: v for k, v in zip(keys, res.x)})


def _signal(rows, predict) -> str:
    """Confidence test: bucket by predicted P(NRFI), report NRFI rate per bucket."""
    scored = sorted(((predict(r), r["nrfi"]) for r in rows), key=lambda t: t[0])
    n = len(scored)
    size = n // 3
    out = []
    for b in range(3):
        chunk = scored[b * size: n if b == 2 else (b + 1) * size]
        rate = sum(o for _, o in chunk) / len(chunk) * 100
        out.append((round(chunk[0][0], 3), round(chunk[-1][0], 3), len(chunk), round(rate, 1)))
    spread = out[-1][3] - out[0][3]
    return out, round(spread, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=40)
    args = ap.parse_args()

    print(f"Collecting completed games from the last {args.days} days...")
    rows = _collect(args.days)
    base = sum(r["nrfi"] for r in rows) / len(rows) * 100 if rows else 0
    print(f"  {len(rows)} games, NRFI base rate {base:.1f}%")
    if len(rows) < 120:
        print("  Too few games to validate — increase --days.")
        return 1

    cut = int(len(rows) * 0.7)
    train, test = rows[:cut], rows[cut:]
    print(f"  train={len(train)}  test={len(test)} (temporal split)")

    fitted = _fit(train)
    print("\nFitted v2 params:", {k: round(v, 4) for k, v in fitted.items() if k != "lg_ops"})

    v1 = lambda r: N.project_nrfi_v1(r["h_era"], r["h_k9"], r["a_era"], r["a_k9"])
    v2 = lambda r: N.project_nrfi_v2(r["h_era"], r["h_k9"], r["a_era"], r["a_k9"],
                                     r["h_ops"], r["a_ops"], params=fitted)

    print("\n── HELD-OUT confidence test (higher predicted NRFI → higher actual NRFI rate?) ──")
    for name, pred in (("v1 (ERA/K9 only)", v1), ("v2 (offense-aware)", v2)):
        buckets, spread = _signal(test, pred)
        bs = "  ".join(f"[{lo:.2f}-{hi:.2f}] n={n} {rate:.0f}%" for lo, hi, n, rate in buckets)
        verdict = ("REAL signal" if spread >= 8 else "inverted" if spread <= -4 else "flat")
        print(f"  {name:20s} spread={spread:+.1f}pts  {verdict}")
        print(f"    {bs}")

    print("\n── log-loss on held-out test (lower = better calibrated) ──")
    ll1 = sum(-(r['nrfi']*math.log(min(max(v1(r),1e-6),1-1e-6)) +
                (1-r['nrfi'])*math.log(1-min(max(v1(r),1e-6),1-1e-6))) for r in test)/len(test)
    ll2 = _logloss(test, fitted)
    print(f"  v1: {ll1:.4f}    v2: {ll2:.4f}    Δ={ll1-ll2:+.4f}")
    print("\nParams to paste into nrfi._V2 if v2 wins:")
    print("  " + str({k: round(v, 4) for k, v in fitted.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

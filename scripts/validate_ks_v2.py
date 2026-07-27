"""
Validate the pitcher_strikeouts v2 rebuild against v1.

v1's structural bugs: a FIXED 5.5 innings for every pitcher, and a Poisson
distribution. This harness tests both on real per-start data (MLB Stats API
game logs — actual Ks + actual IP per start):

  1. INNINGS: does using each pitcher's own avg IP/start beat fixed 5.5 at
     predicting actual strikeouts? (v1 under-projects aces who pitch deep →
     wrongly pushes them UNDER.)
  2. DISPERSION: is the variance of per-start Ks > the mean? (If so, Poisson is
     wrong and overconfident; negative binomial is the honest choice.)

Usage: python3 scripts/validate_ks_v2.py [--pitchers 80]
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.mlb_stats import _cached_get, API_BASE


def _pitcher_ids(days: int) -> set[int]:
    ids: set[int] = set()
    today = date.today()
    for off in range(2, 2 + days):
        d = (today - timedelta(days=off)).isoformat()
        data = _cached_get(f"nrfi_hist_{d}", f"{API_BASE}/schedule",
                           {"sportId": 1, "date": d,
                            "hydrate": "linescore,probablePitcher,team"},
                           max_age_s=999999)
        for day in data.get("dates", []):
            for g in day.get("games", []):
                for side in ("home", "away"):
                    pp = g["teams"][side].get("probablePitcher") or {}
                    if pp.get("id"):
                        ids.add(pp["id"])
    return ids


def _starts(pid: int, season: int) -> list[dict]:
    data = _cached_get(f"pitcher_log_{pid}_{season}",
                       f"{API_BASE}/people/{pid}/stats",
                       {"stats": "gameLog", "group": "pitching", "season": season},
                       max_age_s=999999)
    out = []
    for grp in data.get("stats", []):
        for sp in grp.get("splits", []):
            s = sp.get("stat", {})
            try:
                if int(float(s.get("gamesStarted", 0))) < 1:
                    continue
                ip = float(s.get("inningsPitched", 0))
                k = float(s.get("strikeOuts", 0))
            except (TypeError, ValueError):
                continue
            if ip >= 0.1:
                out.append({"ip": ip, "k": k})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitchers", type=int, default=120)
    ap.add_argument("--days", type=int, default=25)
    args = ap.parse_args()
    season = date.today().year

    ids = list(_pitcher_ids(args.days))[: args.pitchers]
    print(f"Fetching game logs for {len(ids)} starting pitchers...")

    rows = []          # one per start: actual k + the pitcher's season features
    all_ks = []
    for pid in ids:
        starts = _starts(pid, season)
        if len(starts) < 5:
            continue
        tot_ip = sum(s["ip"] for s in starts)
        tot_k = sum(s["k"] for s in starts)
        if tot_ip < 20:
            continue
        k9 = tot_k * 9 / tot_ip
        avg_ip = tot_ip / len(starts)
        for s in starts:
            rows.append({"k": s["k"], "k9": k9, "avg_ip": avg_ip})
            all_ks.append(s["k"])

    if len(rows) < 200:
        print(f"  Only {len(rows)} starts — too few. Increase --pitchers/--days.")
        return 1
    print(f"  {len(rows)} pitcher-starts collected.\n")

    # ── Hypothesis 1: modeled innings vs fixed 5.5 (prediction MAE) ──
    def mae(pred):
        return statistics.mean(abs(pred(r) - r["k"]) for r in rows)
    v1 = lambda r: r["k9"] / 9 * 5.5
    v2 = lambda r: r["k9"] / 9 * r["avg_ip"]
    print("── INNINGS (predict actual Ks) ──")
    print(f"  v1 fixed 5.5 IP:   MAE = {mae(v1):.3f} Ks")
    print(f"  v2 modeled IP:     MAE = {mae(v2):.3f} Ks")
    print(f"  avg IP/start range: {min(r['avg_ip'] for r in rows):.1f}–"
          f"{max(r['avg_ip'] for r in rows):.1f} (fixed 5.5 ignores this)\n")

    # ── Hypothesis 2: overdispersion (Poisson assumes var == mean) ──
    mean_k = statistics.mean(all_ks)
    var_k = statistics.pvariance(all_ks)
    print("── DISPERSION (per-start Ks) ──")
    print(f"  mean = {mean_k:.2f}   variance = {var_k:.2f}   "
          f"var/mean = {var_k / mean_k:.2f}")
    print(f"  → {'OVERDISPERSED — Poisson is overconfident, use neg-binom' if var_k > mean_k * 1.15 else 'roughly Poisson'}")

    # ── Hypothesis 2b: does neg-binom CALIBRATE better in the TAILS? ──
    # The model BETS when the line is far from the projection (big edge) — that's
    # where Poisson vs neg-binom diverge. Test P(over) at deep-tail lines (±2 Ks
    # from the projection), which is where v1's fake edges and losses came from.
    from src.data.player_props import _poisson_over, _nbinom_over
    for label, offset in (("near mean (±0)", 0), ("tail (−2, bet OVER)", -2),
                          ("tail (+2, bet UNDER)", 2)):
        bp = bn = 0.0; n = 0
        for r in rows:
            mu = r["k9"] / 9 * r["avg_ip"]
            line = int(mu) + offset + 0.5
            if line < 0.5:
                continue
            outcome = 1.0 if r["k"] > line else 0.0
            bp += (_poisson_over(mu, line) - outcome) ** 2
            bn += (_nbinom_over(mu, line) - outcome) ** 2
            n += 1
        print(f"\n── CALIBRATION Brier @ {label} (n={n}) ──")
        print(f"  Poisson {bp/n:.4f}   NegBinom {bn/n:.4f}   Δ={(bp-bn)/n:+.5f}"
              f"   → v2 {'better' if bn < bp else 'not better'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

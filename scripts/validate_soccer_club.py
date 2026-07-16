"""
Walk-forward validation for the club soccer models (MLS, Liga MX).

Honest out-of-sample test: fit on the earlier chronological split, freeze the
model (params + data-derived temperature), then predict each match in the later
split from a causal rolling snapshot (only prior matches). Scores multiclass
1X2 Brier + log-loss + modal accuracy and O/U-2.5 Brier against a base-rate
predictor built from the TRAIN split. Also sweeps the Elo K-factor.

Predictions use rest_diff=0 (matches production, where an upcoming fixture's rest
is not plumbed through) — so the rest coefficient is a training-fit term only;
altitude and travel ARE applied at prediction from the static venue table.

Run:  python3 scripts/validate_soccer_club.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.soccer_club_data import load_club_matches
from src.models.soccer_club_model import SoccerClubModel

LEAGUES = ["soccer_usa_mls", "soccer_mexico_ligamx"]
TRAIN_FRAC = 0.70
# v1 baseline (rolling Elo + goals tempo, no context/xG/regression/calibration).
V1 = {
    "soccer_usa_mls":       {"brier": 0.6272, "logloss": 1.0439, "acc": 0.4687},
    "soccer_mexico_ligamx": {"brier": 0.5855, "logloss": 0.9840, "acc": 0.5599},
}


def _o(hs, as_):
    return 0 if hs > as_ else (1 if hs == as_ else 2)


def score(sport_key: str, k_factor: float) -> dict:
    matches = sorted(load_club_matches(sport_key), key=lambda x: x["date"])
    n = len(matches)
    split = int(n * TRAIN_FRAC)
    train, test = matches[:split], matches[split:]

    m = SoccerClubModel(sport_key)
    m.k_factor = k_factor
    m.fit(verbose=False, _matches=train)  # calibrates T on an internal holdout
    frozen = dict(mu=m.mu, alpha=m.alpha, beta=m.beta, delta=m.delta, gamma=m.gamma,
                  c_alt=m.c_alt, c_travel=m.c_travel, c_rest=m.c_rest, rho=m.rho,
                  temperature=m.temperature, tempo_shrink=m.tempo_shrink,
                  league_avg=m.league_avg, xg_sot=m.xg_sot, xg_off=m.xg_off)

    tr_h = sum(1 for x in train if x["home_score"] > x["away_score"]) / len(train)
    tr_d = sum(1 for x in train if x["home_score"] == x["away_score"]) / len(train)
    tr_a = 1 - tr_h - tr_d
    tr_over = sum(1 for x in train if x["home_score"] + x["away_score"] > 2.5) / len(train)

    # Causal snapshots over the full sequence; predict test with frozen params.
    m2 = SoccerClubModel(sport_key)
    m2.k_factor = k_factor
    m2.xg_sot, m2.xg_off = frozen["xg_sot"], frozen["xg_off"]
    snapshots = m2._compute_rolling_elo(matches)
    for kf, v in frozen.items():
        setattr(m2, kf, v)

    bm = bn = lm = ln = 0.0
    boum = boun = 0.0
    correct = 0
    for i in range(split, n):
        mt = matches[i]
        eh, ea, ah, da, aa, dh, *_ = snapshots[i]
        h, a = mt["home_team"], mt["away_team"]
        m2.elo_ratings[h], m2.elo_ratings[a] = eh, ea
        m2.atk_ratings[h], m2.dfn_ratings[h] = ah, dh
        m2.atk_ratings[a], m2.dfn_ratings[a] = aa, da
        r = m2.matchup(h, a, neutral=False)
        p = (r["home_win"], r["draw"], r["away_win"])
        o = _o(mt["home_score"], mt["away_score"])
        bm += sum((p[k] - (1 if k == o else 0)) ** 2 for k in range(3))
        bn += sum(((tr_h, tr_d, tr_a)[k] - (1 if k == o else 0)) ** 2 for k in range(3))
        lm += -math.log(max(p[o], 1e-12))
        ln += -math.log(max((tr_h, tr_d, tr_a)[o], 1e-12))
        if p.index(max(p)) == o:
            correct += 1
        over = 1 if mt["home_score"] + mt["away_score"] > 2.5 else 0
        boum += (r["over_2_5"] - over) ** 2
        boun += (tr_over - over) ** 2

    nt = len(test)
    return {
        "k": k_factor, "n_test": nt,
        "brier": round(bm / nt, 4), "brier_naive": round(bn / nt, 4),
        "logloss": round(lm / nt, 4), "logloss_naive": round(ln / nt, 4),
        "acc": round(correct / nt, 4),
        "brier_ou": round(boum / nt, 4), "brier_ou_naive": round(boun / nt, 4),
        "T": m.temperature,
        "params": {kk: round(getattr(m, kk), 3) for kk in
                   ("mu", "alpha", "beta", "delta", "gamma", "c_alt", "c_travel", "c_rest")},
    }


def main() -> int:
    out = {}
    for lg in LEAGUES:
        print("=" * 70)
        print(f"  {lg} — K sweep")
        sweep = [score(lg, k) for k in (16, 20, 24, 28, 32)]
        best = min(sweep, key=lambda s: s["logloss"])
        for s in sweep:
            flag = "  <== best" if s is best else ""
            print(f"    K={s['k']:>2.0f}  Brier {s['brier']}  LogLoss {s['logloss']}  "
                  f"acc {s['acc']}  T={s['T']:.2f}{flag}")
        v1 = V1[lg]
        print(f"  BEST K={best['k']:.0f}:")
        print(f"    1X2 Brier   {best['brier']}  (v1 {v1['brier']}, naive {best['brier_naive']})"
              f"  → Δv1 {v1['brier']-best['brier']:+.4f}")
        print(f"    1X2 LogLoss {best['logloss']} (v1 {v1['logloss']}, naive {best['logloss_naive']})"
              f"  acc {best['acc']} (v1 {v1['acc']})")
        print(f"    O/U Brier   {best['brier_ou']} (naive {best['brier_ou_naive']})"
              f"  → {'beats' if best['brier_ou']<best['brier_ou_naive'] else 'no edge vs'} naive")
        print(f"    params {best['params']}  T={best['T']}")
        out[lg] = {"best": best, "sweep": sweep, "v1": v1}

    Path("data/models/soccer_club_validation.json").write_text(json.dumps(out, indent=2))
    print("=" * 70)
    print("  wrote data/models/soccer_club_validation.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

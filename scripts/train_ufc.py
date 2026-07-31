#!/usr/bin/env python3
"""Train the UFC fight model walk-forward and write a readable artifact.

WHY WALK-FORWARD AND NOT A RANDOM SPLIT. A random k-fold on fight data leaks:
fold A contains a fighter's 2024 bout while fold B contains their 2019 bout, and
the 2019 row's features were built from a career that the 2024 row is part of.
The model learns who ends up good. Splitting by DATE removes that entirely —
every test fight is scored by a model that has seen nothing after it.

The reported numbers come from FIVE separate one-year holdouts, not one split,
because a single good year is a coin flip about a coin flip.

Usage:
    python3 scripts/train_ufc.py            # train, evaluate, write artifact
    python3 scripts/train_ufc.py --dry-run  # evaluate only, write nothing
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from src.models.ufc_features import FEATURES, Ledger, load_bouts

# Ignore the sport's first two decades when SCORING. Pre-2012 UFC was a
# different sport with a different talent distribution, and early ratings are
# unformed by construction. The bouts still feed the ledger — they are just not
# graded as if the model had a fair shot at them.
SCORE_FROM = 2012
# Both fighters need some UFC record for the features to mean anything. A debut
# is handled by a measured base rate at predict time, not by a fitted row here.
MIN_PRIOR_BOUTS = 2
# Ridge strength. 0.5 chosen on held-out log-loss; the surface is flat between
# 0.2 and 1.0, so this is not a tuned-to-death number.
C_REG = 0.5


def build_matrix() -> tuple[np.ndarray, np.ndarray, list[date], np.ndarray]:
    """Replay every bout, emitting one row per fight BEFORE folding it in.

    Orientation is alphabetical, not winner-first — otherwise the label is
    encoded in the row order and every model scores 100%.
    """
    bouts, stats, tott = load_bouts()
    led = Ledger(stats, tott)
    rows: list[list[float | None]] = []
    ys: list[int] = []
    dates: list[date] = []
    minprior: list[int] = []

    for b in bouts:
        a, z = (b["w"], b["l"]) if b["w"] < b["l"] else (b["l"], b["w"])
        rows.append(led.diff_vector(a, z, b["date"]))
        ys.append(1 if a == b["w"] else 0)
        dates.append(b["date"])
        minprior.append(min(led.state(a).n, led.state(z).n))
        led.apply_bout(b)          # ← state moves only after the row is emitted

    X = np.array([[np.nan if v is None else v for v in r] for r in rows], dtype=float)
    return X, np.array(ys), dates, np.array(minprior)


def _impute(A: np.ndarray, med: np.ndarray) -> np.ndarray:
    out = A.copy()
    for j in range(out.shape[1]):
        fill = med[j] if not np.isnan(med[j]) else 0.0
        out[np.isnan(out[:, j]), j] = fill
    return out


def _fit(Xtr, ytr):
    from sklearn.linear_model import LogisticRegression
    med = np.nanmedian(Xtr, axis=0)
    A = _impute(Xtr, med)
    mu, sd = A.mean(0), A.std(0)
    sd[sd == 0] = 1.0
    m = LogisticRegression(C=C_REG, max_iter=2000, fit_intercept=False)
    m.fit((A - mu) / sd, ytr)
    return m, med, mu, sd


def _score(m, med, mu, sd, Xte, yte) -> dict:
    from sklearn.metrics import log_loss, roc_auc_score
    p = m.predict_proba((_impute(Xte, med) - mu) / sd)[:, 1]
    return {"n": int(len(yte)),
            "log_loss": round(float(log_loss(yte, p)), 4),
            "accuracy": round(float(((p >= 0.5) == (yte == 1)).mean()), 4),
            "auc": round(float(roc_auc_score(yte, p)), 4)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="evaluate without writing")
    args = ap.parse_args()

    X, Y, dates, minprior = build_matrix()
    yr = np.array([d.year for d in dates])
    usable = (yr >= SCORE_FROM) & (minprior >= MIN_PRIOR_BOUTS)
    print(f"{len(Y)} bouts loaded; {int(usable.sum())} scoreable "
          f"({SCORE_FROM}+, both fighters ≥{MIN_PRIOR_BOUTS} prior UFC bouts)")

    print("\nWalk-forward — each year scored by a model that has not seen it:")
    folds = []
    for y in range(2021, max(yr) + 1):
        tr = (yr < y) & usable
        te = (yr == y) & usable
        if te.sum() < 50 or tr.sum() < 200:
            continue
        m, med, mu, sd = _fit(X[tr], Y[tr])
        s = _score(m, med, mu, sd, X[te], Y[te])
        folds.append({"test_year": int(y), **s})
        print(f"  {y}:  n={s['n']:4d}  log-loss={s['log_loss']:.4f}  "
              f"acc={s['accuracy']:.1%}  AUC={s['auc']:.3f}")

    if not folds:
        print("Not enough data to validate — refusing to write an unvalidated model.")
        return 1

    mean_acc = sum(f["accuracy"] for f in folds) / len(folds)
    mean_ll = sum(f["log_loss"] for f in folds) / len(folds)
    print(f"\n  mean across {len(folds)} holdout years: "
          f"acc={mean_acc:.1%}  log-loss={mean_ll:.4f}  (coin flip = {math.log(2):.4f})")

    if mean_ll >= math.log(2):
        print("Model is no better than a coin flip on held-out data — not writing.")
        return 1

    # Final artifact trains on everything; the honest scores above come from the
    # holdouts, and they are what gets recorded in the metadata.
    fit = usable
    m, med, mu, sd = _fit(X[fit], Y[fit])
    art = {
        "trained_on": date.today().isoformat(),
        "coefficients": {k: round(float(v), 6) for k, v in zip(FEATURES, m.coef_[0])},
        "feature_median": {k: (None if np.isnan(v) else round(float(v), 6))
                           for k, v in zip(FEATURES, med)},
        "feature_mean": {k: round(float(v), 6) for k, v in zip(FEATURES, mu)},
        "feature_sd": {k: round(float(v), 6) for k, v in zip(FEATURES, sd)},
        "metadata": {
            "n_train": int(fit.sum()),
            "walk_forward": folds,
            "mean_holdout_accuracy": round(mean_acc, 4),
            "mean_holdout_log_loss": round(mean_ll, 4),
            "coin_flip_log_loss": round(math.log(2), 4),
            "note": ("Scores are from year-by-year holdouts, never from the fit "
                     "above. Roughly market-level accuracy — this is a read on a "
                     "fight, not evidence of a betting edge."),
        },
    }
    # feature_median must not carry NaN into JSON; fall back to 0 where a feature
    # was never observed at all.
    art["feature_median"] = {k: (0.0 if v is None else v)
                             for k, v in art["feature_median"].items()}

    print("\nStandardised weights (magnitude = influence on the prediction):")
    for k, v in sorted(art["coefficients"].items(), key=lambda kv: -abs(kv[1])):
        print(f"  {k:8s} {v:+.3f}")

    if args.dry_run:
        print("\n--dry-run: artifact not written.")
        return 0

    out = Path("data/models/ufc/fight_model.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, indent=2, sort_keys=True))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

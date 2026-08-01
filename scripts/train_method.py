#!/usr/bin/env python3
"""Fit the method-of-victory model and SHIP IT ONLY IF IT EARNS ITS PLACE.

Walk-forward by year, exactly like scripts/train_ufc.py: fit on everything
before year Y, score year Y, never the reverse. The baseline it must beat is
the point-in-time league base rate — i.e. "36% KO, 24% sub, 40% decision, same
answer every fight", which is precisely what the retired simulator was doing
while presenting itself as a per-fight read.

If the fit does not beat that baseline on held-out years, the artifact is
DELETED and the card falls back to saying nothing. A method model that cannot
beat a constant is a constant with extra steps.

    python3 scripts/train_method.py
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.models.global_elo import load_global_bouts          # noqa: E402
from src.models.method_model import (                         # noqa: E402
    CLASSES, FEATURES, MethodLedger, classify_method,
)

ARTIFACT = Path("data/models/ufc/method_model.json")
HOLDOUT_YEARS = (2019, 2020, 2021, 2022, 2023, 2024, 2025)
MIN_FOLD_N = 200


def build_matrix() -> tuple[np.ndarray, np.ndarray, list[date]]:
    """One row per bout, emitted BEFORE that bout updates the ledger.

    Orientation is (winner, loser) in the source data, which would leak the
    result into any asymmetric feature — the reason every feature here is a
    symmetric function of the pair. The label is the method only.
    """
    led = MethodLedger()
    X: list[list[float]] = []
    y: list[int] = []
    dates: list[date] = []
    cls_idx = {c: i for i, c in enumerate(CLASSES)}

    for bt in load_global_bouts():
        cls = classify_method(bt.get("method", ""))
        if cls is not None:
            feats = led.features_for(bt["w"], bt["l"])
            if feats is not None:
                X.append([feats[k] for k in FEATURES])
                y.append(cls_idx[cls])
                dates.append(bt["date"])
        # State advances AFTER the row is emitted — always.
        led.apply_bout(bt["w"], bt["l"], bt.get("method", ""))

    return np.array(X, float), np.array(y, int), dates


def _fit(Xtr: np.ndarray, ytr: np.ndarray):
    from sklearn.linear_model import LogisticRegression
    mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
    sd[sd == 0] = 1.0
    clf = LogisticRegression(max_iter=2000, C=1.0)
    clf.fit((Xtr - mu) / sd, ytr)
    return clf, mu, sd


def _logloss(probs: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(probs[np.arange(len(y)), y], 1e-12, 1.0)
    return float(-np.log(p).mean())


def main() -> int:
    print("Building the method matrix from the global bout graph…")
    X, y, dates = build_matrix()
    print(f"  {len(X):,} bouts with a usable method and at least one rated fighter")
    dist = Counter(y)
    print("  class balance: " + ", ".join(
        f"{CLASSES[i]} {dist[i] / len(y) * 100:.1f}%" for i in range(len(CLASSES))))

    yr = np.array([d.year for d in dates])
    folds, model_ll, base_ll = [], [], []

    print("\nWalk-forward — fit on the past, score the year, never the reverse:")
    for year in HOLDOUT_YEARS:
        tr, te = yr < year, yr == year
        if te.sum() < MIN_FOLD_N or tr.sum() < 2000:
            continue
        clf, mu, sd = _fit(X[tr], y[tr])
        probs = clf.predict_proba((X[te] - mu) / sd)
        ll = _logloss(probs, y[te])

        # The baseline: the base rate as known BEFORE this year — the honest
        # version of "same answer every fight".
        prior = np.bincount(y[tr], minlength=len(CLASSES)) / tr.sum()
        bll = _logloss(np.tile(prior, (te.sum(), 1)), y[te])

        acc = float((probs.argmax(axis=1) == y[te]).mean())
        bacc = float((np.full(te.sum(), prior.argmax()) == y[te]).mean())
        folds.append({"year": year, "n": int(te.sum()), "log_loss": round(ll, 4),
                      "base_log_loss": round(bll, 4), "accuracy": round(acc, 4),
                      "base_accuracy": round(bacc, 4)})
        model_ll.append(ll)
        base_ll.append(bll)
        print(f"  {year}:  n={te.sum():>6}  base={bll:.4f} -> model={ll:.4f}"
              f"   acc {bacc:.1%} -> {acc:.1%}")

    if len(folds) < 3:
        print("\nNot enough holdout years to judge this — refusing to ship.")
        ARTIFACT.unlink(missing_ok=True)
        return 1

    mm, bm = float(np.mean(model_ll)), float(np.mean(base_ll))
    wins = sum(1 for f in folds if f["log_loss"] < f["base_log_loss"])
    print(f"\n  mean: base={bm:.4f} -> model={mm:.4f}  "
          f"(better in {wins}/{len(folds)} years)")

    # THE GATE. Beat the base rate on the mean AND in most years — a single
    # lucky fold is not evidence.
    if not (mm < bm and wins >= len(folds) - 1):
        print("  -> does NOT beat the base rate. Artifact deleted; the card "
              "will say nothing rather than repeat a constant.")
        ARTIFACT.unlink(missing_ok=True)
        return 1

    print("  -> earns its place; shipping.")
    clf, mu, sd = _fit(X, y)      # final fit on everything
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps({
        "classes": list(CLASSES),
        "feature_order": list(FEATURES),
        "coefficients": {f: [float(clf.coef_[k][i]) for k in range(len(CLASSES))]
                         for i, f in enumerate(FEATURES)},
        "intercept": [float(v) for v in clf.intercept_],
        "feature_mean": {f: float(mu[i]) for i, f in enumerate(FEATURES)},
        "feature_sd": {f: float(sd[i]) for i, f in enumerate(FEATURES)},
        "metadata": {
            "n_train": int(len(X)),
            "walk_forward": folds,
            "mean_holdout_log_loss": round(mm, 4),
            "mean_base_log_loss": round(bm, 4),
            "years_better_than_base": wins,
            "note": ("Fitted by scripts/train_method.py on the Sherdog global "
                     "bout graph. Predicts HOW a fight ends, not who wins. "
                     "Ships only while it beats the point-in-time base rate."),
        },
    }, indent=2))
    print(f"\nWrote {ARTIFACT}")

    order = np.argsort(-np.abs(clf.coef_).max(axis=0))
    print("\nStandardised weights (per class: ko_tko / submission / decision):")
    for i in order:
        f = FEATURES[i]
        print(f"  {f:<14} " + " / ".join(f"{clf.coef_[k][i]:+.3f}"
                                         for k in range(len(CLASSES))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

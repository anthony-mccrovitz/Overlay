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


GLOBAL_FEATURES = ["gelo", "pro_exp", "top_share", "pro_form", "pro_layoff"]


def build_global_matrix(dates: list[date], pairs: list[tuple[str, str]]) -> np.ndarray | None:
    """Career-wide features aligned to the UFC training rows, or None.

    Returns None — rather than a matrix of mostly-imputed values — when the
    Sherdog crawl has not covered enough of the roster. Comparing a model built
    on 3% real data against one built on none measures the imputation, not the
    features, and would happily report an improvement that is an artifact.
    """
    from src.models.global_elo import (
        MIN_ROSTER_COVERAGE,
        GlobalLedger,
        load_global_bouts,
        name_to_slug,
        roster_coverage,
    )
    from src.models.ufc_features import load_bouts as _lb
    from src.models.ufc_features import normalize_name

    bouts, _s, tott = _lb()
    names = {n for b in bouts for n in (b["w"], b["l"])}
    cov = roster_coverage(names, tott)
    print(f"  global graph covers {cov:.1%} of the ufcstats roster "
          f"(need {MIN_ROSTER_COVERAGE:.0%})")
    if cov < MIN_ROSTER_COVERAGE:
        print("  -> too thin; global features not offered to the model")
        return None

    slug_of = name_to_slug()
    tt = {normalize_name(k): v for k, v in tott.items()}

    def slug(name: str) -> str | None:
        nn = normalize_name(name)
        dob = (tt.get(nn) or {}).get("dob")
        return slug_of.get((nn, dob.isoformat() if dob else None))

    gb = load_global_bouts()
    led = GlobalLedger()
    gi = 0
    rows: list[list[float]] = []
    for d, (a, z) in zip(dates, pairs):
        # Advance the global ledger to just before this fight — same
        # point-in-time contract, applied across a second data source.
        while gi < len(gb) and gb[gi]["date"] < d:
            led.apply_bout(gb[gi])
            gi += 1
        sa, sz = slug(a), slug(z)
        fa = led.features_for(sa, d) if sa else {}
        fz = led.features_for(sz, d) if sz else {}
        rows.append([
            (fa.get(k) - fz.get(k))
            if (fa.get(k) is not None and fz.get(k) is not None) else np.nan
            for k in GLOBAL_FEATURES
        ])
    return np.array(rows, float)


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
    pairs: list[tuple[str, str]] = []

    for b in bouts:
        a, z = (b["w"], b["l"]) if b["w"] < b["l"] else (b["l"], b["w"])
        rows.append(led.diff_vector(a, z, b["date"]))
        ys.append(1 if a == b["w"] else 0)
        dates.append(b["date"])
        minprior.append(min(led.state(a).n, led.state(z).n))
        pairs.append((a, z))
        led.apply_bout(b)          # ← state moves only after the row is emitted

    X = np.array([[np.nan if v is None else v for v in r] for r in rows], dtype=float)
    return X, np.array(ys), dates, np.array(minprior), pairs


# Features for the debut model, from the UNRATED fighter's point of view.
# We know nothing about their fighting; we do know how old they are and who
# they have been matched against. Both turn out to carry signal.
DEBUT_FEATURES = ["age_diff", "reach_diff", "opp_elo", "opp_exp", "opp_form"]


def build_debut_matrix() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rows for fights where exactly ONE fighter has a UFC record.

    Why this exists: reporting a flat 43.4% for every debut throws away the
    date of birth we already hold for these fighters, and age is the strongest
    feature in the main model. Measured over 1,273 such fights, using it beats
    the flat base rate in six of seven holdout years (mean log-loss 0.6612 vs
    0.6832, AUC 0.635).

    Deliberately NOT extended to fights where BOTH fighters are unrated: that
    was measured too, and age alone gives AUC 0.490 — worse than a coin flip.
    There, "no read" is the honest answer and it stays.
    """
    bouts, stats, tott = load_bouts()
    led = Ledger(stats, tott)
    rows, ys, yrs = [], [], []
    for b in bouts:
        w, l, d = b["w"], b["l"], b["date"]
        if d.year >= 2010:
            for unrated, ranked, y in ((w, l, 1), (l, w, 0)):
                if led.known(unrated) or not led.known(ranked):
                    continue
                fu = led.features_for(unrated, d)
                fr = led.features_for(ranked, d)
                if fu["age"] is None or fr["age"] is None:
                    continue
                reach = (fu["reach"] - fr["reach"]) if (fu["reach"] and fr["reach"]) else np.nan
                rows.append([fu["age"] - fr["age"], reach, fr["elo"] - 1500.0,
                             min(fr["exp"], 25.0), fr["form"] if fr["form"] is not None else 0.5])
                ys.append(y)
                yrs.append(d.year)
                break
        led.apply_bout(b)
    return np.array(rows, float), np.array(ys), np.array(yrs)


def train_debut_model() -> dict | None:
    """Fit and validate the debut model. Returns None if it fails to beat the
    flat base rate — in which case the flat rate is what ships."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss, roc_auc_score

    X, Y, yrs = build_debut_matrix()
    if len(Y) < 300:
        print("  debut model: too few debut fights to fit — keeping the flat base rate")
        return None

    med = np.nanmedian(X, axis=0)
    X = _impute(X, med)

    folds, flat_lls, mdl_lls = [], [], []
    for y in range(2019, int(yrs.max()) + 1):
        tr, te = yrs < y, yrs == y
        if te.sum() < 40 or tr.sum() < 200:
            continue
        mu, sd = X[tr].mean(0), X[tr].std(0)
        sd[sd == 0] = 1.0
        m = LogisticRegression(C=1.0, max_iter=2000).fit((X[tr] - mu) / sd, Y[tr])
        p = m.predict_proba((X[te] - mu) / sd)[:, 1]
        flat = np.full(int(te.sum()), Y[tr].mean())
        f_ll = float(log_loss(Y[te], flat, labels=[0, 1]))
        m_ll = float(log_loss(Y[te], p, labels=[0, 1]))
        auc = float(roc_auc_score(Y[te], p)) if len(set(Y[te])) > 1 else float("nan")
        folds.append({"test_year": int(y), "n": int(te.sum()),
                      "flat_log_loss": round(f_ll, 4),
                      "model_log_loss": round(m_ll, 4), "auc": round(auc, 4)})
        flat_lls.append(f_ll)
        mdl_lls.append(m_ll)
        print(f"  debut {y}: n={te.sum():3d}  flat={f_ll:.4f}  model={m_ll:.4f}  AUC={auc:.3f}")

    if not folds:
        return None
    mean_flat, mean_mdl = float(np.mean(flat_lls)), float(np.mean(mdl_lls))
    print(f"  debut mean: flat={mean_flat:.4f}  model={mean_mdl:.4f}")
    if mean_mdl >= mean_flat:
        print("  debut model does not beat the flat base rate — not shipping it")
        return None

    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    m = LogisticRegression(C=1.0, max_iter=2000).fit((X - mu) / sd, Y)
    return {
        "coefficients": {k: round(float(v), 6) for k, v in zip(DEBUT_FEATURES, m.coef_[0])},
        "intercept": round(float(m.intercept_[0]), 6),
        "feature_median": {k: round(float(v), 6) for k, v in zip(DEBUT_FEATURES, med)},
        "feature_mean": {k: round(float(v), 6) for k, v in zip(DEBUT_FEATURES, mu)},
        "feature_sd": {k: round(float(v), 6) for k, v in zip(DEBUT_FEATURES, sd)},
        "metadata": {
            "n_train": int(len(Y)),
            "walk_forward": folds,
            "mean_flat_log_loss": round(mean_flat, 4),
            "mean_model_log_loss": round(mean_mdl, 4),
            "note": ("Applies only when exactly ONE fighter has a UFC record. "
                     "When BOTH are unrated, age alone gives AUC 0.490 — worse "
                     "than chance — so that case stays 'no read'."),
        },
    }


GLOBAL_FALLBACK_FEATURES = ["gelo_diff", "top_share_diff", "pro_exp_diff"]


def train_global_fallback() -> dict | None:
    """The tier for fights the MAIN model refuses (≥1 fighter under 2 UFC bouts).

    THE SPLIT VERDICT THIS ENCODES. Career-wide features were offered to the
    main model and REFUSED by its gate (base 0.6391 vs +global 0.6444 —
    worse in 5 of 6 holdout years): where both fighters have UFC records, the
    UFC data already carries the information and the 45% imputation is noise.
    But on the population the main model cannot score at all, career Elo alone
    is decisively better than the flat base rate we served instead:

        n=1,167 refused fights, 5 one-year holdouts (2018-2022)
        flat 0.6941  →  global 0.6490      AUC 0.673

    Both answers came from the same experiment; this trains the half that won.
    Ships only if it beats flat on the holdouts, same rule as everything else.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss, roc_auc_score

    from src.models.global_elo import (
        GlobalLedger,
        load_global_bouts,
        name_to_slug,
    )
    from src.models.ufc_features import Ledger, normalize_name

    bouts, stats, tott = load_bouts()
    slug_of = name_to_slug()
    tt = {normalize_name(k): v for k, v in tott.items()}

    def slug(name: str) -> str | None:
        nn = normalize_name(name)
        dob = (tt.get(nn) or {}).get("dob")
        return slug_of.get((nn, dob.isoformat() if dob else None))

    gb = load_global_bouts()
    gled = GlobalLedger()
    gi = 0
    uled = Ledger(stats, tott)
    rows, ys, yrs = [], [], []
    for b in bouts:
        d = b["date"]
        while gi < len(gb) and gb[gi]["date"] < d:
            gled.apply_bout(gb[gi])
            gi += 1
        w, l = b["w"], b["l"]
        if d.year >= 2010 and min(uled.state(w).n, uled.state(l).n) < MIN_PRIOR_BOUTS:
            a, z = (w, l) if w < l else (l, w)
            sa, sz = slug(a), slug(z)
            if sa and sz and gled.known(sa) and gled.known(sz):
                fa, fz = gled.features_for(sa, d), gled.features_for(sz, d)
                rows.append([fa["gelo"] - fz["gelo"],
                             fa["top_share"] - fz["top_share"],
                             fa["pro_exp"] - fz["pro_exp"]])
                ys.append(1 if a == w else 0)
                yrs.append(d.year)
        uled.apply_bout(b)

    if len(ys) < 400:
        print(f"  global fallback: only {len(ys)} scoreable fights — not training")
        return None
    X, Y, yr = np.array(rows), np.array(ys), np.array(yrs)

    folds, f_lls, m_lls = [], [], []
    for y in range(2018, int(yr.max()) + 1):
        tr, te = yr < y, yr == y
        if te.sum() < 40 or tr.sum() < 200:
            continue
        mu, sd = X[tr].mean(0), X[tr].std(0)
        sd[sd == 0] = 1.0
        m = LogisticRegression(C=1.0, max_iter=2000).fit((X[tr] - mu) / sd, Y[tr])
        p = m.predict_proba((X[te] - mu) / sd)[:, 1]
        flat = np.full(int(te.sum()), Y[tr].mean())
        f_ll = float(log_loss(Y[te], flat, labels=[0, 1]))
        m_ll = float(log_loss(Y[te], p, labels=[0, 1]))
        auc = (float(roc_auc_score(Y[te], p))
               if len(set(Y[te])) > 1 else float("nan"))
        folds.append({"test_year": int(y), "n": int(te.sum()),
                      "flat_log_loss": round(f_ll, 4),
                      "model_log_loss": round(m_ll, 4), "auc": round(auc, 4)})
        f_lls.append(f_ll)
        m_lls.append(m_ll)
        print(f"  global-fallback {y}: n={te.sum():3d}  flat={f_ll:.4f}  "
              f"model={m_ll:.4f}  AUC={auc:.3f}")
    if not folds or float(np.mean(m_lls)) >= float(np.mean(f_lls)):
        print("  global fallback does not beat the flat rate — not shipping")
        return None

    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    m = LogisticRegression(C=1.0, max_iter=2000).fit((X - mu) / sd, Y)
    return {
        "coefficients": {k: round(float(v), 6)
                         for k, v in zip(GLOBAL_FALLBACK_FEATURES, m.coef_[0])},
        "intercept": round(float(m.intercept_[0]), 6),
        "feature_mean": {k: round(float(v), 6)
                         for k, v in zip(GLOBAL_FALLBACK_FEATURES, mu)},
        "feature_sd": {k: round(float(v), 6)
                       for k, v in zip(GLOBAL_FALLBACK_FEATURES, sd)},
        "metadata": {
            "n_train": int(len(Y)),
            "walk_forward": folds,
            "mean_flat_log_loss": round(float(np.mean(f_lls)), 4),
            "mean_model_log_loss": round(float(np.mean(m_lls)), 4),
            "note": ("Applies ONLY to fights the main model refuses (a fighter "
                     "under 2 UFC bouts) where BOTH fighters resolve in the "
                     "global graph. The same features were offered to the main "
                     "model and refused — both verdicts are recorded because "
                     "both are true."),
        },
    }


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

    X, Y, dates, minprior, pairs = build_matrix()
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

    # ── do career-wide features earn their place? ────────────────────────────
    # Same holdout years, same everything, one difference: five features built
    # from the fighter's WHOLE professional record rather than the UFC slice.
    # They ship only if they lower held-out log-loss. A feature that sounds
    # obviously useful and does not measure better is still not useful.
    print("\nGlobal (career-wide) features — do they help?")
    G = build_global_matrix(dates, pairs)
    global_used = False
    global_folds: list[dict] = []
    if G is not None:
        XG = np.hstack([X, G])
        g_lls, b_lls = [], []
        for f in folds:
            y = f["test_year"]
            tr = (yr < y) & usable
            te = (yr == y) & usable
            m, med, mu, sd = _fit(XG[tr], Y[tr])
            s = _score(m, med, mu, sd, XG[te], Y[te])
            global_folds.append({"test_year": int(y), **s})
            g_lls.append(s["log_loss"])
            b_lls.append(f["log_loss"])
            print(f"  {y}:  base={f['log_loss']:.4f}  +global={s['log_loss']:.4f}  "
                  f"acc {f['accuracy']:.1%} -> {s['accuracy']:.1%}")
        mg, mb = float(np.mean(g_lls)), float(np.mean(b_lls))
        print(f"  mean: base={mb:.4f}  +global={mg:.4f}")
        if mg < mb:
            global_used = True
            print("  -> global features EARN their place; shipping them")
            X = XG
            mean_ll = mg
            mean_acc = sum(f["accuracy"] for f in global_folds) / len(global_folds)
            folds = global_folds
        else:
            print("  -> no improvement; keeping the UFC-only model")
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
        "feature_order": FEATURES + (GLOBAL_FEATURES if global_used else []),
        "uses_global_features": global_used,
        "coefficients": {k: round(float(v), 6)
                         for k, v in zip(FEATURES + (GLOBAL_FEATURES if global_used else []),
                                         m.coef_[0])},
        "feature_median": {k: (None if np.isnan(v) else round(float(v), 6))
                           for k, v in zip(FEATURES + (GLOBAL_FEATURES if global_used else []), med)},
        "feature_mean": {k: round(float(v), 6) for k, v in zip(FEATURES + (GLOBAL_FEATURES if global_used else []), mu)},
        "feature_sd": {k: round(float(v), 6) for k, v in zip(FEATURES + (GLOBAL_FEATURES if global_used else []), sd)},
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

    print("\nDebut model — fights where exactly one fighter has a UFC record:")
    debut = train_debut_model()
    dpath = Path("data/models/ufc/debut_model.json")
    if debut:
        debut["trained_on"] = date.today().isoformat()
        dpath.write_text(json.dumps(debut, indent=2, sort_keys=True))
        print(f"Wrote {dpath}")
    else:
        # Never leave a stale artifact behind a model that just failed to earn
        # its place — the flat base rate is the honest fallback.
        dpath.unlink(missing_ok=True)
        print("No debut artifact written; the flat base rate applies.")

    print("\nGlobal fallback — the fights the main model refuses:")
    gf = train_global_fallback()
    gpath = Path("data/models/ufc/global_fallback.json")
    if gf:
        gf["trained_on"] = date.today().isoformat()
        gpath.write_text(json.dumps(gf, indent=2, sort_keys=True))
        print(f"Wrote {gpath}")
    else:
        gpath.unlink(missing_ok=True)
        print("No global-fallback artifact; base rates continue to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Probability calibration for EdgeFinder models.

Usage:
  from src.analytics.calibration import recalibrate_all, apply_calibration

  recalibrate_all()                              # fit calibrators on settled picks
  p = apply_calibration(0.62, "nba", "spread")  # returns calibrated probability
"""
from __future__ import annotations

import json
import math
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CALIBRATORS_DIR = Path("data/models/calibrators")
PICKS_PATH      = Path("data/pnl/picks.json")

MIN_PICKS_TO_CALIBRATE = 30

# Isotonic regression overfits on small samples; use Platt (logistic on log-odds) instead.
# Prop markets almost always have high model_prob and low actual win rates — Platt handles
# this gracefully because it learns temperature + bias rather than memorizing percentiles.
# Moneyline is added here because isotonic regression overfits badly on ML data:
# the model clusters probs in a narrow band (0.48-0.70) and isotonic maps the
# tail (0.75+) to 1.0, producing absurd 60% "edges". Platt is safer everywhere.
_PLATT_MARKETS = {"prop", "nrfi", "moneyline"}
_PLATT_THRESHOLD = 150              # also use Platt if n < threshold (not enough for isotonic)


@dataclass
class CalibrationResult:
    sport:        str
    market:       str
    n_picks:      int
    brier_score:  float
    ece:          float           # Expected Calibration Error
    bins:         list[dict]      # [{prob_mid, model_rate, actual_rate, n}]
    calibrated:   bool


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_picks() -> list[dict]:
    if not PICKS_PATH.exists():
        return []
    data = json.loads(PICKS_PATH.read_text())
    return data.get("picks", data) if isinstance(data, dict) else data


def _settled(pick: dict) -> bool:
    return (pick.get("result") or "").upper() in ("WIN", "LOSS", "PUSH")


def _outcome(pick: dict) -> Optional[float]:
    r = (pick.get("result") or "").upper()
    if r == "WIN":  return 1.0
    if r == "LOSS": return 0.0
    return None  # PUSH excluded from calibration


def _normalize_market(m: str) -> str:
    m = (m or "").lower()
    if m in ("h2h", "moneyline", "ml"): return "moneyline"
    if m in ("spreads", "spread", "run_line", "runline", "puck_line"): return "spread"
    if m in ("totals", "total", "over_under"): return "total"
    if m in ("nrfi", "yrfi"): return "nrfi"
    if "prop" in m or m in ("pitcher_strikeouts", "points", "rebounds", "assists"): return "prop"
    return m


def _normalize_sport(s: str) -> str:
    s = (s or "").lower()
    # wnba MUST precede nba: "nba" is a substring of "wnba", and the old order
    # silently pooled WNBA picks into NBA calibrator fits (and would have
    # applied NBA calibrators to WNBA probabilities).
    if "wnba" in s: return "wnba"
    if "mlb" in s or s == "baseball": return "mlb"
    if "nba" in s or s == "basketball": return "nba"
    if "nhl" in s or s == "hockey": return "nhl"
    return s


# ── Core calibration ─────────────────────────────────────────────────────────

def compute_calibration(
    picks: list[dict],
    n_bins: int = 10,
    sport: str = "all",
    market: str = "all",
) -> CalibrationResult:
    """
    Reliability diagram data + Brier score + ECE for a set of picks.
    Filters to sport/market if specified (pass "all" to skip filter).
    """
    settled_picks = []
    for p in picks:
        if not _settled(p):
            continue
        if sport != "all" and _normalize_sport(p.get("sport", "")) != sport:
            continue
        if market != "all" and _normalize_market(p.get("market", "")) != market:
            continue
        prob = p.get("model_prob")
        outcome = _outcome(p)
        if prob is None or outcome is None:
            continue
        prob = float(prob)
        if prob < 0.0 or prob > 1.0:
            continue
        settled_picks.append((prob, outcome))

    n = len(settled_picks)
    if n == 0:
        return CalibrationResult(sport, market, 0, float("nan"), float("nan"), [], False)

    # Brier score: mean squared error of probability estimates
    brier = sum((p - y) ** 2 for p, y in settled_picks) / n

    # Bin into equal-width buckets from 0.5 → 1.0 (we only bet when model_prob > 0.5)
    bin_edges = [0.5 + i * (0.5 / n_bins) for i in range(n_bins + 1)]
    bins = []
    ece_sum = 0.0
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        bucket = [(p, y) for p, y in settled_picks if lo <= p < hi]
        if not bucket:
            continue
        model_rate  = sum(p for p, _ in bucket) / len(bucket)
        actual_rate = sum(y for _, y in bucket) / len(bucket)
        mid = (lo + hi) / 2
        bins.append({
            "prob_mid":    round(mid, 3),
            "model_rate":  round(model_rate, 4),
            "actual_rate": round(actual_rate, 4),
            "n":           len(bucket),
        })
        ece_sum += len(bucket) * abs(model_rate - actual_rate)

    ece = ece_sum / n if n > 0 else float("nan")

    return CalibrationResult(
        sport       = sport,
        market      = market,
        n_picks     = n,
        brier_score = round(brier, 4),
        ece         = round(ece, 4),
        bins        = bins,
        calibrated  = False,
    )


# ── Calibrator fitting ────────────────────────────────────────────────────────

def _fit_platt(X: list[float], y: list[float]):
    """
    Platt scaling: logistic regression on log-odds of raw model prob.
    Learns temperature T and bias b: calibrated = sigmoid(log_odds(p)/T + b).
    More robust than isotonic when n < 200 or when probabilities cluster near 0/1.
    Returns a sklearn LogisticRegression instance (wrapped to accept scalar input).
    """
    from sklearn.linear_model import LogisticRegression
    import math
    eps = 1e-7
    log_odds = [[math.log(max(eps, p) / max(eps, 1 - p))] for p in X]
    clf = LogisticRegression(C=1.0, max_iter=1000)
    clf.fit(log_odds, y)
    return clf


def _apply_platt(clf, prob: float) -> float:
    import math
    eps = 1e-7
    lo = math.log(max(eps, prob) / max(eps, 1 - prob))
    return float(clf.predict_proba([[lo]])[0][1])


def _fit_isotonic(X: list[float], y: list[float]):
    from sklearn.isotonic import IsotonicRegression
    cal = IsotonicRegression(out_of_bounds="clip")
    cal.fit(X, y)
    return cal


def _use_platt(market: str, n: int) -> bool:
    return _normalize_market(market) in _PLATT_MARKETS or n < _PLATT_THRESHOLD


# ── Fit-quality guardrails ────────────────────────────────────────────────────
# A calibrator fit on a losing segment can collapse into a near-constant or
# even INVERTED function (2026-07-18: mlb_nrfi Platt mapped 0.50→0.446 and
# 0.99→0.404 — every slate came out all-YRFI; mlb_f5_total isotonic collapsed
# to one plateau — every pick got the same 0.6094). A degenerate calibrator is
# worse than none: the calibration GATE (k) already zeroes the edge on bad
# segments, so the honest fallback is identity, not a constant that silently
# flips every pick to one side.

_PROBE_GRID = [round(0.05 + 0.05 * i, 2) for i in range(19)]  # 0.05 … 0.95
_MIN_SPREAD     = 0.15  # f(0.8) − f(0.2) must retain at least this much signal
# Mid-band check: model probs live almost entirely in [0.35, 0.65], so a curve
# that is flat THERE destroys the slate even if its global spread looks fine
# (the collapsed F5 isotonic had global spread 0.34 but mid-band 0.075 — every
# realistic input landed on one plateau).
_MIN_MID_SPREAD = 0.10  # f(0.65) − f(0.35)


def _calibrator_curve(cal_type: str, cal) -> list[float]:
    if cal_type == "platt":
        return [_apply_platt(cal, p) for p in _PROBE_GRID]
    return [float(v) for v in cal.predict(_PROBE_GRID)]


def validate_calibrator(cal_type: str, cal) -> tuple[bool, str]:
    """Probe a fitted calibrator on a fixed grid. Returns (ok, reason).

    Rejects: inverted / non-monotone mappings (higher raw prob must never mean
    lower calibrated prob) and range collapse (a flat curve destroys all
    per-game signal and pins an entire slate to one constant).
    """
    try:
        curve = _calibrator_curve(cal_type, cal)
    except Exception as e:  # unpicklable/broken model object
        return False, f"probe failed: {e}"
    eps = 1e-9
    if any(b < a - eps for a, b in zip(curve, curve[1:])):
        return False, "non-monotone (inverted) mapping"
    i20, i80 = _PROBE_GRID.index(0.2), _PROBE_GRID.index(0.8)
    spread = curve[i80] - curve[i20]
    if spread < _MIN_SPREAD:
        return False, f"range collapse: f(0.8)-f(0.2)={spread:.3f} < {_MIN_SPREAD}"
    i35, i65 = _PROBE_GRID.index(0.35), _PROBE_GRID.index(0.65)
    mid = curve[i65] - curve[i35]
    if mid < _MIN_MID_SPREAD:
        return False, f"mid-band collapse: f(0.65)-f(0.35)={mid:.3f} < {_MIN_MID_SPREAD}"
    return True, "ok"


def recalibrate_all(min_picks: int = MIN_PICKS_TO_CALIBRATE, verbose: bool = True) -> dict:
    """
    Fit calibrators for each sport × market combo with enough data.
    Uses Platt scaling (logistic on log-odds) for prop/nrfi markets and small samples;
    isotonic regression for larger game-total/spread/moneyline datasets.
    Saves calibrators to data/models/calibrators/{sport}_{market}.pkl.
    Returns dict of {key: CalibrationResult}.
    """
    try:
        from sklearn.linear_model import LogisticRegression  # noqa: F401
        from sklearn.isotonic import IsotonicRegression      # noqa: F401
    except ImportError:
        print("  [calibration] scikit-learn not installed — skipping")
        return {}

    picks = _load_picks()
    if not picks:
        return {}

    # Group settled picks by sport × market
    groups: dict[str, list[tuple[float, float]]] = {}
    for p in picks:
        if not _settled(p):
            continue
        # Tainted picks came from a known-broken mechanism (degenerate
        # calibrator, team-blind ratings, …) — fitting on them would teach the
        # next calibrator the previous calibrator's disease.
        if p.get("tainted"):
            continue
        # Fit on the PRE-calibration probability when the emitter stamped it.
        # The stored model_prob is post-calibration; training on it and then
        # applying the fit to raw model outputs is a domain mismatch that
        # compounds shrinkage every refit (observed: mlb_moneyline f(0.5)
        # drifted 0.4375 → 0.4196 within one day). Falls back to model_prob
        # for legacy picks recorded before raw stamping existed.
        prob    = p.get("model_prob_raw")
        if prob is None:
            prob = p.get("model_prob")
        outcome = _outcome(p)
        if prob is None or outcome is None:
            continue
        prob = float(prob)
        if not (0.0 <= prob <= 1.0):
            continue
        sport  = _normalize_sport(p.get("sport", ""))
        market = _normalize_market(p.get("market", ""))
        key    = f"{sport}_{market}"
        groups.setdefault(key, []).append((prob, outcome))

    CALIBRATORS_DIR.mkdir(parents=True, exist_ok=True)
    results = {}

    for key, data_pts in groups.items():
        if len(data_pts) < min_picks:
            if verbose:
                print(f"  [calibration] {key}: only {len(data_pts)} picks — need {min_picks}, skipping")
            continue

        X = [p for p, _ in data_pts]
        y = [o for _, o in data_pts]
        _, market_key = key.split("_", 1)

        use_platt = _use_platt(market_key, len(data_pts))
        if use_platt:
            cal      = _fit_platt(X, y)
            y_pred   = [_apply_platt(cal, p) for p in X]
            cal_type = "platt"
        else:
            cal    = _fit_isotonic(X, y)
            y_pred = list(cal.predict(X))
            cal_type = "isotonic"

        path = CALIBRATORS_DIR / f"{key}.pkl"

        # Guardrail: never ship a degenerate calibrator. Also remove any
        # previously-saved pkl for this key so a stale degenerate can't linger —
        # apply_calibration then falls back to identity and the edge gate (k)
        # handles the segment's honesty.
        ok, reason = validate_calibrator(cal_type, cal)
        if not ok:
            if verbose:
                print(f"  [calibration] {key} ({cal_type}): REJECTED — {reason}; "
                      f"falling back to identity")
            path.unlink(missing_ok=True)
            continue

        with open(path, "wb") as f:
            pickle.dump({"type": cal_type, "model": cal}, f)

        brier   = sum((yp - yo) ** 2 for yp, yo in zip(y_pred, y)) / len(y)
        sport_p, market_p = key.split("_", 1)
        raw_result = compute_calibration(picks, sport=sport_p, market=market_p)

        if verbose:
            print(
                f"  [calibration] {key} ({cal_type}): {len(data_pts)} picks | "
                f"Brier {raw_result.brier_score:.4f} → {brier:.4f} | "
                f"ECE {raw_result.ece:.4f}"
            )

        results[key] = raw_result

    return results


def apply_calibration(
    model_prob: float,
    sport: str,
    market: str,
) -> float:
    """
    Apply a fitted calibrator to a raw model probability.
    Falls back to the raw probability if no calibrator is available.
    Handles both legacy isotonic pkl files and new dict-wrapped Platt calibrators.
    """
    key  = f"{_normalize_sport(sport)}_{_normalize_market(market)}"
    path = CALIBRATORS_DIR / f"{key}.pkl"
    if not path.exists():
        return model_prob
    try:
        with open(path, "rb") as f:
            raw = pickle.load(f)
        if isinstance(raw, dict):
            cal_type = raw.get("type", "isotonic")
            cal      = raw["model"]
            if cal_type == "platt":
                return _apply_platt(cal, model_prob)
            else:
                return float(cal.predict([model_prob])[0])
        else:
            # Legacy: bare isotonic calibrator
            return float(raw.predict([model_prob])[0])
    except Exception:
        return model_prob


def apply_calibration_symmetric(
    model_prob: float,
    sport: str,
    market: str,
) -> float:
    """
    Two-sided-market calibration: guarantees f(p) + f(1−p) = 1.

    Applying a calibrator to only ONE side and mirroring (away = 1 − f(home))
    turns any asymmetry in the fit into a structural side bias: the 2026-07-18
    mlb_moneyline Platt had f(0.50)=0.4375, which deflated every HOME prob and
    inflated every AWAY prob — 138/138 July moneyline picks came out AWAY.

    This wrapper symmetrizes any calibrator:
        p_cal = ½ · (f(p) + 1 − f(1−p))
    so a true coin flip stays a coin flip and both sides always sum to 1.
    Use for every market whose two sides are complements (moneyline home/away,
    NRFI/YRFI, totals over/under). Falls back to identity when no calibrator
    exists, same as apply_calibration.
    """
    f_p   = apply_calibration(model_prob, sport, market)
    f_1mp = apply_calibration(1.0 - model_prob, sport, market)
    p = 0.5 * (f_p + (1.0 - f_1mp))
    return min(1.0, max(0.0, p))


# ── Summary printer ───────────────────────────────────────────────────────────

def print_calibration_summary(min_picks: int = 20) -> None:
    picks  = _load_picks()
    sports  = ["mlb", "nba"]
    markets = ["moneyline", "spread", "total", "nrfi", "prop"]

    print("\n  CALIBRATION SUMMARY")
    print("  " + "─" * 60)
    print(f"  {'Segment':<22} {'N':>5}  {'Brier':>7}  {'ECE':>7}  {'Cal?':>5}")
    print("  " + "─" * 60)

    for sport in sports:
        for market in markets:
            res = compute_calibration(picks, sport=sport, market=market)
            if res.n_picks < min_picks:
                continue
            cal_path = CALIBRATORS_DIR / f"{sport}_{market}.pkl"
            has_cal  = "YES" if cal_path.exists() else "no"
            brier_str = f"{res.brier_score:.4f}" if not math.isnan(res.brier_score) else "  —"
            ece_str   = f"{res.ece:.4f}"         if not math.isnan(res.ece)         else "  —"
            print(f"  {sport} {market:<18} {res.n_picks:>5}  {brier_str:>7}  {ece_str:>7}  {has_cal:>5}")

    print("  " + "─" * 60)
    # Overall
    res_all = compute_calibration(picks)
    if res_all.n_picks > 0:
        brier_str = f"{res_all.brier_score:.4f}" if not math.isnan(res_all.brier_score) else "  —"
        ece_str   = f"{res_all.ece:.4f}"         if not math.isnan(res_all.ece)         else "  —"
        print(f"  {'ALL':<22} {res_all.n_picks:>5}  {brier_str:>7}  {ece_str:>7}")


if __name__ == "__main__":
    print("Fitting calibrators...")
    recalibrate_all()
    print()
    print_calibration_summary()

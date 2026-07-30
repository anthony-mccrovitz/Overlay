"""Per-lane expected value against the closing market, with a significance test.

WHY THIS REPLACED THE BEAT-CLOSE GATE. Promotion used to require `beat close
>= 55%`. Measured across the 8 lanes with >=100 settled bets and >=100 scored
CLV rows on 2026-07-30:

    corr(beat_close%, realised ROI) = -0.153
    corr(clv_ev_pct,  realised ROI) = +0.494

The gate criterion was, in this dataset, mildly NEGATIVELY related to making
money. The clearest case is mlb/batter_total_bases: it beats the close 65.3% of
the time — the best rate of any lane — and returns -3.3%.

The reason is structural, not a quirk of props. Beat-close is a RATE and rates
are blind to magnitude: a lane can win 65% of tiny favourable moves while the
35% it loses are large, and finish underwater. Expected value weights each move
by what it was worth, which is why it tracks profit and a hit-rate cannot.

    EV% = fair_close(the exact bet we made) / price_we_paid - 1

Beat-close is still computed and still reported — it is a useful diagnostic of
whether the market agrees with us at all — it just no longer decides promotion.

TWO SEPARATE QUESTIONS, deliberately kept apart:
  clears the gate  — EV > 0, ROI > 0, n >= PROMOTE_MIN_N. A decision rule for
                     putting money at risk, with a data-sufficiency floor.
  proven           — the mean EV is statistically distinguishable from zero.
This mirrors the existing documented invariant that clearing the gate is NOT
proof, and keeps the scoreboard from calling n=30 "READY" as if it were.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

SNAPSHOTS = Path("data/clv/snapshots.json")

# Two-sided 95%. Deliberately NOT Bonferroni-corrected here: this reports one
# lane's own evidence, and the multiple-comparison correction belongs to
# whoever is scanning all lanes at once (see clv_gate, which applies it).
Z_95 = 1.96


@dataclass(frozen=True)
class EVStats:
    n: int
    mean_ev_pct: float
    sd: float
    t: float | None
    n_needed: int | None      # bets required for significance at the observed mean
    significant: bool

    @property
    def positive(self) -> bool:
        return self.mean_ev_pct > 0


def _load() -> list[dict]:
    try:
        blob = json.loads(SNAPSHOTS.read_text().replace("NaN", "null"))
    except (json.JSONDecodeError, ValueError, OSError):
        return []
    rows = blob.get("snapshots", blob) if isinstance(blob, dict) else blob
    return [r for r in rows if isinstance(r, dict)]


def _stats(values: list[float]) -> EVStats | None:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    sd = math.sqrt(var)
    if sd <= 0:
        # Every bet scored identically — degenerate, not significant.
        return EVStats(n, mean, 0.0, None, None, False)
    t = mean / (sd / math.sqrt(n))
    # n required for |t| >= Z_95 at this mean and dispersion.
    needed = math.ceil((Z_95 * sd / abs(mean)) ** 2) if mean else None
    return EVStats(n, mean, sd, t, needed, abs(t) >= Z_95)


def ev_values_by_lane(rows: list[dict] | None = None) -> dict[tuple[str, str], list[float]]:
    """{(sport, market): [per-bet EV%]} — the raw values behind EVStats.

    Exposed so callers that need to POOL several markets can concatenate real
    observations. Reconstructing a pooled sample by repeating a lane's mean n
    times preserves the mean and destroys the variance, which silently forces
    `significant=False` — a lane that could never be proven, for arithmetic
    reasons rather than evidential ones.
    """
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in (rows if rows is not None else _load()):
        if r.get("tainted"):
            continue
        ev = r.get("clv_ev_pct")
        if ev is None:
            continue
        market = str(r.get("market") or "").lower()
        market = {"ml": "moneyline", "h2h": "moneyline"}.get(market, market)
        sport = str(r.get("sport") or "")
        if not sport or not market:
            continue
        try:
            buckets[(sport, market)].append(float(ev))
        except (TypeError, ValueError):
            continue
    return dict(buckets)


def pooled_ev(lanes: list[tuple[str, str]],
              rows: list[dict] | None = None) -> EVStats | None:
    """EVStats over several lanes pooled from their REAL observations."""
    by_lane = ev_values_by_lane(rows)
    vals: list[float] = []
    for lane in lanes:
        vals.extend(by_lane.get(lane, []))
    return _stats(vals)


def ev_by_lane(rows: list[dict] | None = None) -> dict[tuple[str, str], EVStats]:
    """{(sport, market): EVStats} over every snapshot carrying clv_ev_pct.

    Tainted rows are excluded on the same grounds market_stats excludes them:
    they were produced by a model state we have since repudiated, so including
    them measures a thing that no longer exists.
    """
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in (rows if rows is not None else _load()):
        if r.get("tainted"):
            continue
        ev = r.get("clv_ev_pct")
        if ev is None:
            continue
        market = str(r.get("market") or "").lower()
        market = {"ml": "moneyline", "h2h": "moneyline"}.get(market, market)
        sport = str(r.get("sport") or "")
        if not sport or not market:
            continue
        try:
            buckets[(sport, market)].append(float(ev))
        except (TypeError, ValueError):
            continue

    out: dict[tuple[str, str], EVStats] = {}
    for lane, vals in buckets.items():
        st = _stats(vals)
        if st is not None:
            out[lane] = st
    return out


def lane_ev(sport: str, market: str) -> EVStats | None:
    return ev_by_lane().get((sport, str(market).lower()))

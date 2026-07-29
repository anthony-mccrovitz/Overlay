"""
adjustments.py — age curves and depth-chart reality checks.

Projecting 2026 from 2025 production assumes a player is the same person in the
same job. Both halves of that are often false, and these are the two corrections
available from data Sleeper actually publishes.

AGE. Running backs fall off a cliff; quarterbacks barely age. A 30-year-old
back who produced last season is a worse bet than a 24-year-old who produced
identically, and the market knows it — several of the largest "values" on the
raw board are just the market pricing decline correctly.

DEPTH CHART. This is the closest thing we have to modelling team changes, and
it is better than it sounds: a back who signed elsewhere and won the job shows
up as DC1 on his new team, while one who lost his job shows as DC3 regardless of
what he did last year. We do NOT know last year's depth chart, so this is used
as a sanity check on the CURRENT job rather than a delta: production without a
job is not repeatable, and a job without production still gets touches.

Both are deliberately gentle. A projection nudged 15% by a real signal is an
improvement; one swung 60% by a heuristic is a new source of error.
"""
from __future__ import annotations

# Peak age band and per-year decline outside it, by position. Curves are flat
# inside the band — the difference between 25 and 27 for a WR is noise.
AGE_CURVE = {
    #        peak_lo peak_hi  decline/yr  rise/yr (below peak)
    "RB":  (23, 27, 0.055, 0.030),
    "WR":  (24, 28, 0.040, 0.035),
    "TE":  (25, 29, 0.035, 0.045),
    "QB":  (26, 34, 0.025, 0.020),
    "K":   (24, 36, 0.010, 0.005),
    "DEF": (0, 99, 0.0, 0.0),
}

# Floor/ceiling so a single curve can never erase a player.
#
# The floor matters more than it looks. At a 7.5%/yr RB decline with a 0.70
# floor, every back aged 30+ received an identical 30% haircut — so a 30-year-old
# and a 35-year-old were valued the same, flattening the curve exactly where
# differentiation matters most. A gentler slope with a lower floor keeps the
# ordering intact across the tail.
AGE_MIN, AGE_MAX = 0.55, 1.12

# What share of a position's startable workload each depth slot typically sees.
# Used as a ceiling on projected opportunity, not a multiplier on talent.
DEPTH_OPPORTUNITY = {
    "RB": {1: 1.00, 2: 0.55, 3: 0.28, 4: 0.15},
    "WR": {1: 1.00, 2: 0.88, 3: 0.66, 4: 0.40, 5: 0.25},
    "TE": {1: 1.00, 2: 0.45, 3: 0.22},
    "QB": {1: 1.00, 2: 0.12, 3: 0.05},
}
DEPTH_DEFAULT = 0.30


def age_factor(position: str, age: int | None) -> float:
    """Multiplier for a player's projection based on where he is on the curve."""
    if age is None:
        return 1.0
    curve = AGE_CURVE.get(position)
    if not curve:
        return 1.0
    lo, hi, decline, rise = curve
    if lo <= age <= hi:
        return 1.0
    if age > hi:
        f = 1.0 - decline * (age - hi)
    else:
        f = 1.0 - rise * (lo - age)      # young players are still ramping
    return max(AGE_MIN, min(AGE_MAX, f))


def depth_factor(position: str, depth: int | None, projected_rate: float,
                 pos_starter_rate: float) -> float:
    """Reality-check a projection against the player's CURRENT job.

    Only applied when the projection and the job disagree:
      · producing like a starter while buried on the chart  → discount toward
        the opportunity his slot actually gets
      · projecting poorly while holding the job outright    → small boost,
        because DC1 volume has a floor

    A player whose projection already matches his role is left alone — the
    adjustment exists to catch changed circumstances, not to re-rank everyone.
    """
    if depth is None or position not in DEPTH_OPPORTUNITY:
        return 1.0
    share = DEPTH_OPPORTUNITY[position].get(int(depth), DEPTH_DEFAULT)

    if pos_starter_rate <= 0:
        return 1.0
    implied_role = min(1.5, projected_rate / pos_starter_rate)

    if implied_role > share * 1.25:
        # Producing well above what this slot normally supports. Pull partway
        # toward the slot's opportunity rather than all the way: depth charts
        # are a snapshot and committees exist.
        target = share / implied_role
        return max(0.55, 1.0 - 0.6 * (1.0 - target))

    if depth == 1 and implied_role < 0.55:
        return 1.08          # holds the job, modest floor

    return 1.0

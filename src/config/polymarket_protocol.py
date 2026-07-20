"""
Frozen experimental protocol for the Polymarket pilot.

Why this file exists
--------------------
The scanner's rules changed repeatedly while we were looking at the same
board — entry mode, fee model, depth filter, league list, gate exemption. Each
change was justified, but a rule tuned while watching outcomes is a rule
fitted to those outcomes, and a verdict computed over such a sample means
nothing. The experiment only produces a trustworthy answer if the rules stop
moving before the data is collected.

So the rules live here, versioned. Every pick is stamped with
PROTOCOL_VERSION at write time, and the readiness report only counts picks
matching the current version. Changing anything below is allowed — it is a
git commit, visible in review — but it RESETS the sample, which is exactly
the friction that should exist.

Success and failure are both defined here, in advance, so neither can be
rationalised after the fact.
"""
from __future__ import annotations

# Bump when any rule below changes. Doing so invalidates the accumulated
# sample for verdict purposes: picks are counted per-version, never pooled.
PROTOCOL_VERSION = "v1"

# ── Entry rules ──────────────────────────────────────────────────────────────
MIN_EV_PCT = 2.0            # same bar as devig_ev/consensus_ev — comparable verdicts
MIN_LIQUIDITY_USD = 1000    # Gamma-reported; NOT a depth guarantee (see below)
MIN_TOP_DEPTH_USD = 0.0     # 0 = record thin books rather than skip them, so the
                            # experiment can measure how often edges are untradeable
ENTRY_MODE = "make"         # rest inside the bid; sports_fees_v2 is takerOnly
DAYS_AHEAD = 2              # scan D+0..D+2 → picks at ~12h, ~36h, ~60h leads

# ── Bankroll rules (paper, and live if it ever promotes) ─────────────────────
BANKROLL_USD = 112.0
STAKE_FRAC = 0.04                  # flat 4% per pick
MAX_CONCURRENT_EXPOSURE_FRAC = 0.35
# 11 picks on one slate already ties up 44% of the bankroll at flat 4%. Real
# maker orders lock USDC from post until resolution, so overlapping slates
# compound it. Past this fraction the scanner reports picks but the ledger
# stops opening new ones — running out of capital mid-experiment would bias
# the sample toward whatever happened to be early in the day.

# ── Stopping rules — defined BEFORE the data, on purpose ─────────────────────
VERDICT_MIN_SCORED = 300        # the house 300-bet CLV bar
VERDICT_MIN_FILLED = 100        # maker fills needed before a maker verdict counts
MAX_DRAWDOWN_FRAC = 0.25        # paper bankroll down 25% → stop, investigate
# A RETIRE verdict is a SUCCESS. It costs nothing and closes off a
# plausible-looking idea. The failure mode to guard against is not "the
# strategy loses" — it is "the strategy loses and we keep adjusting until it
# looks like it won".

# ── Anchor validation ────────────────────────────────────────────────────────
# Everything rests on Pinnacle's devigged price being the true probability.
# That is well supported for major markets and unestablished for K-League,
# Brazil Serie A and WNBA — exactly the thin books where we hope edge lives.
ANCHOR_MIN_SAMPLE = 200         # picks needed before the calibration read counts
ANCHOR_MAX_MISCALIBRATION = 0.05  # |predicted - actual| above this = anchor is unfit


def as_dict() -> dict:
    """The protocol as data — stamped into reports so any run is reproducible."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "min_ev_pct": MIN_EV_PCT,
        "min_liquidity_usd": MIN_LIQUIDITY_USD,
        "entry_mode": ENTRY_MODE,
        "days_ahead": DAYS_AHEAD,
        "bankroll_usd": BANKROLL_USD,
        "stake_frac": STAKE_FRAC,
        "max_concurrent_exposure_frac": MAX_CONCURRENT_EXPOSURE_FRAC,
        "verdict_min_scored": VERDICT_MIN_SCORED,
        "verdict_min_filled": VERDICT_MIN_FILLED,
        "max_drawdown_frac": MAX_DRAWDOWN_FRAC,
        "anchor_min_sample": ANCHOR_MIN_SAMPLE,
        "anchor_max_miscalibration": ANCHOR_MAX_MISCALIBRATION,
    }

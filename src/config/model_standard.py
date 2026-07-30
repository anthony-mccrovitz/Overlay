"""
model_standard.py — the build standard, expressed as executable checks.

Every rule here exists because skipping it already cost a rebuild. The registry
is full of lanes that shipped fast and produced numbers nobody could trust:
calibrators that flattened every game to one probability, a model that claimed
17pp of edge and realised 1pp, thousands of prop picks with no grader, whole
sports with no CLV coverage at all. None of that was a modelling failure. It was
the absence of a gate.

A standard written in a document gets bypassed on a fast night. This one is
enforced by tests/test_model_standard.py, which fails the build when a LIVE lane
is missing an artifact — so a lane cannot reach card_pick=True by omission.

Legacy is handled with EXEMPTIONS rather than by weakening the checks: an
exemption is visible, dated, and must name what has to happen to retire it. The
test also fails when an exemption is no longer needed, so the list can't rot
into permanent cover.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CALIBRATORS_DIR = Path("data/models/calibrators")
QUARANTINE_DIR  = CALIBRATORS_DIR / "_quarantine_degenerate"
CALIBRATION_JSON = Path("data/models/calibration.json")
EXPERIMENTS_DIR = Path("data/experiments")
TESTS_DIR       = Path("tests")

# A lane needs this many MOVED closing lines before its beat-rate means anything.
MIN_CLV_SAMPLE = 30

# Promotion gate — must match src/pipeline/promoter.py.
#
# DECIDED 2026-07-29: the gate does NOT require statistical significance, and
# that is deliberate rather than an oversight. n>=30 is a data-sufficiency floor;
# proving a true 55% edge against the close needs ~2,400 moved lines, and even
# mlb/total's 58% on n=112 is only z=+1.69.
#
# Enforcing z>=1.96 would demote the only live lane and leave nothing carding for
# weeks. The bet taken instead: three independent signals agreeing (beat-close,
# positive ROI, and k=0.81 saying the claimed edges are real) is enough to size
# at quarter-Kelly on a small bankroll, where a false positive costs little and
# waiting costs real edge. `beat_significance` reports z and n_needed on every
# gate line so "clears the gate" can never again be misread as "proven".
#
# 2026-07-30: PROMOTE_BEAT_MIN no longer gates promotion. Measured across our 8
# best-sampled lanes, beat-close correlated -0.153 with realised ROI while mean
# EV correlated +0.494 — the gate criterion was pointing the wrong way. The gate
# now runs on EV (see clears_promotion_gate); this threshold is retained only
# for the diagnostic beat-close reporting that still appears on every gate line.
PROMOTE_BEAT_MIN = 55.0
PROMOTE_MIN_N    = 30

# Minimum MEAN EV (%) vs the close before a lane may take real money.
#
# Not zero, deliberately. `EV > 0` let mlb/moneyline through at +0.09% on 1,132
# scored bets — t=+0.24, needing ~75,000 bets to distinguish from zero. That is
# a coin flip wearing a plus sign, and it cleared a gate meant to authorise real
# stakes. A floor above zero is also what the parameter-uncertainty literature
# argues for: estimated edges are biased upward, so the honest response is to
# require the estimate to clear a margin rather than merely a sign.
#
# 1.0% sits below the live lane (mlb/total, +2.99%) and above the noise floor
# every break-even lane occupies. Raise it if you want a stricter book; there is
# nothing magic about the number, only about it not being zero.
PROMOTE_MIN_EV   = 1.0

# Independence floor. n counts SNAPSHOTS; this counts the distinct DAYS they
# came from, because bets on one slate share a weather front, a stale board and
# a news cycle — they are not independent draws.
#
# usa_mls/moneyline exposed the gap: 46 rows spread over FOUR days, 63% of them
# on a single one, mean EV +13.00% driven by outliers (median +5.98%; dropping
# the top 3 rows collapses it to +5.01%), entered a MEDIAN 3.7 days before
# kickoff so the "closing line value" largely measures three days of news
# arriving. A t-test assuming 46 independent observations called that
# significant. The live lane for comparison: 215 rows across 60 days.
#
# 15 days is deliberately below mlb/total's 60 and far above the 4 that slipped
# through — enough slates that one unusual card cannot carry a promotion.
PROMOTE_MIN_DAYS = 15

# Edge-shrink floor. k is realized_pp / claimed_pp: how much of the edge the
# model claims actually shows up in results. Below this the model's edges are
# mostly fiction, and any Kelly sizing built on them is oversized.
MIN_EDGE_SHRINK_K = 0.25


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


# ─────────────────────────── artifact lookups ────────────────────────────────

def _slug(sport: str, market: str) -> str:
    return f"{sport}_{market}"


def has_calibrator(sport: str, market: str) -> tuple[bool, str]:
    """A fitted, non-quarantined calibrator.

    Quarantine matters: a degenerate calibrator is REMOVED rather than used, and
    the code falls back to identity. That fallback is safe but it means the
    model's raw probabilities go out uncorrected, which is exactly the state
    that produced phantom double-digit edges.
    """
    name = f"{_slug(sport, market)}.pkl"
    if (CALIBRATORS_DIR / name).exists():
        return True, "fitted"
    if (QUARANTINE_DIR / name).exists():
        return False, "QUARANTINED as degenerate — running on identity fallback"
    return False, "no calibrator fitted"


@lru_cache(maxsize=1)
def _calibration_records() -> dict:
    try:
        return json.loads(CALIBRATION_JSON.read_text())
    except (OSError, ValueError):
        return {}


def edge_shrink(sport: str, market: str) -> tuple[bool, str]:
    """Does the edge the model claims actually materialise?

    k = realized_pp / claimed_pp, measured on settled results. k≈1 means the
    model's stated edge is real. k≈0 means it is inventing the entire number —
    which is survivable in shadow and disqualifying live.
    """
    rec = _calibration_records().get(f"{sport}::{market}")
    if not rec:
        return False, "no edge-shrink record (run chef.py calibrate)"
    k = rec.get("k")
    if k is None:
        return False, "record present but k missing"
    claimed, realized = rec.get("claimed_pp"), rec.get("realized_pp")
    detail = f"k={k:.2f} (claimed {claimed}pp → realized {realized}pp, n={rec.get('n')})"
    return (k >= MIN_EDGE_SHRINK_K), detail


def has_backtest(sport: str, market: str) -> tuple[bool, str]:
    """A recorded baseline in the experiment ledger.

    This is the weakest possible reading of "backtested" — it only asks whether
    the lane was ever measured and written down. Lanes that shipped straight to
    production have nothing here at all.
    """
    path = EXPERIMENTS_DIR / f"{sport}__{market}.json"
    if not path.exists():
        return False, "no experiment record (run chef.py experiment snapshot)"
    try:
        snaps = json.loads(path.read_text())
    except (OSError, ValueError):
        return False, "experiment record unreadable"
    if not snaps:
        return False, "experiment record empty"
    latest = snaps[-1]
    return True, f"{len(snaps)} snapshot(s), latest '{latest.get('tag')}' {latest.get('date')}"


# The enforcement file itself is excluded from the coverage corpus. It names
# markets in order to CHECK them, so counting it would let the standard satisfy
# its own requirement — coverage that exists only because we asked about it.
_CORPUS_EXCLUDE = {"test_model_standard.py"}


@lru_cache(maxsize=1)
def _test_corpus() -> str:
    """All test source concatenated, for grader-coverage checks."""
    out = []
    for p in sorted(TESTS_DIR.glob("test_*.py")):
        if p.name in _CORPUS_EXCLUDE:
            continue
        try:
            out.append(p.read_text())
        except OSError:
            continue
    return "\n".join(out)


def has_grader_test(sport: str, market: str) -> tuple[bool, str]:
    """Is this market named anywhere in the test suite?

    Deliberately a coverage floor, not a proof of correctness: an unnamed market
    is definitionally untested, and that is how batter props reached thousands of
    rows with no grader and WNBA drifted for four weeks unnoticed.
    """
    corpus = _test_corpus()
    if f'"{market}"' in corpus or f"'{market}'" in corpus:
        return True, "market referenced in tests"
    return False, f"market '{market}' appears in no test file"


@lru_cache(maxsize=1)
def _clv_rows() -> dict:
    try:
        from src.analytics.clv_gate import clv_gate
        rows = clv_gate(1)
        rows = rows[0] if isinstance(rows, tuple) else rows
    except Exception:
        return {}
    out = {}
    for r in rows or []:
        m = (r.get("market") or "").lower()
        m = {"ml": "moneyline", "h2h": "moneyline"}.get(m, m)
        out[(r.get("sport"), m)] = r
    return out


def has_clv_coverage(sport: str, market: str) -> tuple[bool, str]:
    """Enough MOVED closing lines to judge the lane at all.

    Tennis and UFC have zero. Their entire graded history is unjudgeable, which
    means rebuilding them without wiring this first would be rebuilding blind.
    """
    r = _clv_rows().get((sport, market))
    if not r:
        return False, "no CLV rows — lane is not instrumented"
    n = r.get("sharp_moved_n") or 0
    beat = r.get("sharp_beat_pct")
    if n < MIN_CLV_SAMPLE:
        return False, f"only {n} moved lines (need {MIN_CLV_SAMPLE})"
    return True, f"{n} moved lines, beats close {beat}%"


def beat_significance(beat_pct: float | None, n: int) -> tuple[float | None, int | None]:
    """(z, n_needed) for a beat-close rate against the coin-flip null.

    Beating the close 58% of the time sounds decisive and, on 112 moved lines,
    is not: z=1.69, which is the wrong side of 1.96. The promotion gate's n>=30
    floor is a data-sufficiency check, NOT a significance test — at a true 55%
    edge you need ~2,400 moved lines to prove it, and at 58% you need 151.
    Reporting z alongside the rate keeps "clears the gate" from being read as
    "proven".
    """
    if beat_pct is None or not n:
        return None, None
    p = beat_pct / 100.0
    z = (p - 0.5) / math.sqrt(0.25 / n)
    needed = math.ceil(0.25 * (1.96 / (p - 0.5)) ** 2) if p > 0.5 else None
    return z, needed


def clears_promotion_gate(sport: str, market: str) -> tuple[bool, str]:
    """The gate a lane must clear to be LIVE: positive EV vs the close AND profit.

    The criterion changed on 2026-07-30. It used to be `beat close >= 55%`, which
    measured across our own 8 best-sampled lanes turned out to be mildly
    NEGATIVELY related to profit (corr -0.153 vs ROI), while mean EV was
    positively related (+0.494). mlb/batter_total_bases beat the close 65.3% of
    the time — the highest rate of any lane — and lost 3.3%.

    A hit rate is blind to magnitude: winning 65% of small favourable moves while
    losing 35% large ones is a losing lane that clears a beat-close gate. EV
    weights every move by what it was worth, which is why it tracks money.

    Beat-close is still reported — it says whether the market agrees with us —
    it just no longer decides. See src/analytics/ev_gate.py for the evidence.
    """
    try:
        from src.analytics.ev_gate import lane_ev
        ev = lane_ev(sport, market)
    except Exception:
        ev = None
    r = _clv_rows().get((sport, market))
    beat = (r or {}).get("sharp_beat_pct")
    beat_txt = f", beats close {beat}%" if beat is not None else ""

    if ev is None:
        return False, "no EV evidence (lane has no scored clv_ev_pct rows)"
    if ev.n < PROMOTE_MIN_N:
        return False, f"insufficient sample (n={ev.n}, need {PROMOTE_MIN_N})"

    try:
        from src.analytics.market_stats import market_stats
        st = market_stats().get((sport, market))
        roi = (st.pnl / st.n * 100) if st and st.n else None
    except Exception:
        roi = None
    if roi is None:
        return False, f"EV {ev.mean_ev_pct:+.2f}% but ROI unknown"

    if ev.n_days and ev.n_days < PROMOTE_MIN_DAYS:
        return False, (f"EV {ev.mean_ev_pct:+.2f}% on n={ev.n} but only "
                       f"{ev.n_days} distinct day(s) "
                       f"({ev.max_day_share:.0%} on one) — need "
                       f"{PROMOTE_MIN_DAYS}; clustered samples are not "
                       f"independent{beat_txt}")
    ok = ev.mean_ev_pct >= PROMOTE_MIN_EV and roi > 0
    # n>=PROMOTE_MIN_N is a DATA-SUFFICIENCY floor, never a significance test.
    # Report the t-statistic and the sample a real verdict would need, so
    # "clears the gate" can never be read as "proven" — the same discipline the
    # old beat-close gate applied with z, preserved on the new criterion.
    if ev.significant:
        sig = f", t={ev.t:+.2f} SIGNIFICANT"
    elif ev.t is not None:
        sig = f", t={ev.t:+.2f} NOT significant"
        if ev.n_needed:
            sig += f" (needs n≈{ev.n_needed})"
    else:
        sig = ", t=n/a"
    return ok, (f"EV {ev.mean_ev_pct:+.2f}% on n={ev.n}, "
                f"ROI {roi:+.1f}%{sig}{beat_txt}")


# ─────────────────────────── the standard ────────────────────────────────────

def pipeline_health(sport: str, market: str) -> tuple[bool, str]:
    """Is the lane still emitting, and are its lines still being captured?

    Every other check reads history. This one asks whether the history is still
    being written — the failure mode where a model's numbers stay frozen and
    keep getting quoted. mlb/total missed 15 of 45 days while its 58% beat-close
    was treated as current, and 9 of those were days the pipeline ran fine and
    only the totals model went silent.
    """
    from src.analytics.coverage import (
        lane_coverage, capture_rate, healthy, MIN_CAPTURE_RATE,
    )
    cov = lane_coverage(sport, market)
    ok, detail = healthy(cov)
    if not ok:
        return False, detail
    n, closed, rate = capture_rate(sport)
    if n and rate < MIN_CAPTURE_RATE:
        return False, (f"{detail}; but only {closed}/{n} snapshots "
                       f"({rate:.0%}) got a closing line — unscoreable")
    return True, f"{detail}; capture {rate:.0%}"


CHECKS = (
    ("backtest",   has_backtest),
    ("calibrator", has_calibrator),
    ("edge_shrink", edge_shrink),
    ("clv_coverage", has_clv_coverage),
    ("grader_test", has_grader_test),
    ("pipeline", pipeline_health),
    ("promotion_gate", clears_promotion_gate),
)


def audit(sport: str, market: str) -> list[Check]:
    """Run every check against one lane."""
    out = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn(sport, market)
        except Exception as err:                     # a broken check is a failure
            ok, detail = False, f"check errored: {err}"
        out.append(Check(name, ok, detail))
    return out


def failures(sport: str, market: str) -> list[str]:
    return [c.name for c in audit(sport, market) if not c.ok]


# ─────────────────────────── legacy exemptions ───────────────────────────────
#
# A lane may be LIVE while failing a check ONLY with an entry here. Every
# exemption names the failing checks, why the lane is still trusted, and what
# retires the exemption. The test fails both when an exemption is missing AND
# when one is no longer needed — so this list cannot quietly become permanent.

# These can NEVER be exempted. A lane may go live without a fitted calibrator if
# its edges are independently shown to be real — but a lane whose claimed edge
# doesn't materialise, or which can't be measured, or which doesn't clear the
# promotion gate, has no argument for taking real money. Allowing an exemption
# here would make the standard decorative.
NON_EXEMPTIBLE = frozenset({"edge_shrink", "clv_coverage", "promotion_gate"})

EXEMPTIONS: dict[tuple[str, str], dict] = {
    ("mlb", "total"): {
        "checks": ["calibrator"],
        "since": "2026-07-29",
        "why": (
            "The calibrator was quarantined as degenerate (it flattened every game "
            "to ~0.5833), so this lane runs on the identity fallback. That is "
            "tolerable here and only here, because the edge-shrink gate independently "
            "says the raw edges are largely real: k=0.81, claimed 5.97pp vs realized "
            "4.87pp on n=225. No other live lane has that evidence."
        ),
        "retire_when": (
            "30+ clean graded picks accumulate post-quarantine and recalibrate_all "
            "fits a non-degenerate mlb_total.pkl; then delete this entry."
        ),
    },
}


def is_exempt(sport: str, market: str, check: str) -> bool:
    ex = EXEMPTIONS.get((sport, market))
    return bool(ex) and check in ex.get("checks", [])

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
PROMOTE_BEAT_MIN = 55.0
PROMOTE_MIN_N    = 30

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
    """The gate a lane must clear to be LIVE: beat the close AND make money."""
    r = _clv_rows().get((sport, market))
    if not r:
        return False, "no CLV evidence"
    n = r.get("sharp_moved_n") or 0
    beat = r.get("sharp_beat_pct")
    if beat is None or n < PROMOTE_MIN_N:
        return False, f"insufficient sample (n={n})"

    try:
        from src.analytics.market_stats import market_stats
        st = market_stats().get((sport, market))
        roi = (st.pnl / st.n * 100) if st and st.n else None
    except Exception:
        roi = None

    if roi is None:
        return False, f"beats close {beat}% but ROI unknown"
    ok = beat >= PROMOTE_BEAT_MIN and roi > 0
    z, needed = beat_significance(beat, n)
    sig = ""
    if z is not None:
        if abs(z) >= 1.96:
            sig = f", z={z:+.2f} SIGNIFICANT"
        else:
            sig = f", z={z:+.2f} NOT significant"
            if needed:
                sig += f" (needs n≈{needed})"
    return ok, f"beats close {beat}% on n={n}, ROI {roi:+.1f}%{sig}"


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

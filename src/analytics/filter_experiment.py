"""
filter_experiment.py — prove a subgroup finding forward, not backward.

Slicing a lane after the fact always finds something. mlb/total's profit turned
out to sit entirely on the OVER side (61.1% / +22.1% vs 50.0% / −0.2% on UNDER),
which is a real pattern and also exactly what a false positive looks like: it
was found by trying fifteen subgroup splits, and its z of 2.35 clears a naive
95% bar but fails Bonferroni at 2.81.

The honest response is neither "ignore it" nor "hard-filter the model on it".
It is to register the filter with a START DATE and measure it on picks emitted
AFTER that date, where it is a prediction rather than a description. The
in-sample record is kept alongside, clearly labelled, so the two can never be
quoted as one number.

This is deliberately NOT a shadow strategy. Shadow strategies generate their own
picks; a filter selects from picks a lane already emits, so logging duplicates
would double-count the lane in every ledger total.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

PICKS_FILE = Path("data/pnl/picks.json")
REGISTRY_FILE = Path("data/experiments/filters.json")


@dataclass
class FilterResult:
    name: str
    sport: str
    market: str
    start_date: str
    # In-sample: the window the finding was discovered in. Descriptive only.
    in_n: int = 0
    in_wr: float | None = None
    in_roi: float | None = None
    # Out-of-sample: picks emitted after start_date. The only honest evidence.
    out_n: int = 0
    out_wr: float | None = None
    out_roi: float | None = None
    # The complement, so "the filter helped" is measured against the alternative
    # rather than against zero.
    comp_n: int = 0
    comp_roi: float | None = None
    note: str = ""
    hypothesis: str = ""

    @property
    def verdict(self) -> str:
        if self.out_n < 30 or self.out_roi is None:
            return f"COLLECTING — {self.out_n}/30 out-of-sample"
        # A negative out-of-sample result is decisive on its own. Requiring the
        # complement first left a clearly-failing filter reading COLLECTING
        # forever whenever the lane happened to emit only the filtered side.
        if self.out_roi <= 0:
            return "FAILING — negative out of sample"
        if self.comp_roi is None:
            return "POSITIVE — no complement to compare against yet"
        if self.out_roi > self.comp_roi:
            return "HOLDING — beats the complement out of sample"
        return "WEAK — positive but not beating the complement"


# ── the registry ─────────────────────────────────────────────────────────────
#
# A filter is (lane, predicate, start_date, hypothesis). The hypothesis is
# mandatory prose: a filter you can't state a reason for is a coincidence you
# got attached to.

FILTERS: dict[str, dict] = {
    "mlb_total_over_only": {
        "sport": "mlb",
        "market": "total",
        "start_date": "2026-07-29",
        "predicate": lambda p: str(p.get("direction", "")).upper() == "OVER",
        "hypothesis": (
            "mlb/total has direction skill but no magnitude skill: overs hit 61.1% "
            "in games the model calls OVER and 50.0% in games it calls UNDER "
            "(+11.1pt spread), while its confidence signal reads flat. If the side "
            "selection is the real edge, the OVER subset should stay profitable "
            "out of sample and the UNDER subset should stay at break-even."
        ),
        "note": (
            "Found post-hoc across 15 subgroup tests; z=2.35 passes a naive 95% "
            "bar and FAILS Bonferroni (2.81). In-sample numbers are descriptive."
        ),
    },
    "mlb_batter_props_over_only": {
        "sport": "mlb",
        "market": ("batter_hits", "batter_total_bases", "batter_rbis",
                   "batter_home_runs"),
        "start_date": "2026-07-30",
        "predicate": lambda p: str(p.get("direction", "")).upper() == "OVER",
        "hypothesis": (
            "The batter-prop models have a SIDE-SELECTION tilt, not a bad model. "
            "They pick UNDER 71-89% of the time, and UNDER is precisely where the "
            "expected value is negative, while the OVER minority is positive on "
            "every one of the four markets: hits OVER +10.07% EV vs UNDER -5.35%, "
            "home_runs +41.00% vs -7.24%, rbis +14.26% vs -5.24%, total_bases "
            "+2.07% vs -6.74%. That is the signature of count models whose "
            "distributions are compressed toward the mean, which makes any line "
            "above the mean look like an easy UNDER. If the tilt is the whole "
            "problem, the OVER subset should stay positive-EV out of sample and "
            "the UNDER complement should stay negative."
        ),
        "note": (
            "STRICTLY IN-SAMPLE at registration: the sides were chosen by looking "
            "at the EV they produced, on the same data. That is the definition of "
            "a post-hoc split and the in-sample numbers below are descriptive "
            "ONLY. Four markets tested at once, so a naive 95% bar needs a "
            "Bonferroni correction to 98.75%. Related prior art: the 2026-06-30 "
            "one-sided over/under fixes (NB dispersion + mean bugs) addressed this "
            "same failure mode elsewhere, which is a reason to suspect a real "
            "mechanism here rather than noise -- and NOT a reason to skip the "
            "out-of-sample test."
        ),
    },
}


# ── evaluation ───────────────────────────────────────────────────────────────

def _load(path: Path = PICKS_FILE) -> list[dict]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    rows = raw.get("picks", raw) if isinstance(raw, dict) else raw
    return [r for r in rows if isinstance(r, dict)]


def _dec(odds) -> float:
    o = float(odds)
    return 1.0 + (o / 100.0 if o > 0 else 100.0 / abs(o))


def _flat_unit_pnl(rows: list[dict]) -> tuple[int, float | None, float | None]:
    """(n, win_rate, roi) at FLAT 1u.

    Never read the stored `profit` field here: shadow stakes are often 0.0 or
    0.5, so dividing booked profit by pick count measures staking policy rather
    than the model.
    """
    graded = [r for r in rows if r.get("result") in ("win", "loss")
              and r.get("odds") is not None]
    if not graded:
        return 0, None, None
    pnl = sum(_dec(r["odds"]) - 1 if r["result"] == "win" else -1.0 for r in graded)
    wins = sum(1 for r in graded if r["result"] == "win")
    n = len(graded)
    return n, round(100 * wins / n, 1), round(100 * pnl / n, 1)


def evaluate(name: str, picks: list[dict] | None = None) -> FilterResult:
    spec = FILTERS[name]
    rows = _load() if picks is None else picks
    pred: Callable[[dict], bool] = spec["predicate"]
    start = spec["start_date"]

    # `market` may name one market or several. A hypothesis about a MECHANISM —
    # count models compressed toward the mean, which tilts every one of them to
    # the UNDER — is a claim about the family, and testing it market-by-market
    # would quarter the sample and multiply the comparisons for no reason.
    markets = spec["market"]
    markets = (markets,) if isinstance(markets, str) else tuple(markets)

    lane = [r for r in rows
            if r.get("sport") == spec["sport"]
            and r.get("market") in markets
            and not r.get("tainted")]

    inside  = [r for r in lane if str(r.get("date") or "") < start]
    outside = [r for r in lane if str(r.get("date") or "") >= start]

    in_n, in_wr, in_roi = _flat_unit_pnl([r for r in inside if pred(r)])
    out_n, out_wr, out_roi = _flat_unit_pnl([r for r in outside if pred(r)])
    comp_n, _, comp_roi = _flat_unit_pnl([r for r in outside if not pred(r)])

    return FilterResult(
        name=name, sport=spec["sport"], market=spec["market"], start_date=start,
        in_n=in_n, in_wr=in_wr, in_roi=in_roi,
        out_n=out_n, out_wr=out_wr, out_roi=out_roi,
        comp_n=comp_n, comp_roi=comp_roi,
        note=spec.get("note", ""), hypothesis=spec.get("hypothesis", ""),
    )


def evaluate_all(picks: list[dict] | None = None) -> list[FilterResult]:
    return [evaluate(n, picks) for n in sorted(FILTERS)]

"""CLV must reach market_stats from the snapshot ledger, not from the pick.

The bug this locks down: `market_stats` computed CLV as

    [p.get("clv_pct") for p in ps if isinstance(p.get("clv_pct"), (int, float))]

but `clv_pct` is written onto CLV *snapshots*, never back onto a pick. Zero of
the ledger's 16,111 picks carried the field, so every lane reported clv=None
and clv_n=0 — indistinguishable from "this lane has never been scored".

It was not a cosmetic hole. `experiment_log._triage_call` gates on
`clv > 0.5`, so `beats_close` was permanently False and `chef.py experiment
triage` printed "CUT/REBUILD — no signal, losing on ROI + CLV" for lanes it had
never measured. Three lanes that BEAT the close were being recommended for
cut/rebuild: tennis/moneyline (+1.44%), mlb/moneyline (+0.51%) and
wnba/moneyline (+1.10%).

This is the failure mode CLAUDE.md names directly — "real lanes report as
un-instrumented while holding hundreds of rows (tennis had 246 CLV snapshots
and reported zero)" — reached by a second, independent route.
"""
from __future__ import annotations

import pytest

from src.analytics import market_stats as ms
from src.analytics.experiment_log import _triage_call


def test_no_pick_carries_clv_pct_so_reading_it_can_only_return_nothing():
    """The premise. If this ever fails, picks gained the field and the old
    implementation could be revisited — until then, reading it is dead code."""
    picks = ms._load_picks(ms._PNL_FILE)
    if not picks:
        pytest.skip("ledger unavailable in this environment")
    assert not any(isinstance(p.get("clv_pct"), (int, float)) for p in picks), (
        "a pick now carries clv_pct — market_stats' CLV source may need revisiting"
    )


def test_market_stats_reports_clv_for_lanes_that_have_snapshots():
    """The fix: scored lanes must come back instrumented."""
    stats = ms.market_stats()
    if not stats:
        pytest.skip("ledger unavailable in this environment")
    scored = [s for s in stats.values() if s.clv is not None]
    assert scored, (
        "every lane reports clv=None. The snapshot ledger holds thousands of "
        "scored rows, so this is the un-instrumented-lane bug again."
    )
    for s in scored:
        assert s.clv_n > 0, f"{s.sport}/{s.market} has a CLV mean but n=0"
        assert s.clv_unit in ("%", "pt"), (
            f"{s.sport}/{s.market} reports CLV {s.clv} with unit {s.clv_unit!r}; "
            "a CLV number without its unit cannot be compared to anything"
        )


def test_moneyline_clv_is_a_percentage_not_points():
    """Unit discipline: probability markets are %, line markets are points."""
    stats = ms.market_stats()
    if not stats:
        pytest.skip("ledger unavailable in this environment")
    for (sport, market), s in stats.items():
        if s.clv is None:
            continue
        if market in ("moneyline", "nrfi"):
            assert s.clv_unit == "%", f"{sport}/{market} should be %, got {s.clv_unit}"
        if market in ("spread", "total"):
            assert s.clv_unit == "pt", f"{sport}/{market} should be pt, got {s.clv_unit}"


class TestTriageCallHonesty:
    """The call must name only the evidence it actually has."""

    def test_positive_percent_clv_beats_the_close(self):
        call = _triage_call(roi=-11.0, clv=1.44, signal="flat", clv_unit="%")
        assert "beats the close" in call

    def test_point_clv_is_not_treated_as_beating_the_close(self):
        """+0.23pt on batter_total_bases sits on a -2.9% ROI. Points are not a
        price edge, and CLAUDE.md judges prop lanes on ROI alone."""
        call = _triage_call(roi=-2.9, clv=0.23, signal="flat", clv_unit="pt")
        assert "beats the close" not in call
        assert "not comparable" in call

    def test_unmeasured_clv_is_never_claimed_as_evidence(self):
        """The exact sentence the bug produced: asserting a CLV loss with no CLV."""
        call = _triage_call(roi=-4.8, clv=None, signal="flat", clv_unit=None)
        assert "losing on ROI + CLV" not in call, (
            "claimed the lane loses on CLV while holding no CLV measurement"
        )
        assert "unmeasured" in call

    def test_profitable_lane_is_still_never_cut(self):
        call = _triage_call(roi=8.9, clv=0.19, signal="flat", clv_unit="pt")
        assert "KEEP" in call

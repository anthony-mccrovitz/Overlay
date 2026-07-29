"""Tests for prospective subgroup testing.

Slicing a lane after the fact always finds something. The point of this module
is that a finding discovered by slicing is a DESCRIPTION, and only picks emitted
after the registration date are EVIDENCE. These tests exist to make sure the two
can never be quoted as one number.
"""
import pytest

from src.analytics import filter_experiment as fx


def _p(date, direction, result, odds=-110, sport="mlb", market="total", tainted=None):
    return {"date": date, "direction": direction, "result": result,
            "odds": odds, "sport": sport, "market": market, "tainted": tainted}


class TestInOutSplit:
    def test_picks_before_start_are_in_sample_only(self):
        picks = [_p("2026-07-01", "OVER", "win")] * 5
        r = fx.evaluate("mlb_total_over_only", picks)
        assert r.in_n == 5
        assert r.out_n == 0

    def test_picks_on_the_start_date_count_as_out_of_sample(self):
        """The registration date is the boundary and belongs to the forward
        test; putting it in-sample would let the discovery day score itself."""
        picks = [_p("2026-07-29", "OVER", "win")] * 3
        r = fx.evaluate("mlb_total_over_only", picks)
        assert r.in_n == 0
        assert r.out_n == 3

    def test_complement_is_measured_out_of_sample(self):
        """'The filter helped' must be judged against the bets it skips, not
        against zero."""
        picks = ([_p("2026-08-01", "OVER", "win")] * 4
                 + [_p("2026-08-01", "UNDER", "loss")] * 6)
        r = fx.evaluate("mlb_total_over_only", picks)
        assert r.out_n == 4
        assert r.comp_n == 6
        assert r.comp_roi == pytest.approx(-100.0)


class TestFlatUnitAccounting:
    def test_roi_ignores_stored_profit(self):
        """Shadow stakes are often 0.0 or 0.5, so booked profit measures staking
        policy rather than the model. A stored profit of 0 must not zero the ROI."""
        picks = [dict(_p("2026-08-01", "OVER", "win", odds=100), stake=0.0, profit=0.0)
                 for _ in range(4)]
        r = fx.evaluate("mlb_total_over_only", picks)
        assert r.out_roi == pytest.approx(100.0)

    def test_tainted_picks_are_excluded(self):
        picks = [_p("2026-08-01", "OVER", "win", tainted=True)] * 5
        r = fx.evaluate("mlb_total_over_only", picks)
        assert r.out_n == 0

    def test_pushes_are_not_counted_as_decisions(self):
        picks = [_p("2026-08-01", "OVER", "push")] * 3 + [_p("2026-08-01", "OVER", "win")]
        r = fx.evaluate("mlb_total_over_only", picks)
        assert r.out_n == 1


class TestVerdict:
    def test_collecting_until_thirty(self):
        picks = [_p("2026-08-01", "OVER", "win")] * 29
        assert fx.evaluate("mlb_total_over_only", picks).verdict.startswith("COLLECTING")

    def test_failing_when_negative_out_of_sample(self):
        picks = [_p("2026-08-01", "OVER", "loss")] * 40
        assert fx.evaluate("mlb_total_over_only", picks).verdict.startswith("FAILING")

    def test_holding_requires_beating_the_complement(self):
        # 25W/15L at +100 is +25% ROI; 20 wins vs 20 losses would be exactly
        # break-even, which reads FAILING, not HOLDING.
        picks = ([_p("2026-08-01", "OVER", "win", odds=100)] * 25
                 + [_p("2026-08-01", "OVER", "loss")] * 15
                 + [_p("2026-08-01", "UNDER", "loss")] * 40)
        r = fx.evaluate("mlb_total_over_only", picks)
        assert r.out_n == 40 and r.comp_n == 40
        assert r.out_roi > 0 > r.comp_roi
        assert r.verdict.startswith("HOLDING")

    def test_negative_is_decisive_without_a_complement(self):
        """A clearly-failing filter must not read COLLECTING just because the
        lane happened to emit only the filtered side."""
        picks = [_p("2026-08-01", "OVER", "loss")] * 40
        r = fx.evaluate("mlb_total_over_only", picks)
        assert r.comp_n == 0
        assert r.verdict.startswith("FAILING")

    def test_a_good_in_sample_record_alone_never_yields_a_verdict(self):
        """The whole failure mode: a filter that looks superb in the window it
        was found in must still read COLLECTING."""
        picks = [_p("2026-07-01", "OVER", "win", odds=200)] * 200
        r = fx.evaluate("mlb_total_over_only", picks)
        assert r.in_roi > 100
        assert r.verdict.startswith("COLLECTING")


class TestRegistryDiscipline:
    def test_every_filter_states_a_hypothesis_and_a_caveat(self):
        for name, spec in fx.FILTERS.items():
            assert spec.get("hypothesis"), f"{name} has no hypothesis"
            assert spec.get("start_date"), f"{name} has no start_date"
            assert callable(spec.get("predicate")), f"{name} has no predicate"

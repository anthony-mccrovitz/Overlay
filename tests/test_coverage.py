"""Tests for pipeline coverage.

The point of this module is to catch the failure nobody notices: the ledger
stops growing and every downstream number keeps reporting confidently on a stale
sample. So the tests care most about the distinction between a dead pipeline and
a silent model — conflating those sends you debugging the wrong system.
"""
from datetime import date

import pytest

from src.analytics import coverage as cov


TODAY = date(2026, 7, 29)


def _p(d, sport="mlb", market="total"):
    return {"date": d, "sport": sport, "market": market}


class TestCanonSport:
    def test_tournament_keys_pool_to_one_lane(self):
        """Tennis logs per-tournament but the registry holds one lane. A local
        re-implementation of this mapping is what made tennis unmeasurable."""
        assert cov.canon_sport("tennis_atp_wimbledon") == "tennis"
        assert cov.canon_sport("tennis_wta_washington_open") == "tennis"

    def test_mma_maps_to_ufc(self):
        assert cov.canon_sport("mma_mixed_martial_arts") == "ufc"

    def test_golf_majors_pool_to_pga(self):
        assert cov.canon_sport("golf_us_open_winner") == "pga"
        assert cov.canon_sport("golf_the_open_championship_winner") == "pga"

    def test_plain_keys_pass_through(self):
        assert cov.canon_sport("mlb") == "mlb"
        assert cov.canon_sport("baseball_mlb") == "mlb"


class TestGapAttribution:
    """A pipeline gap and a market gap look identical in the ledger."""

    def test_pipeline_down_when_sport_logged_nothing(self):
        picks = [_p("2026-07-27"), _p("2026-07-28"), _p("2026-07-29")]
        c = cov.lane_coverage("mlb", "total", days=5, picks=picks, today=TODAY)
        assert c.pipeline_gap_days == ["2026-07-25", "2026-07-26"]
        assert c.market_gap_days == []

    def test_model_silent_when_sport_ran_without_the_market(self):
        """The dangerous case: pipeline healthy, one model stopped emitting.
        This was 9 of mlb/total's 15 missing days."""
        picks = [
            _p("2026-07-27", market="moneyline"),
            _p("2026-07-28", market="moneyline"),
            _p("2026-07-28", market="total"),
            _p("2026-07-29", market="moneyline"),
        ]
        c = cov.lane_coverage("mlb", "total", days=3, picks=picks, today=TODAY)
        assert c.pipeline_gap_days == []
        assert c.market_gap_days == ["2026-07-27", "2026-07-29"]
        assert c.sport_active_days == 3
        assert c.market_days == 1

    def test_both_causes_are_reported_separately(self):
        picks = [_p("2026-07-28", market="moneyline"), _p("2026-07-29", market="total")]
        c = cov.lane_coverage("mlb", "total", days=3, picks=picks, today=TODAY)
        assert c.pipeline_gap_days == ["2026-07-27"]
        assert c.market_gap_days == ["2026-07-28"]


class TestCoverageMaths:
    def test_market_coverage_is_over_active_days_not_calendar(self):
        """Off-days must not count against a model. A sport that plays 3 of 10
        days and emits on all 3 is at 100%, not 30%."""
        picks = [_p("2026-07-27"), _p("2026-07-28"), _p("2026-07-29")]
        c = cov.lane_coverage("mlb", "total", days=10, picks=picks, today=TODAY)
        assert c.market_coverage == pytest.approx(1.0)
        assert c.pipeline_coverage == pytest.approx(0.3)

    def test_longest_gap_counts_consecutive_days(self):
        picks = [_p("2026-07-29")]
        c = cov.lane_coverage("mlb", "total", days=5, picks=picks, today=TODAY)
        assert c.longest_gap == 4

    def test_longest_gap_zero_when_complete(self):
        picks = [_p("2026-07-28"), _p("2026-07-29")]
        c = cov.lane_coverage("mlb", "total", days=2, picks=picks, today=TODAY)
        assert c.longest_gap == 0

    def test_empty_ledger_is_not_a_divide_by_zero(self):
        c = cov.lane_coverage("mlb", "total", days=7, picks=[], today=TODAY)
        assert c.market_coverage == 0.0
        assert c.sport_active_days == 0


class TestHealthVerdict:
    def test_full_coverage_is_healthy(self):
        picks = [_p("2026-07-28"), _p("2026-07-29")]
        c = cov.lane_coverage("mlb", "total", days=2, picks=picks, today=TODAY)
        ok, msg = cov.healthy(c)
        assert ok and "2/2" in msg

    def test_silent_model_is_unhealthy_and_says_so(self):
        picks = [_p(f"2026-07-2{i}", market="moneyline") for i in range(3, 10)]
        picks.append(_p("2026-07-29", market="total"))
        c = cov.lane_coverage("mlb", "total", days=7, picks=picks, today=TODAY)
        ok, msg = cov.healthy(c)
        assert not ok
        assert "pipeline healthy, this model is not" in msg

    def test_dead_sport_is_distinguished_from_silent_model(self):
        c = cov.lane_coverage("mlb", "total", days=7, picks=[], today=TODAY)
        ok, msg = cov.healthy(c)
        assert not ok
        assert "logged nothing" in msg

    def test_threshold_is_the_documented_one(self):
        # 7 of 10 active days == exactly the floor, so it must pass.
        picks = [_p(f"2026-07-2{i}", market="moneyline") for i in range(0, 10)]
        picks += [_p(f"2026-07-2{i}", market="total") for i in range(0, 7)]
        c = cov.lane_coverage("mlb", "total", days=10, picks=picks, today=date(2026, 7, 29))
        assert c.market_coverage >= cov.MIN_MARKET_COVERAGE
        assert cov.healthy(c)[0]

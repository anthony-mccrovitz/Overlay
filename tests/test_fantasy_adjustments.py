"""Tests for age curves and depth-chart reality checks.

These are the two corrections available from data Sleeper publishes, and both
are deliberately gentle: a projection nudged 15% by a real signal is an
improvement, one swung 60% by a heuristic is a new source of error.
"""
import pytest

from src.fantasy.adjustments import (
    AGE_MAX, AGE_MIN, age_factor, depth_factor,
)


class TestAgeCurve:
    def test_peak_years_are_unpenalised(self):
        assert age_factor("RB", 25) == 1.0
        assert age_factor("WR", 26) == 1.0
        assert age_factor("QB", 30) == 1.0

    def test_running_backs_decline_faster_than_receivers(self):
        """The single most reliable ageing fact in fantasy."""
        assert age_factor("RB", 31) < age_factor("WR", 31)

    def test_quarterbacks_barely_age(self):
        assert age_factor("QB", 35) > age_factor("RB", 30)

    def test_the_tail_still_differentiates(self):
        """A 7.5%/yr decline against a 0.70 floor gave every back aged 30+ an
        identical haircut, so a 30-year-old and a 35-year-old were valued the
        same — flattening the curve exactly where it matters most."""
        assert age_factor("RB", 30) > age_factor("RB", 32) > age_factor("RB", 34)

    def test_young_players_are_still_ramping(self):
        assert age_factor("WR", 22) < 1.0
        assert age_factor("WR", 22) > 0.85

    def test_bounded_both_ways(self):
        for pos in ("RB", "WR", "TE", "QB"):
            for age in range(19, 45):
                assert AGE_MIN <= age_factor(pos, age) <= AGE_MAX

    def test_missing_age_is_neutral(self):
        assert age_factor("RB", None) == 1.0

    def test_unknown_position_is_neutral(self):
        assert age_factor("LS", 30) == 1.0


class TestDepthChart:
    def test_starter_production_in_a_starter_role_is_untouched(self):
        """The adjustment exists to catch changed circumstances, not to re-rank
        everyone who is doing exactly what his job implies."""
        assert depth_factor("RB", 1, projected_rate=1.0, pos_starter_rate=1.0) == 1.0

    def test_buried_producer_is_discounted(self):
        """Production without a job is not repeatable."""
        f = depth_factor("RB", 3, projected_rate=1.0, pos_starter_rate=1.0)
        assert f < 1.0

    def test_discount_deepens_with_depth(self):
        d2 = depth_factor("RB", 2, 1.0, 1.0)
        d4 = depth_factor("RB", 4, 1.0, 1.0)
        assert d2 > d4

    def test_never_erases_a_player(self):
        """Depth charts are a snapshot and committees exist, so the discount is
        partial by design."""
        assert depth_factor("RB", 4, 1.0, 1.0) >= 0.55

    def test_job_holder_gets_a_floor(self):
        """DC1 volume has a floor even behind a weak prior season."""
        assert depth_factor("RB", 1, projected_rate=0.4, pos_starter_rate=1.0) > 1.0

    def test_receivers_are_penalised_less_than_backs(self):
        """A WR2 sees most of a WR1's route share; a RB2 does not see a RB1's
        carries."""
        assert depth_factor("WR", 2, 1.0, 1.0) > depth_factor("RB", 2, 1.0, 1.0)

    def test_missing_depth_is_neutral(self):
        assert depth_factor("RB", None, 1.0, 1.0) == 1.0

    def test_zero_starter_rate_does_not_divide_by_zero(self):
        assert depth_factor("RB", 2, 1.0, 0.0) == 1.0

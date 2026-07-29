"""Tests for injury status and handcuff detection.

Two things a board built from last year's box scores cannot see. Tucker Kraft
(PUP, torn ACL) was appearing on the board at full value and turned up in a
simulated roster before this existed — an injured player drafted at his healthy
price is a straight loss, not a rounding error.
"""
import pytest

from src.fantasy.roster_risk import (
    NOISE_STATUSES, OUT_DISCOUNT, OUT_STATUSES, handcuffs, injury_flag,
    my_handcuffs,
)


class TestInjuryFlag:
    def test_healthy_player_is_untouched(self):
        mult, label = injury_flag({})
        assert mult == 1.0 and label == ""

    @pytest.mark.parametrize("status", sorted(OUT_STATUSES))
    def test_unavailable_designations_are_discounted(self, status):
        mult, label = injury_flag({"injury_status": status})
        assert mult == OUT_DISCOUNT
        assert status in label

    @pytest.mark.parametrize("status", sorted(NOISE_STATUSES))
    def test_week_to_week_noise_is_surfaced_not_priced(self, status):
        """August 'questionable' is mostly noise. Flag it so a human can judge;
        do not silently move the projection."""
        mult, label = injury_flag({"injury_status": status})
        assert mult == 1.0
        assert label == status

    def test_body_part_is_included_when_known(self):
        _, label = injury_flag({"injury_status": "PUP", "injury_body_part": "Knee - ACL"})
        assert "Knee - ACL" in label

    def test_discount_is_blunt_by_design(self):
        """The point is to stop him being drafted at a healthy price, not to
        forecast a return date we cannot know."""
        assert 0.2 < OUT_DISCOUNT < 0.7


def _db():
    return {
        "s1": {"position": "RB", "team": "AAA", "depth_chart_order": 1,
               "active": True, "full_name": "Starter One"},
        "b1": {"position": "RB", "team": "AAA", "depth_chart_order": 2,
               "active": True, "full_name": "Backup One"},
        "d1": {"position": "RB", "team": "AAA", "depth_chart_order": 3,
               "active": True, "full_name": "Third String"},
        "s2": {"position": "RB", "team": "BBB", "depth_chart_order": 1,
               "active": True, "full_name": "Starter Two"},
        "w1": {"position": "WR", "team": "AAA", "depth_chart_order": 1,
               "active": True, "full_name": "Receiver"},
    }


class TestHandcuffs:
    def test_pairs_the_backup_with_the_starter(self):
        hc = handcuffs("RB", _db())
        assert len(hc) == 1
        assert hc[0].starter == "Starter One" and hc[0].backup == "Backup One"

    def test_third_string_is_not_a_handcuff(self):
        """A RB3 does not inherit a startable role; he inherits a committee."""
        assert all(h.backup != "Third String" for h in handcuffs("RB", _db()))

    def test_team_without_a_backup_is_skipped(self):
        assert all(h.team != "BBB" for h in handcuffs("RB", _db()))

    def test_only_my_starters_are_worth_protecting(self):
        mine = my_handcuffs(["s1"], "RB", _db())
        assert len(mine) == 1 and mine[0].backup_id == "b1"
        assert my_handcuffs(["s2"], "RB", _db()) == []

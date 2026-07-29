"""Tests for the fantasy draft valuation engine.

The whole point of this tool is that raw points are the wrong unit. These tests
pin the reasoning that makes it different from the ranking list the other eleven
managers will draft from.
"""
import pytest

from src.fantasy import scoring
from src.fantasy.valuation import (
    PlayerValue, add_adp, add_tiers, add_vorp, starters_from_settings,
)


class TestScoring:
    def test_half_ppr_reception_value(self):
        line = {"rec": 10, "rec_yd": 100, "rec_td": 1}
        assert scoring.score(line) == pytest.approx(0.5 * 10 + 10 + 6)

    def test_league_settings_override_the_default(self):
        """A league's own rules must win. Half vs full PPR moves RB/WR ordering
        by whole rounds, so silently defaulting would corrupt the entire board."""
        line = {"rec": 10}
        assert scoring.score(line, {"rec": 1.0}) == pytest.approx(10.0)
        assert scoring.score(line, {"rec": 0.0}) == pytest.approx(0.0)

    def test_unknown_stat_keys_are_ignored(self):
        """Sleeper rows carry dozens of non-scoring keys (ranks, percentages,
        snap counts); multiplying those in would be silent nonsense."""
        line = {"rec": 2, "pos_rank_ppr": 45, "cmp_pct": 68.2, "gp": 17}
        assert scoring.score(line) == pytest.approx(1.0)

    def test_negative_scoring_applies(self):
        assert scoring.score({"pass_int": 3}) == pytest.approx(-6.0)


class TestStarterDemand:
    def test_flex_creates_fractional_demand(self):
        """A flex is not a whole extra RB. Treating it as one overstates RB
        replacement level and drags every running back's value down."""
        s = starters_from_settings(["QB", "RB", "RB", "WR", "WR", "WR",
                                    "TE", "FLEX", "K", "DEF"], teams=12)
        assert s["RB"] == pytest.approx(12 * (2 + 0.55))
        assert s["WR"] == pytest.approx(12 * (3 + 0.45))
        assert s["QB"] == 12

    def test_bench_slots_create_no_demand(self):
        a = starters_from_settings(["QB", "RB", "WR", "TE", "K", "DEF"], teams=10)
        b = starters_from_settings(["QB", "RB", "WR", "TE", "K", "DEF",
                                    "BN", "BN", "BN", "IR"], teams=10)
        assert a == b

    def test_superflex_is_mostly_a_second_qb(self):
        s = starters_from_settings(["QB", "SUPER_FLEX"], teams=12)
        assert s["QB"] > 12 * 1.8


def _mk(pid, pos, pts):
    return PlayerValue(player_id=pid, name=pid, position=pos, team="X",
                       proj_points=pts)


class TestVorp:
    def test_replacement_is_the_next_man_up(self):
        vals = {str(i): _mk(str(i), "RB", 200 - 10 * i) for i in range(6)}
        add_vorp(vals, {"RB": 3})
        # Replacement = the 4th-best RB (index 3) = 170.
        assert vals["0"].vorp == pytest.approx(200 - 170)
        assert vals["3"].vorp == pytest.approx(0.0)

    def test_high_scoring_position_can_rank_below_a_scarce_one(self):
        """The core insight: a QB outscoring every RB is still not the pick,
        because the 13th QB is nearly as good as the 2nd."""
        vals = {}
        for i in range(20):
            vals[f"qb{i}"] = _mk(f"qb{i}", "QB", 330 - 4 * i)   # tightly packed
        for i in range(20):
            vals[f"rb{i}"] = _mk(f"rb{i}", "RB", 300 - 18 * i)  # steep cliff
        add_vorp(vals, {"QB": 12, "RB": 30})
        assert vals["rb0"].vorp > vals["qb0"].vorp
        assert vals["qb0"].proj_points > vals["rb0"].proj_points

    def test_empty_position_does_not_crash(self):
        vals = {"a": _mk("a", "RB", 100)}
        add_vorp(vals, {"RB": 99})     # more starters than players
        assert vals["a"].vorp == pytest.approx(0.0)


class TestTiers:
    def test_a_cliff_starts_a_new_tier(self):
        vals = {}
        for i, pts in enumerate([200, 199, 198, 150, 149]):
            vals[str(i)] = _mk(str(i), "RB", pts)
        add_vorp(vals, {"RB": 99})
        add_tiers(vals)
        assert vals["0"].tier == vals["1"].tier == vals["2"].tier
        assert vals["3"].tier > vals["2"].tier

    def test_flat_group_is_one_tier(self):
        vals = {str(i): _mk(str(i), "WR", 200 - i) for i in range(6)}
        add_vorp(vals, {"WR": 99})
        add_tiers(vals)
        assert len({v.tier for v in vals.values()}) == 1


class TestAdpArbitrage:
    def test_positive_delta_means_he_falls_to_you(self):
        """adp_delta > 0 = market drafts him later than we rank him. That is the
        entire draft-day edge: taking value that slides."""
        vals = {"a": _mk("a", "RB", 300), "b": _mk("b", "RB", 100)}
        add_vorp(vals, {"RB": 99})
        add_adp(vals, {"a": 1.0, "b": 40.0})
        assert vals["b"].adp_delta > 0        # we rank 2nd, market 40th
        assert vals["a"].adp_delta == pytest.approx(0.0)

    def test_missing_adp_is_not_invented(self):
        vals = {"a": _mk("a", "TE", 100)}
        add_vorp(vals, {"TE": 12})
        add_adp(vals, {})
        assert vals["a"].adp is None and vals["a"].adp_delta is None

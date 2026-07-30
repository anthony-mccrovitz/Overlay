"""Ceiling and floor must be directional, damped, and honest about being an estimate.

WHY: the draft board ranked on VORP alone — an EXPECTATION. Two players with the
same projection are not interchangeable: one grinds 14 a week, the other posts 4
and 31. Clustering on volatility and drafting the high-variance players is the
documented way to climb a table, because you cannot catch a leader by matching
them.

This estimates volatility from structural drivers (position, depth, sample size,
age, injury flag) because we do not store weekly game logs. These tests pin the
properties that make the estimate usable rather than decorative.
"""
import pytest

from src.fantasy.volatility import estimate, draft_posture, _POS_BASE


def test_touchdown_dependent_positions_are_swingier():
    """RB/TE lean on touchdowns, which arrive in clumps. QB/WR sit on volume."""
    assert _POS_BASE["TE"] > _POS_BASE["WR"]
    assert _POS_BASE["RB"] > _POS_BASE["QB"]
    rb = estimate("RB", 250)
    qb = estimate("QB", 250)
    assert rb.sigma_pct > qb.sigma_pct


def test_a_committee_role_widens_the_range():
    starter = estimate("RB", 250, depth=1)
    committee = estimate("RB", 250, depth=2)
    buried = estimate("RB", 250, depth=3)
    assert buried.sigma_pct > committee.sigma_pct > starter.sigma_pct
    assert starter.ceiling < buried.ceiling


def test_a_thin_sample_counts_as_uncertainty():
    """Not knowing is itself a form of variance."""
    full = estimate("WR", 250, games_2025=17)
    thin = estimate("WR", 250, games_2025=6)
    assert thin.sigma_pct > full.sigma_pct


def test_an_injury_flag_widens_it():
    clean = estimate("RB", 250, note="")
    flagged = estimate("RB", 250, note="Questionable")
    assert flagged.sigma_pct > clean.sigma_pct
    assert "injury" in flagged.drivers


def test_season_range_is_damped_relative_to_weekly_spread():
    """THE property that keeps this honest. Week-to-week noise partially cancels
    across a season, so a season range must be far tighter than sigma implies.
    Skipping the damping would overstate every ceiling on the board."""
    v = estimate("RB", 250, depth=1)
    weekly_naive = v.sigma_pct * 250          # if we ignored cancellation
    season_half = v.ceiling - 250
    assert season_half < weekly_naive * 0.5, (
        "season range is not damped — ceilings will be fantasy"
    )


def test_floor_never_goes_negative():
    v = estimate("DEF", 12, depth=3, games_2025=2, note="Out")
    assert v.floor >= 0.0


def test_ceiling_brackets_the_projection():
    v = estimate("WR", 300)
    assert v.floor < 300 < v.ceiling


def test_sigma_is_bounded():
    """No single missing field may dominate. An estimate that swings wildly on
    one unknown would be worse than the VORP-only board it improves."""
    worst = estimate("DEF", 100, depth=3, games_2025=1, age_factor=0.5, note="Out")
    best = estimate("QB", 300, depth=1, games_2025=17, age_factor=1.1)
    assert 0.15 <= best.sigma_pct <= worst.sigma_pct <= 0.85


def test_labels_partition_the_range():
    assert estimate("QB", 250, depth=1).label in ("STEADY", "BALANCED")
    assert estimate("TE", 250, depth=3, note="Questionable").label == "SWINGY"


def test_posture_is_directional_not_a_verdict():
    """Variance is not good or bad — it depends on whether you are chasing."""
    chase = draft_posture("SWINGY", chasing=True)
    protect = draft_posture("SWINGY", chasing=False)
    assert chase != protect
    assert "cannot catch" in chase
    assert "risky" in protect


def test_maverick_flag_matches_the_label():
    assert estimate("TE", 250, depth=3, note="Questionable").is_maverick
    assert not estimate("QB", 250, depth=1).is_maverick

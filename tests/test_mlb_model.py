import math

from src.models.mlb_model import (
    pythagorean_win_pct,
    log5,
    predict_game,
    _pitcher_adjusted_ra,
    _early_season_blend,
)
from src.data.mlb_stats import TeamStats, PitcherStats, Matchup


def _team(name="Team A", rs=4.5, ra=4.0, era=3.80, games=80, wins=44, losses=36) -> TeamStats:
    return TeamStats(
        team_id=1, name=name, games=games,
        runs_scored=rs * games, runs_allowed=ra * games,
        rs_per_game=rs, ra_per_game=ra, ops=0.750, era=era,
        whip=1.20, wins=wins, losses=losses,
    )


def _pitcher(name="Ace", era=2.80, ip=90.0) -> PitcherStats:
    return PitcherStats(
        player_id=1, name=name, era=era, whip=1.00,
        innings_pitched=ip, k_per_9=9.0, bb_per_9=2.5, games_started=15,
    )


# ---- Pythagorean ----

def test_pythagorean_balanced():
    assert pythagorean_win_pct(4.5, 4.5) == 0.5


def test_pythagorean_good_team():
    pct = pythagorean_win_pct(5.0, 3.5)
    assert 0.60 < pct < 0.75


def test_pythagorean_bad_team():
    pct = pythagorean_win_pct(3.0, 5.0)
    assert 0.25 < pct < 0.40


def test_pythagorean_zero_runs():
    assert pythagorean_win_pct(0, 0) == 0.5
    assert pythagorean_win_pct(4.5, 0) == 0.95
    assert pythagorean_win_pct(0, 4.5) == 0.05


# ---- Log5 ----

def test_log5_equal_teams():
    assert log5(0.5, 0.5) == 0.5


def test_log5_strong_vs_weak():
    p = log5(0.65, 0.35)
    assert 0.75 < p < 0.90


def test_log5_symmetric():
    p_ab = log5(0.60, 0.40)
    p_ba = log5(0.40, 0.60)
    assert abs(p_ab + p_ba - 1.0) < 1e-10


# ---- Pitcher adjustment ----

def test_pitcher_adjustment_ace():
    team = _team(ra=4.0, era=4.00)
    ace = _pitcher(era=2.50, ip=100)
    adjusted = _pitcher_adjusted_ra(team, ace)
    assert adjusted < 4.0


def test_pitcher_adjustment_bad_pitcher():
    team = _team(ra=4.0, era=4.00)
    bad = _pitcher(era=6.00, ip=80)
    adjusted = _pitcher_adjusted_ra(team, bad)
    assert adjusted > 4.0


def test_pitcher_adjustment_no_pitcher():
    team = _team(ra=4.0, era=4.00)
    adjusted = _pitcher_adjusted_ra(team, None)
    assert adjusted == 4.0


def test_pitcher_adjustment_tiny_sample():
    team = _team(ra=4.0, era=4.00)
    rookie = _pitcher(era=1.50, ip=5.0)
    adjusted = _pitcher_adjusted_ra(team, rookie)
    assert adjusted == 4.0  # not trusted yet


# ---- Early season blend ----

def test_early_season_shrinks_to_avg():
    team = _team(rs=7.0, ra=2.0, games=5)
    blended = _early_season_blend(team)
    assert blended.rs_per_game < 7.0
    assert blended.ra_per_game > 2.0


def test_full_season_no_change():
    team = _team(rs=5.5, ra=3.0, games=80)
    blended = _early_season_blend(team)
    assert blended.rs_per_game == 5.5
    assert blended.ra_per_game == 3.0


# ---- Full prediction ----

def test_predict_game_returns_valid_prob():
    m = Matchup(
        game_id=1,
        game_time="2026-03-30T18:00:00Z",
        home_team=_team("Orioles", rs=5.0, ra=3.5, era=3.30),
        away_team=_team("Yankees", rs=4.2, ra=4.5, era=4.20),
        home_pitcher=_pitcher("Burnes", era=2.80),
        away_pitcher=_pitcher("Cole", era=3.20),
    )
    pred = predict_game(m)
    assert 0.05 <= pred.home_win_prob <= 0.95
    assert pred.home_team == "Orioles"
    assert pred.away_team == "Yankees"
    assert len(pred.edge_drivers) > 0


def test_predict_game_home_team_should_be_favored():
    m = Matchup(
        game_id=2,
        game_time="2026-03-30T18:00:00Z",
        home_team=_team("Dodgers", rs=5.5, ra=3.0, era=3.00),
        away_team=_team("Rockies", rs=3.5, ra=5.5, era=5.50),
        home_pitcher=_pitcher("Ace SP", era=2.50),
        away_pitcher=_pitcher("Bad SP", era=5.80),
    )
    pred = predict_game(m)
    assert pred.home_win_prob > 0.65

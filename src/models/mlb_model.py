"""
MLB game prediction using Pythagorean expectation + pitcher adjustment + Log5.

This is a proven sabermetric approach (Bill James). It doesn't need training
data — it works from first principles using run scoring and run prevention.

For a given game:
  1. Compute each team's "true talent" win% via Pythagorean expectation
  2. Adjust for the specific starting pitcher vs team average
  3. Use Log5 to compute P(home wins) from two "true talent" levels
  4. Apply home field advantage (~53.8% historical)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from src.data.mlb_stats import Matchup, TeamStats, PitcherStats

PYTH_EXPONENT = 1.83
HOME_FIELD_ADVANTAGE = 0.038  # ~53.8% historical home win rate vs 50%
SP_INNINGS_WEIGHT = 0.55      # SP covers ~55% of game pitching


@dataclass
class GamePrediction:
    game_id: int
    home_team: str
    away_team: str
    home_win_prob: float
    home_pitcher: str
    away_pitcher: str
    home_pyth: float
    away_pyth: float
    edge_drivers: list[str]


def pythagorean_win_pct(rs_per_game: float, ra_per_game: float, exponent: float = PYTH_EXPONENT) -> float:
    """
    Bill James Pythagorean expectation.
    W% = RS^x / (RS^x + RA^x)
    """
    if rs_per_game <= 0 and ra_per_game <= 0:
        return 0.5
    if ra_per_game <= 0:
        return 0.95
    if rs_per_game <= 0:
        return 0.05

    rs_x = rs_per_game ** exponent
    ra_x = ra_per_game ** exponent
    return rs_x / (rs_x + ra_x)


def log5(p_a: float, p_b: float) -> float:
    """
    Bill James Log5: P(A beats B) given each team's true talent win%.
    Handles the "common opponent" problem.
    """
    p_a = max(0.01, min(0.99, p_a))
    p_b = max(0.01, min(0.99, p_b))
    return (p_a - p_a * p_b) / (p_a + p_b - 2 * p_a * p_b)


def _pitcher_adjusted_ra(
    team: TeamStats,
    pitcher: PitcherStats | None,
) -> float:
    """
    Adjust team's RA/game for the specific starting pitcher.

    If the SP is better than team average, the team allows fewer runs today.
    SP covers ~55% of innings; bullpen covers the rest at team-average rate.
    """
    base_ra = team.ra_per_game
    if base_ra <= 0:
        base_ra = 4.5  # league average fallback

    if pitcher is None or pitcher.era <= 0 or team.era <= 0:
        return base_ra

    # Avoid extreme adjustments from tiny sample sizes
    if pitcher.innings_pitched < 10:
        return base_ra

    # SP's ERA relative to team ERA, bounded to avoid wild swings
    ratio = max(0.3, min(2.5, pitcher.era / team.era))
    adjusted = base_ra * (SP_INNINGS_WEIGHT * ratio + (1 - SP_INNINGS_WEIGHT))
    return adjusted


def _early_season_blend(team: TeamStats, league_avg_rpg: float = 4.5) -> TeamStats:
    """
    Early in the season, shrink team stats toward league average
    to avoid noise from small samples.

    Fully trust current-season stats after ~30 games.
    """
    if team.games >= 30:
        return team

    import copy
    blended = copy.copy(team)
    w = min(team.games / 30.0, 1.0)

    blended.rs_per_game = w * team.rs_per_game + (1 - w) * league_avg_rpg
    blended.ra_per_game = w * team.ra_per_game + (1 - w) * league_avg_rpg
    if team.era > 0:
        blended.era = w * team.era + (1 - w) * 4.50
    else:
        blended.era = 4.50

    return blended


def predict_game(matchup: Matchup) -> GamePrediction:
    """
    Predict P(home team wins) for a single MLB game.
    """
    home = _early_season_blend(matchup.home_team)
    away = _early_season_blend(matchup.away_team)

    # Adjust RA/game for opposing starting pitcher
    # Home team faces away pitcher → their RS is adjusted
    # Away team faces home pitcher → their RS is adjusted
    home_adj_ra = _pitcher_adjusted_ra(home, matchup.home_pitcher)
    away_adj_ra = _pitcher_adjusted_ra(away, matchup.away_pitcher)

    home_pyth = pythagorean_win_pct(home.rs_per_game, home_adj_ra)
    away_pyth = pythagorean_win_pct(away.rs_per_game, away_adj_ra)

    raw_prob = log5(home_pyth, away_pyth)

    # Home field advantage
    home_win_prob = max(0.05, min(0.95, raw_prob + HOME_FIELD_ADVANTAGE))

    # Build explanation drivers
    drivers = _build_drivers(home, away, matchup.home_pitcher, matchup.away_pitcher)

    return GamePrediction(
        game_id=matchup.game_id,
        home_team=home.name,
        away_team=away.name,
        home_win_prob=home_win_prob,
        home_pitcher=matchup.home_pitcher.name if matchup.home_pitcher else "TBD",
        away_pitcher=matchup.away_pitcher.name if matchup.away_pitcher else "TBD",
        home_pyth=home_pyth,
        away_pyth=away_pyth,
        edge_drivers=drivers,
    )


def predict_all_games(matchups: list[Matchup]) -> list[GamePrediction]:
    return [predict_game(m) for m in matchups]


def predictions_to_dict(preds: list[GamePrediction]) -> dict[tuple[str, str], float]:
    """
    Convert predictions to the format expected by find_value_bets().
    Returns dict of (home_team, away_team) → P(home wins).
    """
    return {(p.home_team, p.away_team): p.home_win_prob for p in preds}


def _build_drivers(
    home: TeamStats,
    away: TeamStats,
    home_pitcher: PitcherStats | None,
    away_pitcher: PitcherStats | None,
) -> list[str]:
    drivers = []

    rs_diff = home.rs_per_game - away.rs_per_game
    if abs(rs_diff) > 0.5:
        better = "Home" if rs_diff > 0 else "Away"
        drivers.append(
            f"{better} offense stronger ({max(home.rs_per_game, away.rs_per_game):.1f} vs "
            f"{min(home.rs_per_game, away.rs_per_game):.1f} R/G)."
        )

    if home_pitcher and away_pitcher and home_pitcher.era > 0 and away_pitcher.era > 0:
        era_diff = away_pitcher.era - home_pitcher.era
        if abs(era_diff) > 0.75:
            better_name = home_pitcher.name if era_diff > 0 else away_pitcher.name
            better_era = min(home_pitcher.era, away_pitcher.era)
            worse_era = max(home_pitcher.era, away_pitcher.era)
            drivers.append(f"Pitching edge: {better_name} ({better_era:.2f} ERA vs {worse_era:.2f}).")

    ra_diff = home.ra_per_game - away.ra_per_game
    if abs(ra_diff) > 0.5:
        better = "Home" if ra_diff < 0 else "Away"
        drivers.append(f"{better} allows fewer runs ({min(home.ra_per_game, away.ra_per_game):.1f} vs "
                       f"{max(home.ra_per_game, away.ra_per_game):.1f} RA/G).")

    if not drivers:
        drivers.append("Close matchup — edge from home field + statistical margins.")

    return drivers[:3]

"""
Multi-market betting architecture.

Defines bet types, market-aware edge detection, and the registry that
connects prediction models to odds markets.
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass


class BetType(str, Enum):
    """All supported bet types."""
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"
    TEAM_TOTAL = "team_total"
    NRFI = "nrfi"
    F5_ML = "f5_moneyline"
    F5_SPREAD = "f5_spread"
    F5_TOTAL = "f5_total"
    PITCHER_KS = "pitcher_strikeouts"
    PITCHER_HITS = "pitcher_hits_allowed"
    PITCHER_EARNED_RUNS = "pitcher_earned_runs"
    BATTER_HITS = "batter_hits"
    BATTER_TOTAL_BASES = "batter_total_bases"
    BATTER_HOME_RUNS = "batter_home_runs"
    BATTER_RBIS = "batter_rbis"
    BATTER_RUNS = "batter_runs_scored"
    BATTER_STRIKEOUTS = "batter_strikeouts"
    FUTURES_WS = "futures_world_series"
    FUTURES_DIVISION = "futures_division"


# Maps BetType to the Odds API market key
ODDS_API_MARKET_MAP: dict[BetType, str] = {
    BetType.MONEYLINE: "h2h",
    BetType.SPREAD: "spreads",
    BetType.TOTAL: "totals",
    BetType.TEAM_TOTAL: "team_totals",
    BetType.NRFI: "h2h_1st_1_innings",
    BetType.F5_ML: "h2h_1st_5_innings",
    BetType.F5_TOTAL: "totals_1st_5_innings",
    BetType.PITCHER_KS: "pitcher_strikeouts",
    BetType.PITCHER_HITS: "pitcher_hits_allowed",
    BetType.PITCHER_EARNED_RUNS: "pitcher_earned_runs",
    BetType.BATTER_HITS: "batter_hits",
    BetType.BATTER_TOTAL_BASES: "batter_total_bases",
    BetType.BATTER_HOME_RUNS: "batter_home_runs",
    BetType.BATTER_RBIS: "batter_rbis",
    BetType.BATTER_RUNS: "batter_runs_scored",
    BetType.BATTER_STRIKEOUTS: "batter_strikeouts",
    BetType.FUTURES_WS: "outrights",
    BetType.FUTURES_DIVISION: "outrights",
}


@dataclass
class MarketPrediction:
    """A model prediction for a specific market."""
    bet_type: BetType
    game_id: str
    team: str
    opponent: str

    # For binary outcomes (ML, spread, NRFI)
    model_prob: float | None = None

    # For continuous outcomes (totals, props)
    predicted_value: float | None = None
    line: float | None = None  # The market line (e.g., O/U 8.5)
    over_prob: float | None = None  # P(actual > line)

    # Player props
    player_name: str | None = None
    player_id: int | None = None

    # Common
    best_odds: int = 0
    sportsbook: str = ""
    edge: float = 0.0
    implied_prob: float = 0.5
    commence_time: str = ""


# Which bet types are game-level (one per game)
GAME_LEVEL_MARKETS = {
    BetType.MONEYLINE, BetType.SPREAD, BetType.TOTAL, BetType.TEAM_TOTAL,
    BetType.NRFI, BetType.F5_ML, BetType.F5_SPREAD, BetType.F5_TOTAL,
}

# Which bet types are player-level (multiple per game)
PLAYER_LEVEL_MARKETS = {
    BetType.PITCHER_KS, BetType.PITCHER_HITS, BetType.PITCHER_EARNED_RUNS,
    BetType.BATTER_HITS, BetType.BATTER_TOTAL_BASES, BetType.BATTER_HOME_RUNS,
    BetType.BATTER_RBIS, BetType.BATTER_RUNS, BetType.BATTER_STRIKEOUTS,
}

# Which bet types are over/under style
OVER_UNDER_MARKETS = {
    BetType.TOTAL, BetType.TEAM_TOTAL, BetType.F5_TOTAL,
    BetType.PITCHER_KS, BetType.PITCHER_HITS, BetType.PITCHER_EARNED_RUNS,
    BetType.BATTER_HITS, BetType.BATTER_TOTAL_BASES, BetType.BATTER_HOME_RUNS,
    BetType.BATTER_RBIS, BetType.BATTER_RUNS, BetType.BATTER_STRIKEOUTS,
}

# Bet types that use the standard per-event API endpoint
EVENT_ODDS_MARKETS = PLAYER_LEVEL_MARKETS | {
    BetType.NRFI, BetType.F5_ML, BetType.F5_SPREAD, BetType.F5_TOTAL,
}

"""
Central configuration for Overlay models.
Import from here instead of hardcoding thresholds per-file.
"""

# Minimum edge required to surface a bet, by market and sport
MIN_EDGE = {
    "moneyline": {"mlb": 0.03, "baseball_mlb": 0.03, "nba": 0.04, "basketball_nba": 0.04, "nhl": 0.05, "icehockey_nhl": 0.05},
    "spread":    {"mlb": 0.4,  "baseball_mlb": 0.4,  "nba": 0.04, "basketball_nba": 0.04, "nhl": 0.05, "icehockey_nhl": 0.05},
    "total":     {"mlb": 1.5,  "baseball_mlb": 1.5,  "nba": 0.04, "basketball_nba": 0.04, "nhl": 0.05, "icehockey_nhl": 0.05},
    "prop":      {"mlb": 0.04, "baseball_mlb": 0.04, "nba": 0.05, "basketball_nba": 0.05, "nhl": 0.05, "icehockey_nhl": 0.05},
    "nrfi":      {"mlb": 0.04, "baseball_mlb": 0.04},
}

# Kelly criterion settings
KELLY_FRACTION = 0.25    # 25% fractional Kelly — conservative, protects bankroll
MAX_BET_PCT    = 0.05    # never stake more than 5% of bankroll on a single pick

# Model normal distribution sigmas (single-game spread variance)
SPREAD_SIGMA = {
    "nba": 12.0,   # pts
    "nhl": 1.8,    # goals
    "mlb": 2.8,    # runs (for totals model)
}

# Minimum graded picks required before a calibration update is trusted
CALIBRATION_MIN_PICKS = 30


def get_min_edge(market: str, sport: str) -> float:
    """Return the minimum edge threshold for a given market + sport."""
    sport_key = sport.lower().replace("baseball_", "").replace("basketball_", "").replace("icehockey_", "")
    market_thresholds = MIN_EDGE.get(market.lower(), {})
    # Try full sport key first, then short form
    return market_thresholds.get(sport.lower(), market_thresholds.get(sport_key, 0.04))

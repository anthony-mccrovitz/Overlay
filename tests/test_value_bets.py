"""
Tests for value_bets.py edge cases introduced/fixed in session.
"""
import math
import pandas as pd
import pytest
from unittest.mock import patch

from src.betting.value_bets import find_value_bets
from src.betting.markets import BetType

# Calibration is trained on real data and is irrelevant to edge-detection logic.
# These tests patch it to a no-op so they verify pure pick/skip reasoning.
_NO_CAL = patch("src.betting.value_bets.apply_calibration", side_effect=lambda p, *a, **kw: p)


def _odds_row(home="Team A", away="Team B", home_ml=None, away_ml=None):
    """Build a minimal odds_df row."""
    h = float(home_ml) if home_ml is not None else float("nan")
    a = float(away_ml) if away_ml is not None else float("nan")

    def _imp(ml):
        if math.isnan(ml):
            return 0.5
        if ml > 0:
            return 100 / (ml + 100)
        return abs(ml) / (abs(ml) + 100)

    return pd.DataFrame([{
        "GameID": "g1",
        "HomeTeam": home,
        "AwayTeam": away,
        "BestHomeML": h,
        "BestAwayML": a,
        "BestHomeSportsbook": "FanDuel" if not math.isnan(h) else "",
        "BestAwaySportsbook": "DraftKings" if not math.isnan(a) else "",
        "HomeImpliedProb": _imp(h),
        "AwayImpliedProb": _imp(a),
        "ConsensusSpread": 0,
        "CommenceTime": "2026-04-13T17:05:00Z",
    }])


# ── NaN moneyline guard ───────────────────────────────────────────────────────

def test_nan_moneyline_both_skipped():
    """When a game is live (both MLs are NaN), no fake edge should be reported."""
    odds = _odds_row(home_ml=None, away_ml=None)
    preds = {("Team A", "Team B"): 0.65}
    bets = find_value_bets(preds, odds, min_edge=0.03, market=BetType.MONEYLINE)
    assert bets.empty, "Live game with NaN odds should produce 0 value bets"


def test_nan_moneyline_home_only_skipped():
    """If only home ML is NaN, skip the game entirely (conservative)."""
    odds = _odds_row(home_ml=None, away_ml=150)
    preds = {("Team A", "Team B"): 0.65}
    bets = find_value_bets(preds, odds, min_edge=0.03, market=BetType.MONEYLINE)
    assert bets.empty, "Game with partial NaN odds should be skipped"


def test_real_odds_finds_edge():
    """With valid odds and genuine model edge, value bet is found."""
    # Home -110 → implied 52.4%. Model says 62% → edge ~9.6%
    odds = _odds_row(home_ml=-110, away_ml=100)
    preds = {("Team A", "Team B"): 0.62}
    with _NO_CAL:
        bets = find_value_bets(preds, odds, min_edge=0.03, market=BetType.MONEYLINE)
    assert len(bets) == 1
    assert bets.iloc[0]["Team"] == "Team A"
    assert bets.iloc[0]["BestOdds"] == -110
    assert bets.iloc[0]["Edge"] > 0.09


def test_no_edge_below_threshold():
    """Model prob barely above implied → no bet at 3% threshold."""
    # Home -110 → implied 52.4%. Model says 54% → edge ~1.6%
    odds = _odds_row(home_ml=-110, away_ml=100)
    preds = {("Team A", "Team B"): 0.54}
    with _NO_CAL:
        bets = find_value_bets(preds, odds, min_edge=0.03, market=BetType.MONEYLINE)
    assert bets.empty


def test_away_team_edge_detected():
    """Edge on the away side is correctly identified."""
    # Away +150 → implied 40%. Model says 52% on away → edge ~12%
    odds = _odds_row(home_ml=-170, away_ml=150)
    preds = {("Team A", "Team B"): 0.48}  # 48% home = 52% away
    with _NO_CAL:
        bets = find_value_bets(preds, odds, min_edge=0.03, market=BetType.MONEYLINE)
    assert len(bets) == 1
    assert bets.iloc[0]["Team"] == "Team B"
    assert bets.iloc[0]["BestOdds"] == 150

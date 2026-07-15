"""
tests/test_props.py — Unit tests for individual prop prediction models.

Tests each model in isolation with synthetic inputs (no API calls, no disk models).
Covers the inference path and the fallback path when no trained model exists.

Run: python3 -m pytest tests/test_props.py -v
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import numpy as np


# ─────────────────────────── NRFI model (src/data/nrfi.py) ──────────────────

class TestNRFIProjection:
    def test_league_average_pitchers(self):
        from src.data.nrfi import project_nrfi
        p = project_nrfi(
            home_sp_era=4.20, home_sp_k9=8.5,
            away_sp_era=4.20, away_sp_k9=8.5,
        )
        # League-average matchup → close to baseline ~67%
        assert 0.60 <= p <= 0.75

    def test_ace_vs_ace(self):
        from src.data.nrfi import project_nrfi
        p = project_nrfi(
            home_sp_era=2.50, home_sp_k9=11.0,
            away_sp_era=2.50, away_sp_k9=11.0,
        )
        # Both aces → higher NRFI probability
        assert p > 0.65

    def test_weak_pitchers_lower_nrfi(self):
        from src.data.nrfi import project_nrfi
        p_weak = project_nrfi(
            home_sp_era=5.50, home_sp_k9=6.0,
            away_sp_era=5.50, away_sp_k9=6.0,
        )
        p_avg = project_nrfi(
            home_sp_era=4.20, home_sp_k9=8.5,
            away_sp_era=4.20, away_sp_k9=8.5,
        )
        assert p_weak < p_avg

    def test_ace_vs_mop_asymmetry(self):
        from src.data.nrfi import project_nrfi
        # Same home SP, different away SP → should differ
        p_ace = project_nrfi(2.50, 11.0, 2.50, 11.0)
        p_mop = project_nrfi(2.50, 11.0, 6.00, 5.5)
        assert p_ace > p_mop

    def test_output_is_valid_probability(self):
        from src.data.nrfi import project_nrfi
        p = project_nrfi(3.0, 10.0, 4.5, 8.0)
        assert 0.0 < p < 1.0

    def test_devig_removes_vig(self):
        from src.data.nrfi import _devig
        # Symmetric -110 / -110 market → 50/50 fair probability
        p = _devig(-110, -110)
        assert abs(p - 0.5) < 0.01

    def test_devig_favorite(self):
        from src.data.nrfi import _devig
        # -150 / +130 → YRFI is the favorite
        p_yrfi = _devig(-150, 130)
        assert p_yrfi > 0.5

    def test_find_nrfi_edges_no_odds_fallback(self):
        """When book data unavailable, edges still generated with no_odds=True."""
        from src.data.nrfi import find_nrfi_edges
        inputs = [{
            "home_team": "Yankees",
            "away_team": "Red Sox",
            "home_sp_name": "Cole",
            "home_sp_era": 3.0,
            "home_sp_k9": 10.5,
            "away_sp_name": "Sale",
            "away_sp_era": 3.5,
            "away_sp_k9": 9.5,
            "event_id": None,
        }]
        # Patch API key to empty string → forces no_odds path
        with patch("src.data.nrfi._api_key", return_value=None):
            with patch("src.data.player_props.fetch_mlb_event_ids", return_value=[]):
                edges = find_nrfi_edges(inputs, min_edge=0.0)
        assert len(edges) == 1
        assert edges[0]["no_odds"] is True
        assert "stake" not in edges[0]  # stake is set downstream in pnl logging, not in edge dict

    def test_nrfi_card_filters_no_odds(self):
        """Picks with no_odds=True must not reach the card renderer."""
        with_odds = {"direction": "NRFI", "no_odds": False, "edge_pct": 8.5, "odds": -130}
        without_odds = {"direction": "NRFI", "no_odds": True, "edge_pct": None, "odds": -120}
        plays = [with_odds, without_odds]
        live = [p for p in plays if not p.get("no_odds")]
        assert len(live) == 1
        assert live[0]["edge_pct"] == 8.5


# ─────────────────────────── Pitcher Ks (mlb_pitcher_ks.py) ─────────────────

class TestPitcherKsModel:
    def test_predict_no_model_uses_fallback(self):
        """When pkl not present, returns k9/9 * avg_ip estimate."""
        from src.models.mlb_pitcher_ks import predict_pitcher_ks
        with patch("src.models.mlb_pitcher_ks.load_pitcher_ks_model", return_value=None):
            result = predict_pitcher_ks(pitcher_k9=9.0, pitcher_avg_ip=6.0)
        # Fallback: 9.0/9 * 6.0 = 6.0
        assert abs(result - 6.0) < 0.01

    def test_predict_with_mock_model(self):
        """With a mock model, predict() is called on the feature row."""
        from src.models.mlb_pitcher_ks import predict_pitcher_ks, KS_FEATURES
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([7.2])
        with patch("src.models.mlb_pitcher_ks.load_pitcher_ks_model",
                   return_value=(mock_model, KS_FEATURES)):
            result = predict_pitcher_ks(
                pitcher_k9=10.0, pitcher_bb9=2.5, pitcher_avg_ip=6.0,
                pitcher_era=2.8, pitcher_whip=1.1, pitcher_starts=15,
                pitcher_recent_k_avg=8.0, opp_team_k_rate=0.25,
            )
        assert result == pytest.approx(7.2)
        mock_model.predict.assert_called_once()

    def test_features_used_by_model(self):
        """All KS_FEATURES are present in the feature vector sent to predict."""
        from src.models.mlb_pitcher_ks import predict_pitcher_ks, KS_FEATURES
        import pandas as pd
        captured_X = {}

        def capture(X):
            captured_X["df"] = X
            return np.array([6.5])

        mock_model = MagicMock()
        mock_model.predict.side_effect = capture
        with patch("src.models.mlb_pitcher_ks.load_pitcher_ks_model",
                   return_value=(mock_model, KS_FEATURES)):
            predict_pitcher_ks()

        assert set(captured_X["df"].columns) == set(KS_FEATURES)

    def test_high_k9_predicts_more_ks(self):
        """Ace pitcher (high K/9) fallback predicts more Ks than average."""
        from src.models.mlb_pitcher_ks import predict_pitcher_ks
        with patch("src.models.mlb_pitcher_ks.load_pitcher_ks_model", return_value=None):
            ace = predict_pitcher_ks(pitcher_k9=13.0, pitcher_avg_ip=6.0)
            avg = predict_pitcher_ks(pitcher_k9=7.0, pitcher_avg_ip=6.0)
        assert ace > avg


# ─────────────────────────── Batter Props (mlb_batter_props.py) ──────────────

class TestBatterPropsModel:
    def test_predict_no_model_uses_fallback(self):
        """Without pkl, returns season-average estimates for all targets."""
        from src.models.mlb_batter_props import predict_batter_props
        with patch("src.models.mlb_batter_props.load_batter_props_model", return_value=None):
            result = predict_batter_props(
                batter_hits_per_game=1.1,
                batter_tb_per_game=1.7,
                batter_hr_per_game=0.06,
                batter_rbi_per_game=0.5,
                batter_runs_per_game=0.5,
            )
        assert result["hits"] == pytest.approx(1.1)
        assert result["total_bases"] == pytest.approx(1.7)
        assert result["home_runs"] == pytest.approx(0.06)

    def test_predict_returns_all_targets(self):
        """predict_batter_props must return all 5 prop targets."""
        from src.models.mlb_batter_props import predict_batter_props, PROP_TARGETS
        with patch("src.models.mlb_batter_props.load_batter_props_model", return_value=None):
            result = predict_batter_props()
        for t in PROP_TARGETS:
            assert t in result

    def test_predict_with_mock_models(self):
        """With mock per-target models, each model's predict() is called."""
        from src.models.mlb_batter_props import predict_batter_props, PROP_TARGETS, BATTER_FEATURES
        mock_models = {}
        for t in PROP_TARGETS:
            m = MagicMock()
            m.predict.return_value = np.array([1.5])
            mock_models[t] = m

        with patch("src.models.mlb_batter_props.load_batter_props_model",
                   return_value=(mock_models, BATTER_FEATURES, PROP_TARGETS)):
            result = predict_batter_props()

        for t in PROP_TARGETS:
            assert result[t] == pytest.approx(1.5)
            mock_models[t].predict.assert_called_once()

    def test_good_batter_predicts_more_hits(self):
        """High-average batter fallback: hits_per_game input passed through."""
        from src.models.mlb_batter_props import predict_batter_props
        with patch("src.models.mlb_batter_props.load_batter_props_model", return_value=None):
            good = predict_batter_props(batter_hits_per_game=1.5)
            poor = predict_batter_props(batter_hits_per_game=0.6)
        assert good["hits"] > poor["hits"]


# ─────────────────────────── Player Props edge finder (player_props.py) ──────

class TestPlayerPropsEdgeFinder:
    def test_devig_strikeouts(self):
        """De-vig of over/under strikeout line produces sensible fair probability."""
        from src.data.player_props import _devig
        # -120 / +100 → over is ~54.5% fair
        p = _devig(-120, 100)
        assert 0.50 < p < 0.60

    def test_devig_symmetric(self):
        """Even odds (-110/-110 both sides) → 50% fair."""
        from src.data.player_props import _devig
        p = _devig(-110, -110)
        assert abs(p - 0.5) < 0.02

    def test_find_prop_edges_no_key_returns_empty(self):
        """Without API key, find_prop_edges returns []."""
        from src.data.player_props import find_prop_edges
        with patch("src.data.player_props._api_key", return_value=None):
            edges = find_prop_edges([{
                "home_team": "Cubs", "away_team": "Cardinals",
                "home_sp_k9": 8.0, "away_sp_k9": 8.0,
            }])
        assert edges == []


# ─────────────────────────── Batter Props edge finder (mlb_batter_props.py) ─

class TestBatterPropsEdgeFinder:
    def test_find_batter_prop_edges_no_key_returns_empty(self):
        """Without API key, find_batter_prop_edges returns []."""
        from src.data.mlb_batter_props import find_batter_prop_edges
        with patch("src.data.mlb_batter_props._api_key", return_value=None):
            edges = find_batter_prop_edges([{
                "home_team": "Cubs", "away_team": "Cardinals",
                "home_sp_whip": 1.3, "away_sp_whip": 1.3,
                "home_sp_hr9": 1.2, "away_sp_hr9": 1.2,
            }])
        assert edges == []


# ─────────────────────────── Model registry ──────────────────────────────────

class TestModelRegistry:
    def test_nba_totals_is_live(self):
        from src.config.models import is_live
        assert is_live("nba", "total") is True

    def test_mlb_spread_is_incubating(self):
        # mlb·spread has not cleared the CLV gate (negative ROI) — stays shadow.
        from src.config.models import is_live
        assert is_live("mlb", "spread") is False

    def test_nrfi_is_incubating(self):
        from src.config.models import is_live, model_status
        assert is_live("mlb", "nrfi") is False
        assert model_status("mlb", "nrfi") == "incubating"

    def test_pitcher_ks_is_incubating(self):
        from src.config.models import is_live
        assert is_live("mlb", "pitcher_strikeouts") is False

    def test_batter_hr_is_incubating(self):
        from src.config.models import is_live
        assert is_live("mlb", "batter_home_runs") is False

    def test_nhl_is_live(self):
        # NHL moneyline + puck line stay live. NHL totals were DEMOTED 2026-07-15
        # (36% win, CLV -2.2% — overconfident and losing to the close), so it must
        # no longer post publicly.
        from src.config.models import is_live
        assert is_live("nhl", "moneyline") is True
        assert is_live("nhl", "puck_line") is True
        assert is_live("nhl", "total") is False

    def test_unknown_model_defaults_incubating(self):
        from src.config.models import model_status
        assert model_status("pga", "nonexistent") == "incubating"

    def test_incubating_moneyline_never_card_pick(self):
        # Regression: predict.py used to post mlb·moneyline at a hardcoded 8%
        # edge, bypassing the incubating gate — flooding the card with
        # negative-CLV favorite-longshot dogs. An incubating market must NEVER
        # be a card pick, no matter how large the edge.
        from src.config.models import is_card_pick
        assert is_card_pick("mlb", "moneyline", 8.0) is False
        assert is_card_pick("mlb", "moneyline", 50.0) is False

    def test_live_total_respects_edge_floor(self):
        # mlb·total is live but must clear the 3% floor (sub-3% is noise).
        from src.config.models import is_card_pick
        assert is_card_pick("mlb", "total", 2.5) is False
        assert is_card_pick("mlb", "total", 3.5) is True

    def test_live_models_list(self):
        from src.config.models import live_models
        live = live_models()
        # Lock the currently-promoted set (update deliberately when you
        # promote/demote via chef.py — that's the guardrail working).
        assert ("nba", "total") in live
        assert ("mlb", "total") in live
        assert ("nhl", "moneyline") in live
        # Incubating markets must NEVER appear as live (real-money guard).
        assert ("mlb", "spread") not in live
        from src.config.models import MODELS
        for k in live:
            assert MODELS[k]["status"] == "live"

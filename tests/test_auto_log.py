"""
tests/test_auto_log.py — Tests for pick logging and NRFI grading behavior.

Guards against regressions in:
  - edge_pct stored as percentage points (not raw fraction) for moneylines
  - card_pick never auto-set to True by the system
  - unit-based profit in picks.json grading path
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestAutoLogPicks:
    """Regression tests for _auto_log_picks() in predict.py."""

    def _run_auto_log(self, picks_list: list[dict], tmp_path: Path, game_date=None) -> list[dict]:
        from datetime import date as _date
        import predict as _pred

        orig_pnl = _pred._PNL_FILE
        _pred._PNL_FILE = tmp_path / "picks.json"
        try:
            _pred._auto_log_picks(picks_list, game_date=game_date or _date(2026, 4, 24))
            data = json.loads((tmp_path / "picks.json").read_text())
            return data.get("picks", [])
        finally:
            _pred._PNL_FILE = orig_pnl

    def _sample_ml_pick(self, edge_fraction=0.082):
        return {
            "Team": "Chicago Cubs",
            "Opponent": "Milwaukee Brewers",
            "HomeTeam": "Chicago Cubs",
            "Market": "moneyline",
            "BestOdds": 106,
            "ModelProb": 0.571,
            "Edge": edge_fraction,
            "Sportsbook": "FanDuel",
            "Matchup": "Milwaukee Brewers @ Chicago Cubs",
        }

    def test_card_pick_never_auto_set(self, tmp_path):
        picks = self._run_auto_log([self._sample_ml_pick()], tmp_path)
        assert len(picks) == 1
        assert picks[0]["card_pick"] is False

    def test_stake_zero_for_auto_log(self, tmp_path):
        picks = self._run_auto_log([self._sample_ml_pick()], tmp_path)
        assert picks[0]["stake"] == 0.0

    def test_edge_pct_percentage_points_for_moneyline(self, tmp_path):
        picks = self._run_auto_log([self._sample_ml_pick(edge_fraction=0.082)], tmp_path)
        assert len(picks) == 1
        edge = picks[0]["edge_pct"]
        assert edge is not None
        assert abs(edge - 8.2) < 0.1, f"Expected ~8.2 pct points, got {edge}"

    def test_zero_odds_pick_skipped(self, tmp_path):
        pick = self._sample_ml_pick()
        pick["BestOdds"] = 0
        import predict as _pred
        orig = _pred._PNL_FILE
        _pred._PNL_FILE = tmp_path / "picks.json"
        try:
            from datetime import date as _date
            count = _pred._auto_log_picks([pick], game_date=_date(2026, 4, 24))
            assert count == 0
            assert not (tmp_path / "picks.json").exists()
        finally:
            _pred._PNL_FILE = orig

    def test_direction_home_away_detection(self, tmp_path):
        pick = self._sample_ml_pick()
        pick["HomeTeam"] = "Chicago Cubs"
        picks = self._run_auto_log([pick], tmp_path)
        assert picks[0]["direction"] == "HOME"

    def test_direction_away_when_not_home(self, tmp_path):
        pick = self._sample_ml_pick()
        pick["HomeTeam"] = "Milwaukee Brewers"
        picks = self._run_auto_log([pick], tmp_path)
        assert picks[0]["direction"] == "AWAY"

    def test_totals_edge_not_multiplied(self, tmp_path):
        pick = {
            "Team": "OVER 9.5",
            "Opponent": "Baltimore Orioles @ Kansas City Royals",
            "HomeTeam": "",
            "Market": "total",
            "Direction": "OVER",
            "BestOdds": -110,
            "ModelProb": 0.62,
            "Edge": 2.1,
            "BetLine": 9.5,
            "Sportsbook": "FanDuel",
            "Matchup": "Baltimore Orioles @ Kansas City Royals",
        }
        picks = self._run_auto_log([pick], tmp_path)
        assert len(picks) == 1
        edge = picks[0]["edge_pct"]
        assert edge is not None
        assert abs(edge - 2.1) < 0.01, f"Total edge should stay as runs (2.1), got {edge}"


class TestNrfiAutoLog:
    """Regression test: NRFI auto-log must never set card_pick=True."""

    def test_nrfi_card_pick_always_false(self, tmp_path):
        from datetime import date as _date
        import src.grading.auto_grade as _ag

        orig = _ag._PNL_FILE
        _ag._PNL_FILE = tmp_path / "picks.json"
        try:
            nrfi_picks = [
                {
                    "home_team": "Kansas City Royals",
                    "away_team": "Baltimore Orioles",
                    "direction": "NRFI",
                    "odds": -130,
                    "no_odds": False,
                    "projected_nrfi": 0.72,
                    "label": "Bal/KC NRFI",
                }
            ]
            _ag._update_pnl_nrfi(nrfi_picks, [], _date(2026, 4, 24))
            data = json.loads((tmp_path / "picks.json").read_text())
            picks = data.get("picks", [])
            assert len(picks) >= 1
            nrfi_pick = next((p for p in picks if p.get("market") == "nrfi"), None)
            assert nrfi_pick is not None
            assert nrfi_pick["card_pick"] is False, "NRFI picks must never be auto-set as card picks"
        finally:
            _ag._PNL_FILE = orig

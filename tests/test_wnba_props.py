"""WNBA player props must be gradeable — and must fail loudly, not silently.

The gap this closes: WNBA prop picks had no grading path of any kind. The only
basketball prop grader, _grade_nba_props_v2, filters sport == "basketball_nba"
and reads nba_api's leaguegamelog, which does not serve the WNBA. 45 picks were
emitted on 2026-07-29 and not one was ever settled, so they sat as permanent
open positions — and, because closing archives store moneyline only, they also
dragged WNBA's closing-capture rate to 46% (moneyline alone: 75%) and tripped
the integrity monitor's UN-VALIDATABLE floor.

ESPN is mocked throughout: these assert the grading LOGIC, not the network.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import grade


def _box(labels, athletes):
    """One ESPN boxscore team block."""
    return {"statistics": [{"labels": labels,
                            "athletes": [{"athlete": {"displayName": n}, "stats": s}
                                         for n, s in athletes]}]}


def _responses(events, box):
    """requests.get side effect: scoreboard first, then each summary."""
    def _get(url, **kw):
        r = MagicMock(status_code=200)
        r.json.return_value = {"events": events} if url.endswith("/scoreboard") else {"boxscore": box}
        return r
    return _get


_EVENTS = [{"id": "401", "competitions": [{"status": {"type": {"completed": True}}}]}]
_BOX = {"players": [_box(["PTS", "REB", "AST", "STL", "BLK", "3PT"],
                         [("Jordin Canada", ["11", "4", "9", "2", "0", "1-3"]),
                          ("A'ja Wilson", ["27", "12", "3", "1", "2", "0-1"]),
                          ("Did Not Play", [])])]}


@pytest.fixture(autouse=True)
def _clear_cache():
    grade._WNBA_PROP_CACHE.clear()
    yield
    grade._WNBA_PROP_CACHE.clear()


class TestFetch:
    def test_parses_players_and_combos(self):
        with patch("requests.get", side_effect=_responses(_EVENTS, _BOX)):
            stats = grade._fetch_wnba_player_stats("20260729")
        assert stats["Jordin Canada"]["pts"] == 11
        assert stats["Jordin Canada"]["ast"] == 9
        assert stats["Jordin Canada"]["fg3m"] == 1        # "1-3" → 1 made
        assert stats["A'ja Wilson"]["pra"] == 27 + 12 + 3

    def test_dnp_rows_are_omitted_not_zeroed(self):
        """A scratch must VOID, never grade as a 0 — that invents a result."""
        with patch("requests.get", side_effect=_responses(_EVENTS, _BOX)):
            stats = grade._fetch_wnba_player_stats("20260729")
        assert "Did Not Play" not in stats

    def test_incomplete_games_are_skipped(self):
        live = [{"id": "401", "competitions": [{"status": {"type": {"completed": False}}}]}]
        with patch("requests.get", side_effect=_responses(live, _BOX)):
            assert grade._fetch_wnba_player_stats("20260729") == {}

    def test_a_failed_fetch_returns_empty_and_is_not_cached(self):
        """'Could not check' must not be remembered as 'no games'."""
        with patch("requests.get", return_value=MagicMock(status_code=503)):
            assert grade._fetch_wnba_player_stats("20260729") == {}
        assert "20260729" not in grade._WNBA_PROP_CACHE


class TestGrade:
    def _ledger(self, tmp_path, picks):
        f = tmp_path / "picks.json"
        f.write_text(json.dumps({"picks": picks}))
        return f

    def _pick(self, **kw):
        base = {"date": "2026-07-29", "sport": "wnba", "market": "player_assists",
                "team": "Jordin Canada UNDER 8.5", "line": 8.5, "direction": "UNDER",
                "odds": -110, "stake": 1.0, "result": None}
        base.update(kw)
        return base

    def _run(self, tmp_path, monkeypatch, picks, side_effect=None):
        f = self._ledger(tmp_path, picks)
        monkeypatch.setattr(grade, "_PNL_FILE", f, raising=False)
        monkeypatch.setattr(grade, "_load", lambda: json.loads(f.read_text()))
        saved = {}
        monkeypatch.setattr(grade, "_save", lambda d: saved.update(d))
        with patch("requests.get", side_effect=side_effect or _responses(_EVENTS, _BOX)):
            grade._grade_wnba_props("20260729")
        return saved.get("picks", [])

    def test_under_that_missed_is_a_loss(self, tmp_path, monkeypatch):
        # Canada had 9 assists; UNDER 8.5 loses.
        out = self._run(tmp_path, monkeypatch, [self._pick()])
        assert out[0]["result"] == "loss"

    def test_over_that_hit_is_a_win(self, tmp_path, monkeypatch):
        out = self._run(tmp_path, monkeypatch,
                        [self._pick(direction="OVER", line=8.5, odds=120)])
        assert out[0]["result"] == "win"
        assert out[0]["profit"] == pytest.approx(1.2)

    def test_exact_line_pushes(self, tmp_path, monkeypatch):
        out = self._run(tmp_path, monkeypatch, [self._pick(line=9.0)])
        assert out[0]["result"] == "push" and out[0]["profit"] == 0.0

    def test_missing_player_voids_with_a_reason(self, tmp_path, monkeypatch):
        out = self._run(tmp_path, monkeypatch,
                        [self._pick(team="Nobody Here UNDER 5.5", line=5.5)])
        assert out[0]["result"] == "void"
        assert out[0]["void_reason"] == "no_stat_line"
        assert out[0]["profit"] == 0.0

    def test_an_unreadable_source_leaves_picks_pending(self, tmp_path, monkeypatch):
        """The load-bearing one: a source outage must NOT settle anything.

        Voiding 45 real props because ESPN 503'd would destroy the record while
        looking like tidy housekeeping.
        """
        out = self._run(tmp_path, monkeypatch, [self._pick()],
                        side_effect=lambda *a, **k: MagicMock(status_code=503))
        assert out == [] or out[0]["result"] in (None, "pending")

    def test_points_and_rebounds_route_to_the_right_stat(self, tmp_path, monkeypatch):
        out = self._run(tmp_path, monkeypatch, [
            self._pick(market="player_points", team="A'ja Wilson OVER 20.5",
                       line=20.5, direction="OVER"),          # 27 → win
            self._pick(market="player_rebounds", team="A'ja Wilson UNDER 10.5",
                       line=10.5, direction="UNDER"),         # 12 → loss
        ])
        assert [p["result"] for p in out] == ["win", "loss"]


def test_the_sweep_routes_wnba_props_to_the_prop_grader():
    """grade_backlog must batch them by date, not drop them in `unresolved`."""
    src = (grade.Path(__file__).resolve().parents[1]
           / "scripts" / "grade_backlog.py").read_text()
    assert "wnba_prop_dates" in src
    assert "_grade_wnba_props" in src


def test_wnba_props_are_reachable_from_the_nightly_grader():
    """A grader nothing invokes is the same as no grader (see grade_outrights)."""
    src = (grade.Path(__file__).resolve().parents[1] / "grade.py").read_text()
    assert "_grade_wnba_props(grade_date)" in src

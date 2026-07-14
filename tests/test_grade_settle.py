"""
tests/test_grade_settle.py — Direct tests for grade.py settle + fetch logic.

test_grading.py pins the profit math by reimplementing it; these tests call
the actual functions that write the record: _settle_game_pick (score-side
assignment, push stamping, market routing), _grade_mlb_props (batter markets,
void/push, name matching) with a mocked MLB Stats API, _fetch_scores_espn
parsing (alias lists, draws, malformed rows), tennis find_result fallback,
and chef's alias-aware record filter.

Run: python3 -m pytest tests/test_grade_settle.py -v
"""
import sys
from datetime import date as _date
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import grade
from src.data.tennis_results import find_result
from chef import _sport_matches


def _game(home="Dallas Wings", away="Toronto Tempo", hs=108.0, aw=95.0, **extra):
    winner = home if hs > aw else away if aw > hs else "Draw"
    info = {
        "home": home, "away": away,
        "home_score": hs, "away_score": aw,
        "total": hs + aw, "winner": winner,
        "margin": abs(hs - aw),
    }
    info.update(extra)
    return info


# ─────────────────────────── _settle_game_pick ──────────────────────────────

class TestSettleGamePick:
    def test_moneyline_win(self):
        p = {"team": "Dallas Wings", "market": "moneyline", "odds": -300, "stake": 1.0}
        assert grade._settle_game_pick(p, _game()) == "win"
        assert p["result"] == "win"
        assert p["profit"] == pytest.approx(1 / 3, abs=1e-3)
        assert p["resulted_at"]

    def test_moneyline_loss(self):
        p = {"team": "Toronto Tempo", "market": "moneyline", "odds": 220, "stake": 1.0}
        assert grade._settle_game_pick(p, _game()) == "loss"
        assert p["profit"] == -1.0

    def test_spread_away_side_scores(self):
        # Away dog +14.5 with a 13-point loss covers
        p = {"team": "Toronto Tempo", "market": "spread", "odds": -110,
             "line": 14.5, "stake": 1.0}
        assert grade._settle_game_pick(p, _game()) == "win"

    def test_spread_home_side_scores(self):
        # Home favourite -5.5 winning by 13 covers
        p = {"team": "Dallas Wings", "market": "spread", "odds": -110,
             "line": -5.5, "stake": 1.0}
        assert grade._settle_game_pick(p, _game()) == "win"

    @pytest.mark.parametrize("market", ["run_line", "runline", "puck_line"])
    def test_spread_market_aliases(self, market):
        # Regression: "runline" wasn't routed and picks silently stayed pending
        p = {"team": "Dallas Wings", "market": market, "odds": -110,
             "line": -1.5, "stake": 1.0}
        assert grade._settle_game_pick(p, _game()) == "win"

    def test_total_over_under(self):
        over = {"team": "OVER 180.5", "market": "total", "odds": -110,
                "line": 180.5, "direction": "OVER", "stake": 1.0}
        under = {"team": "UNDER 220.5", "market": "total", "odds": -110,
                 "line": 220.5, "direction": "UNDER", "stake": 1.0}
        assert grade._settle_game_pick(over, _game()) == "win"     # 203 > 180.5
        assert grade._settle_game_pick(under, _game()) == "win"    # 203 < 220.5

    def test_total_push_stamps_pick(self):
        p = {"team": "OVER 203.0", "market": "total", "odds": -110,
             "line": 203.0, "direction": "OVER", "stake": 1.0}
        assert grade._settle_game_pick(p, _game()) == "push"
        assert p["result"] == "push"
        assert p["profit"] == 0.0
        assert p["resulted_at"]

    def test_total_direction_from_team_field(self):
        # Old picks encode direction only in the team field
        p = {"team": "UNDER 250.5", "market": "total", "odds": -110,
             "line": 250.5, "stake": 1.0}
        assert grade._settle_game_pick(p, _game()) == "win"

    def test_unknown_market_returns_none(self):
        p = {"team": "Dallas Wings", "market": "player_points", "odds": -110}
        assert grade._settle_game_pick(p, _game()) is None
        assert "result" not in p


# ─────────────────────────── _fetch_scores_espn ─────────────────────────────

def _espn_event(home, away, hs, aw, completed=True):
    def side(t, score, ha):
        return {
            "homeAway": ha, "score": str(score),
            "team": {"displayName": t[0], "shortDisplayName": t[1],
                     "name": t[2], "abbreviation": t[3], "location": t[4]},
        }
    return {
        "competitions": [{
            "status": {"type": {"completed": completed}},
            "competitors": [side(home, hs, "home"), side(away, aw, "away")],
        }]
    }


class TestFetchScoresEspn:
    def _payload(self):
        return {"events": [
            _espn_event(("Bosnia-Herzegovina", "Bosnia", "Bosnia-Herzegovina", "BIH", "Bosnia"),
                        ("Switzerland", "Switzerland", "Switzerland", "SUI", "Switzerland"),
                        1, 4),
            _espn_event(("Colombia", "Colombia", "Colombia", "COL", "Colombia"),
                        ("Switzerland", "Switzerland", "Switzerland", "SUI", "Switzerland"),
                        0, 0),
            _espn_event(("In Progress FC", "IPFC", "IPFC", "IP", "Nowhere"),
                        ("Other FC", "OFC", "OFC", "OF", "Elsewhere"),
                        1, 1, completed=False),
        ]}

    def _fetch(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = self._payload()
        with patch("requests.get", return_value=resp):
            return grade._fetch_scores_espn("soccer_fifa_world_cup", "20260618")

    def test_games_keyed_by_all_aliases(self):
        games = self._fetch()
        for alias in ("Bosnia-Herzegovina", "Bosnia", "BIH", "Switzerland", "SUI"):
            assert alias in games, f"missing alias key {alias}"

    def test_alias_lists_attached(self):
        games = self._fetch()
        g = games["BIH"]
        assert "Bosnia" in g["home_names"]
        assert "SUI" in g["away_names"]

    def test_draw_and_winner(self):
        games = self._fetch()
        assert games["BIH"]["winner"] == "Switzerland"
        assert games["Colombia"]["winner"] == "Draw"

    def test_incomplete_games_skipped(self):
        games = self._fetch()
        assert "In Progress FC" not in games

    def test_unknown_sport_key_returns_empty(self):
        assert grade._fetch_scores_espn("cricket_ipl", "20260618") == {}


# ─────────────────────────── _grade_mlb_props ───────────────────────────────

def _boxscore_player(name, batting=None, pitching=None):
    stats = {}
    if batting is not None:
        stats["batting"] = batting
    if pitching is not None:
        stats["pitching"] = pitching
    return {"person": {"fullName": name}, "stats": stats}


class TestGradeMlbProps:
    """Mock the MLB Stats API + picks file; verify batter/pitcher settling."""

    PICKS = [
        {"pick_id": "a", "date": "2026-07-08", "sport": "mlb", "market": "batter_hits",
         "team": "Juan Soto OVER 0.5", "direction": "OVER", "line": 0.5,
         "odds": -150, "stake": 1.0, "result": None},
        {"pick_id": "b", "date": "2026-07-08", "sport": "mlb", "market": "batter_walks",
         "team": "Juan Soto UNDER 0.5", "direction": "UNDER", "line": 0.5,
         "odds": 120, "stake": 1.0, "result": None},
        {"pick_id": "c", "date": "2026-07-08", "sport": "baseball_mlb",
         "market": "pitcher_strikeouts", "team": "Kyle Harrison OVER 5.5",
         "direction": "OVER", "line": 5.5, "odds": 122, "stake": 1.0, "result": None},
        {"pick_id": "d", "date": "2026-07-08", "sport": "mlb", "market": "batter_rbis",
         "team": "Scratched Guy OVER 0.5", "direction": "OVER", "line": 0.5,
         "odds": 200, "stake": 1.0, "result": None},
        {"pick_id": "e", "date": "2026-07-08", "sport": "mlb",
         "market": "batter_total_bases", "team": "Juan Soto OVER 2.0",
         "direction": "OVER", "line": 2.0, "odds": -110, "stake": 1.0, "result": None},
        # moneyline pick on the same date must NOT be touched by the props grader
        {"pick_id": "f", "date": "2026-07-08", "sport": "mlb", "market": "moneyline",
         "team": "New York Mets", "odds": -120, "stake": 1.0, "result": None},
    ]

    def _run(self):
        import copy
        data = {"picks": copy.deepcopy(self.PICKS)}

        sched = MagicMock(status_code=200)
        sched.json.return_value = {"dates": [{"games": [
            {"gamePk": 1, "status": {"abstractGameState": "Final"}},
        ]}]}
        box = MagicMock(status_code=200)
        box.json.return_value = {"teams": {"home": {"players": {
            "p1": _boxscore_player("Juan Soto",
                                   batting={"hits": 2, "baseOnBalls": 0,
                                            "totalBases": 2, "rbi": 1, "homeRuns": 0}),
            "p2": _boxscore_player("Kyle Harrison",
                                   pitching={"strikeOuts": 7},
                                   batting={}),
        }}, "away": {"players": {}}}}

        def fake_get(url, **kw):
            return sched if "schedule" in url else box

        with patch("requests.get", side_effect=fake_get), \
             patch.object(grade, "_load", return_value=data), \
             patch.object(grade, "_save"), \
             patch("src.analytics.public_stats.write_public_stats"):
            grade._grade_mlb_props("20260708")
        return {p["pick_id"]: p for p in data["picks"]}

    def test_batter_and_pitcher_markets_graded(self):
        out = self._run()
        assert out["a"]["result"] == "win"      # 2 hits > 0.5
        assert out["b"]["result"] == "win"      # 0 walks < 0.5
        assert out["c"]["result"] == "win"      # 7 Ks > 5.5
        assert out["c"]["profit"] == pytest.approx(1.22)

    def test_scratched_player_voided(self):
        out = self._run()
        assert out["d"]["result"] == "void"
        assert out["d"]["profit"] == 0.0

    def test_exact_line_pushes(self):
        out = self._run()
        assert out["e"]["result"] == "push"     # 2 total bases == 2.0
        assert out["e"]["profit"] == 0.0

    def test_game_lines_untouched(self):
        out = self._run()
        assert out["f"]["result"] is None

    def test_prop_markets_excluded_from_auto_grade(self):
        for m in grade._MLB_BATTER_STATS:
            assert m in grade._MLB_PROP_MARKETS
        assert "pitcher_strikeouts" in grade._MLB_PROP_MARKETS
        assert "prop" in grade._MLB_PROP_MARKETS


# ─────────────────────────── tennis find_result ─────────────────────────────

class TestFindResultFallback:
    D = _date(2026, 6, 29)

    def _idx(self):
        return {
            frozenset({"vallejo d", "mejia n"}): [
                {"date": self.D, "winner_key": "vallejo d", "completed": True}],
            frozenset({"wang xin", "bencic b"}): [
                {"date": self.D, "winner_key": "wang xin", "completed": True}],
            frozenset({"wang xiy", "osorio m"}): [
                {"date": self.D, "winner_key": "osorio m", "completed": True}],
        }

    def test_middle_name_initial_mismatch_matches(self):
        # "Adolfo Daniel Vallejo" is indexed as 'vallejo d' (goes by Daniel)
        rec = find_result(self._idx(), "Nicolas Mejia", "Adolfo Daniel Vallejo", self.D)
        assert rec is not None and rec["winner_key"] == "vallejo d"

    def test_disambiguated_initials_match(self):
        # 'wang x' (from "Xinyu Wang") must match index key 'wang xin'
        rec = find_result(self._idx(), "Xinyu Wang", "Belinda Bencic", self.D)
        assert rec is not None and rec["winner_key"] == "wang xin"

    def test_multi_token_surname_matches(self):
        rec = find_result(self._idx(), "Maria Camila Osorio Serrano", "Xiyu Wang", self.D)
        assert rec is not None and rec["winner_key"] == "osorio m"

    def test_no_match_returns_none(self):
        assert find_result(self._idx(), "Novak Djokovic", "Wu Yibing", self.D) is None

    def test_ambiguous_multiple_hits_in_window_returns_none(self):
        idx = {frozenset({"wang xin", "bencic b"}): [
            {"date": self.D, "winner_key": "wang xin", "completed": True},
            {"date": self.D, "winner_key": "bencic b", "completed": True},
        ]}
        assert find_result(idx, "Xinyu Wang", "Belinda Bencic", self.D) is None

    def test_outside_window_returns_none(self):
        rec = find_result(self._idx(), "Nicolas Mejia", "Adolfo Daniel Vallejo",
                          _date(2026, 7, 15))
        assert rec is None


# ─────────────────────────── chef record filter ─────────────────────────────

class TestSportMatches:
    def test_short_name_matches_itself(self):
        assert _sport_matches("wnba", "wnba")

    def test_odds_api_key_matches_short_name(self):
        assert _sport_matches("basketball_wnba", "wnba")
        assert _sport_matches("baseball_mlb", "mlb")
        assert _sport_matches("icehockey_nhl", "nhl")

    def test_no_cross_sport_match(self):
        assert not _sport_matches("basketball_wnba", "nba")
        assert not _sport_matches("mlb", "nhl")

    def test_none_sport_safe(self):
        assert not _sport_matches(None, "wnba")

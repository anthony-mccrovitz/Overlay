"""
tests/test_grade_backlog.py — Matching ladder tests for the nightly backlog sweep.

scripts/grade_backlog.py runs every night and writes results into the public
record. The invariants pinned here are the ones that protect the record from
wrong-game settles:

  - exact-date match wins; a doubleheader (same pairing twice that day) is
    ambiguous and must NOT settle
  - adjacent-day fallback settles only a UNIQUE match
  - the wide window requires a full away@home matchup and global uniqueness
    (playoff series pairings repeat -> must stay pending)
  - name matching survives accents, "&" vs "and", hyphens, and token order

Run: python3 -m pytest tests/test_grade_backlog.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from scripts.grade_backlog import (
    _norm, _toks, _matchup_teams, _side_match, _pick_matches_game,
    _find_game, _find_game_wide, _settle, _void_reason, _terminal_void,
)


def _game(home, away, hs=4.0, aw=2.0, **extra):
    winner = home if hs > aw else away if aw > hs else "Draw"
    info = {
        "home": home, "away": away,
        "home_score": hs, "away_score": aw,
        "total": hs + aw, "winner": winner,
        "margin": abs(hs - aw),
    }
    info.update(extra)
    return info


def _board(*games):
    """games dict keyed by both team names, like the fetchers produce."""
    out = {}
    for g in games:
        out.setdefault(g["home"], g)
        out.setdefault(g["away"], g)
    return out


# ─────────────────────────── name normalization ─────────────────────────────

class TestNameMatching:
    def test_norm_strips_accents_and_ampersand(self):
        assert _norm("Montréal Canadiens") == "montreal canadiens"
        assert _norm("Bosnia & Herzegovina") == "bosnia and herzegovina"

    def test_toks_hyphen_and_filler_words(self):
        assert _toks(_norm("Bosnia & Herzegovina")) == _toks(_norm("Bosnia-Herzegovina"))
        assert _toks("dr congo") == _toks("congo dr")

    def test_matchup_teams_parses_at_format(self):
        away, home = _matchup_teams({"matchup": "Toronto Tempo @ Dallas Wings"})
        assert (away, home) == ("toronto tempo", "dallas wings")

    def test_matchup_teams_rejects_single_name(self):
        assert _matchup_teams({"matchup": "Kansas City Royals"}) == ("", "")

    def test_side_match_uses_alias_lists(self):
        info = _game("United States", "Australia",
                     home_names=["United States", "USA"], away_names=["Australia", "AUS"])
        assert _side_match("usa", info, "home")
        assert not _side_match("usa", info, "away")

    def test_side_match_accent_via_norm(self):
        info = _game("Montreal Canadiens", "Carolina Hurricanes")
        assert _side_match(_norm("Montréal Canadiens"), info, "home")

    def test_pick_matches_game_full_matchup_is_side_specific(self):
        info = _game("San Antonio Spurs", "New York Knicks")  # Knicks AT Spurs
        assert _pick_matches_game(
            {"matchup": "New York Knicks @ San Antonio Spurs"}, info)
        # Reversed home/away is a DIFFERENT game and must not match
        assert not _pick_matches_game(
            {"matchup": "San Antonio Spurs @ New York Knicks"}, info)


# ─────────────────────────── _find_game ladder ──────────────────────────────

class TestFindGame:
    G_710 = _game("Dallas Wings", "Toronto Tempo")
    G_711 = _game("Chicago Sky", "Los Angeles Sparks")

    def _pick(self, matchup, date="2026-07-10", team=""):
        return {"matchup": matchup, "team": team, "date": date}

    def test_exact_date_match(self):
        boards = [("20260710", _board(self.G_710)), ("20260711", _board(self.G_711))]
        got = _find_game(self._pick("Toronto Tempo @ Dallas Wings"), boards)
        assert got is self.G_710

    def test_doubleheader_same_day_is_ambiguous(self):
        g1 = _game("New York Yankees", "Boston Red Sox", 5, 3)
        g2 = _game("New York Yankees", "Boston Red Sox", 2, 7)
        board = {"New York Yankees": g1, "Boston Red Sox": g1, "g2h": g2, "g2a": g2}
        boards = [("20260710", board)]
        assert _find_game(self._pick("Boston Red Sox @ New York Yankees"), boards) is None

    def test_adjacent_day_unique_match(self):
        # Pick dated 7/10, game actually on 7/11 (slate-date drift)
        boards = [("20260710", {}), ("20260711", _board(self.G_711))]
        got = _find_game(self._pick("Los Angeles Sparks @ Chicago Sky"), boards)
        assert got is self.G_711

    def test_adjacent_day_repeat_is_ambiguous(self):
        # Same pairing on 7/09 AND 7/11 (a series) — cannot know which one
        g_a = _game("Chicago Sky", "Los Angeles Sparks", 80, 90)
        g_b = _game("Chicago Sky", "Los Angeles Sparks", 70, 60)
        boards = [("20260709", _board(g_a)), ("20260710", {}), ("20260711", _board(g_b))]
        assert _find_game(self._pick("Los Angeles Sparks @ Chicago Sky"), boards) is None

    def test_opponent_only_matchup_matches_pair(self):
        # Old MLB ML picks: team=side taken, matchup=opponent name only
        p = {"matchup": "Toronto Tempo", "team": "Dallas Wings", "date": "2026-07-10"}
        boards = [("20260710", _board(self.G_710))]
        assert _find_game(p, boards) is self.G_710


class TestFindGameWide:
    def test_unique_across_window_settles(self):
        g = _game("Switzerland", "Bosnia-Herzegovina", 4, 1)
        boards = [("20260616", {}), ("20260618", _board(g)), ("20260624", {})]
        p = {"matchup": "Bosnia & Herzegovina @ Switzerland", "team": "Switzerland",
             "date": "2026-06-16"}
        assert _find_game_wide(p, boards) is g

    def test_repeated_pairing_stays_pending(self):
        # Playoff series: same away@home pairing twice in the window
        g1 = _game("Carolina Hurricanes", "Vegas Golden Knights", 4, 5)
        g2 = _game("Carolina Hurricanes", "Vegas Golden Knights", 4, 3)
        boards = [("20260602", _board(g1)), ("20260604", _board(g2))]
        p = {"matchup": "Vegas Golden Knights @ Carolina Hurricanes",
             "team": "Under 5.5", "date": "2026-05-31"}
        assert _find_game_wide(p, boards) is None

    def test_requires_full_matchup(self):
        g = _game("Dallas Wings", "Toronto Tempo")
        p = {"matchup": "Dallas Wings", "team": "Dallas Wings", "date": "2026-07-10"}
        assert _find_game_wide(p, [("20260710", _board(g))]) is None


# ─────────────────────────── _settle routing ────────────────────────────────

class TestSettle:
    def test_moneyline_routes_to_settle_game_pick(self):
        p = {"team": "Dallas Wings", "market": "moneyline", "odds": -150,
             "stake": 1.0, "date": "2026-07-10"}
        assert _settle(p, _game("Dallas Wings", "Toronto Tempo")) == "win"

    def test_runline_routes(self):
        # Regression: "runline" used to fall through and stay pending forever
        p = {"team": "Dallas Wings", "market": "runline", "odds": -110,
             "line": -1.5, "stake": 1.0, "date": "2026-07-10"}
        assert _settle(p, _game("Dallas Wings", "Toronto Tempo", 5, 2)) == "win"

    def test_nrfi_win_and_loss(self):
        clean = _game("New York Yankees", "Boston Red Sox",
                      first_inning_home_runs=0, first_inning_away_runs=0)
        scored = _game("New York Yankees", "Boston Red Sox",
                       first_inning_home_runs=1, first_inning_away_runs=0)
        w = {"market": "nrfi", "direction": "NRFI", "odds": -130, "stake": 1.0}
        l = {"market": "nrfi", "direction": "NRFI", "odds": -130, "stake": 1.0}
        assert _settle(w, clean) == "win"
        assert _settle(l, scored) == "loss"
        assert w["first_inning_runs"] == 0

    def test_nrfi_missing_inning_data_returns_none(self):
        p = {"market": "nrfi", "direction": "NRFI", "odds": -130, "stake": 1.0}
        assert _settle(p, _game("A", "B")) is None
        assert "result" not in p

    def test_f5_total_push_win_loss(self):
        g = _game("New York Yankees", "Boston Red Sox",
                  f5_home_runs=3, f5_away_runs=1)  # F5 total = 4
        push = {"market": "f5_total", "direction": "UNDER", "line": 4.0,
                "odds": -110, "stake": 1.0}
        win = {"market": "f5_total", "direction": "UNDER", "line": 4.5,
               "odds": -110, "stake": 1.0}
        loss = {"market": "f5_total", "direction": "OVER", "line": 4.5,
                "odds": -110, "stake": 1.0}
        assert _settle(push, g) == "push" and push["profit"] == 0.0
        assert _settle(win, g) == "win"
        assert _settle(loss, g) == "loss"

    def test_f5_missing_data_returns_none(self):
        p = {"market": "f5_total", "direction": "UNDER", "line": 4.5,
             "odds": -110, "stake": 1.0}
        assert _settle(p, _game("A", "B")) is None

    def test_unknown_market_returns_none(self):
        p = {"market": "player_points", "odds": -110, "stake": 1.0}
        assert _settle(p, _game("A", "B")) is None


class TestTerminalVoid:
    """The sweep must eventually stop calling an ungradeable pick "pending".

    A pick that no source can ever settle is not an open position — leaving it
    pending inflates the open count, trips the stale-pending watchdog nightly,
    and refetches boards for a game that never happened. But voiding is a write
    to the public record, so it only fires when the pick is PROVABLY dead:
    never on a guess, never on a source that might still update.
    """

    def _old(self, **kw):
        p = {"date": "2026-01-01", "odds": -110, "stake": 1.0, "result": None,
             "sport": "nba", "market": "moneyline", "matchup": "A Team @ B Team"}
        p.update(kw)
        return p

    def test_prop_without_stat_type_is_unrecoverable(self):
        # "Ron Holland OVER 4.5" never says points vs rebounds — grading it
        # would mean guessing which stat the bet was on.
        p = self._old(market="prop", team="Ron Holland OVER 4.5", prop_market=None)
        assert _void_reason(p) == "prop_market_missing"

    def test_prop_with_stat_type_is_left_alone(self):
        p = self._old(market="prop", prop_market="points", backlog_attempts=0)
        assert _void_reason(p) is None

    def test_tennis_outside_source_coverage(self):
        # tennis-data.co.uk carries main draw only; qualifying never lands.
        p = self._old(sport="tennis_atp_french_open", matchup="A Player vs B Player")
        assert _void_reason(p) == "source_coverage_gap"

    def test_exhausted_search_is_terminal(self):
        assert _void_reason(self._old(backlog_attempts=3)) == "unresolvable_after_retries"

    def test_search_not_yet_exhausted_stays_pending(self):
        assert _void_reason(self._old(backlog_attempts=2)) is None

    def test_matchup_without_pair_cannot_be_searched(self):
        assert _void_reason(self._old(matchup="Kansas City Royals")) == "matchup_incomplete"

    def test_mma_judged_on_retries_not_matchup_shape(self):
        # MMA grades by fighter name off ESPN's UFC board, so a "vs" matchup
        # with no "@" is normal — it must not be called matchup_incomplete.
        p = self._old(sport="mma_mixed_martial_arts", matchup="A Fighter vs B Fighter")
        assert _void_reason(p) is None
        p["backlog_attempts"] = 3
        assert _void_reason(p) == "source_coverage_gap"

    def test_manual_only_sports_are_never_auto_voided(self):
        # Outrights settle by hand via --winner; the sweep must not touch them.
        for sport in ("golf_the_open_championship_winner", "auto_racing_indycar_series"):
            assert _void_reason(self._old(sport=sport, backlog_attempts=9)) is None

    def test_recent_picks_are_never_voided(self):
        from datetime import datetime, timedelta
        fresh = self._old(backlog_attempts=9,
                          date=(datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"))
        assert _terminal_void([fresh], dry_run=False) == {}
        assert fresh["result"] is None

    def test_void_settles_at_zero_and_records_reason(self):
        p = self._old(backlog_attempts=3)
        out = _terminal_void([p], dry_run=False)
        assert p["result"] == "void" and p["profit"] == 0.0
        assert p["void_reason"] == "unresolvable_after_retries"
        assert sum(out.values()) == 1

    def test_dry_run_reports_without_writing(self):
        p = self._old(backlog_attempts=3)
        out = _terminal_void([p], dry_run=True)
        assert sum(out.values()) == 1
        assert p["result"] is None and "void_reason" not in p

    def test_already_graded_picks_are_untouched(self):
        p = self._old(backlog_attempts=9, result="win", profit=0.91)
        assert _terminal_void([p], dry_run=False) == {}
        assert p["result"] == "win" and p["profit"] == 0.91

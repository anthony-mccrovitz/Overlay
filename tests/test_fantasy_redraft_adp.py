"""Tests for the redraft ADP overlay.

The board originally ran on Sleeper's only ADP field, which is DYNASTY ADP.
In a redraft league that misprices veteran RBs by whole rounds (James Cook:
dynasty 23 vs redraft 14; Travis Etienne: 71 vs 37), which poisons survival
estimates and the draft simulator at once. These tests pin the matching logic
that maps real redraft mock-draft prices onto Sleeper player IDs — and the
name normalization whose failure would silently drop the exact players the
overlay exists to fix.
"""
import pytest

from src.fantasy.redraft_adp import _norm, match


class TestNameNormalization:
    def test_generational_suffixes_collide(self):
        """FFC says "James Cook III", Sleeper says "James Cook". If these
        don't match, the highest-stakes players in the fix are the ones
        silently left at their dynasty price."""
        assert _norm("James Cook III") == _norm("James Cook")
        assert _norm("Travis Etienne Jr.") == _norm("Travis Etienne")
        assert _norm("Marvin Harrison Sr.") == _norm("Marvin Harrison")

    def test_punctuation_and_case_collide(self):
        assert _norm("Ja'Marr Chase") == _norm("JaMarr Chase")
        assert _norm("A.J. Brown") == _norm("A J Brown")

    def test_distinct_names_stay_distinct(self):
        assert _norm("James Cook") != _norm("Dalvin Cook")


def _db(*players):
    """Minimal Sleeper players_db; fantasy_players() requires active+team+pos."""
    return {
        pid: {"player_id": pid, "full_name": name, "position": pos,
              "team": team, "active": True}
        for pid, name, pos, team in players
    }


class TestMatching:
    def test_suffix_mismatch_still_matches(self):
        db = _db(("4034", "James Cook", "RB", "BUF"))
        rows = [{"name": "James Cook III", "position": "RB",
                 "team": "BUF", "adp": 14.2}]
        assert match(rows, db) == {"4034": 14.2}

    def test_position_must_agree(self):
        """Two NFL players can share a name at different positions; position
        is the first gate so a QB's price never lands on a WR."""
        db = _db(("1", "Josh Allen", "QB", "BUF"))
        rows = [{"name": "Josh Allen", "position": "WR", "team": "BUF", "adp": 30.0}]
        assert match(rows, db) == {}

    def test_same_name_same_position_resolved_by_team(self):
        db = _db(("1", "Mike Williams", "WR", "LAC"),
                 ("2", "Mike Williams", "WR", "NYJ"))
        rows = [{"name": "Mike Williams", "position": "WR", "team": "NYJ", "adp": 90.0}]
        assert match(rows, db) == {"2": 90.0}

    def test_ambiguous_without_team_is_dropped_not_guessed(self):
        """A wrong ID silently reprices the wrong player, which is worse than
        leaving him at his dynasty price."""
        db = _db(("1", "Mike Williams", "WR", "LAC"),
                 ("2", "Mike Williams", "WR", "NYJ"))
        rows = [{"name": "Mike Williams", "position": "WR", "team": "FA", "adp": 90.0}]
        assert match(rows, db) == {}

    def test_ffc_kicker_code_maps_to_sleeper(self):
        db = _db(("5", "Justin Tucker", "K", "BAL"))
        rows = [{"name": "Justin Tucker", "position": "PK", "team": "BAL", "adp": 160.0}]
        assert match(rows, db) == {"5": 160.0}

    def test_team_defense_matches_via_display_name(self):
        """Defenses carry no full_name in Sleeper (first/last split) and FFC
        writes them as one string; both normalize to the same key."""
        db = {"SF": {"player_id": "SF", "first_name": "San Francisco",
                     "last_name": "49ers", "position": "DEF", "team": "SF",
                     "active": True}}
        rows = [{"name": "San Francisco 49ers", "position": "DEF",
                 "team": "SF", "adp": 140.0}]
        assert match(rows, db) == {"SF": 140.0}

    def test_malformed_rows_are_skipped(self):
        db = _db(("4034", "James Cook", "RB", "BUF"))
        rows = [{"name": None, "position": "RB", "adp": 14.2},
                {"name": "James Cook", "position": "RB", "adp": "N/A"},
                {"position": "RB", "adp": 14.2}]
        assert match(rows, db) == {}


class TestOverlaySemantics:
    def test_redraft_wins_dynasty_fills_the_tail(self):
        """The merge in build_board: {**dynasty, **redraft}. Players FFC
        prices move to the redraft number; everyone else keeps dynasty."""
        dynasty = {"cook": 23.0, "deep_bench": 180.0}
        redraft = {"cook": 14.2}
        merged = {**dynasty, **redraft}
        assert merged["cook"] == 14.2
        assert merged["deep_bench"] == 180.0

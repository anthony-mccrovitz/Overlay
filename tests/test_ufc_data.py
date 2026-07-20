"""
tests/test_ufc_data.py — UFC ratings-from-fight-history guard.

The model used to rate only ~70 hand-typed champions, so full cards came back
"both fighters unknown" and got skipped. Now ratings are computed from the real
UFC fight record. These tests pin the rating math (winners gain, losers lose,
scale stays sane) and the style derivation, using a synthetic fight set so they
never touch the network.

Run: python3 -m pytest tests/test_ufc_data.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data import ufc_data


def _fights():
    # A dominates: beats B (KO) then C (decision). B beats C. Chronological.
    return [
        {"date": "2024-01-01", "winner": "A Fighter", "loser": "B Fighter", "method": "KO/TKO"},
        {"date": "2024-02-01", "winner": "B Fighter", "loser": "C Fighter", "method": "Decision - Unanimous"},
        {"date": "2024-03-01", "winner": "A Fighter", "loser": "C Fighter", "method": "Submission"},
    ]


class TestEloComputation:
    def test_winner_gains_loser_loses(self):
        r = ufc_data.compute_ratings(_fights())
        assert r["A Fighter"]["mu"] > ufc_data._ELO_START
        assert r["C Fighter"]["mu"] < ufc_data._ELO_START

    def test_ordering_reflects_results(self):
        r = ufc_data.compute_ratings(_fights())
        # A beat B and C; B beat C -> A > B > C
        assert r["A Fighter"]["mu"] > r["B Fighter"]["mu"] > r["C Fighter"]["mu"]

    def test_bout_counts(self):
        r = ufc_data.compute_ratings(_fights())
        assert r["A Fighter"]["n"] == 2
        assert r["C Fighter"]["n"] == 2

    def test_finish_moves_rating_more_than_decision(self):
        ko = [{"date": "2024-01-01", "winner": "P", "loser": "Q", "method": "KO/TKO"}]
        dec = [{"date": "2024-01-01", "winner": "P", "loser": "Q", "method": "Decision - Split"}]
        rk = ufc_data.compute_ratings(ko)["P"]["mu"]
        rd = ufc_data.compute_ratings(dec)["P"]["mu"]
        assert rk > rd   # finishes carry a bigger K-factor


class TestStyleDerivation:
    def test_striker_profile_from_kos(self):
        s = ufc_data._style_from_methods(ko=8, sub=0, dec=0)
        assert s["striking"] > s["grappling"] and s["striking"] > s["wrestling"]

    def test_grappler_profile_from_subs(self):
        s = ufc_data._style_from_methods(ko=0, sub=8, dec=0)
        assert s["grappling"] > s["striking"]

    def test_thin_record_is_neutral(self):
        assert ufc_data._style_from_methods(ko=1, sub=0, dec=0) == {
            "striking": 0.5, "wrestling": 0.5, "grappling": 0.5}


class TestHistoryParsing:
    def test_outcome_orientation(self, monkeypatch):
        results = ("EVENT,BOUT,OUTCOME,WEIGHTCLASS,METHOD,ROUND,TIME\n"
                   "E1,Alice Ace vs. Bob Boxer,W/L,LW,KO/TKO,1,1:00\n"
                   "E1,Carl Cole vs. Dan Dole,L/W,LW,Submission,2,2:00\n")
        events = "EVENT,URL,DATE,LOCATION\nE1,u,\"March 01, 2026\",Vegas\n"
        monkeypatch.setattr(ufc_data, "_fetch",
                            lambda url, cache, net: results if "results" in url else events)
        fights = ufc_data.load_fight_history()
        assert {"winner": "Alice Ace", "loser": "Bob Boxer"}.items() <= fights[0].items()
        # L/W means the SECOND name won
        assert fights[1]["winner"] == "Dan Dole" and fights[1]["loser"] == "Carl Cole"

    def test_draw_and_nc_dropped(self, monkeypatch):
        results = ("EVENT,BOUT,OUTCOME,WEIGHTCLASS,METHOD,ROUND,TIME\n"
                   "E1,A A vs. B B,D/D,LW,Draw,3,5:00\n"
                   "E1,C C vs. D D,NC,LW,No Contest,1,1:00\n")
        events = "EVENT,URL,DATE,LOCATION\nE1,u,\"March 01, 2026\",Vegas\n"
        monkeypatch.setattr(ufc_data, "_fetch",
                            lambda url, cache, net: results if "results" in url else events)
        assert ufc_data.load_fight_history() == []


class TestModelIntegration:
    def test_model_prefers_computed_when_available(self, monkeypatch):
        import src.models.ufc_model as um
        monkeypatch.setattr("src.data.ufc_data.load_cached_ratings",
                            lambda: {"Test Guy": {"mu": 1700, "style":
                                     {"striking": 0.6, "wrestling": 0.5, "grappling": 0.5}}})
        m = um.UFCModel()
        assert m._source == "computed"
        assert m._is_known_fighter("Test Guy")

    def test_model_falls_back_to_curated_when_empty(self, monkeypatch):
        import src.models.ufc_model as um
        monkeypatch.setattr("src.data.ufc_data.load_cached_ratings", lambda: {})
        m = um.UFCModel()
        assert m._source == "curated_fallback"
        # A curated champion is still known in fallback mode
        assert m._is_known_fighter("Jon Jones")

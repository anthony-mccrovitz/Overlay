"""MMA results come from ESPN, matched diacritic-blind — or they rot pending.

THE BUG THIS PINS. The Odds API drops a finished card from /scores/ within
hours: the 2026-08-01 Fight Night (14 bouts, 49 ledger picks) returned "No UFC
completed games found" the very next morning, and the backlog sweep only
touches picks older than 2 days — so every UFC result lagged ~3 days, or
forever if names didn't match. The ledger writes "Mateusz Rebecki" and
"L'udovit Klein"; ESPN says "Mateusz Rębecki" and "Ludovit Klein". A .lower()
comparison misses both and the miss is silent.
"""
import grade
from grade import _espn_winner_lookup, _norm_name


def test_diacritics_and_apostrophes_normalize_away():
    assert _norm_name("Mateusz Rębecki") == _norm_name("Mateusz Rebecki")
    assert _norm_name("Nina Milošević") == "nina milosevic"
    assert _norm_name("L'udovit Klein") == _norm_name("Ludovit Klein")


def test_lookup_exact_match_is_diacritic_blind():
    winners = {_norm_name("Mateusz Rębecki"): "win",
               _norm_name("Kyle Prepolec"): "loss"}
    assert _espn_winner_lookup(winners, "Mateusz Rebecki") == "win"
    assert _espn_winner_lookup(winners, "Kyle Prepolec") == "loss"


def test_lookup_last_name_fallback_must_be_unique():
    winners = {"ludovit klein": "loss", "tofiq musayev": "win"}
    # first-name variant resolves through the unique last name
    assert _espn_winner_lookup(winners, "L'udovit Klein") == "loss"
    # two fighters sharing a last name is a refusal, not a coin flip
    ambiguous = {"anderson silva": "win", "thiago silva": "loss"}
    assert _espn_winner_lookup(ambiguous, "B. Silva") is None
    # absent fighter (card ESPN never carried) stays ungraded
    assert _espn_winner_lookup(winners, "Jon Jones") is None


def test_backlog_sweep_delegates_not_copies():
    """grade_backlog re-implementing the fetch/normalizer is how the two
    graders drift apart (see test_sport_key_single_source.py for the genre)."""
    import scripts.grade_backlog as gb
    assert gb._norm("Rębecki") == grade._norm_name("Rębecki")
    assert gb._fetch_mma_winners.__doc__ and "Delegates" in gb._fetch_mma_winners.__doc__

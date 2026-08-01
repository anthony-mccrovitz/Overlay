"""Name matching folds spelling; it never guesses who someone is.

This repo has eaten the same bug three times. Last-name matching handed Michael
Chandler the ratings of Michael Page. Four fighters are called Michael Oliveira
and the first search hit is a 0-2 journeyman. The rule that came out of it:

    an unrecognised name must stay unrecognised

because a default rating is honestly weak evidence, while somebody else's
career is a confident lie — and every downstream consumer treats "matched" as
"we know this player", including the confidence gates that exist to stop us
betting blind.

These tests cover the two tiers that were still guessing on 2026-08-01.
"""
from __future__ import annotations

import pytest


# ── UFC: the Glicko ratings cache ────────────────────────────────────────────
def _model(names):
    """A UFCModel with a hand-built ratings book (no disk, no network)."""
    from src.models.ufc_model import UFCModel, GlickoRating, StyleProfile
    m = UFCModel.__new__(UFCModel)
    m.ratings = {n: GlickoRating(mu=1500.0 + 100 * i) for i, n in enumerate(names)}
    m.styles = {n: StyleProfile() for n in names}
    return m


def test_ufc_refuses_a_surname_shared_by_two_fighters():
    """The live shape: 24 Silvas in the cache, and the old code returned the
    first one in dict order for ANY Silva."""
    m = _model(["Erick Silva", "Bruno Silva", "Douglas Silva"])
    assert m._fuzzy_match("Joaquin Silva") is None
    assert m._is_known_fighter("Joaquin Silva") is False, \
        "an unknown fighter was marked known — the both-unknown skip is defeated"


def test_ufc_refuses_when_two_namesakes_share_the_initial():
    """'Michael Oliveira' is four different fighters. Same surname AND same
    initial is still not an identity."""
    m = _model(["Michael Oliveira", "Marcus Oliveira", "Michel Oliveira"])
    assert m._fuzzy_match("M. Oliveira") is None


def test_ufc_still_folds_spelling_of_the_same_fighter():
    """Refusing ambiguity must not break the case it was built for: the odds
    feed and ufcstats spell one fighter differently."""
    m = _model(["Borislav Nikolic", "Jan Blachowicz"])
    assert m._fuzzy_match("Borislav Nikolić") == "Borislav Nikolic"
    m2 = _model(["Ludovit Klein", "Jan Blachowicz"])
    assert m2._fuzzy_match("L'udovit Klein") == "Ludovit Klein"


def test_ufc_matches_a_unique_surname_and_initial():
    """A middle name or an initial-only feed spelling is legitimate variation
    when exactly one fighter can be meant."""
    m = _model(["Alexander Volkanovski", "Jan Blachowicz"])
    assert m._fuzzy_match("Alexander John Volkanovski") == "Alexander Volkanovski"


def test_ufc_unknown_fighter_gets_a_default_rating_not_someone_elses():
    m = _model(["Erick Silva", "Bruno Silva"])
    r = m._get_rating("Joaquin Silva")
    assert r.mu == pytest.approx(1500.0), \
        "an unrated fighter inherited a rated namesake's Glicko rating"


# ── Tennis: the Elo book ─────────────────────────────────────────────────────
def _book():
    """Keys are `surname initial` — the norm_odds_name format."""
    return {
        "tsitsipas s": {"elo": 2100.0, "matches": 400, "name": "Stefanos Tsitsipas"},
        "cerundolo j": {"elo": 1800.0, "matches": 200, "name": "Juan Cerundolo"},
        "zverev a":    {"elo": 2050.0, "matches": 380, "name": "Alexander Zverev"},
    }


def test_tennis_refuses_a_different_first_name_on_a_unique_surname():
    """THE bug: an unrated qualifier uniquely matching a star's surname was
    handed the star's Elo *and* match count, so the confidence gate passed."""
    from src.data.tennis_data import _lookup
    assert _lookup(_book(), "Petros Tsitsipas") is None


def test_tennis_still_resolves_middle_names():
    """The tier that legitimately exists: same person, longer feed spelling."""
    from src.data.tennis_data import _lookup
    rec = _lookup(_book(), "Juan Manuel Cerundolo")
    assert rec is not None and rec["name"] == "Juan Cerundolo"


def test_tennis_exact_key_still_wins():
    from src.data.tennis_data import _lookup
    rec = _lookup(_book(), "Stefanos Tsitsipas")
    assert rec is not None and rec["name"] == "Stefanos Tsitsipas"


def test_tennis_unknown_player_is_pure_market_not_a_borrowed_rating():
    """The contract downstream depends on: no identity → (1500, 0) → the model
    weight collapses to 0 and the market price stands alone."""
    from src.data import tennis_data
    from src.data.tennis_data import _lookup
    assert _lookup(_book(), "Qualifier Nobody") is None

"""The weekly golf pipeline: field parsing, three-tier skill, honest labels.

Nothing here touches the network. The live smoke is `chef.py golf`.

Backstory that shaped these tests: the PGA model only ran four weeks a year
because it derived the FIELD from the Odds API board (majors-only). And its
"live" SG feed — statdata.pgatour.com — turned out to be a dead host failing
silently into a 54-player static DB, which covered 21 of the Rocket Classic's
147 players. The three-tier skill map (sg → owgr → labelled-unrated) exists so
coverage is real and its provenance is visible per player.
"""
from __future__ import annotations

import pytest

from src.data.golf_field import parse_events
from src.data.owgr import OWGR_SKILL_COEF, OWGR_SKILL_INTERCEPT, skill_from_points
from src.models.golf_week import UNRATED_SKILL, build_skill_map, read_week


# ── ESPN field parsing ───────────────────────────────────────────────────────
def _espn(players, name="Test Open", status="Scheduled"):
    return {"events": [{
        "id": "401", "name": name, "date": "2026-08-06T11:00Z",
        "endDate": "2026-08-09", "status": {"type": {"description": status}},
        "competitions": [{"competitors": [
            {"athlete": {"displayName": p}, "score": "-3",
             "status": {"type": {"name": "active"}}} for p in players
        ]}],
    }]}


def test_parse_extracts_event_and_field():
    evs = parse_events(_espn(["Cameron Young", "Rickie Fowler"]))
    assert len(evs) == 1
    ev = evs[0]
    assert ev.name == "Test Open"
    assert ev.start == "2026-08-06"
    assert [p.name for p in ev.players] == ["Cameron Young", "Rickie Fowler"]
    assert not ev.in_progress


def test_parse_tolerates_missing_fields():
    """A half-formed event with a real field beats an exception."""
    evs = parse_events({"events": [{"competitions": [{"competitors": [
        {"athlete": {"displayName": "Someone"}},
        {"athlete": {}},          # nameless — dropped, not fatal
        {},                       # empty — dropped
    ]}]}]})
    assert len(evs) == 1
    assert [p.name for p in evs[0].players] == ["Someone"]


def test_parse_empty_input():
    assert parse_events({}) == []
    assert parse_events({"events": []}) == []


# ── the three-tier skill map ─────────────────────────────────────────────────
_RATINGS = {"Cameron Young": {"sg_total": 2.2, "form": 1.0}}
_OWGR = {"Chris Gotterup": 4.0, "Cameron Young": 8.2}


def test_sg_beats_owgr_beats_unrated():
    """Precedence: real strokes-gained first, ranking-derived second, labelled
    default last. Cameron Young is in BOTH sources and must be priced from SG."""
    skills, src = build_skill_map(
        ["Cameron Young", "Chris Gotterup", "Random Qualifier"],
        ratings=_RATINGS, owgr=_OWGR)
    assert src == {"Cameron Young": "sg", "Chris Gotterup": "owgr",
                   "Random Qualifier": "none"}
    assert skills["Cameron Young"] == pytest.approx(2.2)
    assert skills["Chris Gotterup"] == pytest.approx(skill_from_points(4.0))
    assert skills["Random Qualifier"] == UNRATED_SKILL


def test_an_unknown_player_is_never_priced_as_average():
    """The UFC lesson, applied to golf: 'we do not know them' must price BELOW
    every rated player, and carry its label."""
    skills, src = build_skill_map(["Nobody Atall"], ratings=_RATINGS, owgr=_OWGR)
    assert src["Nobody Atall"] == "none"
    assert skills["Nobody Atall"] < min(2.2, skill_from_points(4.0))


def test_name_folding_joins_espn_to_ratings_spellings():
    """ESPN writes 'Joaquin Niemann'; a ratings source may carry the accent.
    Folded-exact must join them — and stay exact, never fuzzy."""
    ratings = {"Joaquín Niemann": {"sg_total": 1.8, "form": 1.0}}
    skills, src = build_skill_map(["Joaquin Niemann"], ratings=ratings, owgr={})
    assert src["Joaquin Niemann"] == "sg"
    skills2, src2 = build_skill_map(["Joaquin Niemanns"], ratings=ratings, owgr={})
    assert src2["Joaquin Niemanns"] == "none", "near-miss names must NOT join"


def test_form_multiplier_is_clamped():
    ratings = {"Hot Hand": {"sg_total": 2.0, "form": 9.9},
               "Cold Hand": {"sg_total": 2.0, "form": 0.1}}
    skills, _ = build_skill_map(["Hot Hand", "Cold Hand"], ratings=ratings, owgr={})
    assert skills["Hot Hand"] == pytest.approx(2.0 * 1.15)
    assert skills["Cold Hand"] == pytest.approx(2.0 * 0.85)


# ── the OWGR→skill mapping ───────────────────────────────────────────────────
def test_owgr_mapping_constants_are_the_fitted_ones():
    """Fitted on the 51-player overlap with the static SG database (r²=0.52).
    Guards a quiet 'tune' without a refit — rerun `python3 -m src.data.owgr`
    and update BOTH numbers together if the static DB changes."""
    assert OWGR_SKILL_COEF == pytest.approx(0.588, abs=1e-3)
    assert OWGR_SKILL_INTERCEPT == pytest.approx(0.710, abs=1e-3)


def test_owgr_mapping_is_monotonic_and_sane():
    assert skill_from_points(16.3) > skill_from_points(8.0) > skill_from_points(1.0)
    assert skill_from_points(0.0) == 0.0
    # Scheffler-level points land in elite-SG territory, conservatively.
    assert 1.8 < skill_from_points(16.3) < 3.0


# ── end to end, offline ──────────────────────────────────────────────────────
def test_read_week_prices_a_field_coherently():
    ev = parse_events(_espn(["Cameron Young", "Chris Gotterup", "Random Qualifier",
                             "Other Guy", "Fifth Man"]))[0]
    reads, _sim = read_week(ev, n_sim=4000, ratings=_RATINGS, owgr=_OWGR)
    assert len(reads) == 5
    total_win = sum(r.win_pct for r in reads)
    assert total_win == pytest.approx(100.0, abs=1.5), "someone must win"
    assert reads[0].player == "Cameron Young", "the best-rated player leads"
    by = {r.player: r for r in reads}
    assert not by["Random Qualifier"].rated
    assert by["Random Qualifier"].win_pct < by["Cameron Young"].win_pct
    for r in reads:
        assert r.top5_pct >= r.win_pct
        assert r.top10_pct >= r.top5_pct
        assert r.top20_pct >= r.top10_pct


def test_market_matching_requires_a_distinctive_token(monkeypatch):
    """A majors futures board must NOT be joined to the Rocket Classic just
    because both say 'golf' — pricing this week against next April's Masters
    board would be the wrong-market join all over again."""
    import requests as _rq

    ev = parse_events(_espn(["A"], name="Rocket Classic"))[0]

    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return [{"key": "golf_masters_tournament_winner", "active": True},
                    {"key": "golf_us_open_winner", "active": True}]
    monkeypatch.setenv("ODDS_API_KEY", "test")
    monkeypatch.setattr(_rq, "get", lambda *a, **k: _R())
    # fetch_odds returns a SENTINEL, so the assertion below distinguishes
    # "no board matched" ({}) from "a wrong board matched and was fetched".
    # The first version of this test skipped this, and a mutant that matched
    # ANY board still passed: the mutant's fetch_odds call choked politely on
    # the fake response and returned {} — indistinguishable from a refusal.
    # Agreement produced by two different failures is not a passing test.
    monkeypatch.setattr("src.models.pga_championship.fetch_odds",
                        lambda board: {"Somebody": {"best_odds": +500,
                                                    "best_book": "x",
                                                    "implied_prob": 0.17}})
    from src.models.golf_week import market_for_event
    assert market_for_event(ev) == {}, "no distinctive token overlap → no board"


def test_market_matching_joins_the_right_board(monkeypatch):
    """And when a genuinely matching board exists, it IS fetched."""
    import requests as _rq

    ev = parse_events(_espn(["A"], name="PGA Championship"))[0]

    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return [{"key": "golf_pga_championship_winner", "active": True}]
    monkeypatch.setenv("ODDS_API_KEY", "test")
    monkeypatch.setattr(_rq, "get", lambda *a, **k: _R())
    sentinel = {"Somebody": {"best_odds": +500, "best_book": "x",
                             "implied_prob": 0.17}}
    monkeypatch.setattr("src.models.pga_championship.fetch_odds",
                        lambda board: sentinel)
    from src.models.golf_week import market_for_event
    assert market_for_event(ev) == sentinel

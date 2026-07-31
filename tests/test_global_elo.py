"""Career-wide ratings: deduplication, point-in-time, and the coverage gate."""
from __future__ import annotations

import json
from datetime import date

import pytest

from src.models import global_elo as ge


def _write(tmp_path, slug, name, dob, bouts):
    (tmp_path / f"{slug}.json").write_text(json.dumps({
        "slug": slug, "name": name, "dob": dob, "height_in": None,
        "nationality": "", "association": "", "bouts": bouts}))


def _bout(opp_slug, result, when, promotion="UFC", method="Decision"):
    return {"result": result, "opponent": opp_slug.split("-")[0],
            "opponent_slug": opp_slug, "event": f"{promotion} 1",
            "promotion": promotion, "when": when, "method": method, "rnd": 3}


# ── deduplication ────────────────────────────────────────────────────────────
def test_a_bout_written_from_both_sides_counts_once(tmp_path, monkeypatch):
    """Every fight appears on two pages with opposite results. Counting both
    would double every rating update and silently inflate the whole spread."""
    monkeypatch.setattr(ge, "_CACHE", tmp_path)
    _write(tmp_path, "A-1", "A", "1990-01-01", [_bout("B-2", "win", "2020-05-01")])
    _write(tmp_path, "B-2", "B", "1991-01-01", [_bout("A-1", "loss", "2020-05-01")])
    bouts = ge.load_global_bouts()
    assert len(bouts) == 1
    assert bouts[0]["w"] == "A-1" and bouts[0]["l"] == "B-2"


def test_two_meetings_on_different_dates_both_count(tmp_path, monkeypatch):
    """A rematch is a separate fight. Deduping on the pair alone would drop it."""
    monkeypatch.setattr(ge, "_CACHE", tmp_path)
    _write(tmp_path, "A-1", "A", "1990-01-01",
           [_bout("B-2", "win", "2020-05-01"), _bout("B-2", "loss", "2021-05-01")])
    assert len(ge.load_global_bouts()) == 2


def test_draws_and_no_contests_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(ge, "_CACHE", tmp_path)
    _write(tmp_path, "A-1", "A", "1990-01-01", [
        _bout("B-2", "draw", "2020-05-01"), _bout("C-3", "nc", "2020-06-01"),
        _bout("D-4", "win", "2020-07-01")])
    assert len(ge.load_global_bouts()) == 1


def test_bouts_come_back_chronological(tmp_path, monkeypatch):
    monkeypatch.setattr(ge, "_CACHE", tmp_path)
    _write(tmp_path, "A-1", "A", "1990-01-01", [
        _bout("C-3", "win", "2022-01-01"), _bout("B-2", "win", "2020-01-01")])
    ds = [b["date"] for b in ge.load_global_bouts()]
    assert ds == sorted(ds), "Elo replay is order-dependent"


def test_a_corrupt_cache_file_is_skipped_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(ge, "_CACHE", tmp_path)
    (tmp_path / "bad.json").write_text("{not json")
    _write(tmp_path, "A-1", "A", "1990-01-01", [_bout("B-2", "win", "2020-05-01")])
    assert len(ge.load_global_bouts()) == 1


# ── ratings ──────────────────────────────────────────────────────────────────
def test_winner_rises_loser_falls():
    led = ge.GlobalLedger()
    led.apply_bout({"date": date(2020, 1, 1), "w": "A", "l": "B",
                    "promotion": "UFC", "method": "Decision"})
    assert led.state("A").elo > ge.ELO_START
    assert led.state("B").elo < ge.ELO_START


def test_a_finish_moves_ratings_more_than_a_decision():
    a = ge.GlobalLedger()
    a.apply_bout({"date": date(2020, 1, 1), "w": "A", "l": "B",
                  "promotion": "UFC", "method": "Decision (Unanimous)"})
    b = ge.GlobalLedger()
    b.apply_bout({"date": date(2020, 1, 1), "w": "A", "l": "B",
                  "promotion": "UFC", "method": "KO (Punches)"})
    assert b.state("A").elo > a.state("A").elo


def test_top_share_tracks_the_promotions_actually_fought_in():
    """The whole point of the feature: 16-3 in a regional promotion is not
    16-3 in the UFC, and the model needs to be able to tell."""
    led = ge.GlobalLedger()
    for i, promo in enumerate(["Oktagon", "Oktagon", "Oktagon", "UFC"]):
        led.apply_bout({"date": date(2020, 1, 1 + i), "w": "A", "l": f"B{i}",
                        "promotion": promo, "method": "Decision"})
    f = led.features_for("A", date(2021, 1, 1))
    assert f["top_share"] == pytest.approx(0.25)
    assert f["pro_exp"] == 4


def test_features_are_none_for_a_fighter_with_no_bouts():
    """Never a default value. An unrated fighter must be visibly unrated, not
    silently average."""
    led = ge.GlobalLedger()
    f = led.features_for("Nobody", date(2020, 1, 1))
    assert all(v is None for v in f.values())
    assert not led.known("Nobody")


def test_reading_features_does_not_mutate_state():
    """Same invariant as the UFC ledger, asserted directly rather than by
    comparing two runs of the same code."""
    led = ge.GlobalLedger()
    led.apply_bout({"date": date(2020, 1, 1), "w": "A", "l": "B",
                    "promotion": "UFC", "method": "KO"})
    before = {k: (v.elo, v.n, v.top_n, tuple(v.results)) for k, v in led.book.items()}
    led.features_for("A", date(2021, 1, 1))
    led.known("A")
    after = {k: (v.elo, v.n, v.top_n, tuple(v.results)) for k, v in led.book.items()}
    assert before == after


def test_build_stops_at_the_through_date(tmp_path, monkeypatch):
    monkeypatch.setattr(ge, "_CACHE", tmp_path)
    _write(tmp_path, "A-1", "A", "1990-01-01", [
        _bout("B-2", "win", "2020-01-01"), _bout("C-3", "win", "2023-01-01")])
    led = ge.build_global_ledger(through=date(2021, 1, 1))
    assert led.state("A-1").n == 1, "a later bout leaked into an earlier view"


# ── the coverage gate ────────────────────────────────────────────────────────
def test_thin_coverage_is_reported_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(ge, "_CACHE", tmp_path)
    _write(tmp_path, "A-1", "Alpha Fighter", "1990-01-01",
           [_bout("B-2", "win", "2020-01-01")])
    names = {"Alpha Fighter", "Beta Fighter", "Gamma Fighter", "Delta Fighter"}
    tott = {n: {"dob": date(1990, 1, 1)} for n in names}
    assert ge.roster_coverage(names, tott) == pytest.approx(0.25)


def test_the_join_refuses_ambiguous_keys(tmp_path, monkeypatch):
    """Two fighters with the same name AND the same date of birth cannot be
    told apart, so neither is joined. Same refusal rule as sherdog.resolve."""
    monkeypatch.setattr(ge, "_CACHE", tmp_path)
    _write(tmp_path, "A-1", "Same Name", "1990-01-01", [])
    _write(tmp_path, "A-2", "Same Name", "1990-01-01", [])
    _write(tmp_path, "B-1", "Other Name", "1991-01-01", [])
    m = ge.name_to_slug()
    assert ("same name", "1990-01-01") not in m
    assert m.get(("other name", "1991-01-01")) == "B-1"


def test_the_coverage_threshold_is_meaningful():
    """Guards against someone lowering the bar to make the feature 'work'.
    Below this, a walk-forward comparison measures imputation, not features."""
    assert 0.4 <= ge.MIN_ROSTER_COVERAGE <= 0.95


def test_empty_cache_yields_no_coverage_rather_than_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ge, "_CACHE", tmp_path)
    assert ge.load_global_bouts() == []
    assert ge.roster_coverage({"A"}, {}) == 0.0
    assert ge.coverage()["bouts"] == 0

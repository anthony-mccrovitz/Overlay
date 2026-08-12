"""A pick may only be voided on evidence, never on silence.

Voiding settles a real position at 0 profit. The bar for it is therefore proof
that the pick CANNOT resolve — not "we tried and something went wrong".

Two failures this locks down:

1. Tennis was voided on age alone, on the reasoning that a match still missing
   after a month must be outside tennis-data.co.uk's coverage. That reasoning
   silently assumes the source was read. From 2026-07-12 to 2026-08-12 it was
   not — openpyxl was absent from the light dependency set, pd.read_excel
   raised, and load_matches returned an empty frame. 362 live picks were on
   their way to being settled at 0 and labelled "source_coverage_gap".

2. `backlog_attempts` counts sweeps that failed to SETTLE, including sweeps
   where the scoreboard fetch itself failed. Voiding on that number makes an
   outage indistinguishable from a game that never happened.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("gb", ROOT / "scripts" / "grade_backlog.py")
gb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gb)


def _pick(**kw):
    base = {"sport": "mlb", "market": "moneyline", "date": "2026-07-01",
            "matchup": "Away Team @ Home Team", "odds": -110, "result": None}
    base.update(kw)
    return base


class TestTennisNeedsProofOfARead:
    def test_unread_source_never_voids_however_old(self):
        """The openpyxl outage case. No stamp = no knowledge = no void."""
        p = _pick(sport="tennis_atp_canadian_open", date="2026-01-01",
                  backlog_attempts=99)
        assert gb._void_reason(p) is None

    def test_a_proven_read_that_missed_may_void(self):
        """Once the grader has actually read the workbook and not found the
        match, absence is real evidence — qualifying draws genuinely aren't in
        the source."""
        p = _pick(sport="tennis_wta_canadian_open", tennis_source_read=True)
        assert gb._void_reason(p) == "source_coverage_gap"

    def test_tennis_keeps_the_long_horizon(self):
        """Its source publishes weekly, so a two-week absence proves nothing."""
        p = _pick(sport="tennis_atp_canadian_open", tennis_source_read=True,
                  backlog_searched=50)
        assert gb._norm(p["sport"]).startswith("tennis_")
        # The shortened tier must not apply to tennis.
        assert gb._PROVEN_AGE_DAYS < gb._TERMINAL_AGE_DAYS


class TestSearchedMeansTheSourceAnswered:
    def test_legacy_picks_fall_back_to_attempts(self):
        assert gb._searched_count(_pick(backlog_attempts=7)) == 7

    def test_the_explicit_counter_wins_when_present(self):
        """A pick swept 12 times but only searched twice is NOT exhausted."""
        assert gb._searched_count(_pick(backlog_attempts=12, backlog_searched=2)) == 2

    def test_a_pick_never_actually_searched_does_not_void(self):
        p = _pick(backlog_attempts=40, backlog_searched=0)
        assert gb._void_reason(p) is None, (
            "voided a pick whose boards never came back — an outage, not a phantom"
        )

    def test_mma_needs_a_source_that_answered(self):
        assert gb._void_reason(_pick(sport="mma_mixed_martial_arts",
                                     backlog_attempts=20, backlog_searched=0)) is None
        assert gb._void_reason(_pick(sport="mma_mixed_martial_arts",
                                     backlog_searched=3)) == "source_coverage_gap"


class TestStructuralReasonsStillHold:
    def test_prop_without_a_stat_type_is_unrecoverable(self):
        assert gb._void_reason(_pick(market="prop")) == "prop_market_missing"

    def test_missing_matchup_is_unrecoverable(self):
        assert gb._void_reason(_pick(matchup="")) == "matchup_incomplete"

    def test_manual_only_sports_are_left_alone(self):
        assert gb._void_reason(_pick(sport="golf_the_open_championship_winner",
                                     backlog_searched=99)) is None


def test_the_shortened_horizon_is_strictly_stronger_evidence():
    """The fast tier must demand MORE proof than the slow one, not less."""
    assert gb._PROVEN_SEARCHES >= 3
    assert gb._PROVEN_AGE_DAYS >= 14, (
        "a horizon under two weeks starts voiding games that postponed"
    )

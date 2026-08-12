"""edge_shrink judges the money, and never hides the rest.

Decided 2026-08-12. The check used to average every pick a lane logged, card
and shadow together. The build standard's question is narrower — is this lane
fit to be LIVE, i.e. to put money on the card — and the two answers came apart
badly on mlb/total:

    lane-wide   k=0.18   claimed 7.90pp → realized 1.44pp   n=277   FAIL
    card only   k=0.82   claimed 2.84pp → realized 2.32pp   n=76    PASS  ROI +4.7%

The 201-pick gap is shadow picks whose edges exceeded _CARD_EDGE_MAX — picks
the gate examined and REFUSED to bet. Failing the lane on them penalises the
card band for working, and the only remedy on offer (demote) would have emptied
the board, since mlb/total is the sole live lane in the registry.

What did NOT change: MIN_EDGE_SHRINK_K. This is a population choice, not a
lowered bar. Guarded here so it cannot quietly become one.
"""
from __future__ import annotations

import pytest

from src.config import model_standard as ms
from src.config.model_standard import (EDGE_SHRINK_MIN_CARD_N,
                                       MIN_EDGE_SHRINK_K, edge_shrink)


@pytest.fixture
def record(monkeypatch):
    """Install one synthetic calibration record for lane 'x::y'."""
    def _install(**row):
        monkeypatch.setattr(ms, "_calibration_records", lambda: {"x::y": row})
    return _install


def test_the_threshold_itself_is_unchanged():
    """A population change must not become a lowered bar by accident."""
    assert MIN_EDGE_SHRINK_K == 0.25


def test_a_healthy_card_passes_despite_a_failing_lane_wide_number(record):
    """The mlb/total case, exactly."""
    record(n=277, claimed_pp=7.897, realized_pp=1.438, k=0.182,
           card_n=76, card_claimed_pp=2.842, card_realized_pp=2.318, card_k=0.8156)
    ok, detail = edge_shrink("x", "y")
    assert ok
    assert "CARD n=76" in detail


def test_both_numbers_are_always_reported(record):
    """The overclaim on shadow is the reason not to widen the band. It must
    survive in the report even when the card is what passes."""
    record(n=277, claimed_pp=7.897, realized_pp=1.438, k=0.182,
           card_n=76, card_claimed_pp=2.842, card_realized_pp=2.318, card_k=0.8156)
    _, detail = edge_shrink("x", "y")
    assert "lane-wide k=0.18" in detail
    assert "card k=0.82" in detail
    assert "do not widen it" in detail


def test_a_failing_card_still_fails(record):
    """The band cannot launder a lane whose actual bets don't materialise."""
    record(n=300, claimed_pp=8.0, realized_pp=6.0, k=0.75,
           card_n=90, card_claimed_pp=9.0, card_realized_pp=0.4, card_k=0.044)
    ok, detail = edge_shrink("x", "y")
    assert not ok
    assert "CARD n=90" in detail


def test_a_thin_card_falls_back_to_everything_logged(record):
    """Under the floor the card says too little, so the lane answers for the
    whole population — a 3-pick hot streak cannot certify a lane."""
    record(n=400, claimed_pp=9.0, realized_pp=0.5, k=0.055,
           card_n=EDGE_SHRINK_MIN_CARD_N - 1,
           card_claimed_pp=2.0, card_realized_pp=1.9, card_k=0.95)
    ok, detail = edge_shrink("x", "y")
    assert not ok, "a sub-floor card sample certified a lane that logged k=0.055"
    assert "lane-wide n=400" in detail


def test_legacy_records_without_a_card_split_still_work(record):
    """Tables written before card_k existed must not crash the standard."""
    record(n=200, claimed_pp=6.0, realized_pp=4.0, k=0.667)
    ok, detail = edge_shrink("x", "y")
    assert ok and "lane-wide n=200" in detail


def test_a_missing_record_is_a_failure_not_a_pass(record):
    """No measurement is not evidence of health."""
    import src.config.model_standard as m
    ok, detail = m.edge_shrink("nosuch", "lane")
    assert not ok

"""Vig removal must be exact, ordered, and monotone in the bias it corrects.

These are round-trip tests, not fixtures: build odds FROM known probabilities
plus a known margin, then check each method recovers something sane. A fixture
test would just re-assert whatever the code happened to output the day it was
written.
"""
import pytest

from src.analytics.devig import (american_to_implied, implied_to_american,
                                 devig, DEFAULT_METHOD_FOR)

METHODS = ("multiplicative", "power", "shin")


def _with_margin(probs, margin):
    """Odds for `probs` inflated by `margin` (proportionally applied).

    Callers must keep p*(1+margin) below 1 — a 0.90 favourite with 12% margin
    implies a 1.008 probability, which is not a price any book can quote and not
    something devig should be asked to interpret.
    """
    out = []
    for p in probs:
        q = p * (1.0 + margin)
        assert q < 1.0, f"test input invalid: p={p} at margin={margin} implies {q}"
        out.append(implied_to_american(q))
    return out


def test_odds_probability_round_trip():
    for p in (0.05, 0.25, 0.5, 0.5001, 0.75, 0.95):
        assert american_to_implied(implied_to_american(p)) == pytest.approx(p, abs=1e-6)


@pytest.mark.parametrize("method", METHODS)
def test_output_is_a_probability_distribution(method):
    for probs in ([0.5, 0.5], [0.75, 0.25], [0.85, 0.15], [0.45, 0.30, 0.25]):
        for margin in (0.02, 0.05, 0.12):
            out = devig(_with_margin(probs, margin), method=method)
            assert out is not None
            assert sum(out) == pytest.approx(1.0, abs=1e-9)
            assert all(0.0 < p < 1.0 for p in out)


@pytest.mark.parametrize("method", METHODS)
def test_order_is_preserved(method):
    """Fair probabilities must come back in input order — a transposition here
    would silently swap the over and under sides of every prop."""
    out = devig(_with_margin([0.7, 0.3], 0.08), method=method)
    assert out[0] > out[1]


@pytest.mark.parametrize("method", METHODS)
def test_symmetric_market_is_recovered_exactly(method):
    """With a symmetric book, every method must return 50/50 — no bias to correct."""
    out = devig([-110, -110], method=method)
    assert out == pytest.approx([0.5, 0.5], abs=1e-9)


def test_shin_and_power_shade_the_longshot_up_relative_to_multiplicative():
    """The whole point of Shin/power: on a lopsided market they assign LESS
    margin to the favourite and MORE to the longshot than multiplicative does,
    so the devigged longshot probability comes out lower.

    This is the property that matters for props, where the margin is large and
    the sides are often lopsided. If it ever inverts, the methods are wired up
    backwards and prop fair values are biased the wrong way.
    """
    odds = _with_margin([0.85, 0.15], 0.10)
    mult = devig(odds, method="multiplicative")
    shin = devig(odds, method="shin")
    powr = devig(odds, method="power")
    assert shin[1] < mult[1], "Shin should shade the longshot BELOW multiplicative"
    assert powr[1] < mult[1], "power should shade the longshot BELOW multiplicative"
    # NOTE: no assertion on Shin vs power ordering. Both correct in the same
    # DIRECTION, but which corrects harder depends on the odds and the margin —
    # asserting a fixed ordering would encode a coincidence of these inputs.


def test_high_vig_moves_the_answer_more_than_low_vig():
    """Method choice is near-irrelevant at Pinnacle vig and material at prop vig.

    This is the empirical justification for using multiplicative on game lines
    and Shin on props rather than one method everywhere.
    """
    probs = [0.8, 0.2]
    lo = abs(devig(_with_margin(probs, 0.02), method="shin")[1]
             - devig(_with_margin(probs, 0.02), method="multiplicative")[1])
    hi = abs(devig(_with_margin(probs, 0.12), method="shin")[1]
             - devig(_with_margin(probs, 0.12), method="multiplicative")[1])
    assert hi > lo * 2, f"expected method choice to matter more at high vig (lo={lo}, hi={hi})"


def test_market_selects_the_method():
    """Callers pass a market and get the right method — nobody re-encodes the
    'props use Shin' rule at each call site."""
    assert DEFAULT_METHOD_FOR["pitcher_strikeouts"] == "shin"
    assert DEFAULT_METHOD_FOR["moneyline"] == "multiplicative"
    odds = _with_margin([0.85, 0.15], 0.10)
    assert devig(odds, market="pitcher_strikeouts") == devig(odds, method="shin")
    assert devig(odds, market="moneyline") == devig(odds, method="multiplicative")


def test_unknown_market_falls_back_to_historical_behaviour():
    odds = _with_margin([0.6, 0.4], 0.05)
    assert devig(odds, market="some_new_market") == devig(odds, method="multiplicative")


def test_rejects_incomplete_or_junk_input():
    """Devig is only defined on a COMPLETE probability space. A partial market
    must return None rather than a confidently wrong number."""
    assert devig([-110], method="shin") is None
    assert devig([-110, None], method="shin") is None
    assert devig([], method="shin") is None


def test_no_vig_input_is_passed_through():
    """A book quoting a sub-100% market (stale/crossed) must not be 'corrected'
    into something with more confidence than the input justifies."""
    out = devig([200, 200], method="shin")   # 33.3 + 33.3 = 66.7% overround
    assert out == pytest.approx([0.5, 0.5], abs=1e-9)


@pytest.mark.parametrize("method", METHODS)
def test_deterministic(method):
    odds = _with_margin([0.62, 0.38], 0.09)
    assert devig(odds, method=method) == devig(odds, method=method)

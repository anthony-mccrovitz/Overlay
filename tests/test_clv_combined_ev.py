"""A bet that moved on BOTH the line and the price must be scored on both.

THE BUG: `_score_prop` and `_score_total` only computed price CLV when the line
was unchanged —

    if abs(close_line - open_line) < 1e-9:
        price_clv_pct = ...

— so a prop that went 5.5 → 6.5 AND -110 → -130 was graded on the half-point
alone and the price move was thrown away. On props, where both dimensions move
independently and constantly, that is the majority of bets.

`clv_ev_pct` replaces the two one-dimensional numbers with the economic one:

    EV% = fair_close(the exact bet we made) / price_we_paid - 1

Mixing a devigged close against a raw entry price is CORRECT here — it is the
standard +EV computation, not the fair-vs-raw asymmetry error. It also works
around a real limitation: prop snapshots record only the side we took, so the
entry has no opposite price and cannot be devigged at all.
"""
import pytest

from src.analytics.clv_tracker import _score_prop, _ou_combined_ev


def _snap(**kw):
    base = {"sport": "mlb", "market": "pitcher_strikeouts", "opening_line": 5.5,
            "direction": "OVER", "opening_odds": -110,
            "opening_implied_prob": 0.5238}
    base.update(kw)
    return base


def _close(line=5.5, over=-110, under=-110):
    return {"line": line, "over": over, "under": under, "source": "pinnacle"}


def test_price_move_alone_is_scored():
    """Line held, price shortened → the market moved toward us → positive EV."""
    res = _score_prop(_snap(), _close(over=-150, under=+120))
    assert res["clv_ev_pct"] > 0


def test_line_and_price_move_together_are_both_counted():
    """The regression case. Line moves our way AND price shortens: EV must
    exceed what the price move alone would have produced."""
    price_only = _score_prop(_snap(), _close(line=5.5, over=-130, under=+108))
    both = _score_prop(_snap(), _close(line=6.5, over=-130, under=+108))
    assert both["clv_ev_pct"] is not None
    # OVER 5.5 is easier to clear when the market's number rises to 6.5.
    assert both["clv_ev_pct"] > price_only["clv_ev_pct"], (
        "the line move contributed nothing — price and line are not being combined"
    )


def test_price_is_no_longer_discarded_when_the_line_moves():
    """Same line move, worse closing price → strictly less EV. Under the old
    code these two were identical, because price was ignored entirely."""
    good = _score_prop(_snap(), _close(line=6.5, over=-160, under=+130))
    bad = _score_prop(_snap(), _close(line=6.5, over=+140, under=-170))
    assert good["clv_ev_pct"] > bad["clv_ev_pct"]


def test_direction_is_respected():
    """An identical market move is good for one side and bad for the other."""
    over = _score_prop(_snap(direction="OVER"), _close(line=6.5))
    under = _score_prop(_snap(direction="UNDER"), _close(line=6.5))
    assert over["clv_ev_pct"] > 0 > under["clv_ev_pct"]


def test_no_calibration_means_no_number_rather_than_a_guess():
    """When the line moved and this lane has no usable points→probability slope,
    the honest answer is None. Interpolating through an uncalibrated slope would
    manufacture precision — the failure mode this whole audit was about."""
    snap = _snap(sport="nosuchsport", market="nosuchmarket")
    assert _ou_combined_ev(snap, _close(line=6.5), "OVER", 5.5, 6.5)["clv_ev_pct"] is None
    # ...but an unmoved line needs no slope at all, so it still scores.
    assert _ou_combined_ev(snap, _close(line=5.5), "OVER", 5.5, 5.5)["clv_ev_pct"] is not None


def test_a_market_that_did_not_move_scores_near_zero():
    """Bet at the number it closed at, with a fair book: no value, no penalty."""
    snap = _snap(opening_odds=-110, opening_implied_prob=0.5238)
    res = _score_prop(snap, _close(line=5.5, over=-110, under=-110))
    # Fair close is 50%; we paid -110 (52.38% raw), so EV is the vig we conceded.
    assert res["clv_ev_pct"] == pytest.approx(-4.5, abs=1.0)


def test_totals_get_the_same_treatment():
    """mlb/total is the live lane — it must produce an EV number too."""
    from src.analytics.clv_tracker import _score_total
    snap = {"sport": "mlb", "market": "total", "opening_line": 8.5,
            "direction": "OVER", "opening_odds": -110,
            "opening_implied_prob": 0.5238}
    res = _score_total(snap, {"line": 9.0, "over": -115, "under": -105})
    assert res["clv_ev_pct"] is not None, "totals still have no EV number"

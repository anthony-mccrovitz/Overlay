"""Promotion must run on expected value, not on a hit rate.

WHY THE GATE CHANGED (2026-07-30). It required `beat close >= 55%`. Measured on
our own 8 best-sampled lanes:

    corr(beat_close%, realised ROI) = -0.153
    corr(clv_ev_pct,  realised ROI) = +0.494

The criterion was pointing the wrong way. mlb/batter_total_bases beat the close
85.4% of the time and returned -2.9%; under the old gate its only obstacle was
ROI. mlb/f5_total showed "READY" on the scoreboard at 60.5% beat-close while its
mean EV was -5.67% (t=-10.3) — a lane about to be promoted on a metric that
could not see it was buying bad prices.

A rate is blind to magnitude. Winning 85% of half-cent moves while losing 15%
big ones is a losing lane with an excellent hit rate. These tests pin the
properties that make EV the right criterion and keep the two questions —
"clears the gate" and "is proven" — from being conflated.
"""
import math

import pytest

from src.analytics.ev_gate import EVStats, ev_by_lane, _stats


def _rows(sport, market, evs, **extra):
    return [dict(sport=sport, market=market, clv_ev_pct=e, **extra) for e in evs]


def test_a_high_hit_rate_with_negative_ev_is_negative():
    """THE case. Nine small wins, one large loss: 90% 'beat close', losing lane.

    This is the shape that made batter_total_bases look like the best lane in
    the book. Any criterion that ranks it positively is measuring the wrong
    thing.
    """
    evs = [0.5] * 9 + [-20.0]
    st = _stats(evs)
    beat_rate = sum(1 for e in evs if e > 0) / len(evs)
    assert beat_rate == 0.9, "hit rate is excellent"
    assert st.mean_ev_pct < 0, "yet expected value is negative"
    assert not st.positive


def test_a_low_hit_rate_with_positive_ev_is_positive():
    """The mirror image: mostly small losses, occasionally a big win."""
    st = _stats([-0.5] * 8 + [12.0, 10.0])
    assert st.mean_ev_pct > 0
    assert st.positive


def test_significance_is_separate_from_positivity():
    """A positive mean on a noisy handful of bets is not proof.

    The documented invariant is that clearing the gate != proven. EVStats keeps
    those as two fields so a caller cannot accidentally read one as the other.
    """
    noisy = _stats([30.0, -28.0, 25.0, -20.0, 5.0])
    assert noisy.positive
    assert not noisy.significant, "5 wild observations should not be significant"

    tight = _stats([2.0, 2.1, 1.9, 2.0, 2.05] * 12)
    assert tight.positive and tight.significant


def test_n_needed_is_reported_when_not_yet_significant():
    """Every gate line must be able to say how much more data a verdict needs."""
    st = _stats([1.0, -0.5, 2.0, 0.5, -1.0, 1.5])
    assert not st.significant
    assert st.n_needed and st.n_needed > st.n


def test_n_needed_shrinks_as_the_edge_grows():
    """A bigger edge needs fewer bets to prove — the sample floor is not a constant.

    Both series carry the SAME dispersion (±10, realistic for per-bet EV) and
    differ only in mean, which is the comparison that matters: n_needed is
    driven by the edge-to-noise ratio, not by the edge alone. This is the
    argument against a single fixed PROMOTE_MIN_N for every lane.
    """
    small = _stats([0.5 + 10, 0.5 - 10] * 20)
    large = _stats([5.0 + 10, 5.0 - 10] * 20)
    assert small.n_needed > large.n_needed > 1
    # A 0.5% edge against ±10 noise needs on the order of a thousand bets.
    assert small.n_needed > 500


def test_degenerate_zero_variance_is_not_significant():
    """Identical scores every time means something is wrong upstream, not that
    we have found a certainty."""
    st = _stats([1.0] * 50)
    assert st.sd == 0.0 and not st.significant


def test_too_few_rows_yields_nothing():
    assert _stats([]) is None
    assert _stats([1.0]) is None


def test_tainted_rows_are_excluded():
    """Same grounds market_stats excludes them: they were produced by a model
    state we have repudiated, so counting them measures something extinct."""
    rows = _rows("mlb", "total", [5.0] * 40) + _rows("mlb", "total", [-99.0] * 40, tainted=True)
    st = ev_by_lane(rows)[("mlb", "total")]
    assert st.n == 40
    assert st.mean_ev_pct == pytest.approx(5.0)


def test_moneyline_aliases_collapse():
    rows = _rows("mlb", "ml", [1.0] * 10) + _rows("mlb", "moneyline", [1.0] * 10)
    lanes = ev_by_lane(rows)
    assert ("mlb", "moneyline") in lanes
    assert lanes[("mlb", "moneyline")].n == 20


def test_rows_without_ev_are_skipped_not_zeroed():
    """A missing EV must not be read as 0% — that would drag every lane toward
    neutral and quietly dilute a real edge."""
    rows = _rows("mlb", "total", [4.0] * 10) + [
        {"sport": "mlb", "market": "total", "clv_ev_pct": None} for _ in range(50)]
    st = ev_by_lane(rows)[("mlb", "total")]
    assert st.n == 10
    assert st.mean_ev_pct == pytest.approx(4.0)


def test_gate_reports_ev_and_never_promotes_on_hit_rate_alone(monkeypatch):
    """End-to-end: the gate's verdict must follow EV, and its reason string must
    show EV, sample, ROI and a significance verdict."""
    import src.config.model_standard as ms

    monkeypatch.setattr(ms, "_clv_rows", lambda: {("x", "y"): {"sharp_beat_pct": 85.4}})
    monkeypatch.setattr("src.analytics.ev_gate.lane_ev",
                        lambda s, m: EVStats(500, -2.20, 8.0, -2.90, None, True))

    class _St:
        pnl, n = -14.5, 500
    monkeypatch.setattr("src.analytics.market_stats.market_stats",
                        lambda: {("x", "y"): _St()})

    ok, why = ms.clears_promotion_gate("x", "y")
    assert not ok, "promoted a lane with negative EV because its hit rate was 85%"
    assert "EV -2.20%" in why and "n=500" in why
    assert "85.4" in why, "beat-close should still be REPORTED as a diagnostic"


def test_the_f5_total_case_is_blocked(monkeypatch):
    """The lane the OLD gate was about to promote, with its real numbers.

    mlb/f5_total on 2026-07-30: beat close 60.5%, ROI +2.3% — it cleared the old
    gate on both counts and the scoreboard printed "✅ READY — clears gate". Its
    mean EV was -5.67% on n=292 (t=-10.3): it was systematically buying prices
    worse than the closing market, and the positive ROI was 243 bets of variance
    sitting on top of a negative edge.

    This is the ONLY configuration that distinguishes the two criteria — high
    hit rate AND positive ROI AND negative EV. A test where ROI is negative
    passes under either gate and proves nothing, which an earlier version of
    this file did.
    """
    import src.config.model_standard as ms

    monkeypatch.setattr(ms, "_clv_rows", lambda: {("mlb", "f5_total"): {"sharp_beat_pct": 60.5}})
    monkeypatch.setattr("src.analytics.ev_gate.lane_ev",
                        lambda s, m: EVStats(292, -5.67, 9.4, -10.30, None, True))

    class _St:
        pnl, n = 5.6, 243          # +2.3% ROI — profitable so far
    monkeypatch.setattr("src.analytics.market_stats.market_stats",
                        lambda: {("mlb", "f5_total"): _St()})

    ok, why = ms.clears_promotion_gate("mlb", "f5_total")
    assert not ok, (
        "promoted f5_total: it beats the close 60.5% and is +2.3% ROI, but its "
        "expected value against the close is -5.67%. The gate is running on hit "
        "rate again."
    )
    assert "EV -5.67%" in why


def test_gate_promotes_a_positive_ev_profitable_lane(monkeypatch):
    import src.config.model_standard as ms

    monkeypatch.setattr(ms, "_clv_rows", lambda: {("x", "y"): {"sharp_beat_pct": 58.0}})
    monkeypatch.setattr("src.analytics.ev_gate.lane_ev",
                        lambda s, m: EVStats(214, 2.99, 13.1, 3.34, None, True))

    class _St:
        pnl, n = 21.0, 214
    monkeypatch.setattr("src.analytics.market_stats.market_stats",
                        lambda: {("x", "y"): _St()})

    ok, why = ms.clears_promotion_gate("x", "y")
    assert ok
    assert "SIGNIFICANT" in why


def test_gate_holds_the_data_sufficiency_floor(monkeypatch):
    import src.config.model_standard as ms
    monkeypatch.setattr(ms, "_clv_rows", lambda: {})
    monkeypatch.setattr("src.analytics.ev_gate.lane_ev",
                        lambda s, m: EVStats(5, 40.0, 2.0, 44.0, None, True))
    ok, why = ms.clears_promotion_gate("x", "y")
    assert not ok and "insufficient sample" in why


def test_a_hair_above_zero_does_not_unlock_real_money(monkeypatch):
    """The materiality floor. mlb/moneyline's real numbers after the rework.

    EV +0.09% on n=1132 with t=+0.24 — it needs ~75,000 bets to be told apart
    from zero, yet `EV > 0 and ROI > 0` waved it through onto a gate that
    authorises real stakes. Estimated edges are biased upward, so the estimate
    has to clear a margin, not merely a sign.
    """
    import src.config.model_standard as ms

    monkeypatch.setattr(ms, "_clv_rows", lambda: {("mlb", "moneyline"): {"sharp_beat_pct": 48.9}})
    monkeypatch.setattr("src.analytics.ev_gate.lane_ev",
                        lambda s, m: EVStats(1132, 0.09, 12.7, 0.24, 74953, False))

    class _St:
        pnl, n = 2.8, 695          # +0.4% ROI
    monkeypatch.setattr("src.analytics.market_stats.market_stats",
                        lambda: {("mlb", "moneyline"): _St()})

    ok, why = ms.clears_promotion_gate("mlb", "moneyline")
    assert not ok, "promoted a lane whose edge is +0.09% and needs 75k bets to prove"
    assert "NOT significant" in why and "74953" in why


def test_the_floor_is_above_zero():
    """Guards the decision itself: someone setting this back to 0 reopens the
    hole above, so the constant is asserted rather than trusted."""
    from src.config.model_standard import PROMOTE_MIN_EV
    assert PROMOTE_MIN_EV > 0

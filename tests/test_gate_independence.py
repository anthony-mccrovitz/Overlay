"""A big sample from few slates is a small sample wearing a disguise.

THE CASE (2026-07-30): usa_mls/moneyline cleared every gate check and was one
approval from taking real money.

    EV +13.00% on n=46, ROI +7.9%, t=+2.28 SIGNIFICANT

What the number hid:
  · the 46 rows came from FOUR distinct days, 63% of them from ONE
  · the mean was outlier-driven — median +5.98%, and dropping the top 3 rows
    collapsed it to +5.01%; the largest single row read +192.7% EV
  · entries went in a MEDIAN 3.7 days before kickoff (max 16.6), so the
    "closing line value" mostly measures three days of news arriving
  · the t-test assumed 46 independent observations. They were not: bets on one
    slate share a weather front, a stale board and a news cycle.

For contrast the live lane, mlb/total, is 215 rows across 60 days with no day
over 6%.

n counts snapshots. PROMOTE_MIN_DAYS counts independent opportunities, which is
what a significance claim actually rests on.
"""
import pytest

from src.analytics.ev_gate import EVStats, ev_by_lane, _stats
from src.config.model_standard import PROMOTE_MIN_DAYS


def _rows(sport, market, evs, dates):
    return [{"sport": sport, "market": market, "clv_ev_pct": e, "date": d}
            for e, d in zip(evs, dates)]


def test_stats_counts_distinct_days():
    dates = ["2026-07-22"] * 29 + ["2026-05-23"] * 10 + ["2026-07-25"] * 6 + ["2026-07-30"]
    st = _stats([1.0] * 46, dates)
    assert st.n == 46
    assert st.n_days == 4
    assert st.max_day_share == pytest.approx(29 / 46, abs=0.01)


def test_clustering_is_visible_through_ev_by_lane():
    dates = ["2026-07-22"] * 29 + ["2026-05-23"] * 17
    lanes = ev_by_lane(_rows("soccer_usa_mls", "moneyline", [5.0] * 46, dates))
    st = lanes[("usa_mls", "moneyline")]
    assert st.n == 46 and st.n_days == 2


def test_a_spread_out_sample_is_not_flagged():
    dates = [f"2026-05-{d:02d}" for d in range(1, 31)] + [f"2026-06-{d:02d}" for d in range(1, 17)]
    st = _stats([2.0] * 46, dates)
    assert st.n_days == 46 and st.max_day_share == pytest.approx(1 / 46, abs=0.01)


def test_gate_blocks_the_usa_mls_shape(monkeypatch):
    """The real numbers. Everything else passes; only independence stops it."""
    import src.config.model_standard as ms
    monkeypatch.setattr(ms, "_clv_rows", lambda: {("usa_mls", "moneyline"): {"sharp_beat_pct": 51.4}})
    monkeypatch.setattr("src.analytics.ev_gate.lane_ev",
                        lambda s, m: EVStats(46, 13.00, 38.0, 2.28, None, True, 4, 0.63))

    class _St:
        pnl, n = 4.67, 59          # +7.9% ROI — genuinely profitable so far
    monkeypatch.setattr("src.analytics.market_stats.market_stats",
                        lambda: {("usa_mls", "moneyline"): _St()})

    ok, why = ms.clears_promotion_gate("usa_mls", "moneyline")
    assert not ok, (
        "promoted usa_mls on 46 rows from 4 days with 63% on one — the sample is "
        "large and thin at the same time"
    )
    assert "distinct day" in why and "4" in why


def test_gate_allows_a_well_spread_lane(monkeypatch):
    """mlb/total's shape must keep passing — this guard must not demote the only
    live lane."""
    import src.config.model_standard as ms
    monkeypatch.setattr(ms, "_clv_rows", lambda: {("mlb", "total"): {"sharp_beat_pct": 58.4}})
    monkeypatch.setattr("src.analytics.ev_gate.lane_ev",
                        lambda s, m: EVStats(215, 3.02, 13.1, 3.38, None, True, 60, 0.06))

    class _St:
        pnl, n = 21.9, 246
    monkeypatch.setattr("src.analytics.market_stats.market_stats",
                        lambda: {("mlb", "total"): _St()})
    ok, _ = ms.clears_promotion_gate("mlb", "total")
    assert ok


def test_the_floor_is_meaningful():
    assert PROMOTE_MIN_DAYS >= 10, "an independence floor under 10 days barely binds"


def test_missing_day_data_does_not_silently_block(monkeypatch):
    """Legacy rows without dates yield n_days=0. That is 'unknown', and the
    guard must not turn unknown into a rejection — the other checks still apply.
    """
    import src.config.model_standard as ms
    monkeypatch.setattr(ms, "_clv_rows", lambda: {})
    monkeypatch.setattr("src.analytics.ev_gate.lane_ev",
                        lambda s, m: EVStats(215, 3.0, 13.0, 3.4, None, True, 0, 0.0))

    class _St:
        pnl, n = 21.0, 215
    monkeypatch.setattr("src.analytics.market_stats.market_stats",
                        lambda: {("x", "y"): _St()})
    ok, _ = ms.clears_promotion_gate("x", "y")
    assert ok

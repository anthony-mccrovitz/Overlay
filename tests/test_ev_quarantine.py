"""Repriced markets must not count as closing-line evidence.

THE FINDING (2026-07-31). tennis/moneyline read EV +19.25% — the best number
on the scoreboard — while its realised ROI was −11%. The entire mean was three
rows, and the worst was Francesca Jones: opening +294, closing −325, "EV
+201%". A two-way market does not move 51 implied points on betting flow. It
moves on news that voids or remakes the bet — a tennis pre-match withdrawal
REFUNDS the stake, so that +201% could never have been collected — or the
closing join swapped sides. Either way it is not evidence of anything except
that the market repriced.

The bound is empirical, not aesthetic: across all 1,525 scored rows carrying
both prices, p99 of |implied move| is 23 points and only 5 rows (0.33%) exceed
35 — each one flip-shaped on inspection. mlb/total, the live lane, loses zero
rows to it.
"""
from __future__ import annotations

import pytest

from src.analytics.ev_gate import (
    MAX_IMPLIED_MOVE,
    ev_by_lane,
    ev_values_by_lane,
)


def _row(ev, o=0.50, c=0.52, sport="tennis_wta_wimbledon", market="moneyline",
         date="2026-06-29", **kw):
    d = {"clv_ev_pct": ev, "opening_implied_prob": o, "closing_implied_prob": c,
         "sport": sport, "market": market, "date": date}
    d.update(kw)
    return d


def test_a_flip_shaped_row_is_excluded_from_the_lane_mean():
    """The Jones row, in miniature: +294 -> -325 is a 51-point implied move."""
    rows = [_row(2.0, 0.50, 0.52, date=f"2026-06-{d:02d}") for d in range(1, 11)]
    rows.append(_row(201.3, 0.254, 0.765, date="2026-06-29"))
    st = ev_by_lane(rows)[("tennis", "moneyline")]
    assert st.n == 10, "the flip row must not be in the sample"
    assert st.mean_ev_pct == pytest.approx(2.0)
    assert st.n_quarantined == 1, "and its exclusion must be VISIBLE, not silent"


def test_ordinary_moves_are_untouched():
    """A 20-point move is a big but honest line move (p99 is 23); it stays."""
    rows = [_row(5.0, 0.50, 0.70, date=f"2026-06-{d:02d}") for d in range(1, 11)]
    st = ev_by_lane(rows)[("tennis", "moneyline")]
    assert st.n == 10
    assert st.n_quarantined == 0


def test_rows_missing_either_price_are_not_quarantined():
    """Prop rows store no opening/closing implied pair. The bound cannot judge
    them and must not eat them — quarantine requires evidence of a flip, and
    'unknown' is not evidence."""
    rows = [_row(60.0, o=None, c=None, sport="mlb", market="batter_home_runs",
                 date=f"2026-06-{d:02d}") for d in range(1, 11)]
    st = ev_by_lane(rows)[("mlb", "batter_home_runs")]
    assert st.n == 10
    assert st.n_quarantined == 0


def test_both_readers_apply_the_same_rule():
    """ev_values_by_lane feeds pooled_ev; if only ev_by_lane quarantined, a
    pooled lane would sneak the flip rows back in."""
    rows = [_row(2.0, date=f"2026-06-{d:02d}") for d in range(1, 6)]
    rows.append(_row(201.3, 0.254, 0.765))
    vals = ev_values_by_lane(rows)[("tennis", "moneyline")]
    assert len(vals) == 5
    assert all(v == 2.0 for v in vals)


def test_the_bound_is_the_documented_one():
    """35 points, chosen from the measured distribution (p99 = 23 pts, 0.33% of
    rows beyond 35, all flip-shaped). Guards a quiet 'loosen it so my lane
    passes' edit."""
    assert MAX_IMPLIED_MOVE == pytest.approx(0.35)


def test_exactly_at_the_bound_survives():
    """The bound excludes only what is BEYOND it. Kudermetova sits at exactly
    35.0 points and stays — a boundary case decided toward keeping data."""
    rows = [_row(165.0, 0.208, 0.558, date=f"2026-07-{d:02d}") for d in range(1, 6)]
    st = ev_by_lane(rows)[("tennis", "moneyline")]
    assert st.n == 5
    assert st.n_quarantined == 0


def test_gate_reason_names_the_quarantine(monkeypatch):
    """A lane that needed the quarantine must say so in its verdict."""
    from types import SimpleNamespace

    from src.config import model_standard as ms
    ev = SimpleNamespace(n=40, mean_ev_pct=5.0, significant=True, t=2.5,
                         n_needed=None, n_days=20, max_day_share=0.1,
                         n_quarantined=2)
    monkeypatch.setattr("src.analytics.ev_gate.lane_ev", lambda s, m: ev)
    monkeypatch.setattr(ms, "_clv_rows", lambda: {})

    class _St:
        pnl, n = 10.0, 40
    monkeypatch.setattr("src.analytics.market_stats.market_stats",
                        lambda: {("tennis", "moneyline"): _St()})
    ok, why = ms.clears_promotion_gate("tennis", "moneyline")
    assert "2 repriced row(s) quarantined" in why

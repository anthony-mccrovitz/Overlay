"""Unit tests for spread/total CLV scoring (line CLV in points + price CLV).

These lock in the sign conventions, which are the easy thing to get backwards:
positive line_clv must always mean "you got a better number than the close."
"""
from src.analytics.clv_tracker import (
    _score_spread, _score_total, _score_nrfi, _resolve_spread_team,
)


def _snap(opening_line, direction=None, opening_implied_prob=0.5):
    return {
        "opening_line": opening_line,
        "direction": direction,
        "opening_implied_prob": opening_implied_prob,
    }


# ── Spreads: positive line_clv = better number ──────────────────────────────

def test_spread_favorite_line_improves():
    # Laid -1.5, closed -2.5 → your -1.5 is easier to cover → +1.0 points.
    res = _score_spread(_snap(-1.5), {"line": -2.5, "odds": -110, "opp_odds": -110})
    assert res["line_clv"] == 1.0
    assert res["beat_close"] is True


def test_spread_favorite_line_worsens():
    # Laid -2.5, closed -2.0 → you laid too many points → -0.5.
    res = _score_spread(_snap(-2.5), {"line": -2.0, "odds": -110, "opp_odds": -110})
    assert res["line_clv"] == -0.5
    assert res["beat_close"] is False


def test_spread_underdog_line_worsens():
    # Took +1.5, closed +2.5 → dog now gets more points → your +1.5 is worse → -1.0.
    res = _score_spread(_snap(1.5), {"line": 2.5, "odds": -110, "opp_odds": -110})
    assert res["line_clv"] == -1.0
    assert res["beat_close"] is False


def test_spread_price_clv_only_at_matched_line():
    # Same line → price CLV is computed; better closing price → positive.
    res = _score_spread(_snap(-1.5, opening_implied_prob=0.50),
                        {"line": -1.5, "odds": -200, "opp_odds": 170})
    assert res["line_clv"] == 0.0
    assert res["price_clv_pct"] is not None
    # Line moved → price CLV suppressed (can't compare different lines).
    res2 = _score_spread(_snap(-1.5), {"line": -2.5, "odds": -110, "opp_odds": -110})
    assert res2["price_clv_pct"] is None


# ── Totals: direction-aware ─────────────────────────────────────────────────

def test_total_over_line_improves():
    # Took Over 8.0, closed 8.5 → lower bar for your over → +0.5.
    res = _score_total(_snap(8.0, "OVER"), {"line": 8.5, "over": -110, "under": -110})
    assert res["line_clv"] == 0.5
    assert res["beat_close"] is True


def test_total_under_line_improves():
    # Took Under 10.0, closed 9.5 → your under 10 is easier → +0.5.
    res = _score_total(_snap(10.0, "UNDER"), {"line": 9.5, "over": -110, "under": -110})
    assert res["line_clv"] == 0.5
    assert res["beat_close"] is True


def test_total_over_line_worsens():
    # Took Over 9.0, closed 8.0 → market dropped → your over is harder → -1.0.
    res = _score_total(_snap(9.0, "OVER"), {"line": 8.0, "over": -110, "under": -110})
    assert res["line_clv"] == -1.0
    assert res["beat_close"] is False


def test_total_requires_direction():
    assert _score_total(_snap(8.0, None), {"line": 8.0, "over": -110, "under": -110}) is None


def test_missing_opening_line_returns_none():
    assert _score_spread(_snap(None), {"line": -1.5, "odds": -110, "opp_odds": -110}) is None


# ── F5 totals reuse _score_total (same Over/Under shape) ────────────────────

def test_f5_total_over_line_improves():
    res = _score_total(_snap(4.5, "OVER"), {"line": 5.0, "over": -110, "under": -110})
    assert res["line_clv"] == 0.5
    assert res["beat_close"] is True


# ── NRFI / YRFI: binary prob CLV (no line), stored in clv/clv_pct ───────────

def test_nrfi_better_closing_prob_is_positive():
    # Took NRFI at opening implied 0.55; closing de-vig prob is higher → +CLV.
    snap = {"direction": "NRFI", "opening_implied_prob": 0.55}
    res = _score_nrfi(snap, {"nrfi": -200, "yrfi": 170})  # NRFI ~0.63 de-vig
    assert res["clv"] > 0
    assert res["clv_pct"] == round(res["clv"] * 100, 3)


def test_yrfi_uses_over_side():
    snap = {"direction": "YRFI", "opening_implied_prob": 0.40}
    res = _score_nrfi(snap, {"nrfi": -200, "yrfi": 170})
    # Picked YRFI → closing odds should be the YRFI (over) price.
    assert res["closing_odds"] == 170


# ── Team resolution ─────────────────────────────────────────────────────────

def test_resolve_full_name():
    assert _resolve_spread_team(
        "Milwaukee Brewers", "Milwaukee Brewers @ Detroit Tigers"
    ) == "Milwaukee Brewers"


def test_resolve_initials():
    assert _resolve_spread_team(
        "LAD -1.5 RL", "Los Angeles Dodgers @ San Francisco Giants"
    ) == "Los Angeles Dodgers"


def test_resolve_first_three():
    assert _resolve_spread_team(
        "MIL +1.5 RL", "Milwaukee Brewers @ Detroit Tigers"
    ) == "Milwaukee Brewers"


# ── get_clv_summary: headline counts line-CLV, not just price-CLV ────────────

def test_clv_summary_counts_line_and_price_markets(monkeypatch):
    """Regression: totals/spreads store `line_clv`, not `clv`. The headline must
    count them in scored coverage and the unified beat-close rate — otherwise the
    dashboard looks frozen at the moneyline-only count even as totals grow."""
    import src.analytics.clv_tracker as ct

    snaps = [
        # 2 price-CLV moneyline picks, 1 beats the close
        {"market": "moneyline", "clv": 0.02, "clv_pct": 2.0},
        {"market": "moneyline", "clv": -0.01, "clv_pct": -1.0},
        # 3 line-CLV totals, 2 beat the close
        {"market": "total", "line_clv": 0.5, "beat_close": True},
        {"market": "total", "line_clv": -0.5, "beat_close": False},
        {"market": "spread", "line_clv": 1.0, "beat_close": True},
        # an untracked snapshot (no closing) must not count
        {"market": "total"},
    ]
    monkeypatch.setattr(ct, "_load_snapshots", lambda: snaps)

    s = ct.get_clv_summary()
    assert s["with_clv"] == 2          # price-CLV only (back-compat key)
    assert s["with_line_clv"] == 3     # totals + spread
    assert s["scored_all"] == 5        # union, excludes the unscored total
    # unified beat-close: 1 price (clv_pct>0) + 2 line beats = 3 / 5 = 60%
    assert s["beat_close_pct_all"] == 60.0

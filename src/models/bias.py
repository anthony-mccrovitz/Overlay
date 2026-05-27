"""
Favorite-longshot bias correction (Snowberg & Wolfers 2010, Hubaček et al. 2019).

FLS research (20+ papers) shows that bettors systematically OVERbet longshots
(lotto-ticket mentality) and underbet heavy favorites. Books exploit this:
  - Heavy favorites: books can offer slightly lower odds than fair value
    because public underbacks them → implied overstates true probability
    → correction lowers adjusted_implied → easier to find edge on favorites
  - Heavy longshots: public overbacks them so books offer worse odds than
    fair value → implied ALSO overstates true probability → correction RAISES
    adjusted_implied → harder to find edge on longshots (penalizes them)

Both ends of the spectrum have book implied > true probability. The correction
adds a positive term for both, but the sign of the resulting edge impact differs:
  - Favorites (implied > 0.65): correction is negative → lowers bar → pro-favorite
  - Longshots (implied < 0.38): correction is positive → raises bar → anti-longshot

Magnitude calibrated to Snowberg & Wolfers (2010) and Vlastakis (2008) Table 3:
  - Heavy favorites (-200 or shorter): implied overstated ~3-5%
  - Heavy longshots (+200 or longer): implied overstated ~4-8% (stronger effect)
"""
from __future__ import annotations


def fls_correction(implied_prob: float) -> float:
    """
    Additive correction to the bookmaker's implied probability before computing
    edge. Raises adjusted_implied for longshots (requiring more model edge to
    pass threshold) and lowers it for heavy favorites (slightly easier to find
    edge vs books that systematically overcharge favorites).

    Usage:
        adjusted_implied = implied_prob + fls_correction(implied_prob)
        edge = (model_prob - adjusted_implied) * 100
    """
    if implied_prob >= 0.72:
        # Heavy favorite (-257 or shorter): books overcharge ~4% → lower bar
        return -0.04
    elif implied_prob >= 0.65:
        # Favorite (-186 to -257): books overcharge ~2% → lower bar slightly
        return -0.02
    elif implied_prob <= 0.28:
        # Heavy longshot (+257 or longer): raise bar by 6% — research shows
        # longshots are systematically overpriced; need substantial model edge
        return +0.06
    elif implied_prob <= 0.38:
        # Longshot (+163 to +257): raise bar by 3%
        return +0.03
    # Pick'em range: no reliable systematic bias
    return 0.0


def adjusted_edge(model_prob: float, implied_prob: float) -> float:
    """
    Edge in percentage points, with favorite-longshot bias correction applied
    to the implied probability before comparison.

    Positive = model thinks this side is underpriced (buy signal).
    Negative = model thinks this side is overpriced (fade signal).
    """
    corrected_implied = implied_prob + fls_correction(implied_prob)
    return (model_prob - corrected_implied) * 100

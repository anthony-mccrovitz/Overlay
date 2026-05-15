"""
Favorite-longshot bias correction (Vlastakis et al. 2008, Hubaček et al. 2019).

Books systematically overcharge on heavy favorites (implied > 0.65) and
undercharge on heavy longshots (implied < 0.40). Applying this correction
decorrelates our model from the bookmaker's pricing bias and improves CLV.

Magnitude calibrated to Vlastakis (2008) Table 3:
  - Heavy favorites (-200 or shorter): books overvalue by ~3-5%
  - Heavy longshots (+200 or longer): books undervalue by ~2-4%
  - Mid-range (roughly pick'em to -150): minimal systematic bias
"""
from __future__ import annotations


def fls_correction(implied_prob: float) -> float:
    """
    Additive correction to apply to the bookmaker's implied probability
    before computing edge. Positive = implied was understated (longshot),
    negative = implied was overstated (favorite).

    Usage:
        adjusted_implied = implied_prob + fls_correction(implied_prob)
        edge = (model_prob - adjusted_implied) * 100
    """
    if implied_prob >= 0.72:
        # Heavy favorite (-257 or shorter): books overcharge ~4%
        return -0.04
    elif implied_prob >= 0.65:
        # Favorite (-186 to -257): books overcharge ~2%
        return -0.02
    elif implied_prob <= 0.28:
        # Heavy longshot (+257 or longer): books undercharge ~4%
        return +0.04
    elif implied_prob <= 0.38:
        # Longshot (+163 to +257): books undercharge ~2%
        return +0.02
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

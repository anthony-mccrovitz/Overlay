"""Vig removal — one implementation, three methods, chosen by market vig.

WHY THIS EXISTS SEPARATELY: `entry_fair._devig` does `raw / overround`, the
multiplicative (proportional) method. That is the right call on a Pinnacle
moneyline, where the overround is 1–3% and there is barely any margin to
misallocate. It is the WRONG call on a retail player prop carrying 8–15% vig,
because multiplicative spreads that margin in proportion to raw probability and
therefore ignores favourite–longshot bias — the well-documented tendency of
books to load proportionally more margin onto the longshot side.

The consequence in this repo is not academic. Prop fair probabilities feed the
edge calculation AND the CLV benchmark, so a biased devig biases both the reason
we bet and the scorecard we grade ourselves with, in the same direction.

Methods, in increasing order of how aggressively they correct that bias:

  multiplicative  p_i = π_i / Σ
                  Margin proportional to raw probability. Fast, standard, fine
                  under ~4% vig. Default for Pinnacle-priced game lines.

  power           p_i = π_i^k, k solved so Σp = 1
                  Sits between multiplicative and Shin. Corrects longshot bias
                  without committing to Shin's insider-trading model.

  shin            p_i = [√(z² + 4(1−z)·π_i²/Σ) − z] / (2(1−z)), z solved so Σp = 1
                  Models the margin as the book's defence against insider money
                  (Shin 1993), which predicts more margin on longshots. The most
                  theoretically grounded option and the usual recommendation for
                  high-vig markets. Default for props here.

All three are deterministic and exact-inverse-checked by tests: feed in odds
built from known probabilities plus a known margin, get the probabilities back.
"""
from __future__ import annotations

__all__ = ["american_to_implied", "implied_to_american", "devig", "DEFAULT_METHOD_FOR"]

# Which method each market family should use. Keyed by market string; anything
# unlisted falls back to multiplicative, matching the historical behaviour so an
# unrecognised market can never silently change its numbers.
DEFAULT_METHOD_FOR: dict[str, str] = {
    # High-vig retail props → Shin.
    "prop": "shin", "pitcher_strikeouts": "shin", "batter_hits": "shin",
    "batter_home_runs": "shin", "batter_total_bases": "shin",
    "batter_rbis": "shin", "batter_walks": "shin", "batter_runs_scored": "shin",
    "player_points": "shin", "player_rebounds": "shin", "player_assists": "shin",
    "player_threes": "shin", "player_pra": "shin", "player_blocks": "shin",
    "player_steals": "shin", "player_goals": "shin",
    "player_shots_on_goal": "shin", "player_blocked_shots": "shin",
    "anytime_scorer": "shin", "player_goal_scorer_anytime": "shin",
    # Low-vig, sharp-priced game lines → multiplicative.
    "moneyline": "multiplicative", "total": "multiplicative",
    "spread": "multiplicative", "f5_total": "multiplicative",
    "puck_line": "multiplicative", "nrfi": "multiplicative",
}

_TOL = 1e-12
_MAX_ITER = 200


def american_to_implied(odds: float) -> float:
    """American odds → raw (with-vig) implied probability."""
    odds = float(odds)
    if odds == 0:
        return 0.5
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def implied_to_american(p: float) -> float:
    """Probability → American odds (inverse of american_to_implied)."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"probability out of range: {p}")
    return round(-100.0 * p / (1.0 - p), 2) if p >= 0.5 else round(100.0 * (1.0 - p) / p, 2)


def _multiplicative(raw: list[float]) -> list[float]:
    total = sum(raw)
    return [r / total for r in raw]


def _power(raw: list[float]) -> list[float]:
    """Solve Σ π_i^k = 1 for k by bisection.

    Overround > 1 means Σπ > 1, and every π_i < 1, so raising to a HIGHER power
    shrinks the sum: k lives above 1 and the sum is monotonically decreasing in
    k. That monotonicity is what makes plain bisection safe here.
    """
    total = sum(raw)
    if total <= 1.0:                       # no vig to strip (or a stale quote)
        return _multiplicative(raw)
    lo, hi = 1.0, 2.0
    while sum(r ** hi for r in raw) > 1.0 and hi < 64.0:
        hi *= 2.0
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        s = sum(r ** mid for r in raw)
        if abs(s - 1.0) < _TOL:
            break
        if s > 1.0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2.0
    out = [r ** k for r in raw]
    s = sum(out)
    return [o / s for o in out]            # normalise away residual solver error


def _shin(raw: list[float]) -> list[float]:
    """Solve Shin's z (the insider-money fraction) by bisection on Σp = 1.

    Bisection rather than the two-outcome closed form on purpose: the same code
    then serves 3-way soccer 1X2 and any n-way market, and there is only one
    path to test. z is bounded in [0, 1) and Σp decreases monotonically in z.
    """
    total = sum(raw)
    if total <= 1.0:
        return _multiplicative(raw)

    def probs(z: float) -> list[float]:
        if z <= 0.0:
            return _multiplicative(raw)
        d = 2.0 * (1.0 - z)
        return [((z * z + 4.0 * (1.0 - z) * (r * r) / total) ** 0.5 - z) / d
                for r in raw]

    lo, hi = 0.0, 0.99
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        s = sum(probs(mid))
        if abs(s - 1.0) < _TOL:
            break
        if s > 1.0:
            lo = mid
        else:
            hi = mid
    out = probs((lo + hi) / 2.0)
    s = sum(out)
    return [o / s for o in out] if s > 0 else _multiplicative(raw)


_METHODS = {"multiplicative": _multiplicative, "power": _power, "shin": _shin}


def devig(odds: list[float] | tuple[float, ...], method: str = "multiplicative",
          market: str | None = None) -> list[float] | None:
    """Strip vig from a complete set of American odds for one market.

    Pass EVERY outcome (both sides of a total, all three of a 1X2) — the methods
    are defined on a complete probability space and silently return nonsense on
    a partial one. Returns fair probabilities in input order, or None if the
    input is unusable.

    `market` selects the method automatically via DEFAULT_METHOD_FOR, so callers
    don't each hard-code "props use Shin" and drift apart the way the sport-key
    mapping did.
    """
    vals = [o for o in odds if o is not None]
    if len(vals) < 2 or len(vals) != len(odds):
        return None
    if market is not None:
        method = DEFAULT_METHOD_FOR.get(str(market), method)
    fn = _METHODS.get(method)
    if fn is None:
        raise ValueError(f"unknown devig method: {method!r}")
    try:
        raw = [american_to_implied(o) for o in vals]
    except (TypeError, ValueError):
        return None
    if any(r <= 0.0 or r >= 1.0 for r in raw):
        return None
    out = fn(raw)
    if any(p <= 0.0 or p >= 1.0 for p in out):
        return None
    return out

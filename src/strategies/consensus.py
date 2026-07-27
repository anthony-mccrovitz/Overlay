"""
src/strategies/consensus.py — cross-book consensus fair probabilities.

Kaunitz, Zhong & Kreiner (2017, arXiv:1710.02824) showed that the AVERAGE of
many bookmakers' odds is an extremely accurate outcome-probability estimate
(R² ≈ 0.999 against realized results), and that simply betting any single book
priced sufficiently above that consensus was +EV for a decade of closing odds —
no forecasting model involved. devig_ev anchors on Pinnacle alone; this module
anchors on the MEDIAN of every book quoting both sides (the robust small-board
analog of Kaunitz's 32-book mean — see loo_consensus), with the destination
book left out of its own consensus (a lagging book must not drag the reference
toward itself — that lag IS the signal).

The math lives here, pandas-free, because two consumers need it byte-identical:
the live shadow strategy (consensus_ev over the wide odds DataFrame) and the
historical replay (scripts/backtest_consensus.py over raw Odds API JSON).
"""
from __future__ import annotations

# LOO consensus needs enough independent books to be a "crowd" — with fewer
# than 3 the mean is just one or two other books' opinion, not a consensus.
MIN_BOOKS = 3
# Same bar as devig_ev's _MIN_EV_PCT so the two strategies' CLV verdicts are a
# clean head-to-head: Pinnacle-anchor vs board-consensus, identical threshold.
MIN_EV_PCT = 2.0
# Same per-book two-way sanity band as shadow_strategies: a clean 2-way book
# sums ~1.02-1.10; below 0.95 it's a 3-way market missing an outcome (phantom
# EV on every side), above 1.25 the quote is malformed or hyper-vigged.
OVERROUND_MIN, OVERROUND_MAX = 0.95, 1.25


def implied(odds: float | None) -> float | None:
    """American odds → raw (with-vig) implied probability. None-safe."""
    if odds is None:
        return None
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return None
    if o != o or o == 0:  # NaN or zero
        return None
    if o > 0:
        return 100.0 / (o + 100.0)
    return abs(o) / (abs(o) + 100.0)


def per_book_fair(
    pairs: dict[str, tuple],
    overround_bounds: tuple[float, float] = (OVERROUND_MIN, OVERROUND_MAX),
) -> dict[str, float]:
    """Two(+)-sided devig per book: {book: fair prob of the FIRST outcome}.

    `pairs` maps book → tuple of American odds with the picked outcome first
    and every other outcome after it, e.g. {"FanDuel": (-120, +104)}. A book
    missing any side, or whose summed implied probs fall outside
    `overround_bounds`, is dropped — vig is a per-book property, so each book
    is devigged against itself before it may join a consensus.
    """
    lo, hi = overround_bounds
    out: dict[str, float] = {}
    for book, odds_tuple in pairs.items():
        imps = [implied(o) for o in odds_tuple]
        if len(imps) < 2 or any(i is None or i <= 0 for i in imps):
            continue
        overround = sum(imps)  # type: ignore[arg-type]
        if not (lo <= overround <= hi):
            continue
        out[book] = imps[0] / overround  # type: ignore[operator]
    return out


def draw_team(away: str, home: str) -> str:
    """Canonical `team` label for a DRAW-side pick: "Draw (Away @ Home)".

    Every join in the pick/snapshot/closing pipeline keys on (date, team) —
    a bare "Draw" collides with every other draw on a multi-game slate, so
    the matchup is packed INTO the team string. Both sides of every join
    (pick emission, entry_fair, closing fetchers) must build the key through
    this one function so the format can never drift apart.
    """
    return f"Draw ({away} @ {home})"


def is_draw_selection(team: str | None) -> bool:
    """True when a pick/snapshot `team` value is a DRAW-side selection.

    Used to bypass the substring-fallback joins: "Draw (X @ Y)" CONTAINS both
    team names, so a partial match would silently score the draw as a team pick.
    """
    return str(team or "").strip().lower().startswith("draw")


def loo_consensus(
    fair_by_book: dict[str, float],
    exclude: str | None = None,
    min_books: int = MIN_BOOKS,
) -> tuple[float, int] | None:
    """Leave-one-out consensus: MEDIAN fair prob across books, `exclude` omitted.

    Kaunitz used the mean — over ~32 books, where one outlier barely moves it.
    Our boards carry ~5-8 books, where a single off book (even Pinnacle on an
    early sharp move) drags a mean far enough to fire phantom picks and
    collapse this strategy into a noisy copy of the Pinnacle-anchored devig_ev.
    The median is the same crowd estimate made robust at small n: a lone
    outlier — sharp or soft — is just one vote, never the verdict.

    Returns (median_prob, n_books) or None when fewer than `min_books` books
    survive the exclusion — a consensus of one or two books isn't a crowd.
    """
    probs = sorted(p for b, p in fair_by_book.items() if b != exclude)
    n = len(probs)
    if n < min_books:
        return None
    mid = n // 2
    median = probs[mid] if n % 2 else (probs[mid - 1] + probs[mid]) / 2.0
    return median, n

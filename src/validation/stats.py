"""
Statistical validation for paper trading results.

Answers the question: "Do we have a real edge, or is this noise?"

Tests:
  1. Binomial test — is our win rate significantly above home-team baseline?
  2. CLV t-test — is mean CLV significantly positive?
  3. ROI bootstrap — 95% confidence interval on return on investment
  4. Sharpe ratio — risk-adjusted return per unit of volatility
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np


HOME_BASELINE = 0.537  # MLB home team historical win rate


@dataclass
class ValidationResult:
    total_bets: int
    wins: int
    losses: int
    win_rate: float
    roi: float
    total_profit: float
    total_staked: float

    # Binomial test
    binom_p_value: float
    binom_significant: bool

    # CLV
    clv_mean: float
    clv_picks_with_closing: int
    clv_t_stat: float
    clv_p_value: float
    clv_significant: bool

    # ROI confidence interval (bootstrap)
    roi_ci_lower: float
    roi_ci_upper: float

    # Risk metrics
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_pct: float

    # Verdict
    verdict: str
    verdict_detail: str
    days_tracked: int
    bets_needed: int


def _binomial_test(wins: int, n: int, baseline: float = HOME_BASELINE) -> float:
    """One-sided binomial test: P(X >= wins) given baseline probability."""
    if n == 0:
        return 1.0
    try:
        from scipy.stats import binomtest
        result = binomtest(wins, n, baseline, alternative="greater")
        return result.pvalue
    except ImportError:
        p = 0.0
        for k in range(wins, n + 1):
            p += math.comb(n, k) * (baseline ** k) * ((1 - baseline) ** (n - k))
        return p


def _t_test_one_sample(values: list[float], mu_0: float = 0.0) -> tuple[float, float]:
    """One-sample t-test. Returns (t_stat, p_value)."""
    if len(values) < 2:
        return 0.0, 1.0
    arr = np.array(values)
    n = len(arr)
    mean = arr.mean()
    se = arr.std(ddof=1) / math.sqrt(n)
    if se == 0:
        return 0.0, 1.0
    t = (mean - mu_0) / se

    try:
        from scipy.stats import t as t_dist
        p = 1 - t_dist.cdf(t, df=n - 1)
    except ImportError:
        p = 0.5 if t <= 0 else max(0.01, 0.5 - t * 0.05)
    return float(t), float(p)


def _bootstrap_roi_ci(
    profits: list[float],
    stake_per_bet: float,
    n_bootstrap: int = 10000,
    ci: float = 0.95,
) -> tuple[float, float]:
    """Bootstrap 95% CI on ROI."""
    if not profits:
        return 0.0, 0.0
    arr = np.array(profits)
    rng = np.random.default_rng(42)
    rois = []
    for _ in range(n_bootstrap):
        sample = rng.choice(arr, size=len(arr), replace=True)
        roi = sample.sum() / (len(sample) * stake_per_bet)
        rois.append(roi)
    rois = np.array(rois)
    alpha = (1 - ci) / 2
    return float(np.percentile(rois, alpha * 100)), float(np.percentile(rois, (1 - alpha) * 100))


def _sharpe_ratio(daily_profits: list[float]) -> float:
    """Annualized Sharpe ratio from daily P&L."""
    if len(daily_profits) < 2:
        return 0.0
    arr = np.array(daily_profits)
    mean = arr.mean()
    std = arr.std(ddof=1)
    if std == 0:
        return 0.0
    return float((mean / std) * math.sqrt(252))


def _max_drawdown(cumulative_profits: list[float]) -> tuple[float, float]:
    """Max drawdown in absolute dollars and as % of peak."""
    if not cumulative_profits:
        return 0.0, 0.0
    peak = 0.0
    max_dd = 0.0
    max_dd_pct = 0.0
    running = 0.0
    for p in cumulative_profits:
        running += p
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd / peak if peak > 0 else 0.0
    return max_dd, max_dd_pct


def _verdict(
    n: int, binom_p: float, clv_mean: float, clv_n: int, clv_p: float, roi: float,
) -> tuple[str, str, int]:
    """Returns (verdict, detail, bets_still_needed)."""
    if n < 30:
        needed = 50 - n
        return (
            "TOO EARLY",
            f"Only {n} bets tracked. Need at least 50 for any signal, 200 for real confidence.",
            needed,
        )

    if n < 100:
        signals = []
        if binom_p < 0.10:
            signals.append("win rate trending positive")
        if clv_mean > 0.5 and clv_n >= 20:
            signals.append("CLV looks promising")
        if roi > 0:
            signals.append("profitable so far")

        if signals:
            detail = f"Early positive signs: {', '.join(signals)}. Need 100+ bets to confirm."
        else:
            detail = f"No clear signal yet at {n} bets. This is normal — keep tracking."
        return "EARLY SIGNAL", detail, 100 - n

    if n < 200:
        if binom_p < 0.05 and clv_mean > 0:
            return (
                "PROMISING",
                f"Win rate significant (p={binom_p:.3f}), CLV positive ({clv_mean:+.1f}c). "
                f"Continue to 200 bets for full validation.",
                200 - n,
            )
        if roi > 0 and clv_mean > 0:
            return (
                "CAUTIOUSLY POSITIVE",
                f"Profitable with positive CLV but not yet statistically significant (p={binom_p:.3f}). "
                f"Continue tracking.",
                200 - n,
            )
        return (
            "INCONCLUSIVE",
            f"Mixed signals at {n} bets (p={binom_p:.3f}, CLV={clv_mean:+.1f}c). Keep going.",
            200 - n,
        )

    # 200+ bets — decision point
    if binom_p < 0.05 and clv_mean > 0.5:
        return (
            "EDGE CONFIRMED",
            f"Statistically significant win rate (p={binom_p:.4f}) with positive CLV "
            f"({clv_mean:+.1f}c) over {n} bets. Green light for live betting with fractional Kelly.",
            0,
        )
    if binom_p < 0.10 and clv_mean > 0:
        return (
            "LIKELY EDGE",
            f"Near-significant (p={binom_p:.3f}) with positive CLV. Consider live betting "
            f"with very conservative sizing (quarter Kelly).",
            0,
        )
    if clv_mean > 0 and roi > 0:
        return (
            "POSSIBLE EDGE",
            f"Positive ROI and CLV but win rate not significant (p={binom_p:.3f}). "
            f"The edge may be real but small. Continue tracking or iterate on the model.",
            0,
        )
    return (
        "NO EDGE DETECTED",
        f"After {n} bets: p={binom_p:.3f}, CLV={clv_mean:+.1f}c, ROI={roi*100:+.1f}%. "
        f"Model does not show a reliable edge. Iterate before risking real money.",
        0,
    )


def validate(
    pnl_path: Path | str = "data/pnl/picks.json",
    clv_path: Path | str = "data/clv/clv_records.json",
    flat_stake: float = 100.0,
) -> ValidationResult:
    """Run full statistical validation on paper trading results."""
    pnl_path = Path(pnl_path)
    clv_path = Path(clv_path)

    # Load P&L data
    pnl_picks = []
    if pnl_path.exists():
        with open(pnl_path) as f:
            data = json.load(f)
        pnl_picks = [p for p in data.get("picks", []) if p.get("result") in ("win", "loss")]

    wins = sum(1 for p in pnl_picks if p["result"] == "win")
    losses = sum(1 for p in pnl_picks if p["result"] == "loss")
    n = wins + losses
    win_rate = wins / n if n > 0 else 0.0

    profits = [float(p.get("profit", 0) or 0) for p in pnl_picks]
    total_profit = sum(profits)
    total_staked = n * flat_stake
    roi = total_profit / total_staked if total_staked > 0 else 0.0

    # Binomial test
    binom_p = _binomial_test(wins, n)

    # Load CLV data
    clv_values = []
    if clv_path.exists():
        with open(clv_path) as f:
            clv_data = json.load(f)
        clv_values = [
            p["clv_cents"] for p in clv_data.get("picks", [])
            if p.get("clv_cents") is not None
        ]

    clv_mean = sum(clv_values) / len(clv_values) if clv_values else 0.0
    clv_t, clv_p = _t_test_one_sample(clv_values) if clv_values else (0.0, 1.0)

    # ROI bootstrap
    roi_lo, roi_hi = _bootstrap_roi_ci(profits, flat_stake) if profits else (0.0, 0.0)

    # Daily P&L for Sharpe
    daily_pnl: dict[str, float] = {}
    for p in pnl_picks:
        d = (p.get("resulted_at") or p.get("recorded_at") or "")[:10]
        if d:
            daily_pnl[d] = daily_pnl.get(d, 0) + float(p.get("profit", 0) or 0)
    sharpe = _sharpe_ratio(list(daily_pnl.values()))

    # Max drawdown
    max_dd, max_dd_pct = _max_drawdown(profits)

    # Days tracked
    dates = sorted(daily_pnl.keys())
    days_tracked = len(dates)

    # Verdict
    verdict, detail, needed = _verdict(n, binom_p, clv_mean, len(clv_values), clv_p, roi)

    return ValidationResult(
        total_bets=n,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        roi=roi,
        total_profit=total_profit,
        total_staked=total_staked,
        binom_p_value=binom_p,
        binom_significant=binom_p < 0.05,
        clv_mean=clv_mean,
        clv_picks_with_closing=len(clv_values),
        clv_t_stat=clv_t,
        clv_p_value=clv_p,
        clv_significant=clv_p < 0.05,
        roi_ci_lower=roi_lo,
        roi_ci_upper=roi_hi,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        verdict=verdict,
        verdict_detail=detail,
        days_tracked=days_tracked,
        bets_needed=needed,
    )


def print_validation(v: ValidationResult) -> str:
    """Format validation results as a human-readable report."""
    lines = [
        f"\n{'='*60}",
        f"  PAPER TRADING VALIDATION — Day {v.days_tracked}",
        f"{'='*60}",
        f"",
        f"  Record:      {v.wins}-{v.losses} ({v.win_rate:.1%})",
        f"  Baseline:    {HOME_BASELINE:.1%} (MLB home team)",
        f"  P-value:     {v.binom_p_value:.4f} {'*** SIGNIFICANT ***' if v.binom_significant else ''}",
        f"",
        f"  ROI:         {v.roi:+.1%} (${v.total_profit:+,.0f} on ${v.total_staked:,.0f})",
        f"  ROI 95% CI:  [{v.roi_ci_lower:+.1%}, {v.roi_ci_upper:+.1%}]",
        f"",
        f"  CLV:         {v.clv_mean:+.1f} cents avg ({v.clv_picks_with_closing} with closing lines)",
        f"  CLV p-value: {v.clv_p_value:.4f} {'*** SIGNIFICANT ***' if v.clv_significant else ''}",
        f"",
        f"  Sharpe:      {v.sharpe_ratio:.2f}",
        f"  Max DD:      ${v.max_drawdown:,.0f} ({v.max_drawdown_pct:.1%})",
        f"",
        f"  {'─'*50}",
        f"  VERDICT: {v.verdict}",
        f"  {v.verdict_detail}",
    ]
    if v.bets_needed > 0:
        lines.append(f"  Bets remaining: ~{v.bets_needed}")
    lines.append(f"  {'='*50}\n")
    return "\n".join(lines)

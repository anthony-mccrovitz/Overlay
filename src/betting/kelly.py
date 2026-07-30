"""
Kelly criterion bet sizing.

The Kelly criterion tells you the mathematically optimal bet size
based on your edge and the available odds. It maximizes long-term
bankroll growth while minimizing risk of ruin.

Full Kelly can be aggressive — fractional Kelly (e.g., half Kelly)
is more conservative and commonly used in practice.

Kelly formula: f* = (bp - q) / b
  where:
    b = decimal odds - 1 (net odds received on a win)
    p = probability of winning (our model's estimate)
    q = probability of losing (1 - p)
    f* = fraction of bankroll to bet
"""
import pandas as pd
import numpy as np


def _implied_prob(american_odds: float) -> float:
    """American odds → implied (with-vig) probability."""
    o = float(american_odds)
    if o == 0:
        return 0.5
    return 100.0 / (o + 100.0) if o > 0 else abs(o) / (abs(o) + 100.0)


def shrunk_prob(model_prob: float, american_odds: float,
                sport: str | None = None, market: str | None = None) -> float:
    """Pull the model's probability toward the market by its measured reliability.

    WHY: Kelly is exquisitely sensitive to the edge estimate, and our edge
    estimates are known to be inflated — `edge_shrink` measures k = realised_pp /
    claimed_pp per lane, and mlb/total (the only live lane) sits at k=0.67: it
    claims 6.17pp and delivers 4.12pp.

    Until now that shrink was applied to the edge RECORDED in the ledger
    (schema.py calls calibrate_edge) but never to the stake, because size_bets
    passes the raw ModelProb to kelly_fraction. So every bet was written down at
    a shrunk edge and sized at an unshrunk one — the ledger and the wallet
    disagreed about the same bet, and the wallet was the optimistic one.

    At k=0.67 that oversizes by roughly half, which turns a nominal quarter-Kelly
    into ~0.37 Kelly. The asymmetry matters: overbetting Kelly costs growth much
    faster than underbetting, and past ~1.5x the growth rate can go negative. So
    the correction is applied to the EDGE (prob − implied), not to the
    probability itself, which is what "shrink toward the market" actually means.

    No shrink record → returns the input unchanged, matching prior behaviour.
    """
    if sport is None or market is None:
        return model_prob
    try:
        from src.analytics.calibration_gate import calibrate_edge
    except Exception:
        return model_prob
    implied = _implied_prob(american_odds)
    claimed_pp = (model_prob - implied) * 100.0
    if claimed_pp <= 0:
        return model_prob                     # no claimed edge → nothing to shrink
    adj_pp = calibrate_edge(sport, market, claimed_pp)
    if adj_pp is None:
        return model_prob
    return max(0.0, min(1.0, implied + adj_pp / 100.0))


def kelly_fraction(
    model_prob: float,
    american_odds: float,
    fraction: float = 0.5,
) -> float:
    """
    Calculate Kelly criterion bet size as a fraction of bankroll.

    Args:
        model_prob: Our model's estimated win probability
        american_odds: American odds offered by sportsbook
        fraction: Kelly fraction (1.0 = full Kelly, 0.5 = half Kelly)

    Returns:
        Fraction of bankroll to bet (0.0 if no edge)
    """
    # Convert American odds to decimal
    if american_odds > 0:
        decimal_odds = 1 + (american_odds / 100)
    else:
        decimal_odds = 1 + (100 / abs(american_odds))

    b = decimal_odds - 1  # Net profit per dollar wagered
    p = model_prob
    q = 1 - p

    # Kelly formula
    kelly = (b * p - q) / b

    # No bet if no edge. The epsilon matters: shrinking a lane's edge to zero
    # lands the probability exactly on the implied price, where this arithmetic
    # yields ~3e-17 rather than 0 — a "stake" that is numerically non-zero and
    # would keep a fully-discredited lane technically bettable.
    if kelly <= 1e-12:
        return 0.0

    # Apply fraction (half Kelly is more conservative)
    return kelly * fraction


def size_bets(
    value_bets: pd.DataFrame,
    bankroll: float,
    kelly_fraction_pct: float = 0.5,
    max_bet_pct: float = 0.10,
    sport: str | None = None,
    market: str | None = None,
) -> pd.DataFrame:
    """
    Add bet sizing to value bets DataFrame.

    Args:
        value_bets: DataFrame from find_value_bets()
        bankroll: Total bankroll in dollars
        kelly_fraction_pct: Kelly fraction (0.5 = half Kelly)
        max_bet_pct: Maximum single bet as % of bankroll (safety cap)

    Returns:
        DataFrame with added columns: KellyFraction, BetSize, ExpectedProfit
    """
    if value_bets.empty or bankroll <= 0:
        return value_bets

    df = value_bets.copy()

    # Size on the SHRUNK edge. Without sport/market we cannot look up the lane's
    # measured reliability, so this degrades to the old behaviour rather than
    # guessing — callers that know their lane should pass it (predict.py does).
    df["KellyFraction"] = df.apply(
        lambda row: kelly_fraction(
            shrunk_prob(row["ModelProb"], row["BestOdds"],
                        row.get("Sport", sport), row.get("Market", market)),
            row["BestOdds"],
            fraction=kelly_fraction_pct,
        ),
        axis=1,
    )

    # Cap at max_bet_pct of bankroll
    df["KellyFraction"] = df["KellyFraction"].clip(upper=max_bet_pct)

    # Calculate dollar amounts
    df["BetSize"] = (df["KellyFraction"] * bankroll).round(2)

    # Expected profit
    df["ExpectedProfit"] = df.apply(
        lambda row: _expected_profit(
            row["BetSize"], row["ModelProb"], row["BestOdds"]
        ),
        axis=1,
    ).round(2)

    # Expected value (as percentage of bet)
    df["ExpectedValue"] = (df["ExpectedProfit"] / df["BetSize"].replace(0, np.nan)).fillna(0)

    return df


def _expected_profit(bet_size: float, model_prob: float, american_odds: float) -> float:
    """Calculate expected profit for a bet."""
    if bet_size <= 0:
        return 0.0

    # Profit if we win
    if american_odds > 0:
        win_profit = bet_size * (american_odds / 100)
    else:
        win_profit = bet_size * (100 / abs(american_odds))

    # Expected value = P(win) * profit - P(lose) * bet_size
    return model_prob * win_profit - (1 - model_prob) * bet_size


def print_kelly_bets(bets_df: pd.DataFrame, bankroll: float) -> str:
    """Pretty-print Kelly-sized bets."""
    if bets_df.empty:
        return "  No bets to size.\n"

    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  BET SIZING — Kelly Criterion (Bankroll: ${bankroll:,.0f})")
    lines.append(f"{'='*70}")

    total_wagered = 0
    total_ev = 0

    for _, bet in bets_df.iterrows():
        if bet.get("BetSize", 0) <= 0:
            continue

        lines.append(
            f"\n  {bet['Team']} vs {bet['Opponent']}"
        )
        lines.append(
            f"    Bet: ${bet['BetSize']:,.2f} at {bet['BestOdds']:+.0f} "
            f"({bet['Sportsbook']})"
        )
        lines.append(
            f"    Edge: +{bet['Edge']*100:.1f}% | "
            f"Kelly: {bet['KellyFraction']*100:.1f}% | "
            f"EV: ${bet['ExpectedProfit']:+,.2f}"
        )

        total_wagered += bet["BetSize"]
        total_ev += bet["ExpectedProfit"]

    lines.append(f"\n  {'─'*40}")
    lines.append(f"  Total wagered: ${total_wagered:,.2f} ({total_wagered/bankroll*100:.1f}% of bankroll)")
    lines.append(f"  Total expected profit: ${total_ev:+,.2f}")
    lines.append(f"  Expected ROI: {total_ev/total_wagered*100:+.1f}%" if total_wagered > 0 else "")
    lines.append(f"{'='*70}\n")

    return "\n".join(lines)

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

    # No bet if no edge
    if kelly <= 0:
        return 0.0

    # Apply fraction (half Kelly is more conservative)
    return kelly * fraction


def size_bets(
    value_bets: pd.DataFrame,
    bankroll: float,
    kelly_fraction_pct: float = 0.5,
    max_bet_pct: float = 0.10,
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

    df["KellyFraction"] = df.apply(
        lambda row: kelly_fraction(
            row["ModelProb"],
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

"""
Pool-size bracket optimizer.

The key insight: the optimal bracket depends on how many people are in
your pool. In a 10-person pool, pick chalk. In a 1000-person pool,
you NEED contrarian upsets to differentiate yourself.

This module adjusts bracket picks based on:
1. How many people are in the pool
2. How likely the public is to pick each team (popularity estimate)
3. The expected value of each pick given pool size
"""
import numpy as np
import pandas as pd


def optimize_for_pool(
    advancement_probs: pd.DataFrame,
    pool_size: int = 50,
    scoring: str = "espn",
) -> pd.DataFrame:
    """
    Adjust advancement probabilities for pool optimization.

    In larger pools, you need more differentiation (upsets).
    In smaller pools, chalk is safer.

    Args:
        advancement_probs: From Monte Carlo simulation
        pool_size: Number of people in the bracket pool
        scoring: Scoring system ("espn" = 10/20/40/80/160/320,
                 "linear" = 1/2/3/4/5/6 per round)

    Returns:
        DataFrame with adjusted "OptimalPick" probabilities
    """
    df = advancement_probs.copy()

    # Estimate public pick rates based on seed
    # Higher seeds get picked more often by casual bettors
    df["PublicPickRate"] = df["SeedNum"].apply(_estimate_public_pick_rate)

    # Contrarian factor: how much to deviate from chalk
    # Larger pools → more contrarian needed
    contrarian = _contrarian_factor(pool_size)

    # Scoring multipliers by round
    if scoring == "espn":
        round_weights = {"R64": 10, "R32": 20, "S16": 40, "E8": 80, "F4": 160, "Championship": 320}
    else:
        round_weights = {"R64": 1, "R32": 2, "S16": 3, "E8": 4, "F4": 5, "Championship": 6}

    # Calculate expected value of picking each team for each round
    # EV = P(correct) * points * differentiation_bonus
    for round_name, weight in round_weights.items():
        if round_name not in df.columns:
            continue

        base_prob = df[round_name]
        public_rate = df["PublicPickRate"]

        # Differentiation bonus: if few people pick this team and it wins,
        # you gain more ground in the pool standings
        diff_bonus = 1 + contrarian * (1 - public_rate)

        df[f"{round_name}_EV"] = base_prob * weight * diff_bonus

    # Overall pool optimization score
    ev_cols = [c for c in df.columns if c.endswith("_EV")]
    df["PoolScore"] = df[ev_cols].sum(axis=1)

    # Rank teams by pool-optimized score
    df = df.sort_values("PoolScore", ascending=False).reset_index(drop=True)
    df["PoolRank"] = range(1, len(df) + 1)

    return df


def _estimate_public_pick_rate(seed: int) -> float:
    """
    Estimate what % of public brackets pick a team based on seed.
    Based on ESPN Tournament Challenge historical data.
    """
    # Approximate public selection rates by seed
    rates = {
        1: 0.95, 2: 0.88, 3: 0.80, 4: 0.72,
        5: 0.60, 6: 0.55, 7: 0.50, 8: 0.45,
        9: 0.40, 10: 0.35, 11: 0.30, 12: 0.28,
        13: 0.12, 14: 0.08, 15: 0.04, 16: 0.02,
    }
    return rates.get(seed, 0.25)


def _contrarian_factor(pool_size: int) -> float:
    """
    Calculate how contrarian to be based on pool size.

    Pool of 5 → 0.1 (barely deviate from chalk)
    Pool of 50 → 0.3 (moderate differentiation)
    Pool of 500 → 0.5 (significant differentiation)
    Pool of 5000 → 0.7 (very contrarian)
    """
    if pool_size <= 1:
        return 0.0
    return min(0.8, 0.1 + 0.15 * np.log10(pool_size))


def print_pool_picks(
    optimized_df: pd.DataFrame,
    team_names: dict,
    pool_size: int,
    top_n: int = 20,
) -> str:
    """Pretty-print pool-optimized picks."""
    lines = []
    contrarian = _contrarian_factor(pool_size)

    lines.append(f"\n{'='*80}")
    lines.append(f"  POOL-OPTIMIZED PICKS (Pool size: {pool_size}, Contrarian: {contrarian:.2f})")
    lines.append(f"{'='*80}")
    lines.append(
        f"  {'Rank':>4} {'Team':<25} {'Seed':>4} {'Win%':>6} "
        f"{'Public':>7} {'Score':>8}"
    )
    lines.append(f"  {'-'*70}")

    for _, row in optimized_df.head(top_n).iterrows():
        name = team_names.get(row["TeamID"], str(row["TeamID"]))
        lines.append(
            f"  {row['PoolRank']:>4} {name:<25} {row['SeedNum']:>4} "
            f"{row.get('Championship', 0):>5.1%} "
            f"{row['PublicPickRate']:>6.0%} "
            f"{row['PoolScore']:>8.1f}"
        )

    lines.append(f"\n  Strategy: {'CHALK-HEAVY' if contrarian < 0.2 else 'CONTRARIAN' if contrarian > 0.4 else 'BALANCED'}")
    lines.append(f"{'='*80}\n")
    return "\n".join(lines)

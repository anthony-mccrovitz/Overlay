"""
Monte Carlo tournament simulator.

Simulates the entire tournament 10,000+ times using numpy vectorization.
Each simulation uses the model's win probabilities with random outcomes.

Output: advancement probabilities for each team to each round.
This is what makes smart bracket picking possible — you can see that
a 5-seed has a 12% chance of making the Elite Eight even though they're
"supposed" to lose in the Round of 32.
"""
import numpy as np
import pandas as pd

from src.simulation.bracket import SEED_MATCHUPS_R64


def simulate_tournament(
    win_probs: dict[tuple[int, int], float],
    seeds_df: pd.DataFrame,
    n_sims: int = 10000,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Run Monte Carlo simulation of the full tournament.

    Args:
        win_probs: Dict of (team_a_id, team_b_id) → P(A wins)
                   Must contain both orderings or will use 0.5 default
        seeds_df: DataFrame with [TeamID, SeedNum, Region]
        n_sims: Number of tournament simulations
        seed: Random seed for reproducibility

    Returns:
        DataFrame with columns:
        [TeamID, SeedNum, Region, R64, R32, S16, E8, F4, Champ, AvgRound]
        Where each round column = probability of reaching that round
    """
    rng = np.random.default_rng(seed)
    regions = sorted(seeds_df["Region"].unique())

    # Track how far each team advances in each simulation
    team_ids = seeds_df["TeamID"].values
    n_teams = len(team_ids)
    team_idx = {tid: i for i, tid in enumerate(team_ids)}

    # Results: for each sim, how far did each team go? (1-6)
    results = np.ones((n_sims, n_teams), dtype=np.int8)  # Everyone starts at round 1

    def get_prob(a: int, b: int) -> float:
        """Get win probability, checking both orderings."""
        if (a, b) in win_probs:
            return win_probs[(a, b)]
        elif (b, a) in win_probs:
            return 1 - win_probs[(b, a)]
        return 0.5  # No data → coin flip

    for sim in range(n_sims):
        region_winners = {}

        for region in regions:
            region_teams = seeds_df[seeds_df["Region"] == region].sort_values("SeedNum")
            seed_to_team = dict(zip(region_teams["SeedNum"], region_teams["TeamID"]))

            # Round of 64
            r64_winners = []
            for seed_a, seed_b in SEED_MATCHUPS_R64:
                team_a = seed_to_team.get(seed_a)
                team_b = seed_to_team.get(seed_b)
                if team_a is None or team_b is None:
                    r64_winners.append(team_a or team_b)
                    continue

                prob_a = get_prob(team_a, team_b)
                winner = team_a if rng.random() < prob_a else team_b
                r64_winners.append(winner)

                # Record advancement
                if winner in team_idx:
                    results[sim, team_idx[winner]] = 2

            # Rounds 2-4 within region
            current = r64_winners
            for round_num in range(2, 5):
                next_round = []
                for i in range(0, len(current), 2):
                    if i + 1 >= len(current):
                        next_round.append(current[i])
                        continue

                    team_a, team_b = current[i], current[i + 1]
                    prob_a = get_prob(team_a, team_b)
                    winner = team_a if rng.random() < prob_a else team_b
                    next_round.append(winner)

                    if winner in team_idx:
                        results[sim, team_idx[winner]] = round_num + 1

                current = next_round

            if current:
                region_winners[region] = current[0]

        # Final Four
        ff_teams = [region_winners.get(r) for r in regions if r in region_winners]

        ff_winners = []
        for i in range(0, len(ff_teams), 2):
            if i + 1 >= len(ff_teams) or ff_teams[i] is None:
                if ff_teams[i] is not None:
                    ff_winners.append(ff_teams[i])
                continue

            team_a, team_b = ff_teams[i], ff_teams[i + 1]
            if team_a is None or team_b is None:
                ff_winners.append(team_a or team_b)
                continue

            prob_a = get_prob(team_a, team_b)
            winner = team_a if rng.random() < prob_a else team_b
            ff_winners.append(winner)

            if winner in team_idx:
                results[sim, team_idx[winner]] = 6  # Made championship

        # Championship
        if len(ff_winners) >= 2 and ff_winners[0] is not None and ff_winners[1] is not None:
            team_a, team_b = ff_winners[0], ff_winners[1]
            prob_a = get_prob(team_a, team_b)
            winner = team_a if rng.random() < prob_a else team_b

            if winner in team_idx:
                results[sim, team_idx[winner]] = 7  # Won championship

    # Compute advancement probabilities
    advancement = []
    for i, team_id in enumerate(team_ids):
        team_results = results[:, i]
        row = {
            "TeamID": team_id,
            "SeedNum": int(seeds_df[seeds_df["TeamID"] == team_id]["SeedNum"].iloc[0]),
            "Region": seeds_df[seeds_df["TeamID"] == team_id]["Region"].iloc[0],
            "R64": (team_results >= 2).mean(),
            "R32": (team_results >= 3).mean(),
            "S16": (team_results >= 4).mean(),
            "E8": (team_results >= 5).mean(),
            "F4": (team_results >= 6).mean(),
            "Championship": (team_results >= 7).mean(),
            "AvgRound": team_results.mean(),
        }
        advancement.append(row)

    df = pd.DataFrame(advancement)
    df = df.sort_values("Championship", ascending=False).reset_index(drop=True)
    return df


def print_advancement_probs(adv_df: pd.DataFrame, team_names: dict, top_n: int = 20) -> str:
    """Pretty-print advancement probabilities."""
    lines = []
    lines.append(f"\n{'='*80}")
    lines.append("  MONTE CARLO ADVANCEMENT PROBABILITIES (10,000 simulations)")
    lines.append(f"{'='*80}")
    lines.append(
        f"  {'Team':<25} {'Seed':>4} {'R32':>6} {'S16':>6} "
        f"{'E8':>6} {'F4':>6} {'Champ':>6}"
    )
    lines.append(f"  {'-'*75}")

    for _, row in adv_df.head(top_n).iterrows():
        name = team_names.get(row["TeamID"], str(row["TeamID"]))
        lines.append(
            f"  {name:<25} {row['SeedNum']:>4} "
            f"{row['R32']:>5.1%} {row['S16']:>5.1%} "
            f"{row['E8']:>5.1%} {row['F4']:>5.1%} "
            f"{row['Championship']:>5.1%}"
        )

    lines.append(f"{'='*80}\n")
    return "\n".join(lines)

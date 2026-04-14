"""
Historical upset pattern detection.

Not all upsets are random. Structural patterns exist:
- 12-seeds beat 5-seeds ~35% of the time
- Teams with senior-heavy rosters outperform seeds in March
- Mid-majors with slow tempo and elite defense punch above weight

This module scores teams on "upset DNA" — how well they match
historically successful upset profiles.
"""
import numpy as np
import pandas as pd


# Historical upset rates by seed matchup (R64)
HISTORICAL_UPSET_RATES = {
    (1, 16): 0.01,  # Only UMBC (2018)
    (2, 15): 0.06,
    (3, 14): 0.15,
    (4, 13): 0.20,
    (5, 12): 0.35,  # The classic upset
    (6, 11): 0.37,
    (7, 10): 0.39,
    (8, 9): 0.49,   # Basically a coin flip
}


def compute_upset_score(team_stats: dict, seed: int, opponent_seed: int) -> float:
    """
    Score a team's "upset potential" based on profile matching.

    Higher score = more likely to pull off (or be victim of) an upset.

    Factors:
    1. Historical seed matchup rate
    2. Defensive efficiency (good D = tournament success)
    3. Tempo (slow teams upset fast teams)
    4. Experience (veteran teams handle pressure)
    5. 3-point shooting (variance weapon for underdogs)
    """
    score = 0.0
    is_underdog = seed > opponent_seed

    # Base: historical upset rate for this seed matchup
    matchup = (min(seed, opponent_seed), max(seed, opponent_seed))
    base_rate = HISTORICAL_UPSET_RATES.get(matchup, 0.25)

    if is_underdog:
        score += base_rate * 30  # Higher base rate = more likely upset

        # Defensive efficiency boost (top defenses upset more)
        adj_de = team_stats.get("AdjDE", team_stats.get("OppPPG", 70))
        if float(adj_de) < 65:  # Elite defense
            score += 15
        elif float(adj_de) < 70:
            score += 8

        # Slow tempo advantage (controls pace = fewer possessions = less variance for favorite)
        tempo = team_stats.get("AdjTempo", team_stats.get("Possessions", 67))
        if float(tempo) < 64:
            score += 10  # Very slow = grind game
        elif float(tempo) < 67:
            score += 5

        # 3-point volume (more 3s = more variance = upset potential)
        fg3_rate = team_stats.get("FG3Rate", team_stats.get("FG3Pct", 0.33))
        if float(fg3_rate) > 0.40:
            score += 8

        # Experience / win percentage
        win_pct = team_stats.get("WinPct", 0.5)
        if float(win_pct) > 0.75:
            score += 10

    else:
        # For favorites: vulnerability score
        score += (1 - base_rate) * 20

        # Weak defense = vulnerable
        adj_de = team_stats.get("AdjDE", team_stats.get("OppPPG", 70))
        if float(adj_de) > 75:
            score -= 10  # Bad D = more vulnerable

        # Very fast tempo = more variance = more upset risk
        tempo = team_stats.get("AdjTempo", team_stats.get("Possessions", 67))
        if float(tempo) > 72:
            score -= 5

    return max(0, min(100, score))


def find_upset_candidates(
    seeds_df: pd.DataFrame,
    team_stats: pd.DataFrame,
    team_names: dict,
) -> pd.DataFrame:
    """
    Identify the best upset candidates in the tournament.

    Returns DataFrame sorted by upset potential.
    """
    candidates = []

    for _, seed_row in seeds_df.iterrows():
        team_id = seed_row["TeamID"]
        seed = seed_row["SeedNum"]

        if seed <= 8:
            continue  # Only look at underdogs (seeds 9-16)

        stats = team_stats[team_stats["TeamID"] == team_id]
        if stats.empty:
            continue

        stats_dict = stats.iloc[0].to_dict()
        opponent_seed = 17 - seed  # R64 opponent seed

        upset_score = compute_upset_score(stats_dict, seed, opponent_seed)

        candidates.append({
            "TeamID": team_id,
            "Team": team_names.get(team_id, str(team_id)),
            "Seed": seed,
            "OpponentSeed": opponent_seed,
            "UpsetScore": upset_score,
            "WinPct": stats_dict.get("WinPct", 0),
            "Region": seed_row.get("Region", ""),
        })

    df = pd.DataFrame(candidates)
    if not df.empty:
        df = df.sort_values("UpsetScore", ascending=False).reset_index(drop=True)

    return df


def print_upset_radar(candidates_df: pd.DataFrame, top_n: int = 10) -> str:
    """Pretty-print upset radar."""
    if candidates_df.empty:
        return "  No upset candidates identified.\n"

    lines = []
    lines.append(f"\n{'='*65}")
    lines.append("  UPSET RADAR — Who's Most Likely to Bust Your Bracket")
    lines.append(f"{'='*65}")

    for i, (_, row) in enumerate(candidates_df.head(top_n).iterrows()):
        alert = ""
        if row["UpsetScore"] >= 50:
            alert = " *** HIGH ALERT ***"
        elif row["UpsetScore"] >= 35:
            alert = " ** WATCH **"

        lines.append(
            f"\n  #{i+1} ({row['Seed']}) {row['Team']} over ({row['OpponentSeed']}) seed"
            f"{alert}"
        )
        lines.append(
            f"     Upset score: {row['UpsetScore']:.0f}/100 | "
            f"Win%: {row['WinPct']:.0%} | Region: {row['Region']}"
        )

    lines.append(f"\n{'='*65}\n")
    return "\n".join(lines)

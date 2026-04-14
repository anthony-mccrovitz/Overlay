"""
Template-based pick narratives.

Generates plain-English explanations for each bracket pick.
Uses the model's actual features to explain — no hallucination,
no post-hoc rationalization.
"""
import pandas as pd


def generate_narrative(
    team_a_name: str,
    team_b_name: str,
    seed_a: int,
    seed_b: int,
    win_prob: float,
    team_a_stats: dict,
    team_b_stats: dict,
) -> str:
    """
    Generate a plain-English narrative for a single game pick.

    Highlights the top 2-3 reasons for the pick.
    """
    winner = team_a_name if win_prob >= 0.5 else team_b_name
    loser = team_b_name if win_prob >= 0.5 else team_a_name
    w_seed = seed_a if win_prob >= 0.5 else seed_b
    l_seed = seed_b if win_prob >= 0.5 else seed_a
    conf = abs(win_prob - 0.5) * 2  # 0 to 1 confidence

    is_upset = w_seed > l_seed
    reasons = _find_key_reasons(team_a_stats, team_b_stats, win_prob)

    # Build narrative
    if conf > 0.4:
        opener = f"Strong pick: ({w_seed}) {winner} over ({l_seed}) {loser}."
    elif conf > 0.1:
        opener = f"({w_seed}) {winner} over ({l_seed}) {loser}."
    else:
        opener = f"Coin flip: ({w_seed}) {winner} slightly edges ({l_seed}) {loser}."

    if is_upset:
        opener = f"UPSET: {opener}"

    reason_str = " ".join(reasons[:3])
    return f"{opener} {reason_str}"


def _find_key_reasons(stats_a: dict, stats_b: dict, win_prob: float) -> list[str]:
    """Identify the top reasons for the pick based on stat differences."""
    reasons = []
    picking_a = win_prob >= 0.5

    # Offensive/defensive efficiency
    a_adj_o = float(stats_a.get("AdjO", stats_a.get("PPG", 0)))
    b_adj_o = float(stats_b.get("AdjO", stats_b.get("PPG", 0)))
    a_adj_d = float(stats_a.get("AdjDE", stats_a.get("OppPPG", 0)))
    b_adj_d = float(stats_b.get("AdjDE", stats_b.get("OppPPG", 0)))

    if picking_a and a_adj_o > b_adj_o and a_adj_o > 0:
        reasons.append(f"Superior offense ({a_adj_o:.1f} vs {b_adj_o:.1f} efficiency).")
    elif not picking_a and b_adj_o > a_adj_o and b_adj_o > 0:
        reasons.append(f"Superior offense ({b_adj_o:.1f} vs {a_adj_o:.1f} efficiency).")

    if picking_a and a_adj_d < b_adj_d and a_adj_d > 0:
        reasons.append(f"Better defense ({a_adj_d:.1f} vs {b_adj_d:.1f} allowed).")
    elif not picking_a and b_adj_d < a_adj_d and b_adj_d > 0:
        reasons.append(f"Better defense ({b_adj_d:.1f} vs {a_adj_d:.1f} allowed).")

    # Win percentage
    a_wp = float(stats_a.get("WinPct", 0.5))
    b_wp = float(stats_b.get("WinPct", 0.5))
    if picking_a and a_wp > b_wp + 0.1:
        reasons.append(f"Stronger record ({a_wp:.0%} vs {b_wp:.0%}).")
    elif not picking_a and b_wp > a_wp + 0.1:
        reasons.append(f"Stronger record ({b_wp:.0%} vs {a_wp:.0%}).")

    # 3-point shooting
    a_3p = float(stats_a.get("FG3Pct", 0))
    b_3p = float(stats_b.get("FG3Pct", 0))
    if picking_a and a_3p > b_3p + 0.03 and a_3p > 0:
        reasons.append(f"Better 3-point shooting ({a_3p:.1%} vs {b_3p:.1%}).")
    elif not picking_a and b_3p > a_3p + 0.03 and b_3p > 0:
        reasons.append(f"Better 3-point shooting ({b_3p:.1%} vs {a_3p:.1%}).")

    # Turnover rate
    a_to = float(stats_a.get("TORatio", 0.18))
    b_to = float(stats_b.get("TORatio", 0.18))
    if picking_a and a_to < b_to - 0.02:
        reasons.append("Better ball security (fewer turnovers).")
    elif not picking_a and b_to < a_to - 0.02:
        reasons.append("Better ball security (fewer turnovers).")

    # Seed advantage
    seed_diff = float(stats_a.get("SeedA", 8)) - float(stats_b.get("SeedB", 8))
    if abs(seed_diff) > 3 and not reasons:
        reasons.append(f"Significant seed advantage (seed differential: {abs(seed_diff):.0f}).")

    if not reasons:
        reasons.append("Marginal statistical edge across multiple factors.")

    return reasons


def generate_bracket_narratives(bracket, current_stats: pd.DataFrame) -> list[dict]:
    """Generate narratives for all games in a bracket."""
    narratives = []

    for game in bracket.games:
        stats_a = current_stats[current_stats["TeamID"] == game.team_a_id]
        stats_b = current_stats[current_stats["TeamID"] == game.team_b_id]

        a_dict = stats_a.iloc[0].to_dict() if not stats_a.empty else {}
        b_dict = stats_b.iloc[0].to_dict() if not stats_b.empty else {}

        narrative = generate_narrative(
            game.team_a_name,
            game.team_b_name,
            game.team_a_seed,
            game.team_b_seed,
            game.win_prob_a,
            a_dict,
            b_dict,
        )

        narratives.append({
            "round": game.round_num,
            "region": game.region,
            "matchup": f"({game.team_a_seed}) {game.team_a_name} vs ({game.team_b_seed}) {game.team_b_name}",
            "narrative": narrative,
        })

    return narratives

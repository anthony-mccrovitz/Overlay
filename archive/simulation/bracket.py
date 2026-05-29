"""
Tournament bracket structure and generation.

Handles the NCAA tournament bracket:
- 68 teams → First Four → 64-team bracket
- 4 regions × 16 teams
- 6 rounds: R64, R32, Sweet 16, Elite 8, Final Four, Championship

The bracket is represented as a list of matchups per round.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Game:
    """A single tournament game."""
    round_num: int          # 1=R64, 2=R32, 3=S16, 4=E8, 5=F4, 6=Championship
    region: str             # W, X, Y, Z (or FF for Final Four)
    team_a_id: int
    team_b_id: int
    team_a_name: str
    team_b_name: str
    team_a_seed: int
    team_b_seed: int
    win_prob_a: float       # P(team_a wins)
    winner_id: int | None = None
    winner_name: str | None = None
    confidence: float = 0.0  # |win_prob - 0.5| — how sure we are


@dataclass
class Bracket:
    """Full tournament bracket (63 games for 64-team field)."""
    games: list[Game]
    year: int

    def get_round(self, round_num: int) -> list[Game]:
        """Get all games in a specific round."""
        return [g for g in self.games if g.round_num == round_num]

    def get_winner(self) -> Game | None:
        """Get the championship game."""
        finals = self.get_round(6)
        return finals[0] if finals else None

    @property
    def n_upsets(self) -> int:
        """Count games where the lower seed (higher number) won."""
        return sum(
            1 for g in self.games
            if g.winner_id is not None and g.winner_id == g.team_b_id
            and g.team_b_seed > g.team_a_seed
        )

    def to_dict(self) -> list[dict]:
        """Convert to list of dicts for serialization."""
        return [
            {
                "round": g.round_num,
                "region": g.region,
                "team_a": g.team_a_name,
                "team_b": g.team_b_name,
                "seed_a": g.team_a_seed,
                "seed_b": g.team_b_seed,
                "win_prob_a": round(g.win_prob_a, 3),
                "winner": g.winner_name,
                "confidence": round(g.confidence, 3),
            }
            for g in self.games
        ]


# Standard 64-team bracket matchup order (seeds)
# Region R64 matchups: 1v16, 8v9, 5v12, 4v13, 6v11, 3v14, 7v10, 2v15
SEED_MATCHUPS_R64 = [
    (1, 16), (8, 9), (5, 12), (4, 13),
    (6, 11), (3, 14), (7, 10), (2, 15),
]

ROUND_NAMES = {
    1: "Round of 64",
    2: "Round of 32",
    3: "Sweet 16",
    4: "Elite 8",
    5: "Final Four",
    6: "Championship",
}


def build_bracket(
    seeds_df: pd.DataFrame,
    team_names: dict[int, str],
    predict_fn,
    year: int = 2026,
) -> Bracket:
    """
    Build a complete bracket by predicting each game round by round.

    Args:
        seeds_df: DataFrame with [TeamID, SeedNum, Region] for tourney teams
        team_names: Dict of TeamID → canonical name
        predict_fn: Function(team_a_id, team_b_id, seed_a, seed_b) → P(A wins)
        year: Tournament year

    Returns:
        Filled Bracket with all 63 games predicted
    """
    all_games = []
    regions = sorted(seeds_df["Region"].unique())

    # Build initial R64 matchups per region
    advancing = {}  # region → list of (team_id, seed) that advance

    for region in regions:
        region_teams = seeds_df[seeds_df["Region"] == region].sort_values("SeedNum")
        seed_to_team = dict(zip(region_teams["SeedNum"], region_teams["TeamID"]))

        region_winners = []
        for seed_a, seed_b in SEED_MATCHUPS_R64:
            team_a = seed_to_team.get(seed_a)
            team_b = seed_to_team.get(seed_b)

            if team_a is None or team_b is None:
                continue

            prob_a = predict_fn(team_a, team_b, seed_a, seed_b)
            winner = team_a if prob_a >= 0.5 else team_b
            w_seed = seed_a if winner == team_a else seed_b

            game = Game(
                round_num=1,
                region=region,
                team_a_id=team_a,
                team_b_id=team_b,
                team_a_name=team_names.get(team_a, str(team_a)),
                team_b_name=team_names.get(team_b, str(team_b)),
                team_a_seed=seed_a,
                team_b_seed=seed_b,
                win_prob_a=prob_a,
                winner_id=winner,
                winner_name=team_names.get(winner, str(winner)),
                confidence=abs(prob_a - 0.5),
            )
            all_games.append(game)
            region_winners.append((winner, w_seed))

        advancing[region] = region_winners

    # Rounds 2-4 (within regions)
    for round_num in range(2, 5):
        for region in regions:
            winners = advancing[region]
            next_round = []

            for i in range(0, len(winners), 2):
                if i + 1 >= len(winners):
                    next_round.append(winners[i])
                    continue

                team_a, seed_a = winners[i]
                team_b, seed_b = winners[i + 1]

                # Higher seed (lower number) is always Team A
                if seed_a > seed_b:
                    team_a, team_b = team_b, team_a
                    seed_a, seed_b = seed_b, seed_a

                prob_a = predict_fn(team_a, team_b, seed_a, seed_b)
                winner = team_a if prob_a >= 0.5 else team_b
                w_seed = seed_a if winner == team_a else seed_b

                game = Game(
                    round_num=round_num,
                    region=region,
                    team_a_id=team_a,
                    team_b_id=team_b,
                    team_a_name=team_names.get(team_a, str(team_a)),
                    team_b_name=team_names.get(team_b, str(team_b)),
                    team_a_seed=seed_a,
                    team_b_seed=seed_b,
                    win_prob_a=prob_a,
                    winner_id=winner,
                    winner_name=team_names.get(winner, str(winner)),
                    confidence=abs(prob_a - 0.5),
                )
                all_games.append(game)
                next_round.append((winner, w_seed))

            advancing[region] = next_round

    # Final Four (round 5) — region winners face off
    # Standard: W vs X, Y vs Z (or however the regions are paired)
    ff_teams = [(r, advancing[r][0]) for r in regions if advancing[r]]

    ff_winners = []
    for i in range(0, len(ff_teams), 2):
        if i + 1 >= len(ff_teams):
            ff_winners.append(ff_teams[i][1])
            continue

        r_a, (team_a, seed_a) = ff_teams[i]
        r_b, (team_b, seed_b) = ff_teams[i + 1]

        if seed_a > seed_b:
            team_a, team_b = team_b, team_a
            seed_a, seed_b = seed_b, seed_a

        prob_a = predict_fn(team_a, team_b, seed_a, seed_b)
        winner = team_a if prob_a >= 0.5 else team_b
        w_seed = seed_a if winner == team_a else seed_b

        game = Game(
            round_num=5,
            region="FF",
            team_a_id=team_a,
            team_b_id=team_b,
            team_a_name=team_names.get(team_a, str(team_a)),
            team_b_name=team_names.get(team_b, str(team_b)),
            team_a_seed=seed_a,
            team_b_seed=seed_b,
            win_prob_a=prob_a,
            winner_id=winner,
            winner_name=team_names.get(winner, str(winner)),
            confidence=abs(prob_a - 0.5),
        )
        all_games.append(game)
        ff_winners.append((winner, w_seed))

    # Championship (round 6)
    if len(ff_winners) >= 2:
        team_a, seed_a = ff_winners[0]
        team_b, seed_b = ff_winners[1]

        if seed_a > seed_b:
            team_a, team_b = team_b, team_a
            seed_a, seed_b = seed_b, seed_a

        prob_a = predict_fn(team_a, team_b, seed_a, seed_b)
        winner = team_a if prob_a >= 0.5 else team_b

        game = Game(
            round_num=6,
            region="FF",
            team_a_id=team_a,
            team_b_id=team_b,
            team_a_name=team_names.get(team_a, str(team_a)),
            team_b_name=team_names.get(team_b, str(team_b)),
            team_a_seed=seed_a,
            team_b_seed=seed_b,
            win_prob_a=prob_a,
            winner_id=winner,
            winner_name=team_names.get(winner, str(winner)),
            confidence=abs(prob_a - 0.5),
        )
        all_games.append(game)

    return Bracket(games=all_games, year=year)


def print_bracket(bracket: Bracket) -> str:
    """Pretty-print a bracket to terminal."""
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  MARCH MADNESS {bracket.year} — PREDICTED BRACKET")
    lines.append(f"{'='*70}")

    for round_num in range(1, 7):
        games = bracket.get_round(round_num)
        if not games:
            continue

        lines.append(f"\n  {ROUND_NAMES[round_num].upper()}")
        lines.append(f"  {'-'*40}")

        for g in games:
            # Color code: green for confident, yellow for toss-up, red for upset
            conf_marker = ""
            if g.confidence > 0.2:
                conf_marker = " [LOCK]"
            elif g.confidence < 0.05:
                conf_marker = " [TOSS-UP]"

            is_upset = (
                g.winner_id == g.team_b_id
                and g.team_b_seed > g.team_a_seed
            )
            upset_marker = " ** UPSET **" if is_upset else ""

            region = f"[{g.region}] " if g.region != "FF" else ""
            lines.append(
                f"  {region}({g.team_a_seed}) {g.team_a_name} vs "
                f"({g.team_b_seed}) {g.team_b_name}"
            )
            lines.append(
                f"       → Winner: ({g.team_a_seed if g.winner_id == g.team_a_id else g.team_b_seed}) "
                f"{g.winner_name} ({g.win_prob_a:.1%} for {g.team_a_name})"
                f"{conf_marker}{upset_marker}"
            )

    champ = bracket.get_winner()
    if champ:
        lines.append(f"\n{'='*70}")
        lines.append(f"  CHAMPION: {champ.winner_name}")
        lines.append(f"  Total upsets predicted: {bracket.n_upsets}")
        lines.append(f"{'='*70}\n")

    return "\n".join(lines)

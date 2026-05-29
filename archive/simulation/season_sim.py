"""
Monte Carlo MLB season simulator for futures predictions.

Simulates the remainder of the season N times using game-level win
probabilities to generate championship and division-winner probabilities.
Compare against futures odds to find value.

Architecture:
  1. Fetch remaining schedule from MLB Stats API
  2. For each game, compute win probability using our model
  3. Simulate each game as a Bernoulli trial
  4. Determine division standings, wild card, and postseason bracket
  5. Repeat N times to get probability distributions
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from src.data.mlb_stats import _cached_get, API_BASE

CACHE_DIR = Path("data/cache/mlb_sim")

# 2025 MLB divisions
AL_EAST = {"New York Yankees", "Boston Red Sox", "Toronto Blue Jays", "Baltimore Orioles", "Tampa Bay Rays"}
AL_CENTRAL = {"Cleveland Guardians", "Minnesota Twins", "Detroit Tigers", "Chicago White Sox", "Kansas City Royals"}
AL_WEST = {"Houston Astros", "Texas Rangers", "Seattle Mariners", "Los Angeles Angels", "Oakland Athletics"}
NL_EAST = {"Atlanta Braves", "Philadelphia Phillies", "New York Mets", "Miami Marlins", "Washington Nationals"}
NL_CENTRAL = {"Milwaukee Brewers", "Chicago Cubs", "St. Louis Cardinals", "Pittsburgh Pirates", "Cincinnati Reds"}
NL_WEST = {"Los Angeles Dodgers", "San Diego Padres", "Arizona Diamondbacks", "San Francisco Giants", "Colorado Rockies"}

DIVISIONS = {
    "AL East": AL_EAST, "AL Central": AL_CENTRAL, "AL West": AL_WEST,
    "NL East": NL_EAST, "NL Central": NL_CENTRAL, "NL West": NL_WEST,
}

LEAGUE_DIVISIONS = {
    "AL": ["AL East", "AL Central", "AL West"],
    "NL": ["NL East", "NL Central", "NL West"],
}


def _team_to_division(team_name: str) -> str | None:
    for div, teams in DIVISIONS.items():
        if team_name in teams:
            return div
    return None


def _team_to_league(team_name: str) -> str | None:
    div = _team_to_division(team_name)
    if div and div.startswith("AL"):
        return "AL"
    elif div and div.startswith("NL"):
        return "NL"
    return None


@dataclass
class TeamRecord:
    name: str
    wins: int = 0
    losses: int = 0

    @property
    def games(self) -> int:
        return self.wins + self.losses

    @property
    def win_pct(self) -> float:
        return self.wins / max(self.games, 1)


@dataclass
class SimulationResult:
    """Results from one simulation run."""
    records: dict[str, TeamRecord]
    division_winners: dict[str, str]
    wild_cards: dict[str, list[str]]  # league → [team1, team2, team3]
    world_series_winner: str = ""


def fetch_current_standings(season: int | None = None) -> dict[str, TeamRecord]:
    """Fetch current W-L records for all teams."""
    season = season or date.today().year
    try:
        data = _cached_get(
            f"standings_{season}",
            f"{API_BASE}/standings",
            {"leagueId": "103,104", "season": season},
            max_age_s=7200,
        )
    except Exception:
        return {}

    records = {}
    for rec in data.get("records", []):
        for entry in rec.get("teamRecords", []):
            name = entry.get("team", {}).get("name", "")
            w = int(entry.get("wins", 0))
            l = int(entry.get("losses", 0))
            records[name] = TeamRecord(name=name, wins=w, losses=l)

    return records


def fetch_remaining_schedule(season: int | None = None) -> list[dict]:
    """
    Fetch remaining games in the season (not yet played).
    Returns list of {home_team, away_team, date, game_pk}.
    """
    season = season or date.today().year
    today = date.today().isoformat()
    end = f"{season}-10-05"

    try:
        data = _cached_get(
            f"remaining_schedule_{season}_{today}",
            f"{API_BASE}/schedule",
            {
                "sportId": 1,
                "startDate": today,
                "endDate": end,
                "gameType": "R",
            },
            max_age_s=7200,
        )
    except Exception:
        return []

    games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            state = game.get("status", {}).get("abstractGameState", "")
            if state == "Final":
                continue
            home = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
            away = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "")
            if home and away:
                games.append({
                    "home_team": home,
                    "away_team": away,
                    "date": game.get("gameDate", "")[:10],
                    "game_pk": game.get("gamePk"),
                })

    return games


def _assign_win_probs(
    games: list[dict],
    team_records: dict[str, TeamRecord],
    home_advantage: float = 0.037,
) -> list[dict]:
    """
    Assign P(home wins) using log5 method from current records.
    Falls back to home advantage if records are unavailable.
    """
    for game in games:
        home = game["home_team"]
        away = game["away_team"]

        hr = team_records.get(home)
        ar = team_records.get(away)

        if hr and ar and hr.games >= 10 and ar.games >= 10:
            hw = hr.win_pct
            aw = ar.win_pct
            # Log5 formula
            p = (hw * (1 - aw)) / (hw * (1 - aw) + (1 - hw) * aw)
            # Add home advantage
            p = np.clip(p + home_advantage, 0.25, 0.85)
        else:
            p = 0.5 + home_advantage

        game["home_win_prob"] = p

    return games


def simulate_season(
    games: list[dict],
    base_records: dict[str, TeamRecord],
    rng: np.random.Generator | None = None,
) -> SimulationResult:
    """
    Simulate remaining games and determine standings.
    """
    if rng is None:
        rng = np.random.default_rng()

    # Start with current records
    records = {}
    for name, rec in base_records.items():
        records[name] = TeamRecord(name=name, wins=rec.wins, losses=rec.losses)

    # Simulate each remaining game
    for game in games:
        home = game["home_team"]
        away = game["away_team"]
        p = game.get("home_win_prob", 0.54)

        if home not in records:
            records[home] = TeamRecord(name=home)
        if away not in records:
            records[away] = TeamRecord(name=away)

        if rng.random() < p:
            records[home].wins += 1
            records[away].losses += 1
        else:
            records[away].wins += 1
            records[home].losses += 1

    # Determine division winners
    division_winners = {}
    for div, teams in DIVISIONS.items():
        div_records = [(records.get(t, TeamRecord(name=t)), t) for t in teams]
        div_records.sort(key=lambda x: x[0].win_pct, reverse=True)
        division_winners[div] = div_records[0][1]

    # Determine wild cards (top 3 non-division-winners per league)
    wild_cards = {"AL": [], "NL": []}
    for league, divs in LEAGUE_DIVISIONS.items():
        div_winners = {division_winners[d] for d in divs}
        non_winners = []
        for d in divs:
            for t in DIVISIONS[d]:
                if t not in div_winners:
                    non_winners.append((records.get(t, TeamRecord(name=t)), t))
        non_winners.sort(key=lambda x: x[0].win_pct, reverse=True)
        wild_cards[league] = [nw[1] for nw in non_winners[:3]]

    # Simple postseason simulation (bracket)
    al_teams = [division_winners[d] for d in LEAGUE_DIVISIONS["AL"]] + wild_cards["AL"][:3]
    nl_teams = [division_winners[d] for d in LEAGUE_DIVISIONS["NL"]] + wild_cards["NL"][:3]

    def _series_winner(team_a: str, team_b: str, games_needed: int = 4) -> str:
        a_wins, b_wins = 0, 0
        a_rec = records.get(team_a, TeamRecord(name=team_a))
        b_rec = records.get(team_b, TeamRecord(name=team_b))
        p_a = a_rec.win_pct / max(a_rec.win_pct + b_rec.win_pct, 0.01)
        while a_wins < games_needed and b_wins < games_needed:
            if rng.random() < p_a:
                a_wins += 1
            else:
                b_wins += 1
        return team_a if a_wins >= games_needed else team_b

    def _simulate_bracket(teams: list[str]) -> str:
        if len(teams) < 2:
            return teams[0] if teams else ""
        # Sort by record
        teams.sort(key=lambda t: records.get(t, TeamRecord(name=t)).win_pct, reverse=True)

        # Wild Card round: #4 vs #5, #3 vs #6 (best of 3)
        if len(teams) >= 6:
            wc1_winner = _series_winner(teams[3], teams[4], games_needed=2)
            wc2_winner = _series_winner(teams[2], teams[5], games_needed=2)
            # Division Series
            ds1_winner = _series_winner(teams[0], wc2_winner, games_needed=3)
            ds2_winner = _series_winner(teams[1], wc1_winner, games_needed=3)
        elif len(teams) >= 4:
            ds1_winner = _series_winner(teams[0], teams[3], games_needed=3)
            ds2_winner = _series_winner(teams[1], teams[2], games_needed=3)
        else:
            return _series_winner(teams[0], teams[1], games_needed=4)

        # Championship Series
        return _series_winner(ds1_winner, ds2_winner, games_needed=4)

    al_champ = _simulate_bracket(al_teams)
    nl_champ = _simulate_bracket(nl_teams)
    ws_winner = _series_winner(al_champ, nl_champ, games_needed=4)

    return SimulationResult(
        records=records,
        division_winners=division_winners,
        wild_cards=wild_cards,
        world_series_winner=ws_winner,
    )


def run_simulation(
    n_sims: int = 10000,
    season: int | None = None,
    verbose: bool = True,
) -> dict:
    """
    Run full Monte Carlo simulation.

    Returns:
        dict with:
            ws_probs: {team: probability}
            division_probs: {division: {team: probability}}
            playoff_probs: {team: probability}
            pennant_probs: {team: probability}
    """
    season = season or date.today().year

    if verbose:
        print(f"\n  Fetching current standings and remaining schedule...")

    standings = fetch_current_standings(season)
    remaining = fetch_remaining_schedule(season)

    if not remaining:
        if verbose:
            print("  No remaining games found. Season may be over.")
        return {}

    remaining = _assign_win_probs(remaining, standings)

    if verbose:
        print(f"  {len(standings)} teams, {len(remaining)} remaining games")
        print(f"  Running {n_sims:,} simulations...")

    ws_counts: dict[str, int] = defaultdict(int)
    div_counts: dict[str, dict[str, int]] = {d: defaultdict(int) for d in DIVISIONS}
    playoff_counts: dict[str, int] = defaultdict(int)
    pennant_counts: dict[str, int] = defaultdict(int)

    rng = np.random.default_rng(42)

    for i in range(n_sims):
        result = simulate_season(remaining, standings, rng)

        ws_counts[result.world_series_winner] += 1

        for div, winner in result.division_winners.items():
            div_counts[div][winner] += 1

        # Track playoff appearances
        for div, winner in result.division_winners.items():
            playoff_counts[winner] += 1
        for league, wc_teams in result.wild_cards.items():
            for t in wc_teams:
                playoff_counts[t] += 1

        if verbose and (i + 1) % 2500 == 0:
            print(f"    {i+1:,}/{n_sims:,} simulations complete...")

    # Convert counts to probabilities
    ws_probs = {t: c / n_sims for t, c in sorted(ws_counts.items(), key=lambda x: x[1], reverse=True)}
    div_probs = {}
    for div, counts in div_counts.items():
        div_probs[div] = {t: c / n_sims for t, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)}
    playoff_probs = {t: c / n_sims for t, c in sorted(playoff_counts.items(), key=lambda x: x[1], reverse=True)}
    pennant_probs = {t: c / n_sims for t, c in sorted(pennant_counts.items(), key=lambda x: x[1], reverse=True)}

    output = {
        "n_sims": n_sims,
        "remaining_games": len(remaining),
        "ws_probs": ws_probs,
        "division_probs": div_probs,
        "playoff_probs": playoff_probs,
    }

    if verbose:
        print(f"\n  {'='*60}")
        print(f"  WORLD SERIES PROBABILITIES ({n_sims:,} sims)")
        print(f"  {'='*60}")
        for team, prob in list(ws_probs.items())[:10]:
            bar = "█" * int(prob * 100)
            print(f"  {team:28s} {prob:6.1%}  {bar}")

        print(f"\n  DIVISION WINNERS")
        for div in sorted(div_probs):
            print(f"\n  {div}:")
            for team, prob in list(div_probs[div].items())[:3]:
                print(f"    {team:28s} {prob:6.1%}")

        print(f"  {'='*60}\n")

    return output


def find_futures_edges(
    sim_results: dict,
    odds_df=None,
    min_edge: float = 0.03,
) -> list[dict]:
    """
    Compare simulation probabilities against futures odds.

    odds_df should have columns: Team, Odds (American) from the outrights market.
    """
    if not sim_results or not sim_results.get("ws_probs"):
        return []

    from src.data.odds_api import _american_to_prob

    edges = []
    ws_probs = sim_results["ws_probs"]

    if odds_df is not None and not odds_df.empty:
        for _, row in odds_df.iterrows():
            team = row.get("Name", row.get("Team", ""))
            odds = row.get("Odds", 0)
            if not team or not odds:
                continue

            implied = _american_to_prob(odds)
            model_prob = ws_probs.get(team, 0)

            edge = model_prob - implied
            if edge >= min_edge:
                edges.append({
                    "team": team,
                    "model_prob": round(model_prob, 4),
                    "implied_prob": round(implied, 4),
                    "edge": round(edge, 4),
                    "odds": int(odds),
                    "market": "World Series",
                })

    edges.sort(key=lambda e: e["edge"], reverse=True)
    return edges

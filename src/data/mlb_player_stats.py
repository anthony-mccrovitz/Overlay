"""
MLB player-level batting stats from statsapi.mlb.com.

Fetches per-player season stats, game logs, and confirmed lineups
for batter prop predictions.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from src.data.mlb_stats import _cached_get, API_BASE, _safe_float

CACHE_DIR = Path("data/cache/mlb_players")


@dataclass
class BatterStats:
    player_id: int
    name: str
    team_id: int = 0
    team_name: str = ""
    games: int = 0
    at_bats: int = 0
    hits: int = 0
    doubles: int = 0
    triples: int = 0
    home_runs: int = 0
    rbis: int = 0
    runs: int = 0
    strikeouts: int = 0
    walks: int = 0
    avg: float = 0.0
    obp: float = 0.0
    slg: float = 0.0
    ops: float = 0.0

    @property
    def hits_per_game(self) -> float:
        return self.hits / max(self.games, 1)

    @property
    def total_bases(self) -> int:
        return self.hits + self.doubles + 2 * self.triples + 3 * self.home_runs

    @property
    def total_bases_per_game(self) -> float:
        return self.total_bases / max(self.games, 1)

    @property
    def hr_per_game(self) -> float:
        return self.home_runs / max(self.games, 1)

    @property
    def k_rate(self) -> float:
        return self.strikeouts / max(self.at_bats, 1)

    @property
    def rbi_per_game(self) -> float:
        return self.rbis / max(self.games, 1)

    @property
    def runs_per_game(self) -> float:
        return self.runs / max(self.games, 1)


def fetch_player_season_stats(player_id: int, season: int | None = None) -> BatterStats:
    """Fetch a single player's season batting stats."""
    season = season or date.today().year
    data = _cached_get(
        f"batter_{player_id}_{season}",
        f"{API_BASE}/people/{player_id}/stats",
        {"stats": "season", "group": "hitting", "season": season},
        max_age_s=21600,
    )

    bs = BatterStats(player_id=player_id, name="")
    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            s = split.get("stat", {})
            bs.games = int(_safe_float(s.get("gamesPlayed"), 0))
            bs.at_bats = int(_safe_float(s.get("atBats"), 0))
            bs.hits = int(_safe_float(s.get("hits"), 0))
            bs.doubles = int(_safe_float(s.get("doubles"), 0))
            bs.triples = int(_safe_float(s.get("triples"), 0))
            bs.home_runs = int(_safe_float(s.get("homeRuns"), 0))
            bs.rbis = int(_safe_float(s.get("rbi"), 0))
            bs.runs = int(_safe_float(s.get("runs"), 0))
            bs.strikeouts = int(_safe_float(s.get("strikeOuts"), 0))
            bs.walks = int(_safe_float(s.get("baseOnBalls"), 0))
            bs.avg = _safe_float(s.get("avg"), 0.250)
            bs.obp = _safe_float(s.get("obp"), 0.320)
            bs.slg = _safe_float(s.get("slg"), 0.400)
            bs.ops = _safe_float(s.get("ops"), 0.720)
            break

    return bs


def fetch_player_game_logs(player_id: int, season: int | None = None) -> list[dict]:
    """Fetch a batter's game-by-game hitting stats."""
    season = season or date.today().year
    try:
        data = _cached_get(
            f"batter_gamelog_{player_id}_{season}",
            f"{API_BASE}/people/{player_id}/stats",
            {"stats": "gameLog", "group": "hitting", "season": season},
            max_age_s=86400,
        )
    except Exception:
        return []

    logs = []
    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            s = split.get("stat", {})
            ab = int(_safe_float(s.get("atBats"), 0))
            if ab == 0:
                continue

            hits = int(_safe_float(s.get("hits"), 0))
            doubles = int(_safe_float(s.get("doubles"), 0))
            triples = int(_safe_float(s.get("triples"), 0))
            hrs = int(_safe_float(s.get("homeRuns"), 0))

            logs.append({
                "date": split.get("date", ""),
                "at_bats": ab,
                "hits": hits,
                "doubles": doubles,
                "triples": triples,
                "home_runs": hrs,
                "total_bases": hits + doubles + 2 * triples + 3 * hrs,
                "rbis": int(_safe_float(s.get("rbi"), 0)),
                "runs": int(_safe_float(s.get("runs"), 0)),
                "strikeouts": int(_safe_float(s.get("strikeOuts"), 0)),
                "walks": int(_safe_float(s.get("baseOnBalls"), 0)),
                "game_pk": split.get("game", {}).get("gamePk"),
            })

    return logs


def fetch_lineup(game_pk: int) -> dict[str, list[dict]] | None:
    """
    Fetch confirmed lineup for a game.

    Returns dict with "home" and "away" keys, each a list of
    {player_id, name, batting_order, position}.
    Returns None if lineups aren't posted yet.
    """
    try:
        data = _cached_get(
            f"lineup_{game_pk}",
            f"{API_BASE}/game/{game_pk}/boxscore",
            max_age_s=3600,
        )
    except Exception:
        return None

    result = {}
    for side in ["home", "away"]:
        team_data = data.get("teams", {}).get(side, {})
        batting_order = team_data.get("battingOrder", [])

        players = []
        for pid in batting_order:
            player_data = team_data.get("players", {}).get(f"ID{pid}", {})
            person = player_data.get("person", {})
            position = player_data.get("position", {})
            bo = player_data.get("battingOrder")
            players.append({
                "player_id": pid,
                "name": person.get("fullName", ""),
                "batting_order": int(str(bo)[:1]) if bo else 0,
                "position": position.get("abbreviation", ""),
            })

        result[side] = players

    return result if any(result.values()) else None


def fetch_batter_vs_pitcher(
    batter_id: int,
    pitcher_id: int,
    season: int | None = None,
) -> dict:
    """
    Historical batter vs pitcher matchup stats.

    Uses MLB Stats API vsPlayer split. Cached 12 hours.
    Returns dict with: avg, ops, hr, hits, ab, k_rate, bb_rate
    Falls back to neutral defaults when < 5 AB (too small to trust).
    """
    season = season or date.today().year
    _DEFAULTS = {
        "avg": 0.250, "ops": 0.720, "hr": 0, "hits": 0,
        "ab": 0, "k_rate": 0.22, "bb_rate": 0.08, "sample": False,
    }

    try:
        data = _cached_get(
            f"bvp_{batter_id}_{pitcher_id}_{season}",
            f"{API_BASE}/people/{batter_id}/stats",
            {
                "stats": "vsPlayer",
                "group": "hitting",
                "season": season,
                "opposingPlayerId": pitcher_id,
            },
            max_age_s=43200,
        )
    except Exception:
        return _DEFAULTS

    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            s = split.get("stat", {})
            ab = int(_safe_float(s.get("atBats", 0)))
            if ab < 5:
                continue
            hits = int(_safe_float(s.get("hits", 0)))
            hr = int(_safe_float(s.get("homeRuns", 0)))
            bb = int(_safe_float(s.get("baseOnBalls", 0)))
            k = int(_safe_float(s.get("strikeOuts", 0)))
            obp = _safe_float(s.get("obp", 0))
            slg = _safe_float(s.get("slg", 0))
            return {
                "avg": round(hits / ab, 3),
                "ops": round(obp + slg, 3),
                "hr": hr,
                "hits": hits,
                "ab": ab,
                "k_rate": round(k / ab, 3) if ab > 0 else 0.22,
                "bb_rate": round(bb / ab, 3) if ab > 0 else 0.08,
                "sample": True,
            }

    return _DEFAULTS


def fetch_team_bvp_summary(
    batting_team_id: int,
    pitcher_id: int,
    season: int | None = None,
    min_ab: int = 5,
) -> dict:
    """
    Aggregate batter-vs-pitcher stats for an entire batting lineup vs one pitcher.

    Fetches the active roster, pulls BvP for each batter, filters to those
    with enough sample, and returns team-level summary stats.

    Returns:
        {
          'lineup_ops_vs_sp': float,   avg OPS of batters who have faced this SP
          'lineup_avg_vs_sp': float,
          'hr_threat': float,          HR/AB rate vs this SP
          'k_rate_vs_sp': float,
          'sample_batters': int,        how many batters had enough data
          'notable': list[str],         top matchup notes e.g. "Freeman .385 vs Webb"
        }
    """
    season = season or date.today().year
    _FALLBACK = {
        "lineup_ops_vs_sp": 0.720, "lineup_avg_vs_sp": 0.250,
        "hr_threat": 0.033, "k_rate_vs_sp": 0.22,
        "sample_batters": 0, "notable": [],
    }

    roster = fetch_roster(batting_team_id, season)
    if not roster:
        return _FALLBACK

    # Only batters (non-pitchers)
    batters = [p for p in roster if p.get("position_type") not in ("Pitcher",)]

    ops_vals, avg_vals, hr_ab, k_ab = [], [], [], []
    notable = []

    for batter in batters[:15]:
        bid = batter.get("player_id")
        if not bid:
            continue
        bvp = fetch_batter_vs_pitcher(bid, pitcher_id, season)
        if not bvp["sample"] or bvp["ab"] < min_ab:
            continue

        ops_vals.append(bvp["ops"])
        avg_vals.append(bvp["avg"])
        hr_ab.append(bvp["hr"] / bvp["ab"])
        k_ab.append(bvp["k_rate"])

        # Flag notable: .350+ avg or 2+ HR vs this pitcher
        if bvp["avg"] >= 0.350 or bvp["hr"] >= 2:
            name = batter.get("name", "").split()[-1]  # last name only
            note = f"{name} {bvp['avg']:.3f} avg"
            if bvp["hr"] >= 2:
                note += f" {bvp['hr']} HR"
            note += f" vs SP ({bvp['ab']} AB)"
            notable.append(note)

    if not ops_vals:
        return _FALLBACK

    return {
        "lineup_ops_vs_sp": round(sum(ops_vals) / len(ops_vals), 3),
        "lineup_avg_vs_sp": round(sum(avg_vals) / len(avg_vals), 3),
        "hr_threat": round(sum(hr_ab) / len(hr_ab), 3),
        "k_rate_vs_sp": round(sum(k_ab) / len(k_ab), 3),
        "sample_batters": len(ops_vals),
        "notable": notable[:3],  # top 3 matchup notes
    }


def fetch_roster(team_id: int, season: int | None = None) -> list[dict]:
    """Fetch active roster for a team."""
    season = season or date.today().year
    try:
        data = _cached_get(
            f"roster_{team_id}_{season}",
            f"{API_BASE}/teams/{team_id}/roster",
            {"rosterType": "active", "season": season},
            max_age_s=86400,
        )
    except Exception:
        return []

    players = []
    for entry in data.get("roster", []):
        person = entry.get("person", {})
        position = entry.get("position", {})
        players.append({
            "player_id": person.get("id"),
            "name": person.get("fullName", ""),
            "position": position.get("abbreviation", ""),
            "position_type": position.get("type", ""),
        })

    return players

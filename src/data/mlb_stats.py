"""
MLB data from the MLB Stats API (statsapi.mlb.com).

No API key required. Public endpoints used by MLB.com itself.
We cache aggressively to be a good citizen.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import requests

CACHE_DIR = Path("data/cache/mlb")
API_BASE = "https://statsapi.mlb.com/api/v1"


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _cached_get(key: str, url: str, params: dict | None = None, max_age_s: int = 7200) -> dict:
    cache = _cache_path(key)
    if cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < max_age_s:
            with open(cache) as f:
                return json.load(f)

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params or {}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    else:
        raise last_exc  # type: ignore[misc]

    with open(cache, "w") as f:
        json.dump(data, f)
    return data


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TeamStats:
    team_id: int
    name: str
    games: int = 0
    runs_scored: float = 0.0
    runs_allowed: float = 0.0
    rs_per_game: float = 0.0
    ra_per_game: float = 0.0
    ops: float = 0.0
    era: float = 0.0
    whip: float = 0.0
    wins: int = 0
    losses: int = 0


@dataclass
class PitcherStats:
    player_id: int
    name: str
    era: float = 0.0
    whip: float = 0.0
    innings_pitched: float = 0.0
    k_per_9: float = 0.0
    bb_per_9: float = 0.0
    games_started: int = 0


@dataclass
class Matchup:
    game_id: int
    game_time: str
    home_team: TeamStats
    away_team: TeamStats
    home_pitcher: PitcherStats | None = None
    away_pitcher: PitcherStats | None = None


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

def fetch_schedule(game_date: date | None = None) -> list[dict]:
    """
    Fetch today's MLB games with probable pitchers.
    Returns raw game dicts from the API.
    """
    d = game_date or date.today()
    date_str = d.isoformat()
    data = _cached_get(
        f"schedule_{date_str}",
        f"{API_BASE}/schedule",
        {
            "date": date_str,
            "sportId": 1,
            "hydrate": "probablePitcher,team",
        },
        max_age_s=7200,
    )
    games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            state = game.get("status", {}).get("abstractGameState", "")
            coded = game.get("status", {}).get("codedGameState", "")
            game_type = game.get("gameType", "R")
            # Skip finished games and games already in progress (no pre-game markets)
            if state in ("Final", "Live") or coded == "I" or game_type not in ("R", "P", "F", "D", "L", "W"):
                continue
            games.append(game)
    return games


# ---------------------------------------------------------------------------
# Team stats
# ---------------------------------------------------------------------------

def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def fetch_team_stats(season: int | None = None) -> dict[int, TeamStats]:
    """
    Fetch season-level batting + pitching stats for every team.
    Returns dict keyed by team_id.
    """
    season = season or date.today().year
    batting = _cached_get(
        f"team_batting_{season}",
        f"{API_BASE}/teams/stats",
        {"stats": "season", "group": "hitting", "season": season, "sportIds": 1},
        max_age_s=21600,
    )
    pitching = _cached_get(
        f"team_pitching_{season}",
        f"{API_BASE}/teams/stats",
        {"stats": "season", "group": "pitching", "season": season, "sportIds": 1},
        max_age_s=21600,
    )

    teams: dict[int, TeamStats] = {}

    for stat_group in batting.get("stats", []):
        for split in stat_group.get("splits", []):
            tid = split.get("team", {}).get("id")
            if not tid:
                continue
            s = split.get("stat", {})
            gp = _safe_float(s.get("gamesPlayed"), 1)
            rs = _safe_float(s.get("runs"))
            teams[tid] = TeamStats(
                team_id=tid,
                name=split["team"].get("name", ""),
                games=int(gp),
                runs_scored=rs,
                rs_per_game=rs / max(gp, 1),
                ops=_safe_float(s.get("ops")),
            )

    for stat_group in pitching.get("stats", []):
        for split in stat_group.get("splits", []):
            tid = split.get("team", {}).get("id")
            if not tid or tid not in teams:
                continue
            s = split.get("stat", {})
            gp = max(teams[tid].games, 1)
            ra = _safe_float(s.get("runs"))
            teams[tid].runs_allowed = ra
            teams[tid].ra_per_game = ra / gp
            teams[tid].era = _safe_float(s.get("era"))
            teams[tid].whip = _safe_float(s.get("whip"))

    # Standings for W/L records
    try:
        standings = _cached_get(
            f"standings_{season}",
            f"{API_BASE}/standings",
            {"leagueId": "103,104", "season": season},
            max_age_s=21600,
        )
        for rec in standings.get("records", []):
            for entry in rec.get("teamRecords", []):
                tid = entry.get("team", {}).get("id")
                if tid and tid in teams:
                    teams[tid].wins = int(entry.get("wins", 0))
                    teams[tid].losses = int(entry.get("losses", 0))
    except Exception:
        pass

    return teams


# ---------------------------------------------------------------------------
# Pitcher stats
# ---------------------------------------------------------------------------

def fetch_pitcher_stats(player_id: int, season: int | None = None) -> PitcherStats:
    season = season or date.today().year
    data = _cached_get(
        f"pitcher_{player_id}_{season}",
        f"{API_BASE}/people/{player_id}/stats",
        {"stats": "season", "group": "pitching", "season": season},
        max_age_s=21600,
    )
    ps = PitcherStats(player_id=player_id, name="")
    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            s = split.get("stat", {})
            ip = _safe_float(s.get("inningsPitched"))
            k = _safe_float(s.get("strikeOuts"))
            bb = _safe_float(s.get("baseOnBalls"))
            ip_adj = max(ip, 1)
            ps.era = _safe_float(s.get("era"))
            ps.whip = _safe_float(s.get("whip"))
            ps.innings_pitched = ip
            ps.k_per_9 = k / ip_adj * 9 if ip_adj > 0 else 0
            ps.bb_per_9 = bb / ip_adj * 9 if ip_adj > 0 else 0
            ps.games_started = int(_safe_float(s.get("gamesStarted")))
            break
    return ps


def fetch_pitcher_game_logs(
    player_id: int,
    season: int | None = None,
    n: int = 10,
) -> dict:
    """
    Return rolling stats from a pitcher's last N starts.

    Cached for 6 hours (pitchers start every ~5 days).
    Falls back to season-average values when the pitcher has < 5 starts.

    Returns dict with keys:
        era_l10, k9_l10, era_trend (season_era - l10_era, positive = improving)
    """
    season = season or date.today().year
    data = _cached_get(
        f"pitcher_log_{player_id}_{season}",
        f"{API_BASE}/people/{player_id}/stats",
        {"stats": "gameLog", "group": "pitching", "season": season},
        max_age_s=21600,
    )

    starts: list[dict] = []
    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            s = split.get("stat", {})
            # Only count games where pitcher actually started
            if int(_safe_float(s.get("gamesStarted", 0))) < 1:
                continue
            ip = _safe_float(s.get("inningsPitched"))
            er = _safe_float(s.get("earnedRuns"))
            k = _safe_float(s.get("strikeOuts"))
            if ip >= 0.1:
                starts.append({"ip": ip, "er": er, "k": k})

    _DEFAULTS = {"era_l10": 4.50, "k9_l10": 7.5, "era_trend": 0.0}

    if len(starts) < 5:
        # Not enough data — fall back to season average
        season_stats = fetch_pitcher_stats(player_id, season)
        return {
            "era_l10": season_stats.era if season_stats.era > 0 else 4.50,
            "k9_l10": season_stats.k_per_9 if season_stats.k_per_9 > 0 else 7.5,
            "era_trend": 0.0,
        }

    recent = starts[-n:]
    total_ip = sum(s["ip"] for s in recent)
    total_er = sum(s["er"] for s in recent)
    total_k = sum(s["k"] for s in recent)
    ip_adj = max(total_ip, 1.0)
    era_l10 = (total_er * 9) / ip_adj
    k9_l10 = (total_k * 9) / ip_adj

    # Trend: positive = recent form is BETTER than season average (lower ERA)
    season_stats = fetch_pitcher_stats(player_id, season)
    era_season = season_stats.era if season_stats.era > 0 else era_l10
    era_trend = era_season - era_l10  # positive when last-10 ERA < season ERA (improving)

    return {
        "era_l10": round(era_l10, 2),
        "k9_l10": round(k9_l10, 2),
        "era_trend": round(era_trend, 2),
    }


# ---------------------------------------------------------------------------
# Pitcher vs opponent team (historical splits)
# ---------------------------------------------------------------------------

def fetch_pitcher_vs_team(
    pitcher_id: int,
    opponent_team_id: int,
    season: int | None = None,
) -> dict:
    """
    Return pitcher's historical ERA and K/9 specifically against this opponent team.

    Uses MLB Stats API vsTeam split. Cached 12 hours.
    Falls back to {'era_vs_opp': 4.50, 'k9_vs_opp': 7.5, 'pa_vs_opp': 0}
    when no data (pitcher never faced this team or fewer than 10 PA).
    """
    season = season or date.today().year
    _DEFAULTS = {"era_vs_opp": 4.50, "k9_vs_opp": 7.5, "pa_vs_opp": 0}

    data = _cached_get(
        f"pitcher_vs_team_{pitcher_id}_{opponent_team_id}_{season}",
        f"{API_BASE}/people/{pitcher_id}/stats",
        {
            "stats": "vsTeam",
            "group": "pitching",
            "season": season,
            "opposingTeamId": opponent_team_id,
        },
        max_age_s=43200,  # 12 hours
    )

    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            s = split.get("stat", {})
            ip = _safe_float(s.get("inningsPitched"))
            er = _safe_float(s.get("earnedRuns"))
            k = _safe_float(s.get("strikeOuts"))
            pa = int(_safe_float(s.get("plateAppearances", 0) or s.get("battersFaced", 0)))
            if ip < 1.0 or pa < 10:
                continue
            ip_adj = max(ip, 1.0)
            return {
                "era_vs_opp": round((er * 9) / ip_adj, 2),
                "k9_vs_opp": round((k * 9) / ip_adj, 2),
                "pa_vs_opp": pa,
            }

    return _DEFAULTS


# ---------------------------------------------------------------------------
# Lineup quality (day-of batting lineup OPS vs pitcher handedness)
# ---------------------------------------------------------------------------

def fetch_lineup_quality(
    team_id: int,
    game_id: int,
    pitcher_throws: str = "R",  # "R" or "L"
) -> dict:
    """
    Fetch today's confirmed batting lineup and compute average OPS for this season.

    MLB lineup is posted ~2-3 hours before first pitch. Falls back to team-level
    OPS when lineup isn't confirmed yet or individual stats are missing.

    Returns {'lineup_ops': float, 'lineup_confirmed': bool}
    """
    _DEFAULTS = {"lineup_ops": 0.720, "lineup_confirmed": False}

    # Try to get the boxscore / linescore for lineup data
    data = _cached_get(
        f"game_lineup_{game_id}",
        f"{API_BASE}/game/{game_id}/boxscore",
        {},
        max_age_s=1800,  # 30 minutes — lineup can change up to first pitch
    )

    try:
        teams = data.get("teams", {})
        # Find home/away based on team_id
        side = None
        for s in ("home", "away"):
            t = teams.get(s, {})
            if t.get("team", {}).get("id") == team_id:
                side = s
                break
        if not side:
            return _DEFAULTS

        players = teams[side].get("players", {})
        batting_order = teams[side].get("battingOrder", [])
        if not batting_order:
            return _DEFAULTS

        ops_vals = []
        for pid in batting_order[:9]:
            player = players.get(f"ID{pid}", {})
            season_stats = player.get("seasonStats", {}).get("batting", {})
            ops = _safe_float(season_stats.get("ops"))
            if ops > 0:
                ops_vals.append(ops)

        if len(ops_vals) >= 5:
            return {
                "lineup_ops": round(sum(ops_vals) / len(ops_vals), 3),
                "lineup_confirmed": True,
            }
    except Exception:
        pass

    return _DEFAULTS


# ---------------------------------------------------------------------------
# High-level: today's matchups with full context
# ---------------------------------------------------------------------------

def get_todays_matchups(
    game_date: date | None = None,
    season: int | None = None,
) -> list[Matchup]:
    """
    Build fully-hydrated Matchup objects for today's games.
    """
    season = season or (game_date.year if game_date else date.today().year)
    schedule = fetch_schedule(game_date)
    if not schedule:
        return []

    teams = fetch_team_stats(season)
    matchups: list[Matchup] = []

    for game in schedule:
        home_info = game.get("teams", {}).get("home", {})
        away_info = game.get("teams", {}).get("away", {})
        home_id = home_info.get("team", {}).get("id")
        away_id = away_info.get("team", {}).get("id")

        if not home_id or not away_id:
            continue

        home_team = teams.get(home_id)
        away_team = teams.get(away_id)
        if not home_team or not away_team:
            home_name = home_info.get("team", {}).get("name", f"Team {home_id}")
            away_name = away_info.get("team", {}).get("name", f"Team {away_id}")
            home_team = home_team or TeamStats(team_id=home_id, name=home_name)
            away_team = away_team or TeamStats(team_id=away_id, name=away_name)

        home_pitcher = None
        away_pitcher = None

        hp = home_info.get("probablePitcher")
        if hp and hp.get("id"):
            home_pitcher = fetch_pitcher_stats(hp["id"], season)
            home_pitcher.name = hp.get("fullName", "")
            home_pitcher.player_id = hp["id"]
            # Recency weighting: last-5 starts × 60% + season × 40%
            try:
                log5 = fetch_pitcher_game_logs(hp["id"], season, n=5)
                if log5.get("era_l10", 4.5) > 0:  # era_l10 key = last-N ERA
                    home_pitcher.era = round(log5["era_l10"] * 0.6 + home_pitcher.era * 0.4, 2)
                    home_pitcher.k_per_9 = round(log5["k9_l10"] * 0.6 + home_pitcher.k_per_9 * 0.4, 2)
            except Exception:
                pass

        ap = away_info.get("probablePitcher")
        if ap and ap.get("id"):
            away_pitcher = fetch_pitcher_stats(ap["id"], season)
            away_pitcher.name = ap.get("fullName", "")
            away_pitcher.player_id = ap["id"]
            # Recency weighting: last-5 starts × 60% + season × 40%
            try:
                log5 = fetch_pitcher_game_logs(ap["id"], season, n=5)
                if log5.get("era_l10", 4.5) > 0:
                    away_pitcher.era = round(log5["era_l10"] * 0.6 + away_pitcher.era * 0.4, 2)
                    away_pitcher.k_per_9 = round(log5["k9_l10"] * 0.6 + away_pitcher.k_per_9 * 0.4, 2)
            except Exception:
                pass

        matchups.append(Matchup(
            game_id=game.get("gamePk", 0),
            game_time=game.get("gameDate", ""),
            home_team=home_team,
            away_team=away_team,
            home_pitcher=home_pitcher,
            away_pitcher=away_pitcher,
        ))

    return matchups

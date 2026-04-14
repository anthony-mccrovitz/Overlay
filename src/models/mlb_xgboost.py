"""
v3 MLB prediction model — multi-model stacking ensemble.

Improvements over v2:
  1. LightGBM + CatBoost alongside XGBoost (3 gradient boosting variants)
  2. MLB Elo ratings tracked game-by-game (complementary signal)
  3. Stacking meta-learner (logistic regression on out-of-fold predictions)
  4. Rest days, bullpen strength, travel distance features
  5. All v2 features preserved (pitcher-level, momentum, etc.)
"""
from __future__ import annotations

import json
import math
import pickle
from collections import defaultdict, deque
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

try:
    from lightgbm import LGBMClassifier
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False

try:
    from catboost import CatBoostClassifier
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

from src.data.mlb_stats import API_BASE, _cached_get
from src.data.park_factors import get_park_factor, OUTDOOR_PARKS

MODEL_DIR = Path("models")

# --- MLB team coordinates for travel distance ---
TEAM_COORDS: dict[int, tuple[float, float]] = {
    108: (33.445, -112.067),  # ARI - Phoenix
    144: (33.735, -84.390),   # ATL - Atlanta
    110: (39.284, -76.622),   # BAL - Baltimore
    111: (42.346, -71.098),   # BOS - Boston
    112: (41.948, -87.656),   # CHC - Chicago
    145: (41.830, -87.634),   # CWS - Chicago
    113: (39.097, -84.508),   # CIN - Cincinnati
    114: (41.496, -81.685),   # CLE - Cleveland
    115: (39.756, -104.994),  # COL - Denver
    116: (42.339, -83.049),   # DET - Detroit
    117: (29.757, -95.355),   # HOU - Houston
    118: (39.052, -94.480),   # KC  - Kansas City
    108: (33.445, -112.067),  # ARI
    119: (33.800, -117.883),  # LAA - Anaheim
    120: (34.074, -118.240),  # LAD - Los Angeles
    146: (25.778, -80.220),   # MIA - Miami
    158: (43.028, -87.971),   # MIL - Milwaukee
    142: (44.982, -93.278),   # MIN - Minneapolis
    121: (40.757, -73.846),   # NYM - New York
    147: (40.829, -73.926),   # NYY - New York
    133: (37.751, -122.201),  # OAK - Oakland
    143: (39.906, -75.167),   # PHI - Philadelphia
    134: (40.447, -80.006),   # PIT - Pittsburgh
    135: (32.707, -117.157),  # SD  - San Diego
    136: (37.778, -122.389),  # SF  - San Francisco
    137: (47.591, -122.333),  # SEA - Seattle
    138: (38.623, -90.193),   # STL - St. Louis
    139: (27.768, -82.653),   # TB  - St. Petersburg
    140: (32.751, -97.083),   # TEX - Arlington
    141: (43.641, -79.389),   # TOR - Toronto
    120: (34.074, -118.240),  # LAD
    148: (38.873, -77.007),   # WSH - Washington
}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in miles between two lat/lon points."""
    R = 3959
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


FEATURE_COLS = [
    # Team-level run production/prevention
    "home_rs_g", "home_ra_g", "home_pyth", "home_win_pct", "home_games",
    "away_rs_g", "away_ra_g", "away_pyth", "away_win_pct", "away_games",
    # Differentials
    "rs_g_diff", "ra_g_diff", "pyth_diff", "win_pct_diff",
    # Recent form at multiple windows
    "home_last10_pct", "away_last10_pct", "last10_diff",
    "home_last5_pct", "away_last5_pct", "last5_diff",
    "home_last20_pct", "away_last20_pct", "last20_diff",
    # Momentum
    "home_momentum", "away_momentum",
    # Run differential per game
    "home_run_diff_g", "away_run_diff_g", "run_diff_g_diff",
    # Home/away venue splits
    "home_home_pct", "away_away_pct", "venue_pct_diff",
    # Scoring consistency
    "home_rs_std", "away_rs_std",
    # Season phase
    "season_progress",
    # Pythagorean residual
    "home_pyth_residual", "away_pyth_residual",
    # --- PITCHER FEATURES (v2) ---
    "home_sp_era", "away_sp_era", "sp_era_diff",
    "home_sp_k9", "away_sp_k9", "sp_k9_diff",
    "home_sp_bb9", "away_sp_bb9",
    "home_sp_whip", "away_sp_whip", "sp_whip_diff",
    "home_sp_ip", "away_sp_ip",
    "home_sp_era_vs_team", "away_sp_era_vs_team",
    "home_sp_fip_proxy", "away_sp_fip_proxy", "sp_fip_proxy_diff",
    "has_pitcher_data",
    # --- v3 FEATURES ---
    "home_elo", "away_elo", "elo_diff",
    "home_rest_days", "away_rest_days", "rest_diff",
    "home_bullpen_era", "away_bullpen_era", "bullpen_era_diff",
    "travel_distance",
    # --- v4 FEATURES: park, weather, pitcher recent form ---
    "home_park_factor", "park_is_outdoor",
    "home_wind_mph", "wind_favor_sp",
    "home_sp_era_l10", "away_sp_era_l10", "sp_era_l10_diff",
    "home_sp_k9_l10", "away_sp_k9_l10",
    "home_sp_era_trend", "away_sp_era_trend",
    # --- v5 FEATURES: pitcher vs opponent splits + lineup quality ---
    "home_sp_era_vs_opp", "away_sp_era_vs_opp", "sp_era_vs_opp_diff",
    "home_sp_k9_vs_opp", "away_sp_k9_vs_opp",
    "home_lineup_ops", "away_lineup_ops", "lineup_ops_diff",
    # --- v6 FEATURES: batter vs pitcher historical matchup data ---
    "home_lineup_ops_vs_sp", "away_lineup_ops_vs_sp", "lineup_ops_vs_sp_diff",
    "home_hr_threat_vs_sp", "away_hr_threat_vs_sp",
    "home_k_rate_vs_sp", "away_k_rate_vs_sp",
]


def _pyth(rs_g: float, ra_g: float, exp: float = 1.83) -> float:
    if rs_g <= 0 and ra_g <= 0:
        return 0.5
    if ra_g <= 0:
        return 0.95
    if rs_g <= 0:
        return 0.05
    rs_x = rs_g ** exp
    ra_x = ra_g ** exp
    return rs_x / (rs_x + ra_x)


# ---------------------------------------------------------------------------
# Accumulators: track cumulative stats game-by-game (no look-ahead)
# ---------------------------------------------------------------------------

class EloTracker:
    """MLB Elo rating system tracked game-by-game."""
    K = 4.0  # conservative K-factor for MLB (low variance sport)
    HFA = 24  # home field advantage in Elo points (~54%)

    def __init__(self):
        self.ratings: dict[int, float] = defaultdict(lambda: 1500.0)

    def expected(self, team_id: int, opp_id: int, is_home: bool) -> float:
        r = self.ratings[team_id] + (self.HFA if is_home else 0)
        ro = self.ratings[opp_id] + (self.HFA if not is_home else 0)
        return 1 / (1 + 10 ** ((ro - r) / 400))

    def update(self, winner_id: int, loser_id: int, winner_home: bool, margin: int = 1):
        mov_mult = max(1.0, math.log(abs(margin) + 1))
        exp_w = self.expected(winner_id, loser_id, winner_home)
        shift = self.K * mov_mult * (1 - exp_w)
        self.ratings[winner_id] += shift
        self.ratings[loser_id] -= shift

    def season_regress(self):
        """Regress toward 1500 between seasons (30%)."""
        for tid in self.ratings:
            self.ratings[tid] = 1500 + 0.7 * (self.ratings[tid] - 1500)


class TeamAccumulator:
    def __init__(self):
        self.games = 0
        self.wins = 0
        self.rs = 0
        self.ra = 0
        self.recent10: deque[int] = deque(maxlen=10)
        self.recent5: deque[int] = deque(maxlen=5)
        self.recent20: deque[int] = deque(maxlen=20)
        self.home_games = 0
        self.home_wins = 0
        self.away_games = 0
        self.away_wins = 0
        self.rs_history: list[int] = []
        self.team_era_sum = 0.0
        self.team_era_n = 0
        self.last_game_date: str = ""
        self.sp_ip_total = 0.0
        self.sp_er_total = 0
        self.sp_starts = 0

    @property
    def rs_g(self) -> float:
        return self.rs / max(self.games, 1)

    @property
    def ra_g(self) -> float:
        return self.ra / max(self.games, 1)

    @property
    def pyth(self) -> float:
        return _pyth(self.rs_g, self.ra_g)

    @property
    def win_pct(self) -> float:
        return self.wins / max(self.games, 1)

    @property
    def last5_pct(self) -> float:
        return sum(self.recent5) / max(len(self.recent5), 1) if self.recent5 else 0.5

    @property
    def last10_pct(self) -> float:
        return sum(self.recent10) / max(len(self.recent10), 1) if self.recent10 else 0.5

    @property
    def last20_pct(self) -> float:
        return sum(self.recent20) / max(len(self.recent20), 1) if self.recent20 else 0.5

    @property
    def momentum(self) -> float:
        return self.last5_pct - self.last10_pct

    @property
    def home_pct(self) -> float:
        return self.home_wins / max(self.home_games, 1)

    @property
    def away_pct(self) -> float:
        return self.away_wins / max(self.away_games, 1)

    @property
    def run_diff_g(self) -> float:
        return (self.rs - self.ra) / max(self.games, 1)

    @property
    def rs_std(self) -> float:
        if len(self.rs_history) < 5:
            return 2.5
        return float(np.std(self.rs_history[-30:]))

    @property
    def pyth_residual(self) -> float:
        return self.win_pct - self.pyth

    @property
    def avg_era(self) -> float:
        return (self.ra * 9) / max(self.games * 9, 1)

    @property
    def bullpen_era(self) -> float:
        """Estimate bullpen ERA: team total RA minus starter contribution."""
        if self.games < 10:
            return 4.20
        team_era = self.avg_era
        if self.sp_starts < 5 or self.sp_ip_total < 20:
            return team_era
        sp_era = (self.sp_er_total * 9) / self.sp_ip_total
        sp_ip_pct = self.sp_ip_total / (self.games * 9)
        bp_era = (team_era - sp_era * sp_ip_pct) / max(1 - sp_ip_pct, 0.2)
        return max(1.0, min(8.0, bp_era))

    def rest_days(self, current_date: str) -> float:
        """Days since last game. Capped at 4 (off-day max)."""
        if not self.last_game_date or not current_date:
            return 1.0
        try:
            cur = datetime.strptime(current_date[:10], "%Y-%m-%d")
            prev = datetime.strptime(self.last_game_date[:10], "%Y-%m-%d")
            return min(float((cur - prev).days), 4.0)
        except (ValueError, TypeError):
            return 1.0

    def update(self, runs_for: int, runs_against: int, is_home: bool, game_date: str = ""):
        won = runs_for > runs_against
        self.games += 1
        self.wins += int(won)
        self.rs += runs_for
        self.ra += runs_against
        self.recent5.append(int(won))
        self.recent10.append(int(won))
        self.recent20.append(int(won))
        self.rs_history.append(runs_for)
        if game_date:
            self.last_game_date = game_date
        if is_home:
            self.home_games += 1
            self.home_wins += int(won)
        else:
            self.away_games += 1
            self.away_wins += int(won)

    def update_sp_stats(self, ip: float, er: int):
        """Track starter IP/ER for bullpen ERA calculation."""
        self.sp_starts += 1
        self.sp_ip_total += ip
        self.sp_er_total += er


class PitcherAccumulator:
    """Track a single pitcher's cumulative stats game-by-game."""

    def __init__(self, pitcher_id: int):
        self.pitcher_id = pitcher_id
        self.starts = 0
        self.ip_total = 0.0
        self.er_total = 0
        self.k_total = 0
        self.bb_total = 0
        self.h_total = 0
        # Rolling last-10-starts windows for recent form features
        self._l10_ip: deque[float] = deque(maxlen=10)
        self._l10_er: deque[float] = deque(maxlen=10)
        self._l10_k: deque[float] = deque(maxlen=10)

    @property
    def era(self) -> float:
        if self.ip_total < 3:
            return 4.50
        return (self.er_total * 9) / self.ip_total

    @property
    def k_per_9(self) -> float:
        if self.ip_total < 3:
            return 7.5
        return (self.k_total * 9) / self.ip_total

    @property
    def bb_per_9(self) -> float:
        if self.ip_total < 3:
            return 3.5
        return (self.bb_total * 9) / self.ip_total

    @property
    def whip(self) -> float:
        if self.ip_total < 3:
            return 1.35
        return (self.bb_total + self.h_total) / self.ip_total

    @property
    def fip_proxy(self) -> float:
        """K-BB rate as FIP proxy. Higher = better pitcher."""
        if self.ip_total < 3:
            return 0.0
        return ((self.k_total - self.bb_total) * 9) / self.ip_total

    @property
    def era_l10(self) -> float:
        """ERA over last 10 starts. Falls back to season ERA if < 5 starts recorded."""
        if len(self._l10_ip) < 5:
            return self.era
        ip = max(sum(self._l10_ip), 1.0)
        return (sum(self._l10_er) * 9) / ip

    @property
    def k9_l10(self) -> float:
        """K/9 over last 10 starts. Falls back to season K/9 if < 5 starts."""
        if len(self._l10_ip) < 5:
            return self.k_per_9
        ip = max(sum(self._l10_ip), 1.0)
        return (sum(self._l10_k) * 9) / ip

    @property
    def era_trend(self) -> float:
        """Positive = improving (recent ERA is lower than season ERA)."""
        if len(self._l10_ip) < 5:
            return 0.0
        return self.era - self.era_l10

    def update(self, ip: float, er: int, k: int, bb: int, h: int):
        self.starts += 1
        self.ip_total += ip
        self.er_total += er
        self.k_total += k
        self.bb_total += bb
        self.h_total += h
        self._l10_ip.append(ip)
        self._l10_er.append(float(er))
        self._l10_k.append(float(k))


PITCHER_DEFAULTS = {
    "era": 4.50, "k9": 7.5, "bb9": 3.5, "whip": 1.35,
    "ip": 0.0, "era_vs_team": 1.0, "fip_proxy": 0.0,
    "era_l10": 4.50, "k9_l10": 7.5, "era_trend": 0.0,
}


# ---------------------------------------------------------------------------
# Data fetching (with pitcher IDs)
# ---------------------------------------------------------------------------

ALL_SEASONS = [
    2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018,
    2019, 2021, 2022, 2023, 2024, 2025,
]
TRAIN_SEASONS = [
    2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018,
    2019, 2021, 2022, 2023, 2024,
]
TEST_SEASONS = [2025]


def _fetch_season_games(season: int) -> list[dict]:
    """Fetch games with pitcher IDs for a season."""
    start, end = f"{season}-03-20", f"{season}-10-05"
    data = _cached_get(
        f"mlb_pitcher_schedule_{season}",
        f"{API_BASE}/schedule",
        {
            "startDate": start,
            "endDate": end,
            "sportId": 1,
            "gameType": "R",
            "hydrate": "probablePitcher",
            "fields": (
                "dates,date,games,gamePk,gameDate,"
                "status,abstractGameState,"
                "teams,home,away,team,id,name,score,"
                "probablePitcher,id,fullName"
            ),
        },
        max_age_s=86400 * 365,
    )
    games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue
            home = game.get("teams", {}).get("home", {})
            away = game.get("teams", {}).get("away", {})
            hs, as_ = home.get("score"), away.get("score")
            if hs is None or as_ is None:
                continue
            hp = home.get("probablePitcher", {})
            ap = away.get("probablePitcher", {})
            games.append({
                "game_pk": game.get("gamePk"),
                "date": date_entry.get("date", ""),
                "home_id": home.get("team", {}).get("id"),
                "away_id": away.get("team", {}).get("id"),
                "home_name": home.get("team", {}).get("name", ""),
                "away_name": away.get("team", {}).get("name", ""),
                "home_score": int(hs),
                "away_score": int(as_),
                "home_pitcher_id": hp.get("id"),
                "away_pitcher_id": ap.get("id"),
            })
    games.sort(key=lambda g: (g["date"], g["game_pk"] or 0))
    return games


def _estimate_pitcher_line(runs_against: int, innings: float = 6.0) -> dict:
    """Estimate a starter's game-level pitching line from the team's total runs allowed."""
    sp_ra = runs_against * 0.55
    er = max(0, int(round(sp_ra * 0.9)))
    k = int(round(innings * 0.83))
    bb = int(round(innings * 0.39))
    h = int(round(innings * 1.0))
    return {"ip": innings, "er": er, "k": k, "bb": bb, "h": h}


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _pitcher_features(
    pitcher: PitcherAccumulator | None,
    team: TeamAccumulator,
) -> dict:
    """Build pitcher-level features for one side of the game."""
    if pitcher is None or pitcher.starts < 2:
        return dict(PITCHER_DEFAULTS)
    team_era = team.avg_era if team.avg_era > 0 else 4.50
    return {
        "era": pitcher.era,
        "k9": pitcher.k_per_9,
        "bb9": pitcher.bb_per_9,
        "whip": pitcher.whip,
        "ip": pitcher.ip_total,
        "era_vs_team": pitcher.era / max(team_era, 1.0),
        "fip_proxy": pitcher.fip_proxy,
    }


def _make_feature_row(
    home: TeamAccumulator,
    away: TeamAccumulator,
    home_sp: PitcherAccumulator | None,
    away_sp: PitcherAccumulator | None,
    game: dict,
    season: int,
    elo: EloTracker | None = None,
) -> dict:
    game_date = game["date"]
    month = int(game_date[5:7]) if len(game_date) >= 7 else 6
    season_progress = max(0.0, min(1.0, (month - 3) / 7.0))

    hp = _pitcher_features(home_sp, home)
    ap = _pitcher_features(away_sp, away)
    has_data = 1.0 if (home_sp and home_sp.starts >= 2 and away_sp and away_sp.starts >= 2) else 0.0

    hid, aid = game["home_id"], game["away_id"]
    home_elo = elo.ratings[hid] if elo else 1500.0
    away_elo = elo.ratings[aid] if elo else 1500.0

    h_rest = home.rest_days(game_date)
    a_rest = away.rest_days(game_date)

    h_coords = TEAM_COORDS.get(hid)
    a_coords = TEAM_COORDS.get(aid)
    travel = 0.0
    if h_coords and a_coords:
        travel = _haversine(h_coords[0], h_coords[1], a_coords[0], a_coords[1])

    return {
        "season": season,
        "game_pk": game["game_pk"],
        "date": game_date,
        "home_team": game["home_name"],
        "away_team": game["away_name"],
        "home_won": int(game["home_score"] > game["away_score"]),
        "home_score": game["home_score"],
        "away_score": game["away_score"],
        # Team features
        "home_rs_g": home.rs_g, "home_ra_g": home.ra_g,
        "home_pyth": home.pyth, "home_win_pct": home.win_pct, "home_games": home.games,
        "away_rs_g": away.rs_g, "away_ra_g": away.ra_g,
        "away_pyth": away.pyth, "away_win_pct": away.win_pct, "away_games": away.games,
        "rs_g_diff": home.rs_g - away.rs_g, "ra_g_diff": home.ra_g - away.ra_g,
        "pyth_diff": home.pyth - away.pyth, "win_pct_diff": home.win_pct - away.win_pct,
        "home_last10_pct": home.last10_pct, "away_last10_pct": away.last10_pct,
        "last10_diff": home.last10_pct - away.last10_pct,
        "home_last5_pct": home.last5_pct, "away_last5_pct": away.last5_pct,
        "last5_diff": home.last5_pct - away.last5_pct,
        "home_last20_pct": home.last20_pct, "away_last20_pct": away.last20_pct,
        "last20_diff": home.last20_pct - away.last20_pct,
        "home_momentum": home.momentum, "away_momentum": away.momentum,
        "home_run_diff_g": home.run_diff_g, "away_run_diff_g": away.run_diff_g,
        "run_diff_g_diff": home.run_diff_g - away.run_diff_g,
        "home_home_pct": home.home_pct, "away_away_pct": away.away_pct,
        "venue_pct_diff": home.home_pct - away.away_pct,
        "home_rs_std": home.rs_std, "away_rs_std": away.rs_std,
        "season_progress": season_progress,
        "home_pyth_residual": home.pyth_residual, "away_pyth_residual": away.pyth_residual,
        # Pitcher features
        "home_sp_era": hp["era"], "away_sp_era": ap["era"],
        "sp_era_diff": hp["era"] - ap["era"],
        "home_sp_k9": hp["k9"], "away_sp_k9": ap["k9"],
        "sp_k9_diff": hp["k9"] - ap["k9"],
        "home_sp_bb9": hp["bb9"], "away_sp_bb9": ap["bb9"],
        "home_sp_whip": hp["whip"], "away_sp_whip": ap["whip"],
        "sp_whip_diff": hp["whip"] - ap["whip"],
        "home_sp_ip": hp["ip"], "away_sp_ip": ap["ip"],
        "home_sp_era_vs_team": hp["era_vs_team"], "away_sp_era_vs_team": ap["era_vs_team"],
        "home_sp_fip_proxy": hp["fip_proxy"], "away_sp_fip_proxy": ap["fip_proxy"],
        "sp_fip_proxy_diff": hp["fip_proxy"] - ap["fip_proxy"],
        "has_pitcher_data": has_data,
        # v3: Elo, rest, bullpen, travel
        "home_elo": home_elo, "away_elo": away_elo,
        "elo_diff": home_elo - away_elo,
        "home_rest_days": h_rest, "away_rest_days": a_rest,
        "rest_diff": h_rest - a_rest,
        "home_bullpen_era": home.bullpen_era, "away_bullpen_era": away.bullpen_era,
        "bullpen_era_diff": home.bullpen_era - away.bullpen_era,
        "travel_distance": travel / 1000.0,
        # v4: park factor, weather (0 during backtest — no historical weather), pitcher form
        "home_park_factor": get_park_factor(game["home_name"]),
        "park_is_outdoor": 1.0 if game["home_name"] in OUTDOOR_PARKS else 0.0,
        "home_wind_mph": 0.0,   # no historical weather data; set 0 for backtest
        "wind_favor_sp": 0.0,
        "home_sp_era_l10": home_sp.era_l10 if home_sp and home_sp.starts >= 2 else 4.50,
        "away_sp_era_l10": away_sp.era_l10 if away_sp and away_sp.starts >= 2 else 4.50,
        "sp_era_l10_diff": (
            (home_sp.era_l10 if home_sp and home_sp.starts >= 2 else 4.50) -
            (away_sp.era_l10 if away_sp and away_sp.starts >= 2 else 4.50)
        ),
        "home_sp_k9_l10": home_sp.k9_l10 if home_sp and home_sp.starts >= 2 else 7.5,
        "away_sp_k9_l10": away_sp.k9_l10 if away_sp and away_sp.starts >= 2 else 7.5,
        "home_sp_era_trend": home_sp.era_trend if home_sp and home_sp.starts >= 5 else 0.0,
        "away_sp_era_trend": away_sp.era_trend if away_sp and away_sp.starts >= 5 else 0.0,
        # v5: pitcher vs opponent splits (backtest: no historical matchup data, use season ERA)
        "home_sp_era_vs_opp": home_sp.era if home_sp and home_sp.starts >= 2 else 4.50,
        "away_sp_era_vs_opp": away_sp.era if away_sp and away_sp.starts >= 2 else 4.50,
        "sp_era_vs_opp_diff": (
            (home_sp.era if home_sp and home_sp.starts >= 2 else 4.50) -
            (away_sp.era if away_sp and away_sp.starts >= 2 else 4.50)
        ),
        "home_sp_k9_vs_opp": home_sp.k_per_9 if home_sp and home_sp.starts >= 2 else 7.5,
        "away_sp_k9_vs_opp": away_sp.k_per_9 if away_sp and away_sp.starts >= 2 else 7.5,
        # v5: lineup quality (backtest: use team OPS proxy from run production)
        "home_lineup_ops": min(max(game.get("home_rs_g", 4.5) / 9.0 + 0.55, 0.60), 0.95),
        "away_lineup_ops": min(max(game.get("away_rs_g", 4.5) / 9.0 + 0.55, 0.60), 0.95),
        "lineup_ops_diff": (
            min(max(game.get("home_rs_g", 4.5) / 9.0 + 0.55, 0.60), 0.95) -
            min(max(game.get("away_rs_g", 4.5) / 9.0 + 0.55, 0.60), 0.95)
        ),
        # v6: batter vs pitcher historical matchup (backtest: no per-AB data, use lineup OPS proxy)
        "home_lineup_ops_vs_sp": min(max(game.get("home_rs_g", 4.5) / 9.0 + 0.55, 0.60), 0.95),
        "away_lineup_ops_vs_sp": min(max(game.get("away_rs_g", 4.5) / 9.0 + 0.55, 0.60), 0.95),
        "lineup_ops_vs_sp_diff": (
            min(max(game.get("home_rs_g", 4.5) / 9.0 + 0.55, 0.60), 0.95) -
            min(max(game.get("away_rs_g", 4.5) / 9.0 + 0.55, 0.60), 0.95)
        ),
        "home_hr_threat_vs_sp": 0.033,  # league avg HR/AB
        "away_hr_threat_vs_sp": 0.033,
        "home_k_rate_vs_sp": 0.22,  # league avg K rate
        "away_k_rate_vs_sp": 0.22,
    }


def build_training_data(
    seasons: list[int] | None = None,
    min_games: int = 15,
    verbose: bool = True,
) -> pd.DataFrame:
    if seasons is None:
        seasons = ALL_SEASONS

    elo = EloTracker()
    all_rows = []
    prev_season = None

    for season in seasons:
        if prev_season and season != prev_season:
            elo.season_regress()
        prev_season = season

        if verbose:
            print(f"  Fetching {season}...", end=" ", flush=True)
        games = _fetch_season_games(season)
        if not games:
            if verbose:
                print("no data")
            continue

        teams: dict[int, TeamAccumulator] = defaultdict(TeamAccumulator)
        pitchers: dict[int, PitcherAccumulator] = {}
        season_rows = 0
        pitcher_games = 0

        for game in games:
            hid, aid = game["home_id"], game["away_id"]
            hs, as_ = game["home_score"], game["away_score"]
            if hs == as_:
                continue

            home, away = teams[hid], teams[aid]
            hp_id, ap_id = game.get("home_pitcher_id"), game.get("away_pitcher_id")
            home_sp = pitchers.get(hp_id) if hp_id else None
            away_sp = pitchers.get(ap_id) if ap_id else None

            if home.games >= min_games and away.games >= min_games:
                row = _make_feature_row(home, away, home_sp, away_sp, game, season, elo)
                all_rows.append(row)
                season_rows += 1
                if home_sp and away_sp and home_sp.starts >= 2 and away_sp.starts >= 2:
                    pitcher_games += 1

            game_date = game.get("date", "")
            home.update(hs, as_, is_home=True, game_date=game_date)
            away.update(as_, hs, is_home=False, game_date=game_date)

            h_line = _estimate_pitcher_line(as_)
            a_line = _estimate_pitcher_line(hs)

            if hp_id:
                if hp_id not in pitchers:
                    pitchers[hp_id] = PitcherAccumulator(hp_id)
                pitchers[hp_id].update(**h_line)
                home.update_sp_stats(h_line["ip"], h_line["er"])
            if ap_id:
                if ap_id not in pitchers:
                    pitchers[ap_id] = PitcherAccumulator(ap_id)
                pitchers[ap_id].update(**a_line)
                away.update_sp_stats(a_line["ip"], a_line["er"])

            winner_id = hid if hs > as_ else aid
            loser_id = aid if hs > as_ else hid
            elo.update(winner_id, loser_id, winner_home=(hs > as_), margin=abs(hs - as_))

        if verbose:
            print(f"{len(games)} games, {season_rows} samples, {pitcher_games} w/ pitcher data")

    return pd.DataFrame(all_rows)


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------

def _make_xgb(n_estimators: int = 300) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=n_estimators,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.7,
        min_child_weight=10,
        reg_alpha=0.1,
        reg_lambda=1.0,
        gamma=0.1,
        eval_metric="logloss",
        random_state=42,
        use_label_encoder=False,
    )


def _make_lgbm(n_estimators: int = 300):
    if not HAS_LGBM:
        return None
    return LGBMClassifier(
        n_estimators=n_estimators,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.7,
        min_child_weight=10,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=43,
        verbose=-1,
    )


def _make_catboost(n_estimators: int = 300):
    if not HAS_CATBOOST:
        return None
    return CatBoostClassifier(
        iterations=n_estimators,
        depth=4,
        learning_rate=0.03,
        subsample=0.8,
        l2_leaf_reg=1.0,
        random_seed=44,
        verbose=0,
    )


def walk_forward_cv(
    df: pd.DataFrame,
    min_train_seasons: int = 4,
    verbose: bool = True,
    use_stacking: bool = True,
) -> list[dict]:
    """
    Walk-forward CV with multi-model stacking.
    Trains XGBoost + LightGBM + CatBoost per fold, then a logistic
    regression meta-learner on their out-of-fold predictions.
    """
    seasons = sorted(df["season"].unique())
    if len(seasons) < min_train_seasons + 1:
        raise ValueError(f"Need at least {min_train_seasons + 1} seasons")

    results = []
    for i in range(min_train_seasons, len(seasons)):
        test_season = seasons[i]
        train_df = df[df["season"].isin(seasons[:i])]
        test_df = df[df["season"] == test_season]
        if train_df.empty or test_df.empty:
            continue

        X_train, y_train = train_df[FEATURE_COLS], train_df["home_won"]
        X_test, y_test = test_df[FEATURE_COLS], test_df["home_won"]

        # Train all base models
        xgb = _make_xgb()
        xgb.fit(X_train, y_train, verbose=False)
        xgb_probs = xgb.predict_proba(X_test)[:, 1]

        model_probs = {"xgb": xgb_probs}
        model_names = ["xgb"]

        lgbm = _make_lgbm()
        if lgbm is not None:
            lgbm.fit(X_train, y_train)
            model_probs["lgbm"] = lgbm.predict_proba(X_test)[:, 1]
            model_names.append("lgbm")

        cb = _make_catboost()
        if cb is not None:
            cb.fit(X_train, y_train)
            model_probs["catboost"] = cb.predict_proba(X_test)[:, 1]
            model_names.append("catboost")

        # Stacking: combine base model predictions via logistic regression
        if use_stacking and len(model_names) >= 2:
            # Generate OOF predictions on training data for the meta-learner
            n_train = len(X_train)
            oof_preds = {name: np.zeros(n_train) for name in model_names}
            train_seasons_list = sorted(train_df["season"].unique())

            for j in range(max(2, len(train_seasons_list) - 3), len(train_seasons_list)):
                inner_test_s = train_seasons_list[j]
                inner_train = train_df[train_df["season"].isin(train_seasons_list[:j])]
                inner_test = train_df[train_df["season"] == inner_test_s]
                if inner_train.empty or inner_test.empty:
                    continue
                inner_idx = inner_test.index

                ix = _make_xgb()
                ix.fit(inner_train[FEATURE_COLS], inner_train["home_won"], verbose=False)
                mask = train_df.index.isin(inner_idx)
                oof_preds["xgb"][mask] = ix.predict_proba(inner_test[FEATURE_COLS])[:, 1]

                if "lgbm" in model_names:
                    il = _make_lgbm()
                    il.fit(inner_train[FEATURE_COLS], inner_train["home_won"])
                    oof_preds["lgbm"][mask] = il.predict_proba(inner_test[FEATURE_COLS])[:, 1]

                if "catboost" in model_names:
                    ic = _make_catboost()
                    ic.fit(inner_train[FEATURE_COLS], inner_train["home_won"])
                    oof_preds["catboost"][mask] = ic.predict_proba(inner_test[FEATURE_COLS])[:, 1]

            valid_mask = oof_preds["xgb"] > 0
            if valid_mask.sum() > 100:
                meta_X = np.column_stack([oof_preds[n][valid_mask] for n in model_names])
                meta_y = y_train.values[valid_mask]
                meta = LogisticRegression(C=1.0, max_iter=1000)
                meta.fit(meta_X, meta_y)

                test_meta_X = np.column_stack([model_probs[n] for n in model_names])
                stacked_probs = meta.predict_proba(test_meta_X)[:, 1]
                raw_probs = stacked_probs
            else:
                raw_probs = xgb_probs
        else:
            raw_probs = xgb_probs

        preds = (raw_probs >= 0.5).astype(int)
        acc = float((preds == y_test.values).mean())
        home_bl = float(y_test.mean())
        brier = float(((raw_probs - y_test.values) ** 2).mean())
        ref_brier = float(((home_bl - y_test.values) ** 2).mean())
        bss = 1 - brier / ref_brier if ref_brier > 0 else 0

        conf_mask = (raw_probs >= 0.58) | (raw_probs <= 0.42)
        conf_preds = (raw_probs[conf_mask] >= 0.5).astype(int)
        conf_actual = y_test.values[conf_mask]
        conf_acc = float((conf_preds == conf_actual).mean()) if len(conf_preds) > 0 else 0

        # Per-model accuracy for reporting
        per_model = {}
        for name, probs in model_probs.items():
            m_acc = float(((probs >= 0.5).astype(int) == y_test.values).mean())
            per_model[name] = m_acc

        fold = {
            "test_season": int(test_season),
            "train_n": len(X_train), "test_n": len(X_test),
            "accuracy": acc, "home_baseline": home_bl,
            "lift": acc - home_bl,
            "brier": brier, "brier_skill_score": float(bss),
            "confident_n": int(conf_mask.sum()), "confident_accuracy": conf_acc,
            "feature_importance": dict(zip(FEATURE_COLS, xgb.feature_importances_)),
            "per_model": per_model,
            "n_models": len(model_names),
        }
        results.append(fold)

        if verbose:
            m = "+" if acc > home_bl else "-"
            model_str = " ".join(f"{n}={per_model[n]:.1%}" for n in model_names)
            print(
                f"  {test_season}: STACK={acc:.1%} [{model_str}] "
                f"(home: {home_bl:.1%}, lift: {acc - home_bl:+.1%}) "
                f"BSS={bss:+.3f} [{m}] "
                f"conf: {conf_acc:.1%} ({int(conf_mask.sum())})"
            )
    return results


# ---------------------------------------------------------------------------
# Ensemble walk-forward CV (XGBoost + Pythagorean)
# ---------------------------------------------------------------------------

def ensemble_walk_forward_cv(
    df: pd.DataFrame,
    min_train_seasons: int = 4,
    pyth_weight: float = 0.45,
    xgb_weight: float = 0.55,
    verbose: bool = True,
) -> list[dict]:
    """
    Walk-forward CV for the ensemble: at each fold, generate both
    Pythagorean and XGBoost predictions, then combine with fixed weights.
    Compares XGBoost-only vs Pythagorean-only vs Ensemble.
    """
    seasons = sorted(df["season"].unique())
    results = []

    for i in range(min_train_seasons, len(seasons)):
        test_season = seasons[i]
        train_df = df[df["season"].isin(seasons[:i])]
        test_df = df[df["season"] == test_season]
        if train_df.empty or test_df.empty:
            continue

        X_train, y_train = train_df[FEATURE_COLS], train_df["home_won"]
        X_test, y_test = test_df[FEATURE_COLS], test_df["home_won"]

        model = _make_xgb()
        model.fit(X_train, y_train, verbose=False)
        xgb_probs = model.predict_proba(X_test)[:, 1]

        pyth_probs = np.array([
            max(0.05, min(0.95, _pyth(row["home_rs_g"], row["home_ra_g"]) -
                _pyth(row["away_rs_g"], row["away_ra_g"]) * 0 +
                0.538))
            for _, row in test_df.iterrows()
        ])

        home_pyth = np.array([_pyth(r["home_rs_g"], r["home_ra_g"]) for _, r in test_df.iterrows()])
        away_pyth = np.array([_pyth(r["away_rs_g"], r["away_ra_g"]) for _, r in test_df.iterrows()])
        pyth_probs = np.array([
            max(0.05, min(0.95,
                (hp * (1 - ap)) / (hp * (1 - ap) + ap * (1 - hp) + 1e-9) + 0.038
            ))
            for hp, ap in zip(home_pyth, away_pyth)
        ])

        ens_probs = pyth_weight * pyth_probs + xgb_weight * xgb_probs
        ens_probs = np.clip(ens_probs, 0.05, 0.95)

        y = y_test.values
        home_bl = float(y.mean())

        def _metrics(probs):
            preds = (probs >= 0.5).astype(int)
            acc = float((preds == y).mean())
            brier = float(((probs - y) ** 2).mean())
            ref_brier = float(((home_bl - y) ** 2).mean())
            bss = 1 - brier / ref_brier if ref_brier > 0 else 0
            cm = (probs >= 0.58) | (probs <= 0.42)
            ca = float(((probs[cm] >= 0.5).astype(int) == y[cm]).mean()) if cm.sum() > 0 else 0
            return {"accuracy": acc, "lift": acc - home_bl, "brier": brier,
                    "bss": float(bss), "conf_acc": ca, "conf_n": int(cm.sum())}

        fold = {
            "test_season": int(test_season),
            "home_baseline": home_bl,
            "xgb": _metrics(xgb_probs),
            "pyth": _metrics(pyth_probs),
            "ensemble": _metrics(ens_probs),
        }
        results.append(fold)

        if verbose:
            x, p, e = fold["xgb"], fold["pyth"], fold["ensemble"]
            best = max(x["accuracy"], p["accuracy"], e["accuracy"])
            tags = {"xgb": x["accuracy"], "pyth": p["accuracy"], "ens": e["accuracy"]}
            winner = max(tags, key=tags.get)
            print(
                f"  {test_season}: XGB={x['accuracy']:.1%} Pyth={p['accuracy']:.1%} "
                f"Ens={e['accuracy']:.1%} [{winner.upper()}] "
                f"conf: X={x['conf_acc']:.1%} P={p['conf_acc']:.1%} E={e['conf_acc']:.1%}"
            )

    return results


# ---------------------------------------------------------------------------
# Full training pipeline
# ---------------------------------------------------------------------------

def train_mlb_model(
    train_seasons: list[int] | None = None,
    test_seasons: list[int] | None = None,
    calibrate: bool = True,
) -> tuple[dict, XGBClassifier]:
    if train_seasons is None:
        train_seasons = TRAIN_SEASONS
    if test_seasons is None:
        test_seasons = TEST_SEASONS

    all_seasons = sorted(set(train_seasons + test_seasons))

    print("\n1. Building feature dataset (with pitcher tracking)...")
    df = build_training_data(all_seasons)
    if df.empty:
        raise ValueError("No training data")
    pitcher_pct = df["has_pitcher_data"].mean()
    print(f"   Total: {len(df):,} samples, {len(FEATURE_COLS)} features, "
          f"{pitcher_pct:.0%} have pitcher data")

    print("\n2. Walk-forward cross-validation...")
    cv_df = df[df["season"].isin(train_seasons)]
    cv_results = walk_forward_cv(cv_df, min_train_seasons=4)

    cv_accs = [r["accuracy"] for r in cv_results]
    cv_bss = [r["brier_skill_score"] for r in cv_results]
    cv_lifts = [r["lift"] for r in cv_results]
    cv_confs = [r["confident_accuracy"] for r in cv_results if r["confident_n"] > 50]

    print(f"\n   CV Summary ({len(cv_results)} folds):")
    print(f"   Mean accuracy:     {np.mean(cv_accs):.1%} +/- {np.std(cv_accs):.1%}")
    print(f"   Mean lift vs home: {np.mean(cv_lifts):+.1%}")
    print(f"   Mean Brier skill:  {np.mean(cv_bss):+.3f}")
    if cv_confs:
        print(f"   Mean conf acc:     {np.mean(cv_confs):.1%}")
    print(f"   Positive folds:    {sum(1 for l in cv_lifts if l > 0)}/{len(cv_lifts)}")

    print("\n3. Ensemble walk-forward (XGBoost vs Pythagorean vs Combined)...")
    ens_results = ensemble_walk_forward_cv(cv_df, min_train_seasons=4)

    ens_xgb = [r["xgb"]["accuracy"] for r in ens_results]
    ens_pyth = [r["pyth"]["accuracy"] for r in ens_results]
    ens_ens = [r["ensemble"]["accuracy"] for r in ens_results]
    ens_xgb_conf = [r["xgb"]["conf_acc"] for r in ens_results]
    ens_pyth_conf = [r["pyth"]["conf_acc"] for r in ens_results]
    ens_ens_conf = [r["ensemble"]["conf_acc"] for r in ens_results]

    xgb_wins = sum(1 for r in ens_results if r["xgb"]["accuracy"] > r["pyth"]["accuracy"] and r["xgb"]["accuracy"] > r["ensemble"]["accuracy"])
    pyth_wins = sum(1 for r in ens_results if r["pyth"]["accuracy"] > r["xgb"]["accuracy"] and r["pyth"]["accuracy"] > r["ensemble"]["accuracy"])
    ens_wins = sum(1 for r in ens_results if r["ensemble"]["accuracy"] >= r["xgb"]["accuracy"] and r["ensemble"]["accuracy"] >= r["pyth"]["accuracy"])

    print(f"\n   Ensemble Summary:")
    print(f"   XGBoost mean:   {np.mean(ens_xgb):.1%}  conf: {np.mean(ens_xgb_conf):.1%}  wins: {xgb_wins}")
    print(f"   Pythagorean:    {np.mean(ens_pyth):.1%}  conf: {np.mean(ens_pyth_conf):.1%}  wins: {pyth_wins}")
    print(f"   Ensemble:       {np.mean(ens_ens):.1%}  conf: {np.mean(ens_ens_conf):.1%}  wins: {ens_wins}")

    print("\n4. Training final models (XGB + LGBM + CatBoost + meta-learner)...")
    train_df = df[df["season"].isin(train_seasons)]
    X_train, y_train = train_df[FEATURE_COLS], train_df["home_won"]

    model = _make_xgb(n_estimators=400)
    model.fit(X_train, y_train, verbose=False)

    lgbm_model = _make_lgbm(n_estimators=400)
    if lgbm_model:
        lgbm_model.fit(X_train, y_train)
        print("    LightGBM trained")

    cb_model = _make_catboost(n_estimators=400)
    if cb_model:
        cb_model.fit(X_train, y_train)
        print("    CatBoost trained")

    # Build stacking meta-learner from OOF predictions
    meta_model = None
    meta_model_names = ["xgb"]
    if lgbm_model:
        meta_model_names.append("lgbm")
    if cb_model:
        meta_model_names.append("catboost")

    if len(meta_model_names) >= 2:
        print("    Training stacking meta-learner...")
        oof_all = {n: np.zeros(len(X_train)) for n in meta_model_names}
        ts_list = sorted(train_df["season"].unique())

        for j in range(max(2, len(ts_list) - 4), len(ts_list)):
            inner_test_s = ts_list[j]
            inner_train = train_df[train_df["season"].isin(ts_list[:j])]
            inner_test = train_df[train_df["season"] == inner_test_s]
            if inner_train.empty or inner_test.empty:
                continue
            mask = train_df["season"] == inner_test_s

            ix = _make_xgb()
            ix.fit(inner_train[FEATURE_COLS], inner_train["home_won"], verbose=False)
            oof_all["xgb"][mask] = ix.predict_proba(inner_test[FEATURE_COLS])[:, 1]

            if "lgbm" in meta_model_names:
                il = _make_lgbm()
                il.fit(inner_train[FEATURE_COLS], inner_train["home_won"])
                oof_all["lgbm"][mask] = il.predict_proba(inner_test[FEATURE_COLS])[:, 1]

            if "catboost" in meta_model_names:
                ic = _make_catboost()
                ic.fit(inner_train[FEATURE_COLS], inner_train["home_won"])
                oof_all["catboost"][mask] = ic.predict_proba(inner_test[FEATURE_COLS])[:, 1]

        valid = oof_all["xgb"] > 0
        if valid.sum() > 200:
            meta_X = np.column_stack([oof_all[n][valid] for n in meta_model_names])
            meta_y = y_train.values[valid]
            meta_model = LogisticRegression(C=1.0, max_iter=1000)
            meta_model.fit(meta_X, meta_y)
            coefs = dict(zip(meta_model_names, meta_model.coef_[0]))
            print(f"    Meta-learner weights: {coefs}")

    calibrator = None
    if calibrate:
        cal_seasons = sorted(train_seasons)[-2:]
        cal_df = train_df[train_df["season"].isin(cal_seasons)]
        if meta_model:
            cal_probs_list = [model.predict_proba(cal_df[FEATURE_COLS])[:, 1]]
            if lgbm_model:
                cal_probs_list.append(lgbm_model.predict_proba(cal_df[FEATURE_COLS])[:, 1])
            if cb_model:
                cal_probs_list.append(cb_model.predict_proba(cal_df[FEATURE_COLS])[:, 1])
            cal_meta_X = np.column_stack(cal_probs_list)
            raw_cal = meta_model.predict_proba(cal_meta_X)[:, 1]
        else:
            raw_cal = model.predict_proba(cal_df[FEATURE_COLS])[:, 1]
        calibrator = IsotonicRegression(y_min=0.05, y_max=0.95, out_of_bounds="clip")
        calibrator.fit(raw_cal, cal_df["home_won"])

    test_df = df[df["season"].isin(test_seasons)]
    test_result = None
    if not test_df.empty:
        print(f"\n5. Held-out test: {test_seasons}")
        X_test, y_test = test_df[FEATURE_COLS], test_df["home_won"]

        if meta_model:
            test_probs_list = [model.predict_proba(X_test)[:, 1]]
            if lgbm_model:
                test_probs_list.append(lgbm_model.predict_proba(X_test)[:, 1])
            if cb_model:
                test_probs_list.append(cb_model.predict_proba(X_test)[:, 1])
            test_meta_X = np.column_stack(test_probs_list)
            raw_probs = meta_model.predict_proba(test_meta_X)[:, 1]
        else:
            raw_probs = model.predict_proba(X_test)[:, 1]

        probs = calibrator.predict(raw_probs) if calibrator else raw_probs
        preds = (probs >= 0.5).astype(int)
        acc = float((preds == y_test.values).mean())
        hbl = float(y_test.mean())
        brier = float(((probs - y_test.values) ** 2).mean())
        raw_brier = float(((raw_probs - y_test.values) ** 2).mean())
        ref_brier = float(((hbl - y_test.values) ** 2).mean())
        cm = (probs >= 0.58) | (probs <= 0.42)
        ca = float(((probs[cm] >= 0.5).astype(int) == y_test.values[cm]).mean()) if cm.sum() > 0 else 0

        # Per-model test accuracy
        xgb_only = float(((model.predict_proba(X_test)[:, 1] >= 0.5).astype(int) == y_test.values).mean())
        per_test = {"xgb": xgb_only}
        if lgbm_model:
            per_test["lgbm"] = float(((lgbm_model.predict_proba(X_test)[:, 1] >= 0.5).astype(int) == y_test.values).mean())
        if cb_model:
            per_test["catboost"] = float(((cb_model.predict_proba(X_test)[:, 1] >= 0.5).astype(int) == y_test.values).mean())

        test_result = {
            "accuracy": acc, "home_baseline": hbl, "lift": acc - hbl,
            "brier_raw": raw_brier, "brier_calibrated": brier,
            "brier_skill_score": 1 - brier / ref_brier if ref_brier > 0 else 0,
            "confident_n": int(cm.sum()), "confident_accuracy": ca,
            "test_n": len(X_test),
            "per_model": per_test,
        }

    importance_accum: dict[str, list[float]] = defaultdict(list)
    for fold in cv_results:
        for feat, imp in fold["feature_importance"].items():
            importance_accum[feat].append(imp)
    stable_importance = {
        feat: (float(np.mean(vals)), float(np.std(vals)))
        for feat, vals in importance_accum.items()
    }
    stable_importance = dict(sorted(stable_importance.items(), key=lambda x: -x[1][0]))

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    save_data = {
        "model": model,
        "calibrator": calibrator,
        "lgbm_model": lgbm_model,
        "catboost_model": cb_model,
        "meta_model": meta_model,
        "meta_model_names": meta_model_names,
        "version": 3,
    }
    with open(MODEL_DIR / "mlb_xgboost.pkl", "wb") as f:
        pickle.dump(save_data, f)

    results = {
        "train_seasons": train_seasons, "test_seasons": test_seasons,
        "train_samples": len(X_train), "total_samples": len(df),
        "n_features": len(FEATURE_COLS),
        "pitcher_data_pct": float(pitcher_pct),
        "cv_results": cv_results,
        "cv_mean_accuracy": float(np.mean(cv_accs)),
        "cv_std_accuracy": float(np.std(cv_accs)),
        "cv_mean_lift": float(np.mean(cv_lifts)),
        "cv_mean_bss": float(np.mean(cv_bss)),
        "cv_mean_conf_accuracy": float(np.mean(cv_confs)) if cv_confs else None,
        "ensemble_results": ens_results,
        "ensemble_summary": {
            "xgb_mean": float(np.mean(ens_xgb)),
            "pyth_mean": float(np.mean(ens_pyth)),
            "ens_mean": float(np.mean(ens_ens)),
            "xgb_conf_mean": float(np.mean(ens_xgb_conf)),
            "pyth_conf_mean": float(np.mean(ens_pyth_conf)),
            "ens_conf_mean": float(np.mean(ens_ens_conf)),
            "xgb_wins": xgb_wins, "pyth_wins": pyth_wins, "ens_wins": ens_wins,
        },
        "test_result": test_result,
        "feature_importance": stable_importance,
        "model_path": str(MODEL_DIR / "mlb_xgboost.pkl"),
        "calibrated": calibrate,
    }
    return results, model


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def load_mlb_model() -> tuple | None:
    """Load the v3 stacking model. Returns (xgb, calibrator, lgbm, catboost, meta, meta_names) or None."""
    path = MODEL_DIR / "mlb_xgboost.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        data = pickle.load(f)
    if isinstance(data, dict) and data.get("version", 1) >= 3:
        return (
            data["model"],
            data.get("calibrator"),
            data.get("lgbm_model"),
            data.get("catboost_model"),
            data.get("meta_model"),
            data.get("meta_model_names", ["xgb"]),
        )
    if isinstance(data, dict):
        return (data["model"], data.get("calibrator"), None, None, None, ["xgb"])
    return (data, None, None, None, None, ["xgb"])


def _build_feature_dict(home_stats: dict, away_stats: dict) -> dict:
    """Build feature dictionary from live stats for inference."""
    h_rs = home_stats.get("rs_g", 4.5)
    h_ra = home_stats.get("ra_g", 4.5)
    a_rs = away_stats.get("rs_g", 4.5)
    a_ra = away_stats.get("ra_g", 4.5)
    h_wp = home_stats.get("win_pct", 0.5)
    a_wp = away_stats.get("win_pct", 0.5)
    h_pyth = _pyth(h_rs, h_ra)
    a_pyth = _pyth(a_rs, a_ra)

    return {
        "home_rs_g": h_rs, "home_ra_g": h_ra, "home_pyth": h_pyth,
        "home_win_pct": h_wp, "home_games": home_stats.get("games", 30),
        "away_rs_g": a_rs, "away_ra_g": a_ra, "away_pyth": a_pyth,
        "away_win_pct": a_wp, "away_games": away_stats.get("games", 30),
        "rs_g_diff": h_rs - a_rs, "ra_g_diff": h_ra - a_ra,
        "pyth_diff": h_pyth - a_pyth, "win_pct_diff": h_wp - a_wp,
        "home_last10_pct": home_stats.get("last10_pct", 0.5),
        "away_last10_pct": away_stats.get("last10_pct", 0.5),
        "last10_diff": home_stats.get("last10_pct", 0.5) - away_stats.get("last10_pct", 0.5),
        "home_last5_pct": home_stats.get("last5_pct", 0.5),
        "away_last5_pct": away_stats.get("last5_pct", 0.5),
        "last5_diff": home_stats.get("last5_pct", 0.5) - away_stats.get("last5_pct", 0.5),
        "home_last20_pct": home_stats.get("last20_pct", 0.5),
        "away_last20_pct": away_stats.get("last20_pct", 0.5),
        "last20_diff": home_stats.get("last20_pct", 0.5) - away_stats.get("last20_pct", 0.5),
        "home_momentum": home_stats.get("momentum", 0.0),
        "away_momentum": away_stats.get("momentum", 0.0),
        "home_run_diff_g": h_rs - h_ra, "away_run_diff_g": a_rs - a_ra,
        "run_diff_g_diff": (h_rs - h_ra) - (a_rs - a_ra),
        "home_home_pct": home_stats.get("home_pct", 0.55),
        "away_away_pct": away_stats.get("away_pct", 0.45),
        "venue_pct_diff": home_stats.get("home_pct", 0.55) - away_stats.get("away_pct", 0.45),
        "home_rs_std": home_stats.get("rs_std", 2.0),
        "away_rs_std": away_stats.get("rs_std", 2.0),
        "season_progress": home_stats.get("season_progress", 0.5),
        "home_pyth_residual": h_wp - h_pyth,
        "away_pyth_residual": a_wp - a_pyth,
        "home_sp_era": home_stats.get("sp_era", 4.50),
        "away_sp_era": away_stats.get("sp_era", 4.50),
        "sp_era_diff": home_stats.get("sp_era", 4.50) - away_stats.get("sp_era", 4.50),
        "home_sp_k9": home_stats.get("sp_k9", 7.5),
        "away_sp_k9": away_stats.get("sp_k9", 7.5),
        "sp_k9_diff": home_stats.get("sp_k9", 7.5) - away_stats.get("sp_k9", 7.5),
        "home_sp_bb9": home_stats.get("sp_bb9", 3.5),
        "away_sp_bb9": away_stats.get("sp_bb9", 3.5),
        "home_sp_whip": home_stats.get("sp_whip", 1.35),
        "away_sp_whip": away_stats.get("sp_whip", 1.35),
        "sp_whip_diff": home_stats.get("sp_whip", 1.35) - away_stats.get("sp_whip", 1.35),
        "home_sp_ip": home_stats.get("sp_ip", 0.0),
        "away_sp_ip": away_stats.get("sp_ip", 0.0),
        "home_sp_era_vs_team": home_stats.get("sp_era_vs_team", 1.0),
        "away_sp_era_vs_team": away_stats.get("sp_era_vs_team", 1.0),
        "home_sp_fip_proxy": home_stats.get("sp_fip_proxy", 0.0),
        "away_sp_fip_proxy": away_stats.get("sp_fip_proxy", 0.0),
        "sp_fip_proxy_diff": home_stats.get("sp_fip_proxy", 0.0) - away_stats.get("sp_fip_proxy", 0.0),
        "has_pitcher_data": home_stats.get("has_pitcher_data", 0.0),
        # v3 features
        "home_elo": home_stats.get("elo", 1500.0),
        "away_elo": away_stats.get("elo", 1500.0),
        "elo_diff": home_stats.get("elo", 1500.0) - away_stats.get("elo", 1500.0),
        "home_rest_days": home_stats.get("rest_days", 1.0),
        "away_rest_days": away_stats.get("rest_days", 1.0),
        "rest_diff": home_stats.get("rest_days", 1.0) - away_stats.get("rest_days", 1.0),
        "home_bullpen_era": home_stats.get("bullpen_era", 4.20),
        "away_bullpen_era": away_stats.get("bullpen_era", 4.20),
        "bullpen_era_diff": home_stats.get("bullpen_era", 4.20) - away_stats.get("bullpen_era", 4.20),
        "travel_distance": home_stats.get("travel_distance", 0.0),
        # v4: park, weather, pitcher recent form
        "home_park_factor": home_stats.get("park_factor", 1.0),
        "park_is_outdoor": home_stats.get("park_is_outdoor", 1.0),
        "home_wind_mph": home_stats.get("wind_mph", 0.0),
        "wind_favor_sp": home_stats.get("wind_favor_sp", 0.0),
        "home_sp_era_l10": home_stats.get("sp_era_l10", 4.50),
        "away_sp_era_l10": away_stats.get("sp_era_l10", 4.50),
        "sp_era_l10_diff": home_stats.get("sp_era_l10", 4.50) - away_stats.get("sp_era_l10", 4.50),
        "home_sp_k9_l10": home_stats.get("sp_k9_l10", 7.5),
        "away_sp_k9_l10": away_stats.get("sp_k9_l10", 7.5),
        "home_sp_era_trend": home_stats.get("sp_era_trend", 0.0),
        "away_sp_era_trend": away_stats.get("sp_era_trend", 0.0),
        # v5: pitcher vs opponent splits + lineup quality
        "home_sp_era_vs_opp": home_stats.get("sp_era_vs_opp", home_stats.get("sp_era", 4.50)),
        "away_sp_era_vs_opp": away_stats.get("sp_era_vs_opp", away_stats.get("sp_era", 4.50)),
        "sp_era_vs_opp_diff": (
            home_stats.get("sp_era_vs_opp", home_stats.get("sp_era", 4.50)) -
            away_stats.get("sp_era_vs_opp", away_stats.get("sp_era", 4.50))
        ),
        "home_sp_k9_vs_opp": home_stats.get("sp_k9_vs_opp", home_stats.get("sp_k9", 7.5)),
        "away_sp_k9_vs_opp": away_stats.get("sp_k9_vs_opp", away_stats.get("sp_k9", 7.5)),
        "home_lineup_ops": home_stats.get("lineup_ops", 0.720),
        "away_lineup_ops": away_stats.get("lineup_ops", 0.720),
        "lineup_ops_diff": home_stats.get("lineup_ops", 0.720) - away_stats.get("lineup_ops", 0.720),
        # v6: batter vs pitcher historical matchup data
        "home_lineup_ops_vs_sp": home_stats.get("lineup_ops_vs_sp", home_stats.get("lineup_ops", 0.720)),
        "away_lineup_ops_vs_sp": away_stats.get("lineup_ops_vs_sp", away_stats.get("lineup_ops", 0.720)),
        "lineup_ops_vs_sp_diff": (
            home_stats.get("lineup_ops_vs_sp", home_stats.get("lineup_ops", 0.720)) -
            away_stats.get("lineup_ops_vs_sp", away_stats.get("lineup_ops", 0.720))
        ),
        "home_hr_threat_vs_sp": home_stats.get("hr_threat_vs_sp", 0.033),
        "away_hr_threat_vs_sp": away_stats.get("hr_threat_vs_sp", 0.033),
        "home_k_rate_vs_sp": home_stats.get("k_rate_vs_sp", 0.22),
        "away_k_rate_vs_sp": away_stats.get("k_rate_vs_sp", 0.22),
    }


def predict_with_xgboost(
    model: XGBClassifier,
    home_stats: dict,
    away_stats: dict,
    calibrator=None,
    lgbm_model=None,
    cb_model=None,
    meta_model=None,
) -> float:
    """Predict using the full stacking ensemble (XGB + LGBM + CatBoost + meta-learner)."""
    features = _build_feature_dict(home_stats, away_stats)
    X = pd.DataFrame([features])[FEATURE_COLS]

    if meta_model and (lgbm_model or cb_model):
        probs_list = [model.predict_proba(X)[0, 1]]
        if lgbm_model:
            probs_list.append(lgbm_model.predict_proba(X)[0, 1])
        if cb_model:
            probs_list.append(cb_model.predict_proba(X)[0, 1])
        meta_X = np.array([probs_list])
        raw_prob = meta_model.predict_proba(meta_X)[0, 1]
    else:
        raw_prob = model.predict_proba(X)[0, 1]

    if calibrator is not None:
        return float(calibrator.predict([raw_prob])[0])
    return float(raw_prob)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_training_results(results: dict) -> str:
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append("  MLB v3 — MULTI-MODEL STACKING + ELO + REST/BULLPEN/TRAVEL")
    lines.append(f"{'='*70}")

    lines.append(f"\n  Data: {results['total_samples']:,} games, "
                 f"{results['n_features']} features, "
                 f"{results.get('pitcher_data_pct', 0):.0%} with pitcher data")

    lines.append(f"\n  {'─'*50}")
    lines.append(f"  WALK-FORWARD CV (Stacking: XGB + LGBM + CatBoost)")
    lines.append(f"  {'─'*50}")
    lines.append(f"  Mean accuracy:     {results['cv_mean_accuracy']:.1%} +/- {results['cv_std_accuracy']:.1%}")
    lines.append(f"  Mean lift vs home: {results['cv_mean_lift']:+.1%}")
    lines.append(f"  Mean Brier skill:  {results['cv_mean_bss']:+.3f}")
    if results.get("cv_mean_conf_accuracy"):
        lines.append(f"  Mean conf acc:     {results['cv_mean_conf_accuracy']:.1%}")
    positive = sum(1 for r in results["cv_results"] if r["lift"] > 0)
    lines.append(f"  Positive folds:    {positive}/{len(results['cv_results'])}")

    es = results.get("ensemble_summary", {})
    if es:
        lines.append(f"\n  {'─'*50}")
        lines.append(f"  ENSEMBLE COMPARISON (Pythagorean vs XGBoost vs Combined)")
        lines.append(f"  {'─'*50}")
        lines.append(f"  {'Model':<16} {'Accuracy':>10} {'Conf Acc':>10} {'Seasons Won':>12}")
        lines.append(f"  {'─'*50}")
        lines.append(f"  {'Pythagorean':<16} {es['pyth_mean']:>10.1%} {es['pyth_conf_mean']:>10.1%} {es['pyth_wins']:>12}")
        lines.append(f"  {'XGBoost':<16} {es['xgb_mean']:>10.1%} {es['xgb_conf_mean']:>10.1%} {es['xgb_wins']:>12}")
        lines.append(f"  {'Ensemble':<16} {es['ens_mean']:>10.1%} {es['ens_conf_mean']:>10.1%} {es['ens_wins']:>12}")

    tr = results.get("test_result")
    if tr:
        lines.append(f"\n  {'─'*50}")
        lines.append(f"  HELD-OUT TEST: {results['test_seasons']}")
        lines.append(f"  {'─'*50}")
        lines.append(f"  Accuracy:        {tr['accuracy']:.1%}")
        lines.append(f"  Home baseline:   {tr['home_baseline']:.1%}")
        lines.append(f"  Lift:            {tr['lift']:+.1%}")
        lines.append(f"  Brier (raw):     {tr['brier_raw']:.4f}")
        if tr["confident_n"] > 0:
            lines.append(f"  High-confidence: {tr['confident_accuracy']:.1%} ({tr['confident_n']} games)")

    lines.append(f"\n  Top features:")
    for feat, (mean, std) in list(results["feature_importance"].items())[:12]:
        lines.append(f"    {feat:25s} {mean:.3f} +/- {std:.3f}")

    lines.append(f"\n  {'='*50}")
    cv_acc = results["cv_mean_accuracy"]
    cv_bss = results["cv_mean_bss"]
    if cv_bss > 0.02 and cv_acc >= 0.56:
        lines.append("  VERDICT: STRONG EDGE")
    elif cv_bss > 0 and cv_acc >= 0.54:
        lines.append("  VERDICT: REAL EDGE")
    elif positive >= len(results["cv_results"]) * 0.6:
        lines.append("  VERDICT: MARGINAL EDGE")
    else:
        lines.append("  VERDICT: NO EDGE")
    lines.append(f"  {'='*50}\n")
    return "\n".join(lines)

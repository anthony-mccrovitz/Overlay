"""
MLB pitcher strikeout prediction model.

Predicts a starting pitcher's strikeout total for a given game using:
  - Pitcher K/9, BB/9, average innings pitched
  - Opposing team's strikeout rate (K% as batters)
  - Historical pitcher K totals from game logs

Used to find edges against pitcher_strikeouts prop lines.
"""
from __future__ import annotations

import csv
import io
import json
import pickle
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from xgboost import XGBRegressor

from src.data.mlb_stats import _cached_get, API_BASE

MODEL_PATH = Path("models/mlb_pitcher_ks.pkl")

KS_FEATURES = [
    "pitcher_k9",
    "pitcher_bb9",
    "pitcher_avg_ip",
    "pitcher_era",
    "pitcher_whip",
    "pitcher_starts",
    "pitcher_recent_k_avg",
    "opp_team_k_rate",
    "opp_team_k_per_game",
    "is_home",
    "season_progress",
    "l5_k_per_ip",
    "k_rate_divergence_pct",
    "stuff_plus",
]

_STUFF_PLUS_URL = (
    "https://baseballsavant.mlb.com/leaderboard/custom"
    "?year={season}&type=pitcher&filter=&sort=stuff_plus_avg&sortDir=desc"
    "&min=50&selections=stuff_plus_avg&chart=false&x=stuff_plus_avg"
    "&y=stuff_plus_avg&r=no&chartType=beeswarm&csv=true"
)
_CACHE_DIR = Path("data/cache")


def _fetch_stuff_plus(season: int, refresh: bool = False) -> dict[int, float]:
    """
    Fetch Baseball Savant Stuff+ for a season.

    Returns dict mapping MLBAM pitcher ID -> stuff_plus value.
    Caches result at data/cache/stuff_plus_{season}.json for 24h.
    Returns {} silently on any error.
    """
    cache_path = _CACHE_DIR / f"stuff_plus_{season}.json"

    if not refresh and cache_path.exists():
        age_s = time.time() - cache_path.stat().st_mtime
        if age_s < 86400:
            try:
                with open(cache_path) as f:
                    raw = json.load(f)
                return {int(k): float(v) for k, v in raw.items()}
            except Exception:
                pass

    try:
        url = _STUFF_PLUS_URL.format(season=season)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")

        result: dict[int, float] = {}
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            pid_raw = row.get("player_id") or row.get("pitcher_id") or ""
            # Try multiple possible column names for stuff+
            sp_raw = (
                row.get("stuff_plus_avg")
                or row.get("stuff_plus")
                or row.get("Stuff+")
                or ""
            )
            if not pid_raw or not sp_raw:
                continue
            try:
                result[int(pid_raw)] = float(sp_raw)
            except (ValueError, TypeError):
                continue

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump({str(k): v for k, v in result.items()}, f)

        return result
    except Exception:
        return {}


def _fetch_pitcher_game_logs(pitcher_id: int, season: int) -> list[dict]:
    """Fetch a pitcher's game-by-game stats for a season."""
    try:
        data = _cached_get(
            f"pitcher_gamelog_{pitcher_id}_{season}",
            f"{API_BASE}/people/{pitcher_id}/stats",
            {"stats": "gameLog", "group": "pitching", "season": season},
            max_age_s=86400 * 7,
        )
    except Exception:
        return []

    logs = []
    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            s = split.get("stat", {})
            ip_str = s.get("inningsPitched", "0")
            try:
                ip = float(ip_str)
            except (ValueError, TypeError):
                ip = 0

            if ip < 1.0:
                continue

            opp = split.get("opponent", {})
            logs.append({
                "date": split.get("date", ""),
                "opponent_id": opp.get("id"),
                "opponent_name": opp.get("name", ""),
                "innings_pitched": ip,
                "strikeouts": int(s.get("strikeOuts", 0)),
                "walks": int(s.get("baseOnBalls", 0)),
                "hits": int(s.get("hits", 0)),
                "earned_runs": int(s.get("earnedRuns", 0)),
                "is_home": split.get("isHome", False),
                "game_pk": split.get("game", {}).get("gamePk"),
            })

    return logs


def _fetch_team_batting_krate(season: int) -> dict[int, float]:
    """Fetch team-level batting strikeout rate (K%) for each team."""
    try:
        data = _cached_get(
            f"team_batting_k_{season}",
            f"{API_BASE}/teams/stats",
            {"stats": "season", "group": "hitting", "season": season, "sportIds": 1},
            max_age_s=86400,
        )
    except Exception:
        return {}

    rates = {}
    for stat_group in data.get("stats", []):
        for split in stat_group.get("splits", []):
            tid = split.get("team", {}).get("id")
            if not tid:
                continue
            s = split.get("stat", {})
            ab = float(s.get("atBats", 0) or 0)
            so = float(s.get("strikeOuts", 0) or 0)
            gp = float(s.get("gamesPlayed", 1) or 1)
            if ab > 0:
                rates[tid] = so / ab
    return rates


def build_ks_training_data(
    seasons: list[int] | None = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Build training data for pitcher K prediction from game logs.

    For each start, features are computed from *prior* games only
    (no lookahead).
    """
    if seasons is None:
        seasons = list(range(2019, 2026))

    all_rows = []

    for season in seasons:
        if verbose:
            print(f"  Processing {season} pitcher logs...")

        team_krates = _fetch_team_batting_krate(season)

        # Get all starters from the season schedule
        try:
            sched_data = _cached_get(
                f"schedule_full_{season}",
                f"{API_BASE}/schedule",
                {
                    "sportId": 1,
                    "startDate": f"{season}-03-20",
                    "endDate": f"{season}-10-05",
                    "gameType": "R",
                    "hydrate": "probablePitcher",
                },
                max_age_s=86400 * 7,
            )
        except Exception:
            continue

        pitcher_ids = set()
        game_pitchers = []

        for date_entry in sched_data.get("dates", []):
            for game in date_entry.get("games", []):
                state = game.get("status", {}).get("abstractGameState", "")
                if state != "Final":
                    continue
                for side in ["home", "away"]:
                    info = game.get("teams", {}).get(side, {})
                    pp = info.get("probablePitcher", {})
                    if pp.get("id"):
                        pitcher_ids.add(pp["id"])
                        opp_side = "away" if side == "home" else "home"
                        opp_id = game.get("teams", {}).get(opp_side, {}).get("team", {}).get("id")
                        game_pitchers.append({
                            "pitcher_id": pp["id"],
                            "game_pk": game.get("gamePk"),
                            "date": game.get("gameDate", "")[:10],
                            "is_home": side == "home",
                            "opp_team_id": opp_id,
                        })

        # Fetch game logs for each pitcher
        pitcher_logs: dict[int, list[dict]] = {}
        for pid in pitcher_ids:
            logs = _fetch_pitcher_game_logs(pid, season)
            if logs:
                pitcher_logs[pid] = sorted(logs, key=lambda x: x["date"])

        # Build training rows with walk-forward features
        for gp in game_pitchers:
            pid = gp["pitcher_id"]
            logs = pitcher_logs.get(pid, [])
            if not logs:
                continue

            # Find this game in logs
            game_log = None
            prior_logs = []
            for log in logs:
                if log["game_pk"] == gp["game_pk"]:
                    game_log = log
                    break
                prior_logs.append(log)

            if game_log is None or len(prior_logs) < 3:
                continue

            total_ip = sum(l["innings_pitched"] for l in prior_logs)
            total_k = sum(l["strikeouts"] for l in prior_logs)
            total_bb = sum(l["walks"] for l in prior_logs)
            total_h = sum(l["hits"] for l in prior_logs)
            total_er = sum(l["earned_runs"] for l in prior_logs)
            n_starts = len(prior_logs)

            ip_adj = max(total_ip, 1)
            k9 = total_k / ip_adj * 9
            bb9 = total_bb / ip_adj * 9
            era = total_er / ip_adj * 9
            whip = (total_bb + total_h) / ip_adj
            avg_ip = total_ip / n_starts

            recent = prior_logs[-5:]
            recent_k_avg = np.mean([l["strikeouts"] for l in recent]) if recent else total_k / max(n_starts, 1)

            opp_id = gp["opp_team_id"]
            opp_krate = team_krates.get(opp_id, 0.22)

            # K per game for opponent
            opp_k_per_game = opp_krate * 36  # ~36 AB per game

            game_month = int(gp["date"][5:7]) if len(gp["date"]) >= 7 else 6
            sp = max(0, min(1, (game_month - 3) / 7.0))

            all_rows.append({
                "season": season,
                "pitcher_id": pid,
                "game_pk": gp["game_pk"],
                "actual_ks": game_log["strikeouts"],
                "actual_ip": game_log["innings_pitched"],
                "pitcher_k9": k9,
                "pitcher_bb9": bb9,
                "pitcher_avg_ip": avg_ip,
                "pitcher_era": era,
                "pitcher_whip": whip,
                "pitcher_starts": n_starts,
                "pitcher_recent_k_avg": recent_k_avg,
                "opp_team_k_rate": opp_krate,
                "opp_team_k_per_game": opp_k_per_game,
                "is_home": int(gp["is_home"]),
                "season_progress": sp,
            })

    if not all_rows:
        return pd.DataFrame()

    return pd.DataFrame(all_rows)


def train_pitcher_ks_model(
    seasons: list[int] | None = None,
    test_seasons: list[int] | None = None,
    verbose: bool = True,
) -> dict:
    """Train pitcher strikeout prediction model."""
    if seasons is None:
        seasons = list(range(2019, 2026))
    if test_seasons is None:
        test_seasons = [seasons[-1]]
    train_seasons = [s for s in seasons if s not in test_seasons]

    df = build_ks_training_data(seasons, verbose=verbose)
    if df.empty:
        return {}

    train_mask = df["season"].isin(train_seasons)
    test_mask = df["season"].isin(test_seasons)

    X_train = df.loc[train_mask, KS_FEATURES].fillna(0)
    y_train = df.loc[train_mask, "actual_ks"]
    X_test = df.loc[test_mask, KS_FEATURES].fillna(0)
    y_test = df.loc[test_mask, "actual_ks"]

    if verbose:
        print(f"\n  Train: {len(X_train)} starts, Test: {len(X_test)} starts")
        print(f"  Train mean Ks: {y_train.mean():.2f}, Test mean Ks: {y_test.mean():.2f}")

    model = XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=15,
        reg_alpha=0.3,
        reg_lambda=1.0,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train, y_train)

    train_pred = model.predict(X_train)
    test_pred = model.predict(X_test)

    train_mae = np.mean(np.abs(train_pred - y_train))
    test_mae = np.mean(np.abs(test_pred - y_test))
    baseline_mae = np.mean(np.abs(y_train.mean() - y_test))

    # Direction accuracy: does model predict higher/lower than actual?
    # (Actual game lines unavailable in training data — this measures whether the
    # model's direction vs the season mean matches the actual outcome direction.)
    ou_correct = np.mean((test_pred > y_train.mean()) == (y_test.values > y_train.mean()))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({
            "model": model,
            "features": KS_FEATURES,
        }, f)

    results = {
        "train_mae": train_mae,
        "test_mae": test_mae,
        "baseline_mae": baseline_mae,
        "ou_accuracy": ou_correct,
        "train_size": len(X_train),
        "test_size": len(X_test),
    }

    if verbose:
        print(f"\n  {'='*50}")
        print(f"  PITCHER STRIKEOUT MODEL RESULTS")
        print(f"  {'='*50}")
        print(f"  Train MAE: {train_mae:.2f} Ks")
        print(f"  Test  MAE: {test_mae:.2f} Ks")
        print(f"  Baseline MAE: {baseline_mae:.2f} Ks")
        print(f"  O/U Accuracy: {ou_correct:.1%}")
        print(f"  Model saved to {MODEL_PATH}")
        print(f"  {'='*50}\n")

    return results


def load_pitcher_ks_model() -> tuple | None:
    """Returns (model, features) or None."""
    if not MODEL_PATH.exists():
        return None
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    return data["model"], data["features"]


def predict_pitcher_ks(
    pitcher_k9: float = 8.0,
    pitcher_bb9: float = 3.0,
    pitcher_avg_ip: float = 5.5,
    pitcher_era: float = 4.0,
    pitcher_whip: float = 1.3,
    pitcher_starts: int = 10,
    pitcher_recent_k_avg: float = 5.5,
    opp_team_k_rate: float = 0.22,
    is_home: bool = True,
    # New params:
    l5_k_per_ip: float | None = None,   # K/IP last 5 starts; None = use season rate
    stuff_plus: float = 100.0,          # 100 = average stuff
) -> float:
    """Predict pitcher's strikeout total for a game."""
    season_k_per_ip = pitcher_k9 / 9
    if l5_k_per_ip is None:
        l5_k_per_ip = season_k_per_ip
    k_rate_divergence_pct = (
        (l5_k_per_ip - season_k_per_ip) / max(season_k_per_ip, 0.001) * 100
    )

    loaded = load_pitcher_ks_model()
    if loaded is None:
        return pitcher_k9 / 9 * pitcher_avg_ip * (stuff_plus / 100) ** 0.3

    model, features = loaded

    row = {
        "pitcher_k9": pitcher_k9,
        "pitcher_bb9": pitcher_bb9,
        "pitcher_avg_ip": pitcher_avg_ip,
        "pitcher_era": pitcher_era,
        "pitcher_whip": pitcher_whip,
        "pitcher_starts": pitcher_starts,
        "pitcher_recent_k_avg": pitcher_recent_k_avg,
        "opp_team_k_rate": opp_team_k_rate,
        "opp_team_k_per_game": opp_team_k_rate * 36,
        "is_home": int(is_home),
        "season_progress": 0.5,
        "l5_k_per_ip": l5_k_per_ip,
        "k_rate_divergence_pct": k_rate_divergence_pct,
        "stuff_plus": stuff_plus,
    }

    X = pd.DataFrame([row])[features].fillna(0)
    return float(model.predict(X)[0])


def find_pitcher_ks_edges(
    game_props: list[dict],
    min_edge_pct: float = 10.0,
) -> list[dict]:
    """
    Find pitcher K prop edges from a list of game prop dicts.

    Each dict in game_props must have:
      pitcher_id (int), pitcher_name (str), team (str), opponent (str),
      line (float), odds (int), book (str),
      pitcher_k9 (float), pitcher_avg_ip (float), opp_team_k_rate (float),
      [optional] pitcher_recent_k_avg, pitcher_bb9, pitcher_era, pitcher_whip,
                 pitcher_starts, is_home, l5_k_per_ip

    Returns list of edge dicts with model_tier="tier2", filtered to:
      - edge_pct >= min_edge_pct (default 10%)
      - implied prob between 30% and 70% (no longshots, no heavy favorites)
    """
    stuff_map = _fetch_stuff_plus(datetime.now().year)

    edges = []
    for g in game_props:
        pitcher_id = g.get("pitcher_id", 0)
        stuff_plus = stuff_map.get(pitcher_id, 100.0)

        projected = predict_pitcher_ks(
            pitcher_k9=g.get("pitcher_k9", 8.0),
            pitcher_bb9=g.get("pitcher_bb9", 3.0),
            pitcher_avg_ip=g.get("pitcher_avg_ip", 5.5),
            pitcher_era=g.get("pitcher_era", 4.0),
            pitcher_whip=g.get("pitcher_whip", 1.3),
            pitcher_starts=g.get("pitcher_starts", 10),
            pitcher_recent_k_avg=g.get("pitcher_recent_k_avg", 5.5),
            opp_team_k_rate=g.get("opp_team_k_rate", 0.22),
            is_home=g.get("is_home", True),
            l5_k_per_ip=g.get("l5_k_per_ip", None),
            stuff_plus=stuff_plus,
        )

        line = float(g["line"])
        odds = int(g["odds"])
        sigma = 1.8

        # Over/under probabilities using Normal distribution
        over_prob = float(1 - norm.cdf(line, loc=projected, scale=sigma))
        under_prob = float(norm.cdf(line, loc=projected, scale=sigma))

        # Implied probability from American odds
        if odds > 0:
            implied_prob = 100 / (odds + 100)
        else:
            implied_prob = abs(odds) / (abs(odds) + 100)

        for direction, model_prob in [("OVER", over_prob), ("UNDER", under_prob)]:
            edge_pct = (model_prob - implied_prob) * 100
            if edge_pct >= min_edge_pct and 0.30 <= implied_prob <= 0.70:
                edges.append({
                    "player": g.get("pitcher_name", ""),
                    "team": g.get("team", ""),
                    "opponent": g.get("opponent", ""),
                    "market": "pitcher_strikeouts",
                    "line": line,
                    "direction": direction,
                    "projected": round(projected, 2),
                    "model_prob": round(model_prob, 4),
                    "implied_prob": round(implied_prob, 4),
                    "edge_pct": round(edge_pct, 2),
                    "odds": odds,
                    "book": g.get("book", ""),
                    "model_tier": "tier2",
                })

    return edges

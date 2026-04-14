"""
MLB batter prop prediction models.

Multi-output models for predicting per-game batting outcomes:
  - Hits
  - Total bases
  - Home runs
  - RBIs
  - Runs scored

Uses batter season stats, recent performance, opposing pitcher quality,
and platoon matchup information.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from src.data.mlb_stats import _cached_get, API_BASE, _safe_float

MODEL_PATH = Path("models/mlb_batter_props.pkl")

PROP_TARGETS = ["hits", "total_bases", "home_runs", "rbis", "runs"]

BATTER_FEATURES = [
    "batter_avg",
    "batter_obp",
    "batter_slg",
    "batter_ops",
    "batter_k_rate",
    "batter_hits_per_game",
    "batter_tb_per_game",
    "batter_hr_per_game",
    "batter_rbi_per_game",
    "batter_runs_per_game",
    "batter_games",
    "batter_recent_hits_avg",
    "batter_recent_tb_avg",
    "opp_pitcher_era",
    "opp_pitcher_whip",
    "opp_pitcher_k9",
    "opp_pitcher_bb9",
    "batting_order",
    "is_home",
]


def _fetch_batter_game_logs(player_id: int, season: int) -> list[dict]:
    """Fetch batter game logs for a season."""
    try:
        data = _cached_get(
            f"batter_gamelog_{player_id}_{season}",
            f"{API_BASE}/people/{player_id}/stats",
            {"stats": "gameLog", "group": "hitting", "season": season},
            max_age_s=86400 * 3,
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
            tb = hits + doubles + 2 * triples + 3 * hrs

            opp = split.get("opponent", {})
            logs.append({
                "date": split.get("date", ""),
                "at_bats": ab,
                "hits": hits,
                "doubles": doubles,
                "triples": triples,
                "home_runs": hrs,
                "total_bases": tb,
                "rbis": int(_safe_float(s.get("rbi"), 0)),
                "runs": int(_safe_float(s.get("runs"), 0)),
                "strikeouts": int(_safe_float(s.get("strikeOuts"), 0)),
                "walks": int(_safe_float(s.get("baseOnBalls"), 0)),
                "opponent_id": opp.get("id"),
                "is_home": split.get("isHome", False),
                "game_pk": split.get("game", {}).get("gamePk"),
            })

    return sorted(logs, key=lambda x: x["date"])


def build_batter_training_data(
    seasons: list[int] | None = None,
    min_prior_games: int = 20,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Build training data from batter game logs.

    For each game appearance with sufficient prior data, compute
    walk-forward features and record actual outcomes.
    """
    if seasons is None:
        seasons = list(range(2021, 2026))

    all_rows = []

    for season in seasons:
        if verbose:
            print(f"  Building batter prop data for {season}...")

        # Get all games from this season schedule
        try:
            sched = _cached_get(
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

        # Collect all pitcher IDs with their game appearances
        game_pitchers: dict[int, dict] = {}
        for date_entry in sched.get("dates", []):
            for game in date_entry.get("games", []):
                state = game.get("status", {}).get("abstractGameState", "")
                if state != "Final":
                    continue
                gpk = game.get("gamePk")
                for side in ["home", "away"]:
                    pp = game.get("teams", {}).get(side, {}).get("probablePitcher", {})
                    if pp.get("id"):
                        game_pitchers[gpk] = game_pitchers.get(gpk, {})
                        game_pitchers[gpk][side] = {
                            "pitcher_id": pp["id"],
                            "pitcher_name": pp.get("fullName", ""),
                        }

        # Sample qualifying batters from rosters
        team_ids = set()
        for date_entry in sched.get("dates", []):
            for game in date_entry.get("games", []):
                for side in ["home", "away"]:
                    tid = game.get("teams", {}).get(side, {}).get("team", {}).get("id")
                    if tid:
                        team_ids.add(tid)

        # Get rosters and fetch game logs for position players
        batter_ids = set()
        for tid in list(team_ids)[:30]:  # limit to avoid excessive API calls
            try:
                roster_data = _cached_get(
                    f"roster_{tid}_{season}",
                    f"{API_BASE}/teams/{tid}/roster",
                    {"rosterType": "active", "season": season},
                    max_age_s=86400 * 7,
                )
            except Exception:
                continue

            for entry in roster_data.get("roster", []):
                pos_type = entry.get("position", {}).get("type", "")
                if pos_type in ("Hitter", "Outfielder", "Infielder"):
                    pid = entry.get("person", {}).get("id")
                    if pid:
                        batter_ids.add(pid)

        # Limit to avoid excessive API calls during training
        batter_ids = list(batter_ids)[:200]

        if verbose:
            print(f"    Processing {len(batter_ids)} batters...")

        # Fetch pitcher stats cache
        pitcher_cache: dict[int, dict] = {}

        def _get_pitcher_stats(pid: int) -> dict:
            if pid in pitcher_cache:
                return pitcher_cache[pid]
            try:
                pdata = _cached_get(
                    f"pitcher_{pid}_{season}",
                    f"{API_BASE}/people/{pid}/stats",
                    {"stats": "season", "group": "pitching", "season": season},
                    max_age_s=86400 * 7,
                )
                for sg in pdata.get("stats", []):
                    for sp in sg.get("splits", []):
                        s = sp.get("stat", {})
                        ip = max(_safe_float(s.get("inningsPitched"), 1), 1)
                        k = _safe_float(s.get("strikeOuts"), 0)
                        bb = _safe_float(s.get("baseOnBalls"), 0)
                        result = {
                            "era": _safe_float(s.get("era"), 4.5),
                            "whip": _safe_float(s.get("whip"), 1.3),
                            "k9": k / ip * 9,
                            "bb9": bb / ip * 9,
                        }
                        pitcher_cache[pid] = result
                        return result
            except Exception:
                pass
            default = {"era": 4.5, "whip": 1.3, "k9": 8.0, "bb9": 3.0}
            pitcher_cache[pid] = default
            return default

        for batter_id in batter_ids:
            logs = _fetch_batter_game_logs(batter_id, season)
            if len(logs) < min_prior_games + 5:
                continue

            for i in range(min_prior_games, len(logs)):
                prior = logs[:i]
                current = logs[i]

                total_ab = sum(l["at_bats"] for l in prior)
                total_hits = sum(l["hits"] for l in prior)
                total_tb = sum(l["total_bases"] for l in prior)
                total_hr = sum(l["home_runs"] for l in prior)
                total_rbi = sum(l["rbis"] for l in prior)
                total_runs = sum(l["runs"] for l in prior)
                total_k = sum(l["strikeouts"] for l in prior)
                n_games = len(prior)

                recent = prior[-10:]
                recent_hits_avg = np.mean([l["hits"] for l in recent]) if recent else total_hits / max(n_games, 1)
                recent_tb_avg = np.mean([l["total_bases"] for l in recent]) if recent else total_tb / max(n_games, 1)

                avg = total_hits / max(total_ab, 1)
                slg = total_tb / max(total_ab, 1)
                total_walks = sum(l["walks"] for l in prior)
                obp = (total_hits + total_walks) / max(total_ab + total_walks, 1)

                # Get opposing pitcher stats
                gpk = current.get("game_pk")
                gp_info = game_pitchers.get(gpk, {})
                opp_side = "away" if current.get("is_home") else "home"
                opp_pitcher_info = gp_info.get(opp_side, {})
                opp_pid = opp_pitcher_info.get("pitcher_id")
                opp_stats = _get_pitcher_stats(opp_pid) if opp_pid else {"era": 4.5, "whip": 1.3, "k9": 8.0, "bb9": 3.0}

                row = {
                    "season": season,
                    "batter_id": batter_id,
                    "game_pk": gpk,
                    "batter_avg": avg,
                    "batter_obp": obp,
                    "batter_slg": slg,
                    "batter_ops": obp + slg,
                    "batter_k_rate": total_k / max(total_ab, 1),
                    "batter_hits_per_game": total_hits / max(n_games, 1),
                    "batter_tb_per_game": total_tb / max(n_games, 1),
                    "batter_hr_per_game": total_hr / max(n_games, 1),
                    "batter_rbi_per_game": total_rbi / max(n_games, 1),
                    "batter_runs_per_game": total_runs / max(n_games, 1),
                    "batter_games": n_games,
                    "batter_recent_hits_avg": recent_hits_avg,
                    "batter_recent_tb_avg": recent_tb_avg,
                    "opp_pitcher_era": opp_stats["era"],
                    "opp_pitcher_whip": opp_stats["whip"],
                    "opp_pitcher_k9": opp_stats["k9"],
                    "opp_pitcher_bb9": opp_stats["bb9"],
                    "batting_order": 5,  # default; real data hard to get historically
                    "is_home": int(current.get("is_home", False)),
                    # Targets
                    "actual_hits": current["hits"],
                    "actual_total_bases": current["total_bases"],
                    "actual_home_runs": current["home_runs"],
                    "actual_rbis": current["rbis"],
                    "actual_runs": current["runs"],
                }
                all_rows.append(row)

    if not all_rows:
        return pd.DataFrame()

    if verbose:
        print(f"  Total training rows: {len(all_rows)}")
    return pd.DataFrame(all_rows)


def train_batter_props_model(
    seasons: list[int] | None = None,
    test_seasons: list[int] | None = None,
    verbose: bool = True,
) -> dict:
    """Train multi-output batter props models (one XGBRegressor per prop)."""
    if seasons is None:
        seasons = list(range(2021, 2026))
    if test_seasons is None:
        test_seasons = [seasons[-1]]
    train_seasons = [s for s in seasons if s not in test_seasons]

    df = build_batter_training_data(seasons, verbose=verbose)
    if df.empty:
        return {}

    train_mask = df["season"].isin(train_seasons)
    test_mask = df["season"].isin(test_seasons)

    models = {}
    results = {}

    for target in PROP_TARGETS:
        actual_col = f"actual_{target}"
        if actual_col not in df.columns:
            continue

        X_train = df.loc[train_mask, BATTER_FEATURES].fillna(0)
        y_train = df.loc[train_mask, actual_col]
        X_test = df.loc[test_mask, BATTER_FEATURES].fillna(0)
        y_test = df.loc[test_mask, actual_col]

        if verbose:
            print(f"\n  Training {target} model ({len(X_train)} train, {len(X_test)} test)...")

        model = XGBRegressor(
            n_estimators=150,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=20,
            reg_alpha=0.5,
            reg_lambda=1.0,
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train, y_train)
        models[target] = model

        test_pred = model.predict(X_test)
        train_pred = model.predict(X_train)

        test_mae = np.mean(np.abs(test_pred - y_test))
        baseline_mae = np.mean(np.abs(y_train.mean() - y_test))
        train_mae = np.mean(np.abs(train_pred - y_train))

        results[target] = {
            "test_mae": float(test_mae),
            "train_mae": float(train_mae),
            "baseline_mae": float(baseline_mae),
            "test_mean": float(y_test.mean()),
            "lift": float(baseline_mae - test_mae),
        }

        if verbose:
            print(f"    {target}: MAE={test_mae:.3f} (baseline={baseline_mae:.3f}, lift={baseline_mae-test_mae:.3f})")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({
            "models": models,
            "features": BATTER_FEATURES,
            "targets": PROP_TARGETS,
        }, f)

    if verbose:
        print(f"\n  Models saved to {MODEL_PATH}")

    return results


def load_batter_props_model() -> tuple | None:
    """Returns (models_dict, features, targets) or None."""
    if not MODEL_PATH.exists():
        return None
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    return data["models"], data["features"], data["targets"]


def predict_batter_props(
    batter_avg: float = 0.260,
    batter_obp: float = 0.330,
    batter_slg: float = 0.420,
    batter_k_rate: float = 0.22,
    batter_games: int = 50,
    batter_hits_per_game: float = 1.0,
    batter_tb_per_game: float = 1.5,
    batter_hr_per_game: float = 0.05,
    batter_rbi_per_game: float = 0.4,
    batter_runs_per_game: float = 0.4,
    batter_recent_hits_avg: float = 1.0,
    batter_recent_tb_avg: float = 1.5,
    opp_pitcher_era: float = 4.0,
    opp_pitcher_whip: float = 1.3,
    opp_pitcher_k9: float = 8.0,
    opp_pitcher_bb9: float = 3.0,
    batting_order: int = 5,
    is_home: bool = True,
) -> dict[str, float]:
    """
    Predict all prop values for a single batter game appearance.

    Returns dict with predicted values for each prop target.
    """
    loaded = load_batter_props_model()
    if loaded is None:
        return {
            "hits": batter_hits_per_game,
            "total_bases": batter_tb_per_game,
            "home_runs": batter_hr_per_game,
            "rbis": batter_rbi_per_game,
            "runs": batter_runs_per_game,
        }

    models, features, targets = loaded

    row = {
        "batter_avg": batter_avg,
        "batter_obp": batter_obp,
        "batter_slg": batter_slg,
        "batter_ops": batter_obp + batter_slg,
        "batter_k_rate": batter_k_rate,
        "batter_hits_per_game": batter_hits_per_game,
        "batter_tb_per_game": batter_tb_per_game,
        "batter_hr_per_game": batter_hr_per_game,
        "batter_rbi_per_game": batter_rbi_per_game,
        "batter_runs_per_game": batter_runs_per_game,
        "batter_games": batter_games,
        "batter_recent_hits_avg": batter_recent_hits_avg,
        "batter_recent_tb_avg": batter_recent_tb_avg,
        "opp_pitcher_era": opp_pitcher_era,
        "opp_pitcher_whip": opp_pitcher_whip,
        "opp_pitcher_k9": opp_pitcher_k9,
        "opp_pitcher_bb9": opp_pitcher_bb9,
        "batting_order": batting_order,
        "is_home": int(is_home),
    }

    X = pd.DataFrame([row])[features].fillna(0)
    predictions = {}
    for target in targets:
        if target in models:
            predictions[target] = float(models[target].predict(X)[0])
        else:
            predictions[target] = 0.0

    return predictions

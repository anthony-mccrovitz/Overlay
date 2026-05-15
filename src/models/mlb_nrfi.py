"""
NRFI (No Run First Inning) prediction model.

Predicts the probability that both teams score 0 runs in the first inning.
Uses pitcher first-inning ERA, team first-inning scoring rates, and
general pitcher quality metrics.

Historical NRFI rate is ~57-60% in MLB, so the baseline is already >50%.
Edge comes from identifying matchups where pitcher quality significantly
shifts the probability.
"""
from __future__ import annotations

import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

MODEL_PATH = Path("models/mlb_nrfi.pkl")

NRFI_FEATURES = [
    "home_sp_1st_era",
    "away_sp_1st_era",
    "home_sp_era",
    "away_sp_era",
    "home_sp_k9",
    "away_sp_k9",
    "home_sp_bb9",
    "away_sp_bb9",
    "home_sp_whip",
    "away_sp_whip",
    "home_team_1st_scoring_rate",
    "away_team_1st_scoring_rate",
    "home_sp_1st_games",
    "away_sp_1st_games",
    "season_progress",
]


def train_nrfi_model(
    seasons: list[int] | None = None,
    test_seasons: list[int] | None = None,
    verbose: bool = True,
) -> dict:
    """
    Train NRFI prediction model using linescore data.

    We use walk-forward: train on seasons[:-1], test on last season.
    """
    from src.data.mlb_linescore import fetch_season_linescores
    from src.models.mlb_xgboost import _fetch_season_games

    if seasons is None:
        seasons = list(range(2019, 2026))
    if test_seasons is None:
        test_seasons = [seasons[-1]]
    train_seasons = [s for s in seasons if s not in test_seasons]

    if verbose:
        print("\n  Building NRFI training data...")

    # Build cumulative first-inning stats per pitcher and team
    pitcher_1st: dict[int, dict] = defaultdict(lambda: {"runs": 0, "games": 0})
    team_1st: dict[int, dict] = defaultdict(lambda: {"runs": 0, "games": 0})

    all_rows = []

    for season in seasons:
        if verbose:
            print(f"  Processing {season}...")

        games = fetch_season_linescores(season, verbose=False)

        # Build walk-forward per-pitcher cumulative stats from game logs.
        # Keyed by pitcher_id; accumulate IP, ER, K, BB, H as games are processed.
        pitcher_cumul: dict[int, dict] = defaultdict(lambda: {
            "ip": 0.0, "er": 0, "k": 0, "bb": 0, "h": 0, "starts": 0,
        })

        # Pre-fetch pitcher game logs for all pitchers seen this season so we
        # can build cumulative stats game-by-game (no lookahead).
        reg_games = _fetch_season_games(season)
        # Sort by date so we can replay in chronological order
        reg_games_sorted = sorted(reg_games, key=lambda g: (g["date"], g["game_pk"] or 0))

        # Build per-pitcher ordered game log from reg_games (estimates from team scores)
        pitcher_game_seq: dict[int, list[dict]] = defaultdict(list)
        for g in reg_games_sorted:
            for side, opp_side in [("home", "away"), ("away", "home")]:
                pid = g.get(f"{side}_pitcher_id")
                if not pid:
                    continue
                opp_runs = g.get(f"{opp_side}_score", 0) or 0
                sp_er = max(0, round(opp_runs * 0.55 * 0.9))
                ip_est = 5.5
                k_est  = round(ip_est * 0.83)
                bb_est = round(ip_est * 0.39)
                h_est  = round(ip_est * 1.00)
                pitcher_game_seq[pid].append({
                    "date": g["date"],
                    "game_pk": g["game_pk"],
                    "ip": ip_est, "er": sp_er, "k": k_est, "bb": bb_est, "h": h_est,
                })

        # For each game in pitcher_game_seq, we build a cumulative stat snapshot
        # *before* that game (walk-forward). Index by game_pk → cumulative stats.
        pitcher_pregame_stats: dict[tuple[int, int], dict] = {}
        for pid, log in pitcher_game_seq.items():
            cum = {"ip": 0.0, "er": 0, "k": 0, "bb": 0, "h": 0, "starts": 0}
            for entry in log:
                gpk = entry["game_pk"]
                pitcher_pregame_stats[(pid, gpk)] = dict(cum)
                cum["ip"]     += entry["ip"]
                cum["er"]     += entry["er"]
                cum["k"]      += entry["k"]
                cum["bb"]     += entry["bb"]
                cum["h"]      += entry["h"]
                cum["starts"] += 1

        def _pitcher_stats(pid: int, gpk: int) -> dict:
            """Return cumulative stats for pitcher pid before game gpk."""
            c = pitcher_pregame_stats.get((pid, gpk), {})
            ip = max(c.get("ip", 0.0), 1.0)
            starts = c.get("starts", 0)
            if starts < 3:
                return {"era": 4.5, "k9": 8.0, "bb9": 3.0, "whip": 1.3, "starts": starts}
            return {
                "era":    round(c.get("er", 0) / ip * 9, 2),
                "k9":     round(c.get("k", 0)  / ip * 9, 2),
                "bb9":    round(c.get("bb", 0)  / ip * 9, 2),
                "whip":   round((c.get("bb", 0) + c.get("h", 0)) / ip, 3),
                "starts": starts,
            }

        month_offset = {3: 0, 4: 0.14, 5: 0.29, 6: 0.43, 7: 0.57, 8: 0.71, 9: 0.86, 10: 1.0}

        for g in games:
            hp_id = g.get("home_pitcher_id")
            ap_id = g.get("away_pitcher_id")
            home_id = g.get("home_id")
            away_id = g.get("away_id")

            if not all([hp_id, ap_id, home_id, away_id]):
                continue

            # Compute features from *prior* data
            hp_1st_era = pitcher_1st[hp_id]["runs"] / max(pitcher_1st[hp_id]["games"], 1) * 9 if pitcher_1st[hp_id]["games"] >= 3 else 4.5
            ap_1st_era = pitcher_1st[ap_id]["runs"] / max(pitcher_1st[ap_id]["games"], 1) * 9 if pitcher_1st[ap_id]["games"] >= 3 else 4.5
            home_1st_rate = team_1st[home_id]["runs"] / max(team_1st[home_id]["games"], 1) if team_1st[home_id]["games"] >= 10 else 0.5
            away_1st_rate = team_1st[away_id]["runs"] / max(team_1st[away_id]["games"], 1) if team_1st[away_id]["games"] >= 10 else 0.5

            game_month = int(g["date"][5:7]) if len(g["date"]) >= 7 else 6
            sp = month_offset.get(game_month, 0.5)

            gpk = g["game_pk"]
            hp_stats = _pitcher_stats(hp_id, gpk)
            ap_stats = _pitcher_stats(ap_id, gpk)

            row = {
                "season": season,
                "game_pk": gpk,
                "nrfi": int(g["nrfi"]),
                "home_sp_1st_era": hp_1st_era,
                "away_sp_1st_era": ap_1st_era,
                "home_sp_era": hp_stats["era"],
                "away_sp_era": ap_stats["era"],
                "home_sp_k9": hp_stats["k9"],
                "away_sp_k9": ap_stats["k9"],
                "home_sp_bb9": hp_stats["bb9"],
                "away_sp_bb9": ap_stats["bb9"],
                "home_sp_whip": hp_stats["whip"],
                "away_sp_whip": ap_stats["whip"],
                "home_team_1st_scoring_rate": home_1st_rate,
                "away_team_1st_scoring_rate": away_1st_rate,
                "home_sp_1st_games": pitcher_1st[hp_id]["games"],
                "away_sp_1st_games": pitcher_1st[ap_id]["games"],
                "season_progress": sp,
            }
            all_rows.append(row)

            # Update cumulative stats *after* recording row
            pitcher_1st[hp_id]["runs"] += g["away_1st_inning_runs"]
            pitcher_1st[hp_id]["games"] += 1
            pitcher_1st[ap_id]["runs"] += g["home_1st_inning_runs"]
            pitcher_1st[ap_id]["games"] += 1
            team_1st[home_id]["runs"] += g["home_1st_inning_runs"]
            team_1st[home_id]["games"] += 1
            team_1st[away_id]["runs"] += g["away_1st_inning_runs"]
            team_1st[away_id]["games"] += 1

    if not all_rows:
        return {}

    df = pd.DataFrame(all_rows)
    train_mask = df["season"].isin(train_seasons)
    test_mask = df["season"].isin(test_seasons)

    X_train = df.loc[train_mask, NRFI_FEATURES].fillna(0)
    y_train = df.loc[train_mask, "nrfi"]
    X_test = df.loc[test_mask, NRFI_FEATURES].fillna(0)
    y_test = df.loc[test_mask, "nrfi"]

    if verbose:
        print(f"  Train: {len(X_train)} games, Test: {len(X_test)} games")
        print(f"  Train NRFI rate: {y_train.mean():.1%}, Test NRFI rate: {y_test.mean():.1%}")

    model = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
    model.fit(X_train, y_train)

    train_probs = model.predict_proba(X_train)[:, 1]
    test_probs = model.predict_proba(X_test)[:, 1]

    train_acc = np.mean((train_probs > 0.5) == y_train)
    test_acc = np.mean((test_probs > 0.5) == y_test)

    baseline_acc = max(y_test.mean(), 1 - y_test.mean())

    # Calibration: actual NRFI rate in each probability bucket
    buckets = np.digitize(test_probs, bins=np.linspace(0, 1, 11))
    cal_data = []
    for b in range(1, 11):
        mask = buckets == b
        if mask.sum() > 0:
            cal_data.append({
                "bucket": f"{(b-1)*10}-{b*10}%",
                "predicted": test_probs[mask].mean(),
                "actual": y_test.values[mask].mean(),
                "count": int(mask.sum()),
            })

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({
            "model": model,
            "features": NRFI_FEATURES,
            "pitcher_1st_stats": dict(pitcher_1st),
            "team_1st_stats": dict(team_1st),
        }, f)

    results = {
        "train_accuracy": train_acc,
        "test_accuracy": test_acc,
        "baseline_accuracy": baseline_acc,
        "test_nrfi_rate": float(y_test.mean()),
        "calibration": cal_data,
        "train_size": len(X_train),
        "test_size": len(X_test),
    }

    if verbose:
        print(f"\n  {'='*50}")
        print(f"  NRFI MODEL RESULTS")
        print(f"  {'='*50}")
        print(f"  Train Accuracy: {train_acc:.1%}")
        print(f"  Test Accuracy:  {test_acc:.1%}")
        print(f"  Baseline (always NRFI): {baseline_acc:.1%}")
        print(f"  Lift over baseline: {(test_acc - baseline_acc)*100:+.1f}%")
        print(f"  Model saved to {MODEL_PATH}")
        print(f"  {'='*50}\n")

    return results


def load_nrfi_model() -> tuple | None:
    """Returns (model, features, pitcher_1st_stats, team_1st_stats) or None."""
    if not MODEL_PATH.exists():
        return None
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    return (
        data["model"],
        data["features"],
        data.get("pitcher_1st_stats", {}),
        data.get("team_1st_stats", {}),
    )


def predict_nrfi(
    home_pitcher_id: int | None,
    away_pitcher_id: int | None,
    home_team_id: int | None,
    away_team_id: int | None,
    home_pitcher_era: float = 4.5,
    away_pitcher_era: float = 4.5,
    home_pitcher_k9: float = 8.0,
    away_pitcher_k9: float = 8.0,
    home_pitcher_bb9: float = 3.0,
    away_pitcher_bb9: float = 3.0,
    home_pitcher_whip: float = 1.3,
    away_pitcher_whip: float = 1.3,
) -> float:
    """
    Predict NRFI probability for a single game.
    Returns P(no runs in 1st inning).
    """
    loaded = load_nrfi_model()
    if loaded is None:
        return 0.58  # historical baseline

    model, features, pitcher_1st, team_1st = loaded

    hp_1st = pitcher_1st.get(home_pitcher_id, {"runs": 0, "games": 0}) if home_pitcher_id else {"runs": 0, "games": 0}
    ap_1st = pitcher_1st.get(away_pitcher_id, {"runs": 0, "games": 0}) if away_pitcher_id else {"runs": 0, "games": 0}
    ht_1st = team_1st.get(home_team_id, {"runs": 0, "games": 0}) if home_team_id else {"runs": 0, "games": 0}
    at_1st = team_1st.get(away_team_id, {"runs": 0, "games": 0}) if away_team_id else {"runs": 0, "games": 0}

    row = {
        "home_sp_1st_era": hp_1st["runs"] / max(hp_1st["games"], 1) * 9 if hp_1st["games"] >= 3 else 4.5,
        "away_sp_1st_era": ap_1st["runs"] / max(ap_1st["games"], 1) * 9 if ap_1st["games"] >= 3 else 4.5,
        "home_sp_era": home_pitcher_era,
        "away_sp_era": away_pitcher_era,
        "home_sp_k9": home_pitcher_k9,
        "away_sp_k9": away_pitcher_k9,
        "home_sp_bb9": home_pitcher_bb9,
        "away_sp_bb9": away_pitcher_bb9,
        "home_sp_whip": home_pitcher_whip,
        "away_sp_whip": away_pitcher_whip,
        "home_team_1st_scoring_rate": ht_1st["runs"] / max(ht_1st["games"], 1) if ht_1st["games"] >= 10 else 0.5,
        "away_team_1st_scoring_rate": at_1st["runs"] / max(at_1st["games"], 1) if at_1st["games"] >= 10 else 0.5,
        "home_sp_1st_games": hp_1st["games"],
        "away_sp_1st_games": ap_1st["games"],
        "season_progress": 0.5,
    }

    X = pd.DataFrame([row])[features].fillna(0)
    return float(model.predict_proba(X)[0, 1])

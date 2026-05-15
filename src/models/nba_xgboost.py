"""
NBA XGBoost model — spread and total prediction.
Replaces the 2007 Kubatko formula with a trained ML model.

Training:  python3 -c "from src.models.nba_xgboost import train; train()"
Inference: from src.models.nba_xgboost import predict_game
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Optional

MODEL_DIR   = Path("data/models")
SPREAD_PATH = MODEL_DIR / "nba_spread_xgb.pkl"
TOTAL_PATH  = MODEL_DIR / "nba_total_xgb.pkl"
META_PATH   = MODEL_DIR / "nba_xgb_meta.json"

_spread_model = None
_total_model  = None
_meta: dict   = {}


def _load_models():
    global _spread_model, _total_model, _meta
    if _spread_model is not None:
        return
    if not SPREAD_PATH.exists() or not TOTAL_PATH.exists():
        return  # not trained yet — caller falls back to formula
    with open(SPREAD_PATH, "rb") as f:
        _spread_model = pickle.load(f)
    with open(TOTAL_PATH, "rb") as f:
        _total_model = pickle.load(f)
    if META_PATH.exists():
        _meta = json.loads(META_PATH.read_text())


def is_trained() -> bool:
    return SPREAD_PATH.exists() and TOTAL_PATH.exists()


def predict_game(features: dict) -> Optional[dict]:
    """
    Predict spread and total from a feature dict.
    Returns {"spread": float, "total": float, "spread_std": float} or None if not trained.
    """
    _load_models()
    if _spread_model is None:
        return None

    from src.models.nba_features import FEATURE_NAMES
    X = [[features.get(f, 0.0) for f in FEATURE_NAMES]]

    spread = float(_spread_model.predict(X)[0])
    total  = float(_total_model.predict(X)[0])
    spread_std = float(_meta.get("spread_std", 12.0))

    return {"spread": spread, "total": total, "spread_std": spread_std}


def train(start_season: str = "2015-16", verbose: bool = True) -> dict:
    """
    Train NBA spread and total XGBoost models with walk-forward cross-validation.
    Saves models to data/models/. Returns validation metrics.
    """
    try:
        import numpy as np
        from xgboost import XGBRegressor
        from sklearn.isotonic import IsotonicRegression
        from sklearn.metrics import mean_absolute_error
    except ImportError:
        print("Install xgboost and scikit-learn: pip install xgboost scikit-learn")
        return {}

    from src.data.nba_historical import load_historical_games
    from src.models.nba_features import build_feature_matrix, features_to_array, FEATURE_NAMES

    if verbose:
        print("Loading historical NBA game data...")
    games = load_historical_games()
    if not games:
        print("No game data — run: python3 src/data/nba_historical.py")
        return {}

    features, y_spread, y_total = build_feature_matrix(games)
    if verbose:
        print(f"  {len(features)} training games after feature engineering")

    X = features_to_array(features)

    # XGBoost hyperparameters.
    # n_estimators is a ceiling — early_stopping_rounds will cut it short.
    # Deeper regularization (min_child_weight=12, reg_lambda=2) to counter
    # overfitting on 13k games of 19 features.
    xgb_params = dict(
        n_estimators=1000,        # high ceiling; early stopping decides actual count
        max_depth=4,              # shallower than 5 — NBA has less feature diversity
        learning_rate=0.03,       # slower learning, more trees stopped early
        subsample=0.75,
        colsample_bytree=0.75,
        min_child_weight=12,      # require more data per leaf
        reg_alpha=1.0,            # L1 sparsity
        reg_lambda=2.0,           # L2 smoother
        random_state=42,
        early_stopping_rounds=40, # stop if val MAE doesn't improve for 40 rounds
    )

    # Walk-forward cross-validation — use seasons from the filtered features list
    feat_seasons = [f.get("season", "") for f in features]
    unique_seasons = sorted(set(feat_seasons))
    val_maes_spread, val_maes_total = [], []
    best_iters_spread, best_iters_total = [], []

    # Use last 3 seasons as validation windows
    for val_season in unique_seasons[-3:]:
        train_idx = [i for i, s in enumerate(feat_seasons) if s < val_season]
        val_idx   = [i for i, s in enumerate(feat_seasons) if s == val_season]
        if len(train_idx) < 500 or len(val_idx) < 50:
            continue

        X_tr = [X[i] for i in train_idx]
        X_va = [X[i] for i in val_idx]
        y_sp_tr = [y_spread[i] for i in train_idx]
        y_sp_va = [y_spread[i] for i in val_idx]
        y_to_tr = [y_total[i] for i in train_idx]
        y_to_va = [y_total[i] for i in val_idx]

        m_sp = XGBRegressor(**xgb_params)
        m_sp.fit(X_tr, y_sp_tr, eval_set=[(X_va, y_sp_va)], verbose=False)

        m_to = XGBRegressor(**xgb_params)
        m_to.fit(X_tr, y_to_tr, eval_set=[(X_va, y_to_va)], verbose=False)

        mae_sp = mean_absolute_error(y_sp_va, m_sp.predict(X_va))
        mae_to = mean_absolute_error(y_to_va, m_to.predict(X_va))
        val_maes_spread.append(mae_sp)
        val_maes_total.append(mae_to)
        best_iters_spread.append(getattr(m_sp, "best_iteration", xgb_params["n_estimators"]))
        best_iters_total.append(getattr(m_to, "best_iteration", xgb_params["n_estimators"]))
        if verbose:
            print(f"  Val {val_season}: spread MAE={mae_sp:.2f} pts (trees={m_sp.best_iteration})  "
                  f"total MAE={mae_to:.2f} pts (trees={m_to.best_iteration})")

    # Final model: train on all data, use median best_iteration from CV as the cap.
    # This avoids overfitting to the most recent season while using all data.
    final_n_spread = int(np.median(best_iters_spread)) + 20 if best_iters_spread else 300
    final_n_total  = int(np.median(best_iters_total))  + 20 if best_iters_total  else 300

    if verbose:
        print(f"\nTraining final models on all data (spread n={final_n_spread}, total n={final_n_total})...")

    # Final params: drop early_stopping (no separate val set), use CV-determined n_estimators
    final_params = {k: v for k, v in xgb_params.items() if k != "early_stopping_rounds"}
    final_params["n_estimators"] = final_n_spread
    final_spread = XGBRegressor(**final_params)
    final_spread.fit(X, y_spread, verbose=False)

    final_params["n_estimators"] = final_n_total
    final_total = XGBRegressor(**final_params)
    final_total.fit(X, y_total, verbose=False)

    # Compute residual std for probability calculation
    import numpy as np
    spread_preds = final_spread.predict(X)
    spread_residuals = np.array(y_spread) - spread_preds
    spread_std = float(np.std(spread_residuals))

    # Feature importance
    importance = dict(zip(FEATURE_NAMES, final_spread.feature_importances_.tolist()))
    top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]
    if verbose:
        print("\n  Top 10 features (spread model):")
        for feat, imp in top_features:
            print(f"    {feat:<20} {imp:.4f}")

    # Save
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(SPREAD_PATH, "wb") as f:
        pickle.dump(final_spread, f)
    with open(TOTAL_PATH, "wb") as f:
        pickle.dump(final_total, f)

    meta = {
        "spread_std":  spread_std,
        "spread_mae":  float(np.mean(val_maes_spread)) if val_maes_spread else None,
        "total_mae":   float(np.mean(val_maes_total))  if val_maes_total  else None,
        "n_games":     len(features),
        "seasons":     unique_seasons,
        "features":    FEATURE_NAMES,
        "top_features": top_features,
    }
    META_PATH.write_text(json.dumps(meta, indent=2))

    if verbose:
        avg_sp = np.mean(val_maes_spread) if val_maes_spread else float("nan")
        avg_to = np.mean(val_maes_total)  if val_maes_total  else float("nan")
        print(f"\n  Avg validation MAE: spread {avg_sp:.2f} pts | total {avg_to:.2f} pts")
        print(f"  Spread residual std: {spread_std:.2f} pts")
        print(f"  Models saved → {MODEL_DIR}/")

    return meta


if __name__ == "__main__":
    train()

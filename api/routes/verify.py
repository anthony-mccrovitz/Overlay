"""
Verified predictions — cryptographic proof that picks were made before games.

Before games: publish a SHA-256 hash of all predictions.
After games: reveal the predictions. Anyone can verify hash matches.

This solves the #1 trust problem in sports betting: faked records.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["verify"])

VERIFY_DIR = Path("data/verified")


def _hash_predictions(predictions: list[dict]) -> str:
    canonical = json.dumps(predictions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@router.post("/verify/lock")
async def lock_predictions(sport: str = "baseball_mlb"):
    """
    Lock today's predictions: generate picks, hash them, save the hash.
    Call this BEFORE games start. The hash is public proof.
    """
    from src.data.mlb_stats import get_todays_matchups
    from src.models.mlb_model import predict_all_games

    today = date.today().isoformat()
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    if sport == "baseball_mlb":
        matchups = get_todays_matchups()
        preds = predict_all_games(matchups)
        predictions = [
            {
                "game_id": p.game_id,
                "home_team": p.home_team,
                "away_team": p.away_team,
                "home_win_prob": round(p.home_win_prob, 4),
                "home_pitcher": p.home_pitcher,
                "away_pitcher": p.away_pitcher,
            }
            for p in preds
        ]
    else:
        return {"error": f"Verification not yet supported for {sport}"}

    prediction_hash = _hash_predictions(predictions)

    lock_file = VERIFY_DIR / f"{sport}_{today}_lock.json"
    lock_file.write_text(json.dumps({
        "sport": sport,
        "date": today,
        "locked_at": datetime.now(tz=timezone.utc).isoformat(),
        "prediction_hash": prediction_hash,
        "num_games": len(predictions),
        "predictions": predictions,
    }, indent=2), encoding="utf-8")

    hash_file = VERIFY_DIR / f"{sport}_{today}_hash.txt"
    hash_file.write_text(prediction_hash, encoding="utf-8")

    return {
        "sport": sport,
        "date": today,
        "prediction_hash": prediction_hash,
        "num_games": len(predictions),
        "message": "Predictions locked. Share the hash publicly before games start.",
    }


@router.get("/verify/hash/{sport}/{date_str}")
async def get_hash(sport: str, date_str: str):
    """Public endpoint: get the pre-game hash for a given date."""
    hash_file = VERIFY_DIR / f"{sport}_{date_str}_hash.txt"
    if not hash_file.exists():
        return {"error": "No locked predictions found for this date"}

    return {
        "sport": sport,
        "date": date_str,
        "prediction_hash": hash_file.read_text().strip(),
    }


@router.get("/verify/reveal/{sport}/{date_str}")
async def reveal_predictions(sport: str, date_str: str):
    """
    After games: reveal the actual predictions.
    Anyone can hash the predictions and verify they match the pre-game hash.
    """
    lock_file = VERIFY_DIR / f"{sport}_{date_str}_lock.json"
    if not lock_file.exists():
        return {"error": "No locked predictions found for this date"}

    data = json.loads(lock_file.read_text())
    verify_hash = _hash_predictions(data["predictions"])

    return {
        "sport": data["sport"],
        "date": data["date"],
        "locked_at": data["locked_at"],
        "prediction_hash": data["prediction_hash"],
        "verification_hash": verify_hash,
        "verified": data["prediction_hash"] == verify_hash,
        "predictions": data["predictions"],
    }

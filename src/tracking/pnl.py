"""
Simple JSON-backed P&L tracker for betting picks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _profit_from_odds(stake: float, odds: float, won: bool) -> float:
    if stake <= 0:
        return 0.0
    if not won:
        return -stake
    if odds is None or odds == 0:
        return stake * (100.0 / 110.0)
    if odds > 0:
        return stake * (odds / 100.0)
    return stake * (100.0 / abs(odds))


@dataclass
class PnLTracker:
    path: Path = Path("data/pnl/picks.json")

    def _load(self) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return {"picks": []}

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "picks" not in data:
                raise ValueError("Invalid PnL schema")
            return data
        except (json.JSONDecodeError, ValueError):
            backup = self.path.with_suffix(".corrupt.json")
            self.path.replace(backup)
            return {"picks": []}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def record_pick(
        self,
        game_id: str,
        team: str,
        opponent: str,
        bet_type: str = "moneyline",
        odds: float = 0.0,
        model_prob: float = 0.5,
        bet_size: float = 0.0,
    ) -> dict:
        data = self._load()
        for existing in data["picks"]:
            if (
                existing.get("game_id") == game_id
                and existing.get("team") == team
                and existing.get("bet_type") == bet_type
            ):
                raise ValueError(f"Duplicate pick for {game_id} / {team} / {bet_type}")

        row = {
            "game_id": game_id,
            "team": team,
            "opponent": opponent,
            "bet_type": bet_type,
            "odds": float(odds),
            "model_prob": float(model_prob),
            "bet_size": float(bet_size),
            "recorded_at": _now_iso(),
            "result": None,
            "profit": None,
            "resulted_at": None,
        }
        data["picks"].append(row)
        self._save(data)
        return row

    def record_result(
        self, game_id: str, team: str, won: bool, bet_type: str | None = None
    ) -> dict:
        data = self._load()
        for pick in data["picks"]:
            if pick.get("game_id") != game_id or pick.get("team") != team:
                continue
            if bet_type is not None and pick.get("bet_type") != bet_type:
                continue
            if pick.get("result") is None:
                pick["result"] = "win" if won else "loss"
                pick["profit"] = round(_profit_from_odds(pick.get("bet_size", 0.0), pick.get("odds", 0.0), won), 2)
                pick["resulted_at"] = _now_iso()
                self._save(data)
                return pick

        raise ValueError(f"No unresolved pick found for game_id={game_id}, team={team}")

    def get_summary(self) -> dict:
        data = self._load()
        picks = data["picks"]
        settled = [p for p in picks if p.get("result") in {"win", "loss"}]

        wins = sum(1 for p in settled if p.get("result") == "win")
        losses = sum(1 for p in settled if p.get("result") == "loss")
        settled_ml = [
            p
            for p in settled
            if (p.get("bet_type") or "moneyline") == "moneyline"
        ]
        staked = sum(float(p.get("bet_size", 0.0)) for p in settled)
        profit = sum(float(p.get("profit", 0.0) or 0.0) for p in settled)
        roi = (profit / staked) if staked > 0 else 0.0
        win_rate = (wins / len(settled)) if settled else 0.0

        streak = 0
        if settled:
            ordered = sorted(settled, key=lambda p: p.get("resulted_at") or p.get("recorded_at") or "")
            direction = ordered[-1].get("result")
            for pick in reversed(ordered):
                if pick.get("result") == direction:
                    streak += 1
                else:
                    break
            streak = streak if direction == "win" else -streak

        return {
            "total_picks": len(picks),
            "settled_picks": len(settled),
            "settled_moneyline": len(settled_ml),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "units_staked": staked,
            "units_profit": profit,
            "roi": roi,
            "streak": streak,
        }

    def get_record_card(self) -> str:
        s = self.get_summary()
        return (
            f"Season: {s['wins']}-{s['losses']} | "
            f"ROI: {s['roi'] * 100:+.1f}% | "
            f"Units: {s['units_profit']:+.2f}"
        )


def record_pick(**kwargs) -> dict:
    return PnLTracker().record_pick(**kwargs)


def record_result(**kwargs) -> dict:
    return PnLTracker().record_result(**kwargs)


def get_summary() -> dict:
    return PnLTracker().get_summary()


def get_record_card() -> str:
    return PnLTracker().get_record_card()

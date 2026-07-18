"""
Closing Line Value (CLV) tracker.

The gold standard metric for measuring whether a sports betting model
has genuine edge. CLV measures whether your picks consistently beat
where the line closes just before game start.

Why CLV matters more than W/L record:
  - W/L has high variance (you can win 60% one week and 40% the next)
  - CLV is low variance (a good model consistently beats the closing line)
  - If you beat the closing line over 500+ bets, you have real edge
  - Pinnacle and other sharp books use CLV to identify winning bettors

Usage:
  tracker = CLVTracker()

  # When you make a pick, record the line
  tracker.record_pick("game_123", "Yankees", pick_odds=-150, model_prob=0.62)

  # Just before game starts, record closing line
  tracker.record_closing_line("game_123", "Yankees", closing_odds=-160)

  # After game, record result
  tracker.record_result("game_123", "Yankees", won=True)

  # Get CLV metrics
  summary = tracker.get_clv_summary()
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


CLV_DIR = Path("data/clv")


def _odds_to_implied(odds: int | float) -> float:
    """Convert American odds to implied probability."""
    if odds == 0:
        return 0.5
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)



@dataclass
class CLVTracker:
    path: Path = field(default_factory=lambda: CLV_DIR / "clv_records.json")

    def _load(self) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return {"picks": []}
        try:
            with open(self.path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"picks": []}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def record_pick(
        self,
        game_id: str,
        team: str,
        pick_odds: int | float,
        model_prob: float,
        sport: str = "mlb",
        sportsbook: str = "",
    ) -> dict:
        data = self._load()

        entry = {
            "game_id": game_id,
            "team": team,
            "sport": sport,
            "pick_odds": pick_odds,
            "pick_implied_prob": _odds_to_implied(pick_odds),
            "model_prob": model_prob,
            "sportsbook": sportsbook,
            "pick_time": datetime.now(timezone.utc).isoformat(),
            "closing_odds": None,
            "closing_implied_prob": None,
            "closing_time": None,
            "won": None,
            "result_time": None,
            "clv_cents": None,
        }

        data["picks"].append(entry)
        self._save(data)
        return entry

    def record_closing_line(
        self,
        game_id: str,
        team: str,
        closing_odds: int | float,
    ) -> dict | None:
        data = self._load()

        for pick in reversed(data["picks"]):
            if pick["game_id"] == game_id and pick["team"] == team:
                pick["closing_odds"] = closing_odds
                pick["closing_implied_prob"] = _odds_to_implied(closing_odds)
                pick["closing_time"] = datetime.now(timezone.utc).isoformat()

                pick_imp = pick["pick_implied_prob"]
                close_imp = pick["closing_implied_prob"]
                pick["clv_cents"] = round((close_imp - pick_imp) * 100, 2)

                self._save(data)
                return pick
        return None

    def record_result(
        self,
        game_id: str,
        team: str,
        won: bool,
    ) -> dict | None:
        data = self._load()
        for pick in reversed(data["picks"]):
            if pick["game_id"] == game_id and pick["team"] == team:
                pick["won"] = won
                pick["result_time"] = datetime.now(timezone.utc).isoformat()
                self._save(data)
                return pick
        return None

    def get_clv_summary(self, sport: str | None = None) -> dict:
        data = self._load()
        picks = data.get("picks", [])
        if sport:
            picks = [p for p in picks if p.get("sport") == sport]

        total = len(picks)
        with_closing = [p for p in picks if p.get("clv_cents") is not None]
        settled = [p for p in picks if p.get("won") is not None]

        if not with_closing:
            return {
                "total_picks": total,
                "with_closing_line": 0,
                "settled": len(settled),
                "clv_mean_cents": 0.0,
                "clv_positive_pct": 0.0,
                "message": "No closing line data yet. CLV requires recording closing lines.",
            }

        clv_values = [p["clv_cents"] for p in with_closing]
        clv_mean = sum(clv_values) / len(clv_values)
        clv_positive = sum(1 for v in clv_values if v > 0)
        clv_positive_pct = clv_positive / len(clv_values)

        wins = sum(1 for p in settled if p["won"])
        win_rate = wins / max(len(settled), 1)

        model_probs = [p["model_prob"] for p in with_closing if p.get("model_prob")]
        avg_model_edge = 0.0
        if model_probs:
            edges = [
                p["model_prob"] - p["pick_implied_prob"]
                for p in with_closing
                if p.get("model_prob") and p.get("pick_implied_prob")
            ]
            avg_model_edge = sum(edges) / max(len(edges), 1)

        return {
            "total_picks": total,
            "with_closing_line": len(with_closing),
            "settled": len(settled),
            "wins": wins if settled else 0,
            "losses": len(settled) - wins if settled else 0,
            "win_rate": win_rate if settled else None,
            "clv_mean_cents": round(clv_mean, 2),
            "clv_median_cents": round(sorted(clv_values)[len(clv_values) // 2], 2),
            "clv_positive_pct": round(clv_positive_pct, 4),
            "clv_total_cents": round(sum(clv_values), 2),
            "avg_model_edge": round(avg_model_edge, 4),
            "verdict": _clv_verdict(clv_mean, len(with_closing)),
        }

    def get_recent_picks(self, n: int = 20) -> list[dict]:
        data = self._load()
        return data.get("picks", [])[-n:]


def _clv_verdict(clv_mean: float, sample_size: int) -> str:
    if sample_size < 50:
        return "INSUFFICIENT DATA — need 50+ picks with closing lines"
    if clv_mean > 2.0:
        return "STRONG EDGE — consistently beating the closing line"
    if clv_mean > 0.5:
        return "POSITIVE CLV — model shows real edge against the market"
    if clv_mean > -0.5:
        return "NEUTRAL — model roughly matches closing line efficiency"
    return "NEGATIVE CLV — model is getting worse odds than the closing line"

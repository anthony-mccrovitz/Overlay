"""
MlbTotalsModel — the reference PickModel adapter.

Wraps the existing, proven `find_totals_edges` (MLB full-game over/under, the
one outcome-verified lane) in the common PickModel contract. This is the
template every other adapter follows: the model's real logic is untouched;
the adapter only translates its output into RawPicks.
"""
from __future__ import annotations

from src.models.mlb_totals import find_totals_edges
from src.models.pick_model import PickModel, RawPick, SportContext


class MlbTotalsModel(PickModel):
    sport = "mlb"
    market = "total"

    def __init__(self, min_edge_runs: float = 1.0) -> None:
        self.min_edge_runs = min_edge_runs

    def generate_picks(self, ctx: SportContext) -> list[RawPick]:
        if ctx.odds_df is None or len(ctx.odds_df) == 0:
            return []

        edges = find_totals_edges(
            ctx.matchups, ctx.odds_df, min_edge_runs=self.min_edge_runs
        )

        picks: list[RawPick] = []
        for e in edges:
            direction = str(e.get("direction", "")).upper()
            line = e.get("market_line")
            try:
                line = float(line) if line is not None else None
            except (TypeError, ValueError):
                line = None

            picks.append(
                RawPick(
                    sport="mlb",
                    market="total",
                    direction=direction,
                    odds=int(e.get("best_odds") or 0),
                    matchup=f'{e.get("away_team", "")} @ {e.get("home_team", "")}',
                    line=line,
                    model_prob=e.get("model_prob"),
                    edge=e.get("edge_runs"),
                    sportsbook=e.get("sportsbook", ""),
                    extras={
                        "proj_total": e.get("predicted_total"),
                        "weather_context": e.get("weather_context", ""),
                    },
                )
            )
        return picks

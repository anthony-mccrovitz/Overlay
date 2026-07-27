"""
MlbF5TotalsModel — first-5-innings totals adapter.

Wraps the existing `find_f5_edges` (over/under on runs through 5 innings — a
sharper market than full-game because it bypasses bullpen variance). Like every
adapter, the model's real logic is untouched; this only builds the SP-stat
inputs from the shared matchups and translates the output into RawPicks.

The SP era/k9 inputs live directly on the matchup objects the MLB context
already loads, so no extra context plumbing is needed — the same board the
totals model sees drives F5 too.
"""
from __future__ import annotations

from datetime import date as _date

from src.data.f5_totals import find_f5_edges
from src.models.pick_model import PickModel, RawPick, SportContext

_DEFAULT_ERA = 4.20
_DEFAULT_K9 = 8.5


class MlbF5TotalsModel(PickModel):
    sport = "mlb"
    market = "f5_total"

    def __init__(self, min_edge: float = 0.08) -> None:
        self.min_edge = min_edge

    def _f5_inputs(self, matchups: list) -> list[dict]:
        """Build the SP-stat input dicts find_f5_edges expects, from matchups."""
        inputs: list[dict] = []
        for m in matchups:
            hp, ap = getattr(m, "home_pitcher", None), getattr(m, "away_pitcher", None)
            inputs.append({
                "home_team": m.home_team.name,
                "away_team": m.away_team.name,
                "home_sp_era": hp.era if hp else _DEFAULT_ERA,
                "home_sp_k9": hp.k_per_9 if hp else _DEFAULT_K9,
                "away_sp_era": ap.era if ap else _DEFAULT_ERA,
                "away_sp_k9": ap.k_per_9 if ap else _DEFAULT_K9,
            })
        return inputs

    def generate_picks(self, ctx: SportContext) -> list[RawPick]:
        if not ctx.matchups:
            return []

        game_date = _date.fromisoformat(ctx.date)
        edges = find_f5_edges(
            self._f5_inputs(ctx.matchups), game_date=game_date, min_edge=self.min_edge
        )

        picks: list[RawPick] = []
        for e in edges:
            line = e.get("line")
            try:
                line = float(line) if line is not None else None
            except (TypeError, ValueError):
                line = None

            picks.append(
                RawPick(
                    sport="mlb",
                    market="f5_total",
                    direction=str(e.get("direction", "")).upper(),
                    odds=int(e.get("odds") or 0),
                    # find_f5_edges already builds the human-readable side label
                    # ("F5 UNDER 4.5 (SEA @ OAK)") so the ledger identifies the game.
                    team=e.get("team", ""),
                    matchup=e.get("matchup", ""),
                    line=line,
                    model_prob=e.get("model_prob"),
                    edge=e.get("edge_pct"),  # percentage points, matching the schema
                    sportsbook=e.get("book", ""),
                    extras={"proj_total": e.get("projected_total")},
                )
            )
        return picks

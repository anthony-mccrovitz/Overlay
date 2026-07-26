"""
SoccerModel — the Dixon-Coles club adapter, the first grid expansion.

Wraps the proven club model's find_edges (3-way moneyline, market-anchored) in
the PickModel contract, across every configured league. This is how the grid's
soccer cell scales: adding a league is one entry in LEAGUES once its model is
fitted — the engine, gate, runner, and promoter are all shared.

Each RawPick keeps its league sport_key (e.g. 'soccer_mexico_ligamx') so the
ledger tracks leagues separately, while the registry gate folds them all to
'soccer' (World Cup is the sole exception, gated as its own 'wc' unit).

The adapter is pure model logic: it reads pre-fetched events from
ctx.extras['events_by_league'] (the runner's context builder fetches them), so
it's fully testable without odds/network.
"""
from __future__ import annotations

from src.models.pick_model import PickModel, RawPick, SportContext

# Leagues with a fitted club model today. Extend this as more are fitted — the
# rest of the factory needs no changes.
LEAGUES = ["soccer_mexico_ligamx", "soccer_usa_mls"]


class SoccerModel(PickModel):
    sport = "soccer"
    market = "moneyline"

    def __init__(self, leagues: list[str] | None = None, min_edge_pct: float = 4.0) -> None:
        self.leagues = leagues if leagues is not None else list(LEAGUES)
        self.min_edge_pct = min_edge_pct
        self._models: dict[str, object] = {}

    def _model_for(self, league: str):
        if league not in self._models:
            from src.models.soccer_club_model import load_or_fit_club_model
            self._models[league] = load_or_fit_club_model(league, verbose=False)
        return self._models[league]

    def generate_picks(self, ctx: SportContext) -> list[RawPick]:
        events_by_league = (ctx.extras or {}).get("events_by_league", {})
        picks: list[RawPick] = []
        for league in self.leagues:
            events = events_by_league.get(league)
            if not events:
                continue
            model = self._model_for(league)
            edges = model.find_edges(events, min_edge_pct=self.min_edge_pct)
            for e in edges:
                picks.append(
                    RawPick(
                        sport=league,                 # keep league identity in the ledger
                        market="moneyline",
                        direction=str(e.get("direction", "")),
                        team=str(e.get("team", "")),
                        odds=int(e.get("odds") or 0),
                        matchup=e.get("matchup", ""),
                        model_prob=e.get("model_prob"),
                        edge=e.get("edge_pct"),
                        sportsbook=e.get("sportsbook", ""),
                        extras={"exp_total": e.get("exp_total")},
                    )
                )
        return picks

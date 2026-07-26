"""
SoccerModel — ONE model per league (not one combined soccer model).

Each league is its own PickModel instance, its own grid cell, and its own
validation lane: Liga MX and MLS must never share a promote/demote verdict
(Liga MX earns +CLV; MLS bleeds). The adapter's `sport` is the league's short
label (e.g. 'mexico_ligamx'), which is exactly how `_key` folds the league —
so the registry, gate, and promoter all judge each league on its own record.

Only leagues with a dedicated fitted model belong here. Adding a European
league means fitting its own model first (extend SOCCER_LEAGUES then).

Pure model logic: reads its league's pre-fetched events from ctx.extras, so
it's fully testable without odds/network.
"""
from __future__ import annotations

from src.models.pick_model import PickModel, RawPick, SportContext

# Full Odds-API sport_keys for leagues that have their OWN dedicated club model.
SOCCER_LEAGUES = ["soccer_mexico_ligamx", "soccer_usa_mls"]


def league_label(sport_key: str) -> str:
    """Short registry label for a league — matches _key('soccer_x') → 'x'."""
    return sport_key.replace("soccer_", "")


class SoccerModel(PickModel):
    market = "moneyline"

    def __init__(self, league: str, min_edge_pct: float = 4.0) -> None:
        self.league = league                 # full sport_key, kept in the ledger
        self.sport = league_label(league)    # short label = registry/grid key
        self.min_edge_pct = min_edge_pct
        self._model = None

    def _load(self):
        if self._model is None:
            from src.models.soccer_club_model import load_or_fit_club_model
            self._model = load_or_fit_club_model(self.league, verbose=False)
        return self._model

    def generate_picks(self, ctx: SportContext) -> list[RawPick]:
        extras = ctx.extras or {}
        # Accept either this league's events directly, or a by-league map.
        events = extras.get("events")
        if events is None:
            events = extras.get("events_by_league", {}).get(self.league)
        if not events:
            return []

        edges = self._load().find_edges(events, min_edge_pct=self.min_edge_pct)
        picks: list[RawPick] = []
        for e in edges:
            picks.append(
                RawPick(
                    sport=self.league,          # full league key → ledger identity
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

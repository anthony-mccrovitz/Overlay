"""
league.py — your league's actual rules, pulled once and cached.

Every valuation decision depends on settings the league publishes, and guessing
them is expensive: this league is FULL PPR with only 2 WR starters + a flex,
where the sensible default guess (half-PPR, 3 WR) put WR demand at 41.4 instead
of the real 29.4. That single error makes every wide receiver look ~40% more
valuable than he is, which is enough to lose a draft.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.fantasy import scoring, sleeper

LEAGUE_ID = "1312101560595009536"       # Fantasy football 2026-27


@dataclass
class LeagueConfig:
    league_id: str
    name: str
    teams: int
    roster_positions: list[str]
    scoring_settings: dict
    bench_slots: int = 0
    playoff_teams: int = 6
    playoff_week_start: int = 15
    waiver_budget: int = 100
    is_redraft: bool = True

    @property
    def format(self) -> str:
        return scoring.describe(self.scoring_settings)

    @property
    def starting_slots(self) -> int:
        return len([s for s in self.roster_positions
                    if s.upper() not in ("BN", "IR", "TAXI")])

    def summary(self) -> str:
        return (f"{self.name} — {self.teams} teams, {self.format}, "
                f"{self.starting_slots} starters + {self.bench_slots} bench")


def load(league_id: str = LEAGUE_ID) -> LeagueConfig:
    L = sleeper.league(league_id)
    s = L.get("settings") or {}
    rp = L.get("roster_positions") or []
    return LeagueConfig(
        league_id=league_id,
        name=L.get("name") or league_id,
        teams=int(L.get("total_rosters") or 12),
        roster_positions=rp,
        scoring_settings=L.get("scoring_settings") or {},
        bench_slots=len([x for x in rp if x.upper() == "BN"]),
        playoff_teams=int(s.get("playoff_teams") or 6),
        playoff_week_start=int(s.get("playoff_week_start") or 15),
        waiver_budget=int(s.get("waiver_budget") or 0),
        is_redraft=(int(s.get("type") or 0) == 0),
    )

"""
roster_risk.py — injuries and handcuffs.

Two things a board built purely from last year's box scores cannot see.

INJURY STATUS. Sleeper carries a live designation. IR and PUP mean a player is
not available at the start of the season, which is not a projection adjustment —
it is a different asset entirely, and drafting one at his healthy price is a
straight loss. "Questionable" in August is usually noise and is surfaced rather
than penalised.

HANDCUFFS. A starting running back's backup inherits a startable workload the
moment the starter goes down, which is why the same body is nearly worthless in
September and a league-winner in October. Depth-chart data gives us this
directly: the DC2 behind each DC1 on the same team. Worth knowing which of your
own backs you should be protecting, and which cheap backup is one snap from
relevance.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.fantasy import sleeper

# Designations that mean "not available now", as distinct from week-to-week noise.
OUT_STATUSES = {"IR", "PUP", "NFI", "Sus", "DNR"}
NOISE_STATUSES = {"Questionable", "Probable"}

# How much to discount a player who will miss the start of the season. Deliberately
# blunt — the point is to stop him being drafted at his healthy price, not to
# forecast a return date we cannot know.
OUT_DISCOUNT = 0.45


@dataclass
class Handcuff:
    starter_id: str
    starter: str
    backup_id: str
    backup: str
    team: str


def injury_flag(player: dict) -> tuple[float, str]:
    """(multiplier, label) for a player's current availability."""
    st = player.get("injury_status")
    if not st:
        return 1.0, ""
    if st in OUT_STATUSES:
        part = player.get("injury_body_part") or ""
        return OUT_DISCOUNT, f"{st}{' — ' + part if part else ''}"
    if st in NOISE_STATUSES:
        # Surfaced, not priced: August "questionable" is mostly noise.
        return 1.0, st
    return 1.0, st


def handcuffs(position: str = "RB", players_db: dict | None = None) -> list[Handcuff]:
    """The DC2 behind each team's DC1 at a position.

    Running backs are the position where this matters — a WR2 is already
    startable, whereas a RB2 is worth almost nothing until the moment he is
    worth a great deal.
    """
    fp = sleeper.fantasy_players(players_db)
    by_team: dict[str, dict[int, dict]] = {}
    for pid, p in fp.items():
        if p.get("position") != position:
            continue
        d = p.get("depth_chart_order")
        if d in (1, 2):
            by_team.setdefault(p["team"], {})[int(d)] = {**p, "_pid": pid}

    out: list[Handcuff] = []
    for team, slots in sorted(by_team.items()):
        if 1 in slots and 2 in slots:
            out.append(Handcuff(
                starter_id=slots[1]["_pid"], starter=sleeper.display_name(slots[1]),
                backup_id=slots[2]["_pid"], backup=sleeper.display_name(slots[2]),
                team=team,
            ))
    return out


def my_handcuffs(my_player_ids: list[str], position: str = "RB",
                 players_db: dict | None = None) -> list[Handcuff]:
    """Handcuffs for backs I actually roster — the ones worth protecting."""
    mine = set(my_player_ids)
    return [h for h in handcuffs(position, players_db) if h.starter_id in mine]

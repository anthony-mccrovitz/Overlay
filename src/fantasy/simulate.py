"""
simulate.py — Monte-Carlo the draft to find out which opening actually works.

Slot 10 of 12 is a structural oddity: picks 10 and 15 arrive five apart, then
nothing until 34. That makes the first two selections effectively one decision —
a PAIR — and the right pair is not obvious. RB-RB corners the scarce position but
concedes the elite receivers; WR-RB takes the best player available and gambles
that a startable back survives to 34.

Nobody in a casual league answers that question with anything but instinct. It is
answerable: simulate the other eleven managers drafting from ADP with realistic
noise, run each candidate opening a few thousand times, and compare the STARTING
LINEUP you end up with.

What is deliberately modelled:
  · opponents draft near ADP, not at it — a normal jitter, because real drafts
    have reaches and slides
  · opponents fill their own roster needs, so positional runs emerge naturally
    rather than being scripted
  · we evaluate the resulting STARTERS, not the roster — a fourth running back
    contributes nothing to a lineup that starts two

What is not modelled: in-season waivers, trades, injuries. So the output ranks
openings against each other; it is not a forecast of points.
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field

from src.fantasy.valuation import PlayerValue

# Real drafts scatter around ADP. A third of the mean matches observed spread
# and keeps early picks tighter than late ones, which is how drafts behave.
ADP_JITTER = 0.33
ADP_JITTER_FLOOR = 5.0

# Opponents are not optimisers. They take need-adjusted best-available with a
# strong ADP anchor, which is what a normal manager does.
OPPONENT_ADP_WEIGHT = 0.75


@dataclass
class SimResult:
    opening: tuple[str, ...]
    mean_starter_vorp: float
    p25: float
    p75: float
    worst: float
    n: int
    example: list[str] = field(default_factory=list)


def _starting_slots(roster_positions: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    flex = 0
    for slot in roster_positions:
        s = slot.upper()
        if s in ("QB", "RB", "WR", "TE", "K", "DEF"):
            counts[s] += 1
        elif s in ("FLEX", "WRRB_FLEX", "REC_FLEX"):
            flex += 1
    return dict(counts), flex


def lineup_value(roster: list[PlayerValue], roster_positions: list[str]) -> float:
    """Value of the best legal STARTING lineup from this roster.

    Evaluating the whole roster would reward hoarding; only what you can start
    on Sunday counts, with the flex filled by the best leftover.
    """
    slots, flex = _starting_slots(roster_positions)
    by_pos: dict[str, list[PlayerValue]] = defaultdict(list)
    for p in roster:
        by_pos[p.position].append(p)
    for v in by_pos.values():
        v.sort(key=lambda p: -p.vorp)

    total = 0.0
    leftovers: list[PlayerValue] = []
    for pos, n in slots.items():
        group = by_pos.get(pos, [])
        total += sum(p.vorp for p in group[:n])
        if pos in ("RB", "WR", "TE"):
            leftovers.extend(group[n:])
    leftovers.sort(key=lambda p: -p.vorp)
    total += sum(p.vorp for p in leftovers[:flex])
    return total


def _jittered_adp(p: PlayerValue, rng: random.Random) -> float:
    base = p.adp if p.adp is not None else 300.0
    sigma = max(ADP_JITTER_FLOOR, base * ADP_JITTER)
    return rng.gauss(base, sigma)


def _opponent_pick(pool: list[PlayerValue], need: dict[str, int],
                   rng: random.Random) -> PlayerValue:
    """A normal manager: ADP-anchored, nudged by his own roster holes."""
    best, best_score = None, -1e9
    for p in pool[:40]:                     # nobody scans 400 names
        adp_rank = _jittered_adp(p, rng)
        want = 1.15 if need.get(p.position, 0) > 0 else 0.85
        score = (-adp_rank * OPPONENT_ADP_WEIGHT) * (1.0 / want)
        if score > best_score:
            best, best_score = p, score
    return best or pool[0]


def simulate_opening(board: list[PlayerValue], opening: tuple[str, ...],
                     my_slot: int, teams: int, rounds: int,
                     roster_positions: list[str], trials: int = 300,
                     seed: int = 7) -> SimResult:
    """Run one opening strategy `trials` times and score the lineup it produces.

    `opening` is the position to take at each of my first picks, e.g.
    ("RB", "RB"). After the opening runs out we take need-adjusted best
    available, which is what a competent manager does anyway.
    """
    rng = random.Random(seed)
    slots, flex = _starting_slots(roster_positions)
    targets = dict(slots)
    targets["RB"] = targets.get("RB", 0) + 1     # flex demand
    targets["WR"] = targets.get("WR", 0) + 1

    my_overall = []
    for r in range(rounds):
        my_overall.append(r * teams + (my_slot if r % 2 == 0 else teams - my_slot + 1))
    my_overall_set = set(my_overall)

    totals: list[float] = []
    example: list[str] = []

    for t in range(trials):
        pool = sorted(board, key=lambda p: (p.adp if p.adp is not None else 999))
        pool = [p for p in pool if p.vorp is not None]
        available = list(pool)
        mine: list[PlayerValue] = []
        opp_need = [dict(targets) for _ in range(teams + 1)]

        for overall in range(1, teams * rounds + 1):
            if not available:
                break
            if overall in my_overall_set:
                idx = my_overall.index(overall)
                pick = None
                if idx < len(opening):
                    want = opening[idx]
                    for p in available:
                        if p.position == want:
                            pick = p
                            break
                if pick is None:
                    have = defaultdict(int)
                    for p in mine:
                        have[p.position] += 1
                    pick = max(
                        available[:40],
                        key=lambda p: p.vorp * (1.25 if have[p.position] < targets.get(p.position, 0) else 0.35),
                    )
                mine.append(pick)
                available.remove(pick)
            else:
                team_idx = ((overall - 1) % teams) + 1
                pick = _opponent_pick(available, opp_need[team_idx], rng)
                opp_need[team_idx][pick.position] = max(
                    0, opp_need[team_idx].get(pick.position, 0) - 1)
                available.remove(pick)

        totals.append(lineup_value(mine, roster_positions))
        if t == 0:
            example = [f"{p.name} ({p.position})" for p in mine[:7]]

    totals.sort()
    n = len(totals)
    return SimResult(
        opening=opening,
        mean_starter_vorp=round(sum(totals) / n, 1),
        p25=round(totals[n // 4], 1),
        p75=round(totals[3 * n // 4], 1),
        worst=round(totals[0], 1),
        n=n, example=example,
    )


def compare_openings(board: list[PlayerValue], openings: list[tuple[str, ...]],
                     my_slot: int, teams: int, rounds: int,
                     roster_positions: list[str],
                     trials: int = 300) -> list[SimResult]:
    out = [simulate_opening(board, o, my_slot, teams, rounds,
                            roster_positions, trials) for o in openings]
    return sorted(out, key=lambda r: -r.mean_starter_vorp)

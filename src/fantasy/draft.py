"""
draft.py — the live draft assistant.

A static cheat sheet tells you who is best. It does not tell you the only thing
that matters while you are on the clock: of the players you want, which one will
still be there next time?

That is the actual decision. If two players are close in value and one reliably
lasts another round, you take the other one and get both. Getting this wrong is
how a good board still produces a mediocre roster.

The assistant polls Sleeper's draft endpoint (public, no auth), removes players
already taken, and ranks what remains by value adjusted for:

  · your roster needs — the 4th running back on your bench is worth far less
    than your first starting receiver, regardless of raw VORP
  · survival to your next pick — estimated from ADP and how many picks away it is
  · tier cliffs — the last player in a tier is worth more than his VORP implies,
    because the drop behind him is the real cost of waiting
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.fantasy import sleeper
from src.fantasy.valuation import PlayerValue

# How much of a starting slot's value the Nth BENCH player at a position
# retains. Index 0 is the first backup, not the last starter — an off-by-one
# here made the first bench player worth a full starting slot, which is exactly
# the error that has a board recommending a fourth running back.
# The first backup has real value (bye weeks, injuries); the fourth does not.
BENCH_DECAY = (0.45, 0.22, 0.10, 0.05, 0.03)

# ADP is a mean, and the spread around it is wide — roughly a third of the mean
# in practice. Used to estimate the chance a player survives N more picks.
ADP_SIGMA_FRACTION = 0.33
ADP_SIGMA_FLOOR = 6.0


@dataclass
class DraftState:
    draft_id: str
    teams: int
    rounds: int
    my_slot: int | None = None            # 1-indexed draft position
    picks_made: int = 0
    taken: set[str] = field(default_factory=set)
    my_players: list[str] = field(default_factory=list)

    @property
    def current_pick(self) -> int:
        return self.picks_made + 1

    def my_next_picks(self, count: int = 3) -> list[int]:
        """Overall pick numbers of my next `count` picks, snake order."""
        if self.my_slot is None:
            return []
        out = []
        rnd = 0
        while len(out) < count and rnd < self.rounds:
            # Snake: odd rounds run 1..N, even rounds run N..1.
            if rnd % 2 == 0:
                overall = rnd * self.teams + self.my_slot
            else:
                overall = rnd * self.teams + (self.teams - self.my_slot + 1)
            if overall >= self.current_pick:
                out.append(overall)
            rnd += 1
        return out


def load_state(draft_id: str, my_user_id: str | None = None) -> DraftState:
    d = sleeper.draft(draft_id)
    picks = sleeper.draft_picks(draft_id)
    settings = d.get("settings") or {}
    teams = int(settings.get("teams") or 12)

    my_slot = None
    order = d.get("draft_order") or {}
    if my_user_id and my_user_id in order:
        my_slot = int(order[my_user_id])

    taken = {p["player_id"] for p in picks if p.get("player_id")}
    mine = [p["player_id"] for p in picks
            if p.get("player_id") and (
                (my_user_id and p.get("picked_by") == my_user_id))]

    return DraftState(
        draft_id=draft_id, teams=teams,
        rounds=int(settings.get("rounds") or 15),
        my_slot=my_slot, picks_made=len(picks),
        taken=taken, my_players=mine,
    )


# ─────────────────────────── roster need ─────────────────────────────────────

def roster_counts(my_players: list[str], board: dict[str, PlayerValue]) -> dict[str, int]:
    counts = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "K": 0, "DEF": 0}
    for pid in my_players:
        v = board.get(pid)
        if v and v.position in counts:
            counts[v.position] += 1
    return counts


def need_multiplier(position: str, have: int, starters_needed: dict[str, int]) -> float:
    """How much a player at this position is worth to THIS roster right now.

    Raw VORP says a fourth running back is as valuable as a first. He is not:
    he cannot be started, and the value of a bench body decays fast. This is
    what stops the board telling you to take RB with every pick just because
    running backs top the board in a 2WR league.
    """
    need = starters_needed.get(position, 0)
    if have < need:
        return 1.0
    depth = have - need
    return BENCH_DECAY[min(depth, len(BENCH_DECAY) - 1)]


# ─────────────────────────── survival ────────────────────────────────────────

def survival_probability(adp: float | None, picks_until_next: int,
                         current_pick: int) -> float:
    """Chance a player is still available at my next pick.

    Modelled as a normal around his ADP: by the time `picks_until_next` more
    selections have happened, the draft has reached pick
    (current_pick + picks_until_next), and a player survives if his realised
    draft slot lands beyond that.
    """
    if adp is None:
        return 0.85                        # undrafted-ish: usually still there
    target = current_pick + picks_until_next
    sigma = max(ADP_SIGMA_FLOOR, adp * ADP_SIGMA_FRACTION)
    z = (adp - target) / sigma
    # P(draft slot > target) under a normal centred on adp.
    return 0.5 * math.erfc(-z / math.sqrt(2))


# ─────────────────────────── recommendation ──────────────────────────────────

@dataclass
class Suggestion:
    value: PlayerValue
    adjusted: float
    survives: float
    reason: str


def bye_conflict(candidate: PlayerValue, my_players: list[str],
                 board: dict[str, PlayerValue], starters_needed: dict[str, int]) -> int:
    """How many players I'd already have resting on this candidate's bye week.

    Three starters on the same bye is a game you lose in September for a reason
    you chose in August, and it is entirely avoidable — the schedule is public.
    Counted across starting-calibre positions only; a backup sharing a bye is
    irrelevant.
    """
    if candidate.bye is None:
        return 0
    n = 0
    for pid in my_players:
        v = board.get(pid)
        if v and v.bye == candidate.bye and v.position in starters_needed:
            n += 1
    return n


def recommend(board_list: list[PlayerValue], state: DraftState,
              starters_needed: dict[str, int], top: int = 12) -> list[Suggestion]:
    """Rank the available players for THIS pick.

    The score is VORP × roster-need, plus an urgency premium for players who are
    unlikely to survive. A player you can get later is worth less NOW than an
    equally good player who will be gone — that difference is the whole point of
    drafting well rather than merely ranking well.
    """
    board = {v.player_id: v for v in board_list}
    have = roster_counts(state.my_players, board)

    nexts = state.my_next_picks(2)
    gap = (nexts[1] - nexts[0]) if len(nexts) >= 2 else state.teams * 2

    out: list[Suggestion] = []
    for v in board_list:
        if v.player_id in state.taken:
            continue
        mult = need_multiplier(v.position, have.get(v.position, 0), starters_needed)
        base = v.vorp * mult
        surv = survival_probability(v.adp, gap, state.current_pick)
        # Urgency: value you would lose by waiting. A player certain to survive
        # carries no premium; one certain to vanish carries his full value.
        adjusted = base * (1.0 + 0.5 * (1.0 - surv))

        # Bye stacking. One shared bye is a note; a third starter resting the
        # same week is a game you lose in September for a reason you chose in
        # August, so it costs the player ground against an equal alternative.
        clash = bye_conflict(v, state.my_players, board, starters_needed)
        if clash >= 2:
            adjusted *= 0.90 ** (clash - 1)

        bits = []
        if clash >= 2:
            bits.append(f"⚠ {clash} others on bye {v.bye}")
        elif clash == 1:
            bits.append(f"bye {v.bye} clash")
        if v.playoff_sos is not None and v.playoff_sos >= 1.06:
            bits.append(f"easy playoffs ({v.playoff_sos:.2f})")
        elif v.playoff_sos is not None and v.playoff_sos <= 0.94:
            bits.append(f"hard playoffs ({v.playoff_sos:.2f})")
        if mult < 1.0:
            bits.append(f"bench {v.position} (×{mult:.2f})")
        if surv < 0.35:
            bits.append("won't last")
        elif surv > 0.75:
            bits.append("likely available later")
        if v.note:
            bits.append(v.note)
        out.append(Suggestion(v, round(adjusted, 1), round(surv, 2), " · ".join(bits)))

    out.sort(key=lambda s: -s.adjusted)
    return out[:top]

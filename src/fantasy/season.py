"""
season.py — the in-season tools: FAAB bidding, trades, and start/sit.

The draft is one day. The season is fourteen weeks, and most leagues are won or
lost after it — by the manager who pays the right price on waivers, wins the
trade, and starts the right guy in a bad matchup.

All three answer the same question in different clothes: what is a player worth
to MY roster, right now, for the games that remain? That is not his ranking. It
is his value above the player he would actually replace in my lineup, which is
why every function here takes the roster as an argument.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.fantasy.valuation import PlayerValue

# Weeks that decide the title in this league. Playoffs start week 15 and pay six
# of twelve teams, so a player's value in December is worth more than in October
# — you only need to make the field, then you need to win it.
PLAYOFF_WEEKS = (15, 16, 17)


# ─────────────────────────── FAAB ────────────────────────────────────────────

@dataclass
class Bid:
    player: PlayerValue
    max_bid: int              # % of remaining budget
    dollars: int
    upgrade: float            # points/week this actually adds to my lineup
    reason: str


def faab_bid(candidate: PlayerValue, my_roster: list[PlayerValue],
             starters_needed: dict[str, int], budget_left: int,
             weeks_left: int = 14, aggression: float = 1.0) -> Bid:
    """What to bid, based on the upgrade to my STARTING lineup.

    The mistake that loses FAAB leagues is bidding on a player's name. A RB2 who
    would be your third-best back adds nothing to a lineup that starts two — his
    value to you is zero regardless of how good he is in the abstract. What
    matters is the delta between him and the man he displaces, multiplied by the
    weeks you would actually get that delta.

    Budget is finite and non-renewable, so the bid scales with how much of the
    season is left: the same upgrade in week 2 is worth far more than in week 12.
    """
    pos = candidate.position
    need = starters_needed.get(pos, 0)
    same = sorted([p for p in my_roster if p.position == pos],
                  key=lambda p: -p.vorp)

    # Who does he actually replace in my lineup?
    if len(same) < need:
        displaced = 0.0                       # fills an empty starting slot
    else:
        displaced = same[need - 1].vorp if need > 0 else same[0].vorp

    upgrade = max(0.0, candidate.vorp - displaced)
    if upgrade <= 0:
        return Bid(candidate, 0, 0, 0.0,
                   "no upgrade — he would not crack your starting lineup")

    # Share of the season the upgrade actually accrues over.
    season_share = max(0.0, min(1.0, weeks_left / 14.0))

    # Convert to a share of remaining budget. A genuinely startable upgrade is
    # worth real money; a marginal one is worth a token bid.
    scale = min(1.0, upgrade / 60.0)          # 60 pts of VORP ≈ a league-winner
    pct = min(0.60, scale * season_share * 0.75 * aggression)
    dollars = int(round(budget_left * pct))

    if pct >= 0.35:
        why = "league-winning upgrade — spend"
    elif pct >= 0.15:
        why = "real starter upgrade"
    else:
        why = "marginal — bid low or pass"
    return Bid(candidate, int(round(pct * 100)), dollars, round(upgrade, 1), why)


# ─────────────────────────── trades ──────────────────────────────────────────

@dataclass
class TradeVerdict:
    my_out: list[PlayerValue]
    my_in: list[PlayerValue]
    lineup_before: float
    lineup_after: float
    delta: float
    verdict: str
    notes: list[str] = field(default_factory=list)


def _best_lineup(roster: list[PlayerValue], starters_needed: dict[str, int],
                 flex: int = 1) -> float:
    by_pos: dict[str, list[PlayerValue]] = {}
    for p in roster:
        by_pos.setdefault(p.position, []).append(p)
    for v in by_pos.values():
        v.sort(key=lambda p: -p.vorp)
    total, leftovers = 0.0, []
    for pos, n in starters_needed.items():
        g = by_pos.get(pos, [])
        total += sum(p.vorp for p in g[:n])
        if pos in ("RB", "WR", "TE"):
            leftovers.extend(g[n:])
    leftovers.sort(key=lambda p: -p.vorp)
    return total + sum(p.vorp for p in leftovers[:flex])


def evaluate_trade(my_roster: list[PlayerValue], give: list[PlayerValue],
                   get: list[PlayerValue],
                   starters_needed: dict[str, int]) -> TradeVerdict:
    """Judge a trade on the STARTING LINEUP it leaves you with.

    Counting raw value on both sides is how people lose 2-for-1s: two players
    who become your RB3 and RB4 are worth almost nothing, while the one you gave
    up was starting every week. Consolidating talent into starting slots is
    usually good and this is what measures it.
    """
    before = _best_lineup(my_roster, starters_needed)
    out_ids = {p.player_id for p in give}
    after_roster = [p for p in my_roster if p.player_id not in out_ids] + list(get)
    after = _best_lineup(after_roster, starters_needed)
    delta = after - before

    notes = []
    if len(get) < len(give):
        notes.append("consolidating — you shed roster spots, which is usually good "
                     "if the incoming player starts")
    if len(get) > len(give):
        notes.append("you take on bodies — only worth it if they crack the lineup")
    for p in get:
        if p.note:
            notes.append(f"{p.name}: {p.note}")

    if delta > 15:
        verdict = "ACCEPT — clear lineup upgrade"
    elif delta > 3:
        verdict = "lean accept"
    elif delta > -3:
        verdict = "roughly neutral — decide on schedule and risk"
    elif delta > -15:
        verdict = "lean decline"
    else:
        verdict = "DECLINE — this weakens your starters"

    return TradeVerdict(list(give), list(get), round(before, 1), round(after, 1),
                        round(delta, 1), verdict, notes)


# ─────────────────────────── start / sit ─────────────────────────────────────

@dataclass
class StartSit:
    player: PlayerValue
    opponent: str
    matchup_index: float       # >1.0 = favourable
    adjusted: float
    verdict: str


def start_sit(candidates: list[PlayerValue], week: int, view,
              starters_needed: dict[str, int]) -> list[StartSit]:
    """Rank my players for one week, matchup-adjusted.

    Uses the same measured quantity as the draft board's schedule work: how many
    fantasy points each defense actually gave up to this position. A projection
    is a season-long average; the week you play a defense that cannot cover
    tight ends is the week your tight end matters.

    Deliberately a nudge, not an override — a good player in a bad matchup still
    usually outscores a bad player in a good one, and the most common start/sit
    error is benching a stud because the matchup "looks hard".
    """
    out: list[StartSit] = []
    for p in candidates:
        opp = (view.opp.get(p.team) or {}).get(week)
        if not opp:
            out.append(StartSit(p, "BYE", 0.0, 0.0, "BYE — cannot start"))
            continue
        allowed = (view.allowed.get(opp) or {}).get(p.position)
        avg = view.league_avg.get(p.position)
        idx = (allowed / avg) if (allowed and avg) else 1.0
        # Cap the swing: matchup moves a projection, it does not rewrite it.
        idx = max(0.85, min(1.15, idx))
        out.append(StartSit(p, opp, round(idx, 3), round(p.vorp * idx, 1), ""))

    out.sort(key=lambda s: -s.adjusted)
    for i, s in enumerate(out):
        if s.opponent == "BYE":
            continue
        need = starters_needed.get(s.player.position, 0)
        rank_at_pos = sum(1 for x in out[:i] if x.player.position == s.player.position)
        s.verdict = "START" if rank_at_pos < need else "bench"
    return out

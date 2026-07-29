"""
valuation.py — what a player is actually worth in YOUR league.

The single biggest edge in a casual 12-team league is not better projections.
It is that most managers draft off a raw ranking list, and raw points are the
wrong unit. Josh Allen outscores every running back and is still not the first
pick, because there are 32 starting quarterbacks and the twelfth-best one is
nearly as good as the second. What matters is the points a player produces ABOVE
the man you could have had for free at the same position.

That quantity is VORP (value over replacement), and computing it needs three
things this module derives rather than assumes:

  1. Points under the league's OWN scoring (see scoring.py).
  2. Replacement level from the league's OWN roster rules — a 12-team league
     starting 2 RB + 3 WR + a flex has a very different RB replacement level
     than one starting 2 RB and no flex.
  3. Tiers, so a two-point VORP gap is never treated like a twenty-point one.

PROJECTION HONESTY
──────────────────
2026 projections here are built from 2025 production regressed toward positional
means, with an availability adjustment. They do NOT model team changes, depth
chart moves, coaching changes or rookies — that is genuinely hard and doing it
badly is worse than not doing it. So the board treats market ADP as a co-input
rather than something to be beaten: where our value and ADP disagree sharply,
that is flagged as a QUESTION, not an answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.fantasy import scoring, sleeper

# A season is 17 games, but nobody plays 17. Using a full season overstates
# every injury-prone player relative to the iron men who actually win weeks.
EXPECTED_GAMES = 16.0

# Regression toward the positional mean. A single season of production is a
# noisy estimate of true talent — especially at RB, where touchdown variance is
# brutal — so shrink toward the position's average rate before projecting.
# Heavier shrink where the stat is noisier.
REGRESSION = {"QB": 0.20, "RB": 0.30, "WR": 0.25, "TE": 0.30, "K": 0.50, "DEF": 0.50}

# Minimum games in the source season for the sample to mean anything.
MIN_GAMES = 4


@dataclass
class PlayerValue:
    player_id: str
    name: str
    position: str
    team: str
    age: int | None = None
    proj_points: float = 0.0        # projected season total
    ppg: float = 0.0                # projected per game
    vorp: float = 0.0               # points above replacement
    tier: int = 0
    adp: float | None = None
    adp_delta: float | None = None  # our rank minus market rank; +ve = falls to us
    games_2025: float = 0.0
    note: str = ""


# ─────────────────────────── roster rules ────────────────────────────────────

def starters_from_settings(roster_positions: list[str] | None,
                           teams: int = 12) -> dict[str, float]:
    """How many of each position the league STARTS in total, flex included.

    Replacement level depends on demand, and flex spots create fractional
    demand: a FLEX taken ~65% by RB and ~35% by WR in practice raises both
    replacement levels without adding a full starter at either.
    """
    rp = roster_positions or ["QB", "RB", "RB", "WR", "WR", "WR",
                              "TE", "FLEX", "K", "DEF"]
    counts: dict[str, float] = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "K": 0, "DEF": 0}
    flex = superflex = 0
    for slot in rp:
        s = slot.upper()
        if s in counts:
            counts[s] += 1
        elif s in ("FLEX", "WRRB_FLEX", "REC_FLEX", "WRRB"):
            flex += 1
        elif s in ("SUPER_FLEX", "SUPERFLEX", "QB_FLEX"):
            superflex += 1
        # BN / IR / TAXI are bench and create no starting demand.

    # Empirical flex split; superflex is overwhelmingly a second QB.
    counts["RB"] += flex * 0.55
    counts["WR"] += flex * 0.45
    counts["QB"] += superflex * 0.85
    counts["RB"] += superflex * 0.08
    counts["WR"] += superflex * 0.07
    return {k: v * teams for k, v in counts.items()}


# ─────────────────────────── projection ──────────────────────────────────────

def project(stats_by_pid: dict, players_db: dict,
            scoring_settings: dict | None = None) -> dict[str, PlayerValue]:
    """2026 projections from 2025 production, regressed and availability-adjusted."""
    fp = sleeper.fantasy_players(players_db)

    # Per-game scoring rate for everyone with a real sample.
    raw: dict[str, tuple[float, float, dict]] = {}
    for pid, st in stats_by_pid.items():
        p = fp.get(pid)
        if not p or not isinstance(st, dict):
            continue
        gp = float(st.get("gp") or 0)
        if gp < MIN_GAMES:
            continue
        raw[pid] = (scoring.score(st, scoring_settings) / gp, gp, p)

    # Positional mean rate among plausible starters, used as the shrink target.
    by_pos: dict[str, list[float]] = {}
    for rate, _gp, p in raw.values():
        by_pos.setdefault(p["position"], []).append(rate)
    pos_mean = {}
    for pos, rates in by_pos.items():
        rates.sort(reverse=True)
        keep = rates[:max(12, len(rates) // 3)]     # starter-ish, not the tail
        pos_mean[pos] = sum(keep) / len(keep) if keep else 0.0

    out: dict[str, PlayerValue] = {}
    for pid, (rate, gp, p) in raw.items():
        pos = p["position"]
        k = REGRESSION.get(pos, 0.25)
        shrunk = (1 - k) * rate + k * pos_mean.get(pos, rate)
        # Availability: a player who missed half of last season is likelier to
        # miss games again, but one bad year shouldn't halve his projection.
        avail = min(1.0, 0.75 + 0.25 * (gp / 17.0))
        proj = shrunk * EXPECTED_GAMES * avail
        out[pid] = PlayerValue(
            player_id=pid, name=sleeper.display_name(p), position=pos,
            team=p.get("team") or "FA", age=p.get("age"),
            proj_points=round(proj, 1), ppg=round(proj / EXPECTED_GAMES, 2),
            games_2025=gp,
        )
    return out


# ─────────────────────────── VORP + tiers ────────────────────────────────────

def add_vorp(values: dict[str, PlayerValue], starters: dict[str, float]) -> None:
    """Set .vorp on every player: points above the last startable man at his
    position.

    Replacement is the (starters+1)-th best, not the worst rosterable body: the
    relevant alternative to drafting a RB is the RB you can still start, not a
    handcuff nobody plays.
    """
    by_pos: dict[str, list[PlayerValue]] = {}
    for v in values.values():
        by_pos.setdefault(v.position, []).append(v)

    for pos, group in by_pos.items():
        group.sort(key=lambda v: -v.proj_points)
        n = int(round(starters.get(pos, 0)))
        idx = min(max(n, 0), len(group) - 1)
        replacement = group[idx].proj_points if group else 0.0
        for v in group:
            v.vorp = round(v.proj_points - replacement, 1)


def add_tiers(values: dict[str, PlayerValue], gap_factor: float = 0.75) -> None:
    """Group each position into tiers, breaking where the VORP gap to the next
    player is unusually large.

    Tiers are what stop a manager reaching. If six players are within a point of
    each other, taking the sixth a round later costs nothing; if there is a
    twenty-point cliff, the cliff is the whole decision.
    """
    by_pos: dict[str, list[PlayerValue]] = {}
    for v in values.values():
        by_pos.setdefault(v.position, []).append(v)

    for group in by_pos.values():
        group.sort(key=lambda v: -v.vorp)
        gaps = [group[i].vorp - group[i + 1].vorp for i in range(len(group) - 1)]
        if not gaps:
            for v in group:
                v.tier = 1
            continue
        positive = [g for g in gaps if g > 0]
        mean_gap = (sum(positive) / len(positive)) if positive else 0.0
        threshold = mean_gap * (1.0 + gap_factor)
        tier = 1
        for i, v in enumerate(group):
            v.tier = tier
            if i < len(gaps) and gaps[i] > threshold and gaps[i] > 0:
                tier += 1


def add_adp(values: dict[str, PlayerValue], adp_map: dict[str, float]) -> None:
    """Attach market ADP and the gap between our ranking and the market's.

    adp_delta > 0 means the market drafts him LATER than we rank him — he is the
    guy who falls to you. < 0 means the market is paying up and we are not.
    """
    ranked = sorted([v for v in values.values() if v.vorp is not None],
                    key=lambda v: -v.vorp)
    our_rank = {v.player_id: i + 1 for i, v in enumerate(ranked)}
    for v in values.values():
        v.adp = adp_map.get(v.player_id)
        if v.adp is not None:
            v.adp_delta = round(v.adp - our_rank.get(v.player_id, 999), 1)


def build_board(scoring_settings: dict | None = None,
                roster_positions: list[str] | None = None,
                teams: int = 12,
                season: int = 2025) -> list[PlayerValue]:
    """The full draft board, best value first."""
    db = sleeper.players()
    stats = sleeper.season_stats(season)
    values = project(stats, db, scoring_settings)
    starters = starters_from_settings(roster_positions, teams)
    add_vorp(values, starters)
    add_tiers(values)
    add_adp(values, sleeper.adp(season + 1))
    return sorted(values.values(), key=lambda v: -v.vorp)

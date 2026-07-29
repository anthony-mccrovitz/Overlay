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

from src.fantasy import adjustments, scoring, sleeper

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

# STREAMING DISCOUNT — the correction VORP alone gets wrong.
#
# VORP measures value against the replacement available AT THE DRAFT. But you do
# not have to live with your draft-day replacement all season: QB, TE, K and DEF
# are startable off waivers most weeks, so the real alternative to drafting the
# 8th quarterback is not the 13th quarterback, it is "whichever quarterback has a
# good matchup, for free, every week". Running backs are not like this — a
# starting RB almost never appears on waivers.
#
# Without this the board recommends Matthew Stafford in the third round because
# his raw VORP is high, which is how people lose leagues. The multiplier shrinks
# VORP toward the streamable floor; it does NOT reorder within a position.
STREAMABILITY = {
    "QB":  0.45,   # 1-QB league: ~20 startable QBs for 12 slots
    "TE":  0.70,   # thin at the top, streamable after the cliff
    "RB":  1.00,   # scarce and not replaceable in-season
    "WR":  1.00,
    "K":   0.10,   # never draft early; any kicker is any other kicker
    "DEF": 0.20,   # matchup-streamed all year
}


@dataclass
class PlayerValue:
    player_id: str
    name: str
    position: str
    team: str
    age: int | None = None
    proj_points: float = 0.0        # projected season total
    ppg: float = 0.0                # projected per game
    vorp: float = 0.0               # points above replacement, streaming-adjusted
    raw_vorp: float = 0.0           # before the streaming discount
    tier: int = 0
    adp: float | None = None
    adp_delta: float | None = None  # our rank minus market rank; +ve = falls to us
    games_2025: float = 0.0
    note: str = ""
    age_factor: float = 1.0
    depth_factor: float = 1.0
    depth: int | None = None


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

    # Starter-level per-game rate per position, the yardstick the depth-chart
    # check compares a player's implied role against.
    starter_rate = {}
    for pos, rates in by_pos.items():
        top = sorted(rates, reverse=True)[:12]
        starter_rate[pos] = (sum(top) / len(top)) if top else 0.0

    out: dict[str, PlayerValue] = {}
    for pid, (rate, gp, p) in raw.items():
        pos = p["position"]
        k = REGRESSION.get(pos, 0.25)
        shrunk = (1 - k) * rate + k * pos_mean.get(pos, rate)
        # Availability: a player who missed half of last season is likelier to
        # miss games again, but one bad year shouldn't halve his projection.
        avail = min(1.0, 0.75 + 0.25 * (gp / 17.0))

        # Age and current job. Both gentle and both documented in adjustments.py
        # — a projection nudged 15% by a real signal is an improvement, one swung
        # 60% by a heuristic is a new source of error.
        af = adjustments.age_factor(pos, p.get("age"))
        df = adjustments.depth_factor(pos, p.get("depth_chart_order"),
                                      shrunk, starter_rate.get(pos, 0.0))

        proj = shrunk * EXPECTED_GAMES * avail * af * df

        flags = []
        if af < 0.93:
            flags.append(f"age {p.get('age')}")
        elif af > 1.02:
            flags.append("ascending")
        if df < 0.9:
            flags.append(f"DC{p.get('depth_chart_order')}")
        elif df > 1.0:
            flags.append("has the job")

        out[pid] = PlayerValue(
            player_id=pid, name=sleeper.display_name(p), position=pos,
            team=p.get("team") or "FA", age=p.get("age"),
            proj_points=round(proj, 1), ppg=round(proj / EXPECTED_GAMES, 2),
            games_2025=gp, note=" · ".join(flags),
            age_factor=round(af, 3), depth_factor=round(df, 3),
            depth=p.get("depth_chart_order"),
        )
    return out


# ─────────────────────────── VORP + tiers ────────────────────────────────────

def add_vorp(values: dict[str, PlayerValue], starters: dict[str, float],
             apply_streaming: bool = True) -> None:
    """Set .vorp on every player: points above the last startable man at his
    position, discounted by how replaceable that position is in-season.

    Replacement is the (starters+1)-th best, not the worst rosterable body: the
    relevant alternative to drafting a RB is the RB you can still start, not a
    handcuff nobody plays.

    The streaming discount is what stops the board recommending a quarterback in
    round three. See STREAMABILITY.
    """
    by_pos: dict[str, list[PlayerValue]] = {}
    for v in values.values():
        by_pos.setdefault(v.position, []).append(v)

    for pos, group in by_pos.items():
        group.sort(key=lambda v: -v.proj_points)
        n = int(round(starters.get(pos, 0)))
        idx = min(max(n, 0), len(group) - 1)
        replacement = group[idx].proj_points if group else 0.0
        mult = STREAMABILITY.get(pos, 1.0) if apply_streaming else 1.0
        for v in group:
            v.raw_vorp = round(v.proj_points - replacement, 1)
            v.vorp = round(v.raw_vorp * mult, 1)


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


# ─────────────────────────── market imputation ───────────────────────────────

def impute_from_adp(values: dict[str, PlayerValue], adp_map: dict[str, float],
                    players_db: dict) -> int:
    """Give a value to draftable players we cannot project from stats.

    Rookies have no prior NFL season, and veterans who missed last year (injury,
    holdout) have no usable sample either. Leaving them off the board is not
    neutral — it is a confident claim that they are worthless, and this league's
    ADP has a rookie running back at pick 21. A board that cannot see the 21st
    pick is not a draft board.

    So for these players only, we take the MARKET's word: fit the relationship
    between ADP and VORP on everyone we CAN project, then read an imputed VORP
    off that curve. This deliberately adds no information — it places them where
    consensus already has them, which is the honest default when we know less
    than the market does. Every imputed player is flagged so the board never
    passes market opinion off as our own analysis.
    """
    known = [(v.adp, v.vorp) for v in values.values()
             if v.adp is not None and v.vorp is not None]
    if len(known) < 30:
        return 0
    known.sort()

    # Bin by ADP and take the MEDIAN VORP per bin, then enforce a monotonically
    # non-increasing curve.
    #
    # Interpolating between adjacent raw points looked reasonable and was badly
    # wrong: ADP order is not our VORP order, so two players a pick apart can
    # differ by 80 points of value, and the nearest neighbour is noise rather
    # than signal. That put a rookie with ADP 21 at board rank 57 — i.e. the
    # imputation was quietly disagreeing with the very market it was supposed to
    # be deferring to. Median-of-bin plus monotonicity is the least we can do and
    # still land a player where consensus has him.
    BIN = 12                                   # roughly one round per bin
    buckets: dict[int, list[float]] = {}
    for a, w in known:
        buckets.setdefault(int(a // BIN), []).append(w)

    curve: list[tuple[float, float]] = []
    for b in sorted(buckets):
        vals_b = sorted(buckets[b])
        med = vals_b[len(vals_b) // 2]
        curve.append(((b + 0.5) * BIN, med))

    # Later picks can never be worth more than earlier ones.
    for i in range(1, len(curve)):
        if curve[i][1] > curve[i - 1][1]:
            curve[i] = (curve[i][0], curve[i - 1][1])

    def vorp_at(adp: float) -> float:
        if adp <= curve[0][0]:
            return curve[0][1]
        if adp >= curve[-1][0]:
            return curve[-1][1]
        for i in range(len(curve) - 1):
            a1, w1 = curve[i]
            a2, w2 = curve[i + 1]
            if a1 <= adp <= a2:
                t = (adp - a1) / (a2 - a1) if a2 > a1 else 0.0
                return w1 + t * (w2 - w1)
        return curve[-1][1]

    added = 0
    for pid, adp_val in adp_map.items():
        if pid in values:
            continue
        p = players_db.get(pid)
        if not isinstance(p, dict):
            continue
        if not p.get("active") or not p.get("team"):
            continue
        pos = p.get("position")
        if pos not in ("QB", "RB", "WR", "TE"):
            continue
        exp = p.get("years_exp")
        values[pid] = PlayerValue(
            player_id=pid, name=sleeper.display_name(p), position=pos,
            team=p.get("team") or "FA", age=p.get("age"),
            proj_points=0.0, ppg=0.0,
            vorp=round(vorp_at(adp_val), 1), raw_vorp=round(vorp_at(adp_val), 1),
            adp=adp_val, games_2025=0.0,
            note="ROOKIE — market value" if exp == 0 else "no 2025 sample — market value",
        )
        added += 1
    return added


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
    adp_map = sleeper.adp(season + 1)
    add_adp(values, adp_map)
    # Impute AFTER real values exist, so the curve is fitted on genuine
    # projections rather than on other imputations.
    impute_from_adp(values, adp_map, db)
    add_tiers(values)
    add_adp(values, adp_map)          # refresh ranks now the board is complete
    return sorted(values.values(), key=lambda v: -v.vorp)

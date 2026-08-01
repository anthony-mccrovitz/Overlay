"""
Shadow strategies — research-rule picks logged but never bet.

A shadow pick is a normal picks.json row with card_pick=False, stake=0, and a
`strategy` tag. It supplies the *opening* half of CLV for markets/edges we don't
bet, so we can measure which strategy beats the close before risking money.

Reuses existing machinery: picks.json → snapshot_from_pnl (opening) →
capture_closing (close) → compute_clv → grade. We only add the strategy rules
here and tag the picks.

A strategy is a pure function `fn(odds_df, sport) -> list[pick dict]`.
Register it in STRATEGIES. See docs/SHADOW_PICKS_PLAN.md.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import date as _date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

_ET = ZoneInfo("America/New_York")

from src.data.odds_api import fetch_odds
from src.data.pinnacle_fair import build_fair_prob_map
from src.strategies.consensus import (
    MIN_EV_PCT as CONSENSUS_MIN_EV_PCT,
    draw_team,
    loo_consensus,
    per_book_fair,
)
from src.tracking.schema import normalize_pick, make_pick_id

PICKS_FILE = Path("data/pnl/picks.json")


def _implied_from_american(odds: float) -> float:
    """American odds → implied (with-vig) probability. NaN-safe."""
    if odds is None or pd.isna(odds) or odds == 0:
        return float("nan")
    return 100.0 / (odds + 100.0) if odds > 0 else abs(odds) / (abs(odds) + 100.0)

# Odds API sport keys to log shadow picks for. Defaults to the in-season set;
# a sport with no games today returns empty (one cheap call) and is skipped.
# Tennis keys rotate per tournament, so they're discovered at run time
# (_active_tennis_sports) rather than listed here. When NBA/NHL/NFL seasons
# start, add their keys here.
DEFAULT_SPORTS = [
    "baseball_mlb",
    "basketball_wnba",
    "soccer_fifa_world_cup",
    "mma_mixed_martial_arts",
    # Club soccer (in-season). consensus_ev prices the full 3-way simplex
    # (DrawOdds comes through the parser); devig_ev still self-skips soccer
    # because its Pinnacle fair-map is 2-way. Totals/spreads consensus are
    # two-way and run as-is. Add la_liga/serie_a/bundesliga here when the
    # European seasons resume in August.
    "soccer_usa_mls",
    "soccer_mexico_ligamx",
    # European top flights, added 2026-07-31 ahead of the mid-August restarts
    # (EPL/La Liga/Ligue 1 ~Aug 15, Serie A/Bundesliga ~Aug 22). Same rationale
    # as the football keys below: an off-season key costs one cheap empty call,
    # and wiring BEFORE the season means evidence accrues from matchday 1
    # instead of whenever someone remembered. Closing capture for all five has
    # been in place since 2026-07-29; the pairing test enforces it stays.
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    # American football, added 2026-07-31 ahead of the season. An off-season key
    # returns an empty board for one cheap call; preseason boards appear ~Aug 6
    # and week 1 evidence starts accruing 2026-09-10 instead of whenever someone
    # remembered. Closing capture for both was wired the same day (the
    # capture-coverage test enforces the pairing), and models._key maps the
    # americanfootball_* prefixes so the lanes are born whole instead of
    # fragmenting like tennis did.
    "americanfootball_nfl",
    "americanfootball_ncaaf",
]


def _active_tennis_sports() -> list[str]:
    """Currently active tennis sport keys from the free /sports endpoint.

    Tennis keys are tournament-scoped (tennis_atp_wimbledon, ...) and rotate
    through the season, so a hardcoded list goes stale within weeks. The
    /sports listing costs zero API credits. Fail-soft: any error returns []
    and the shadow run simply covers the static DEFAULT_SPORTS.
    """
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return []
    try:
        resp = requests.get("https://api.the-odds-api.com/v4/sports",
                            params={"apiKey": key}, timeout=10)
        resp.raise_for_status()
        return [s["key"] for s in resp.json()
                if s.get("active") and str(s.get("key", "")).startswith("tennis_")]
    except Exception:
        return []


# ── Strategies ──────────────────────────────────────────────────────────────

def fav_longshot(odds_df: pd.DataFrame, sport: str) -> list[dict]:
    """Favorite-longshot bias — back the moneyline favorite of every game.

    The most-replicated finding in the betting literature: favorites are
    underpriced, longshots overpriced. One pick per game, best available price
    on the favorite (the side with the higher consensus implied probability).
    """
    if odds_df is None or odds_df.empty:
        return []
    # Moneyline column name drifted across pipelines (HomeMoneyline vs HomeOdds).
    home_ml = "HomeMoneyline" if "HomeMoneyline" in odds_df.columns else "HomeOdds"
    away_ml = "AwayMoneyline" if "AwayMoneyline" in odds_df.columns else "AwayOdds"
    needed = {"GameID", "HomeTeam", "AwayTeam", home_ml, away_ml,
              "HomeImpliedProb", "AwayImpliedProb", "Sportsbook"}
    if not needed.issubset(odds_df.columns):
        return []

    now = datetime.now(tz=timezone.utc)
    picks: list[dict] = []
    for _gid, g in odds_df.groupby("GameID"):
        home = str(g["HomeTeam"].iloc[0])
        away = str(g["AwayTeam"].iloc[0])
        if not home or not away:
            continue
        # Only log a true *opening* — skip games already started.
        if "CommenceTime" in g.columns:
            ct = str(g["CommenceTime"].iloc[0] or "")
            try:
                if ct and datetime.fromisoformat(ct.replace("Z", "+00:00")) <= now:
                    continue
            except ValueError:
                pass
        home_imp = pd.to_numeric(g["HomeImpliedProb"], errors="coerce").mean()
        away_imp = pd.to_numeric(g["AwayImpliedProb"], errors="coerce").mean()
        if pd.isna(home_imp) or pd.isna(away_imp):
            continue

        if home_imp >= away_imp:
            team, direction, odds_col = home, "HOME", home_ml
        else:
            team, direction, odds_col = away, "AWAY", away_ml

        prices = pd.to_numeric(g[odds_col], errors="coerce").dropna()
        if prices.empty:
            continue
        # Best price for the bettor = highest American odds.
        best_idx = prices.idxmax()
        best_odds = int(prices.loc[best_idx])
        book = str(g.loc[best_idx, "Sportsbook"])

        picks.append({
            "sport":     sport,
            "market":    "moneyline",
            "direction": direction,
            "team":      team,
            "matchup":   f"{away} @ {home}",
            "odds":      best_odds,
            "sportsbook": book,
        })
    return picks


# Positive-EV (OddsJam / Monahan method) tuning.
# OddsJam surfaces edges as small as ~1%; we set a slightly higher bar for the
# shadow test so the sample is dominated by spots a human would actually bet.
_MIN_EV_PCT = 2.0
# Pinnacle is the sharp no-vig *reference*, never a bet destination — pricing
# +EV against the book we devigged from would just measure its own vig.
_NON_DESTINATION_BOOKS = {"Pinnacle"}
# devig_ev assumes a TWO-outcome moneyline. Soccer is three-way (home/draw/away)
# and the feed carries no draw price, so devigging home-vs-away alone drops the
# draw mass and inflates BOTH fair probs → phantom edge on every side. Skip
# draw-market sports until a real 3-way devig exists.
_DRAW_MARKET_TOKENS = ("soccer",)
# Secondary guard (belt-and-suspenders behind the soccer skip): a clean two-way
# reference book sums to ~1.02-1.10. A 3-way slice missing the draw sits far
# lower (~0.70-0.85). Floor at 0.95 — below any real 2-way median yet well above
# any draw market — so it nets future 3-way sports without false-killing sparse
# 2-way slates where one off book drags the median just under 1.0.
_OVERROUND_MIN, _OVERROUND_MAX = 0.95, 1.25


def devig_ev(odds_df: pd.DataFrame, sport: str) -> list[dict]:
    """Positive-EV moneyline picks (OddsJam / Alex Monahan method) — model-free.

    For each side, take the no-vig fair probability (Pinnacle devig, median-devig
    fallback — both from build_fair_prob_map) as the 'true' probability, find the
    best price among bettable books, and emit a pick when the gap is +EV by at
    least _MIN_EV_PCT, where EV% = fair_prob / best_implied - 1.

    This never consults the ML model, so unlike a model edge it can't be
    over-confident — the edge is a pure market disagreement (sharp fair line vs a
    soft book that's slow or off). Logged as a shadow strategy and CLV-graded
    before a dollar is risked. Moneyline here; totals live in devig_ev_totals.

    Handles 2-way (MLB/WNBA/…) and 3-way (soccer) moneylines: when a real Draw
    price is present, build_fair_prob_map devigs the full home/away/draw simplex
    and this prices the DRAW as a full third side (draw_team()-keyed, like
    consensus_ev). This is the Pinnacle-ANCHORED twin of consensus_ev's
    board-median anchor — the two grade head-to-head under the 300-bet verdict.
    """
    if odds_df is None or odds_df.empty:
        return []
    home_ml = "HomeMoneyline" if "HomeMoneyline" in odds_df.columns else "HomeOdds"
    away_ml = "AwayMoneyline" if "AwayMoneyline" in odds_df.columns else "AwayOdds"
    needed = {"GameID", "HomeTeam", "AwayTeam", home_ml, away_ml, "Sportsbook"}
    if not needed.issubset(odds_df.columns):
        return []

    is_draw_sport = any(tok in sport.lower() for tok in _DRAW_MARKET_TOKENS)
    fair_map = build_fair_prob_map(odds_df)
    if not fair_map:
        return []

    now = datetime.now(tz=timezone.utc)
    picks: list[dict] = []
    for gid, g in odds_df.groupby("GameID"):
        fair = fair_map.get(str(gid), {}).get("h2h")
        if not fair:
            continue
        home = str(g["HomeTeam"].iloc[0])
        away = str(g["AwayTeam"].iloc[0])
        if not home or not away:
            continue
        # A 3-way market must carry a devigged draw or we don't price it — never
        # fall back to a 2-way devig on soccer (that's the phantom-EV bug).
        game_three_way = is_draw_sport and "draw" in fair
        if is_draw_sport and not game_three_way:
            continue
        # Only log a true *opening* — skip games already started.
        if "CommenceTime" in g.columns:
            ct = str(g["CommenceTime"].iloc[0] or "")
            try:
                if ct and datetime.fromisoformat(ct.replace("Z", "+00:00")) <= now:
                    continue
            except ValueError:
                pass

        bettable = g[~g["Sportsbook"].isin(_NON_DESTINATION_BOOKS)]
        if bettable.empty:
            continue

        # Sanity-check the market overround. Vig is a PER-BOOK property, so judge
        # it by a single SHARP book's implied sum — Pinnacle if present, else the
        # median per-book overround (robust to one off book). Don't use min(): an
        # off soft book legitimately sums <1.0, and that's the +EV signal. A clean
        # reference sits ~1.02-1.10; sum the DRAW too on 3-way so a real soccer
        # market clears the band instead of looking like a broken 2-way slice.
        cols = [home_ml, away_ml] + (["DrawOdds"] if game_three_way else [])
        sided = g.dropna(subset=cols)
        per_book = [
            sum(_implied_from_american(r[c]) for c in cols)
            for _, r in sided.iterrows()
        ]
        per_book = [o for o in per_book if not pd.isna(o)]
        if not per_book:
            continue
        pin = sided[sided["Sportsbook"] == "Pinnacle"]
        if not pin.empty:
            ref_overround = sum(_implied_from_american(pin.iloc[0][c]) for c in cols)
        else:
            ref_overround = float(pd.Series(per_book).median())
        if not (_OVERROUND_MIN <= ref_overround <= _OVERROUND_MAX):
            continue

        sides = [("home", "HOME", home_ml), ("away", "AWAY", away_ml)]
        if game_three_way:
            sides.append(("draw", "DRAW", "DrawOdds"))

        for side, direction, odds_col in sides:
            fair_p = fair.get(side)
            if not fair_p or fair_p <= 0:
                continue
            prices = pd.to_numeric(bettable[odds_col], errors="coerce").dropna()
            if prices.empty:
                continue
            # Best price for the bettor = highest American odds.
            best_idx = prices.idxmax()
            best_odds = int(prices.loc[best_idx])
            book = str(bettable.loc[best_idx, "Sportsbook"])
            implied = _implied_from_american(best_odds)
            if pd.isna(implied) or implied <= 0:
                continue
            ev_pct = (fair_p / implied - 1.0) * 100.0
            if ev_pct < _MIN_EV_PCT:
                continue
            team = (home if side == "home"
                    else away if side == "away"
                    else draw_team(away, home))
            picks.append({
                "sport":      sport,
                "market":     "moneyline",
                "direction":  direction,
                "team":       team,
                "matchup":    f"{away} @ {home}",
                "odds":       best_odds,
                "sportsbook": book,
                # model_prob carries the devig FAIR prob here (not an ML pred) so
                # the CLV-by-strategy view shows what we thought was true.
                "model_prob": round(float(fair_p), 4),
                "edge_pct":   round(float(ev_pct), 2),
            })
    return picks


def devig_ev_totals(odds_df: pd.DataFrame, sport: str) -> list[dict]:
    """Positive-EV totals — devig_ev applied to the totals market.

    Fair over/under probs come from build_fair_prob_map (Pinnacle devig at
    PINNACLE'S line, median fallback). A total at a different number is a
    different bet, so only books quoting the SAME line as the fair source are
    candidates — otherwise a half-run of line difference masquerades as price EV.
    Totals are inherently two-way (no draw), so the soccer skip doesn't apply.
    """
    if odds_df is None or odds_df.empty:
        return []
    needed = {"GameID", "HomeTeam", "AwayTeam", "OverOdds", "UnderOdds",
              "Total", "Sportsbook"}
    if not needed.issubset(odds_df.columns):
        return []

    fair_map = build_fair_prob_map(odds_df)
    if not fair_map:
        return []

    now = datetime.now(tz=timezone.utc)
    picks: list[dict] = []
    for gid, g in odds_df.groupby("GameID"):
        tot = fair_map.get(str(gid), {}).get("totals")
        if not tot or tot.get("line") is None:
            continue
        fair_line = float(tot["line"])
        home = str(g["HomeTeam"].iloc[0])
        away = str(g["AwayTeam"].iloc[0])
        if not home or not away:
            continue
        # Only log a true *opening* — skip games already started.
        if "CommenceTime" in g.columns:
            ct = str(g["CommenceTime"].iloc[0] or "")
            try:
                if ct and datetime.fromisoformat(ct.replace("Z", "+00:00")) <= now:
                    continue
            except ValueError:
                pass

        bettable = g[~g["Sportsbook"].isin(_NON_DESTINATION_BOOKS)]
        same_line = bettable[
            pd.to_numeric(bettable["Total"], errors="coerce") == fair_line
        ]
        if same_line.empty:
            continue

        for side, direction, odds_col in (("over", "OVER", "OverOdds"),
                                          ("under", "UNDER", "UnderOdds")):
            fair_p = tot.get(side)
            if not fair_p or fair_p <= 0:
                continue
            prices = pd.to_numeric(same_line[odds_col], errors="coerce").dropna()
            if prices.empty:
                continue
            best_idx = prices.idxmax()
            best_odds = int(prices.loc[best_idx])
            book = str(same_line.loc[best_idx, "Sportsbook"])
            implied = _implied_from_american(best_odds)
            if pd.isna(implied) or implied <= 0:
                continue
            ev_pct = (fair_p / implied - 1.0) * 100.0
            if ev_pct < _MIN_EV_PCT:
                continue
            picks.append({
                "sport":      sport,
                "market":     "total",
                "direction":  direction,
                "team":       f"{direction} {fair_line}",
                "matchup":    f"{away} @ {home}",
                "odds":       best_odds,
                "line":       fair_line,
                "sportsbook": book,
                "model_prob": round(float(fair_p), 4),
                "edge_pct":   round(float(ev_pct), 2),
            })
    return picks


def consensus_ev(odds_df: pd.DataFrame, sport: str) -> list[dict]:
    """Positive-EV moneyline picks vs the CROSS-BOOK consensus (Kaunitz 2017).

    Where devig_ev anchors on Pinnacle's devig, this anchors on the MEDIAN of
    every book's own self-devigged probability — Kaunitz et al.
    (arXiv:1710.02824) showed the cross-book consensus is a ~R²=0.999
    probability estimate and that betting single books priced above it was +EV
    over 479k games (median, not mean, on our ~5-8 book boards — see
    consensus.loo_consensus). The destination book is left OUT of its own
    consensus (leave-one-out): a lagging book must not drag the reference
    toward itself, because that lag is exactly the signal. Requires ≥MIN_BOOKS
    books in the LOO set; same EV bar as devig_ev so the two anchors grade
    head-to-head under the 300-bet verdict rule.

    Handles BOTH market shapes:
      - 2-way (MLB/WNBA/MMA/tennis): per-book devig over (picked, other).
      - 3-way (soccer): the draw carries 15-30% of the mass, so each book is
        devigged over its FULL (picked, other, draw) simplex — DrawOdds comes
        through the parser now. Books quoting a 3-way game without a draw
        price are excluded from the consensus outright (a partial simplex
        can't be devigged honestly), though they remain valid destinations
        for HOME/AWAY picks (never for DRAW — no draw quote, no draw bet).
        DRAW is a full side: the public hates betting draws, so books shade
        them softest — Kaunitz's +EV soccer sample leaned on exactly this
        outcome. Its `team` is draw_team(away, home) = "Draw (Away @ Home)":
        the matchup packed into the team string keeps every (date, team) join
        key unique across the slate (a bare "draw" collides), and entry_fair/
        closing joins resolve it matchup-scoped via the same helper.
    """
    if odds_df is None or odds_df.empty:
        return []
    home_ml = "HomeMoneyline" if "HomeMoneyline" in odds_df.columns else "HomeOdds"
    away_ml = "AwayMoneyline" if "AwayMoneyline" in odds_df.columns else "AwayOdds"
    needed = {"GameID", "HomeTeam", "AwayTeam", home_ml, away_ml, "Sportsbook"}
    if not needed.issubset(odds_df.columns):
        return []
    is_draw_sport = any(tok in sport.lower() for tok in _DRAW_MARKET_TOKENS)
    has_draw_col = "DrawOdds" in odds_df.columns

    now = datetime.now(tz=timezone.utc)
    picks: list[dict] = []
    for _gid, g in odds_df.groupby("GameID"):
        home = str(g["HomeTeam"].iloc[0])
        away = str(g["AwayTeam"].iloc[0])
        if not home or not away:
            continue
        # Only log a true *opening* — skip games already started.
        if "CommenceTime" in g.columns:
            ct = str(g["CommenceTime"].iloc[0] or "")
            try:
                if ct and datetime.fromisoformat(ct.replace("Z", "+00:00")) <= now:
                    continue
            except ValueError:
                pass

        sided = g.dropna(subset=[home_ml, away_ml])
        if is_draw_sport:
            # 3-way market: a consensus book must quote the whole simplex.
            # Don't rely on the overround floor to catch a missing draw — on
            # extreme-favorite games the 2-way sum can sneak past 0.95.
            if not has_draw_col:
                continue
            sided = sided.dropna(subset=["DrawOdds"])

        def _side_tuples(*cols: str) -> dict[str, tuple]:
            """Per-book price tuples with the picked side FIRST — per_book_fair
            devigs element 0 against the whole tuple, so order IS the side."""
            out: dict[str, tuple] = {}
            for _, r in sided.iterrows():
                book = str(r["Sportsbook"])
                if book:
                    out[book] = tuple(r[c] for c in cols)
            return out

        draw_cols = ["DrawOdds"] if is_draw_sport else []
        side_tuples = {"home": _side_tuples(home_ml, away_ml, *draw_cols),
                       "away": _side_tuples(away_ml, home_ml, *draw_cols)}
        sides = [("home", "HOME", home_ml), ("away", "AWAY", away_ml)]
        if is_draw_sport:
            side_tuples["draw"] = _side_tuples("DrawOdds", home_ml, away_ml)
            sides.append(("draw", "DRAW", "DrawOdds"))

        bettable = g[~g["Sportsbook"].isin(_NON_DESTINATION_BOOKS)]
        if bettable.empty:
            continue

        for side, direction, odds_col in sides:
            if odds_col not in bettable.columns:
                continue
            prices = pd.to_numeric(bettable[odds_col], errors="coerce").dropna()
            if prices.empty:
                continue
            # Best price for the bettor = highest American odds.
            best_idx = prices.idxmax()
            best_odds = int(prices.loc[best_idx])
            book = str(bettable.loc[best_idx, "Sportsbook"])
            fair_by_book = per_book_fair(side_tuples[side])
            cons = loo_consensus(fair_by_book, exclude=book)
            if cons is None:
                continue
            cons_p, _n_books = cons
            implied = _implied_from_american(best_odds)
            if pd.isna(implied) or implied <= 0 or cons_p <= 0:
                continue
            ev_pct = (cons_p / implied - 1.0) * 100.0
            if ev_pct < CONSENSUS_MIN_EV_PCT:
                continue
            team = (home if side == "home"
                    else away if side == "away"
                    else draw_team(away, home))
            picks.append({
                "sport":      sport,
                "market":     "moneyline",
                "direction":  direction,
                "team":       team,
                "matchup":    f"{away} @ {home}",
                "odds":       best_odds,
                "sportsbook": book,
                # model_prob carries the LOO consensus prob (not an ML pred) so
                # the CLV-by-strategy view shows what we thought was true.
                "model_prob": round(float(cons_p), 4),
                "edge_pct":   round(float(ev_pct), 2),
            })
    return picks


def _modal_line(values: pd.Series) -> float | None:
    """Most common line across the board — the consensus market's OWN line
    (devig_ev_totals anchors on Pinnacle's line instead; that's the point of
    difference). Ties break toward the line closest to the overall median."""
    nums = pd.to_numeric(values, errors="coerce").dropna()
    if nums.empty:
        return None
    counts = Counter(float(v) for v in nums)
    top = max(counts.values())
    tied = [ln for ln, c in counts.items() if c == top]
    med = float(nums.median())
    return min(tied, key=lambda ln: (abs(ln - med), ln))


def _consensus_two_way_line(g: pd.DataFrame, line_col: str, a_odds_col: str,
                            b_odds_col: str) -> tuple | None:
    """Shared body for consensus totals/spreads: restrict the board to the
    modal line, devig each book against itself there, and return
    (line, at_line_df, fair_a_by_book) — fair prob of the A side (over/home).
    None when there's no modal line or the board at it is unusable."""
    sided = g.dropna(subset=[line_col, a_odds_col, b_odds_col])
    if sided.empty:
        return None
    line = _modal_line(sided[line_col])
    if line is None:
        return None
    at_line = sided[pd.to_numeric(sided[line_col], errors="coerce") == line]
    pairs: dict[str, tuple] = {}
    for _, r in at_line.iterrows():
        book = str(r["Sportsbook"])
        if book:
            pairs[book] = (r[a_odds_col], r[b_odds_col])
    return line, at_line, per_book_fair(pairs)


def consensus_ev_totals(odds_df: pd.DataFrame, sport: str) -> list[dict]:
    """Positive-EV totals vs the cross-book consensus — consensus_ev applied to
    the totals market. The reference line is the board's MODAL line (the number
    most books agree the game lives at), and only books quoting exactly that
    line join the consensus or qualify as destinations — a different total is a
    different bet, so a half-run of line difference must never masquerade as
    price EV (same guard as devig_ev_totals). Totals are inherently two-way,
    so the soccer/3-way skip doesn't apply.
    """
    if odds_df is None or odds_df.empty:
        return []
    needed = {"GameID", "HomeTeam", "AwayTeam", "OverOdds", "UnderOdds",
              "Total", "Sportsbook"}
    if not needed.issubset(odds_df.columns):
        return []

    now = datetime.now(tz=timezone.utc)
    picks: list[dict] = []
    for _gid, g in odds_df.groupby("GameID"):
        home = str(g["HomeTeam"].iloc[0])
        away = str(g["AwayTeam"].iloc[0])
        if not home or not away:
            continue
        # Only log a true *opening* — skip games already started.
        if "CommenceTime" in g.columns:
            ct = str(g["CommenceTime"].iloc[0] or "")
            try:
                if ct and datetime.fromisoformat(ct.replace("Z", "+00:00")) <= now:
                    continue
            except ValueError:
                pass

        res = _consensus_two_way_line(g, "Total", "OverOdds", "UnderOdds")
        if res is None:
            continue
        line, at_line, fair_over_by_book = res
        bettable = at_line[~at_line["Sportsbook"].isin(_NON_DESTINATION_BOOKS)]
        if bettable.empty:
            continue

        for side, direction, odds_col in (("over", "OVER", "OverOdds"),
                                          ("under", "UNDER", "UnderOdds")):
            prices = pd.to_numeric(bettable[odds_col], errors="coerce").dropna()
            if prices.empty:
                continue
            best_idx = prices.idxmax()
            best_odds = int(prices.loc[best_idx])
            book = str(bettable.loc[best_idx, "Sportsbook"])
            cons = loo_consensus(fair_over_by_book, exclude=book)
            if cons is None:
                continue
            cons_over, _n = cons
            cons_p = cons_over if side == "over" else 1.0 - cons_over
            implied = _implied_from_american(best_odds)
            if pd.isna(implied) or implied <= 0 or cons_p <= 0:
                continue
            ev_pct = (cons_p / implied - 1.0) * 100.0
            if ev_pct < CONSENSUS_MIN_EV_PCT:
                continue
            picks.append({
                "sport":      sport,
                "market":     "total",
                "direction":  direction,
                "team":       f"{direction} {line}",
                "matchup":    f"{away} @ {home}",
                "odds":       best_odds,
                "line":       line,
                "sportsbook": book,
                "model_prob": round(float(cons_p), 4),
                "edge_pct":   round(float(ev_pct), 2),
            })
    return picks


def consensus_ev_spreads(odds_df: pd.DataFrame, sport: str) -> list[dict]:
    """Positive-EV spreads/run lines vs the cross-book consensus.

    Same shape as consensus_ev_totals: modal HOME line across the board, only
    books at exactly that number join the consensus or qualify as destinations,
    median LOO consensus of each book's own two-sided devig. A pick's `line` is
    signed from the picked team's perspective (home = modal, away = -modal),
    matching how model spread picks are recorded in picks.json.
    """
    if odds_df is None or odds_df.empty:
        return []
    needed = {"GameID", "HomeTeam", "AwayTeam", "HomeSpread",
              "HomeSpreadOdds", "AwaySpreadOdds", "Sportsbook"}
    if not needed.issubset(odds_df.columns):
        return []

    now = datetime.now(tz=timezone.utc)
    picks: list[dict] = []
    for _gid, g in odds_df.groupby("GameID"):
        home = str(g["HomeTeam"].iloc[0])
        away = str(g["AwayTeam"].iloc[0])
        if not home or not away:
            continue
        # Only log a true *opening* — skip games already started.
        if "CommenceTime" in g.columns:
            ct = str(g["CommenceTime"].iloc[0] or "")
            try:
                if ct and datetime.fromisoformat(ct.replace("Z", "+00:00")) <= now:
                    continue
            except ValueError:
                pass

        res = _consensus_two_way_line(g, "HomeSpread",
                                      "HomeSpreadOdds", "AwaySpreadOdds")
        if res is None:
            continue
        line, at_line, fair_home_by_book = res
        bettable = at_line[~at_line["Sportsbook"].isin(_NON_DESTINATION_BOOKS)]
        if bettable.empty:
            continue

        for side, direction, odds_col in (("home", "HOME", "HomeSpreadOdds"),
                                          ("away", "AWAY", "AwaySpreadOdds")):
            prices = pd.to_numeric(bettable[odds_col], errors="coerce").dropna()
            if prices.empty:
                continue
            best_idx = prices.idxmax()
            best_odds = int(prices.loc[best_idx])
            book = str(bettable.loc[best_idx, "Sportsbook"])
            cons = loo_consensus(fair_home_by_book, exclude=book)
            if cons is None:
                continue
            cons_home, _n = cons
            cons_p = cons_home if side == "home" else 1.0 - cons_home
            implied = _implied_from_american(best_odds)
            if pd.isna(implied) or implied <= 0 or cons_p <= 0:
                continue
            ev_pct = (cons_p / implied - 1.0) * 100.0
            if ev_pct < CONSENSUS_MIN_EV_PCT:
                continue
            picks.append({
                "sport":      sport,
                "market":     "spread",
                "direction":  direction,
                "team":       home if side == "home" else away,
                "matchup":    f"{away} @ {home}",
                "odds":       best_odds,
                "line":       line if side == "home" else -line,
                "sportsbook": book,
                "model_prob": round(float(cons_p), 4),
                "edge_pct":   round(float(ev_pct), 2),
            })
    return picks


# name -> strategy function. Add new strategies here (see plan doc Phase 2).
STRATEGIES = {
    "fav_longshot":         fav_longshot,
    "devig_ev":             devig_ev,
    "devig_ev_totals":      devig_ev_totals,
    "consensus_ev":         consensus_ev,
    "consensus_ev_totals":  consensus_ev_totals,
    "consensus_ev_spreads": consensus_ev_spreads,
}

# Strategies with a RETIRE verdict from the 300-bet no-vig CLV rule. Kept in
# STRATEGIES so history stays queryable and an explicit
# log_shadow_strategies(strategies=[...]) can still resurrect one for a re-test,
# but the default daily run stops logging them — a settled negative verdict
# doesn't need more sample.
# fav_longshot: RETIRED 2026-07-12 — avg CLV -2.48% at n=344 (chef.py clv).
RETIRED_STRATEGIES = {"fav_longshot"}


# ── Logger ──────────────────────────────────────────────────────────────────

def _load_picks() -> dict:
    if not PICKS_FILE.exists():
        return {"picks": []}
    try:
        blob = json.loads(PICKS_FILE.read_text())
        return blob if isinstance(blob, dict) else {"picks": blob}
    except (json.JSONDecodeError, ValueError, OSError):
        return {"picks": []}


def log_shadow_strategies(date_str: str | None = None,
                          sports: list[str] | None = None,
                          strategies: list[str] | None = None) -> int:
    """Run each registered strategy for each sport, log the shadow picks to
    picks.json (card_pick=False, stake=0, tagged with `strategy`), then snapshot
    their opening lines. Idempotent — picks already present are skipped.

    Returns the number of new shadow picks logged.
    """
    eff_date = date_str or _date.today().isoformat()
    if sports is None:
        # Static in-season set + whatever tennis tournaments are live right now
        # (tennis keys rotate per tournament; discovery is a free /sports call).
        sports = DEFAULT_SPORTS + _active_tennis_sports()
    strat_names = strategies or [n for n in STRATEGIES
                                 if n not in RETIRED_STRATEGIES]
    now_ts = datetime.now(tz=timezone.utc).isoformat()

    # Read-only: the ids we already hold, so a re-run is idempotent. The write
    # itself goes through append_picks_safe (locked + atomic), so this snapshot
    # is never the basis for rewriting the ledger — see the `fresh` list below.
    existing_ids = {p.get("pick_id") for p in _load_picks().get("picks", [])
                    if isinstance(p, dict)}
    fresh: list[dict] = []

    added = 0
    for sport in sports:
        try:
            odds_df = fetch_odds(markets="h2h,spreads,totals", sport=sport, refresh=True)
        except Exception as e:
            print(f"  [shadow] {sport}: odds fetch failed — {e}")
            continue
        if odds_df is None or odds_df.empty:
            continue

        # Restrict to TODAY'S slate (ET). The odds feed returns future fixtures
        # (e.g. the whole World Cup schedule), but a shadow pick must be a today's-
        # game opening — otherwise its close lands in a future-dated archive and the
        # CLV join (±1 day) never matches it, orphaning the pick.
        #
        # FAIL SAFE: the today-filter is the only thing standing between us and
        # logging the entire future schedule stamped with a single date. If the
        # feed comes back without CommenceTime we CANNOT confirm a game is today,
        # so we skip the sport rather than dump the whole bracket (the 2026-06-16
        # World Cup incident: 51 fixtures across the tournament logged under one
        # date because this guard silently no-op'd on a missing column).
        if "CommenceTime" not in odds_df.columns:
            print(f"  [shadow] {sport}: odds feed missing CommenceTime — cannot "
                  f"confirm today's slate; skipping to avoid logging the full "
                  f"future schedule under one date")
            continue
        def _is_today(ct) -> bool:
            try:
                dt = datetime.fromisoformat(str(ct).replace("Z", "+00:00"))
                return dt.astimezone(_ET).date().isoformat() == eff_date
            except (ValueError, TypeError):
                return False
        odds_df = odds_df[odds_df["CommenceTime"].map(_is_today)]
        if odds_df.empty:
            continue

        for name in strat_names:
            fn = STRATEGIES.get(name)
            if fn is None:
                continue
            for raw in fn(odds_df, sport):
                pick = normalize_pick({
                    **raw,
                    "date":      eff_date,
                    "stake":     0.0,
                    "card_pick": False,
                    "strategy":  name,
                    "recorded_at": now_ts,
                })
                if pick is None:
                    continue
                # Namespace the id by strategy so different strategies that land
                # on the same team/market/direction don't collide or dedup.
                pick["pick_id"] = f"{name}__{pick['pick_id']}"
                if pick["pick_id"] in existing_ids:
                    continue
                fresh.append(pick)
                existing_ids.add(pick["pick_id"])

    if fresh:
        # THE LEDGER IS NEVER REWRITTEN FROM A SNAPSHOT HERE. This used to be
        # `PICKS_FILE.write_text(blob)`: a lock-free, non-atomic read-modify-
        # write of the canonical record. Two failure modes, both catastrophic
        # and both silent — a crash mid-write truncates picks.json, and
        # `_load_picks()` answers a truncated file with `{"picks": []}`, so the
        # NEXT run would happily "append" today's shadow picks to nothing and
        # write the whole history away. A concurrent append_picks_safe writer
        # (grid_runner, chef) was also simply lost, last-writer-wins.
        # append_picks_safe holds the exclusive lock, re-reads inside it, and
        # renames atomically — and it is the normalization choke point.
        from src.tracking.schema import append_picks_safe
        added = append_picks_safe(PICKS_FILE, fresh)
        # Snapshot opening lines for the new shadow picks (reuses CLV engine).
        try:
            from src.analytics.clv_tracker import snapshot_from_pnl
            snapshot_from_pnl(eff_date)
        except Exception as e:
            print(f"  [shadow] snapshot warning: {e}")

    return added

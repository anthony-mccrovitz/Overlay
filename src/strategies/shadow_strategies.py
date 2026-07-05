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
from datetime import date as _date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

_ET = ZoneInfo("America/New_York")

from src.data.odds_api import fetch_odds
from src.data.pinnacle_fair import build_fair_prob_map
from src.tracking.schema import normalize_pick, make_pick_id

PICKS_FILE = Path("data/pnl/picks.json")


def _implied_from_american(odds: float) -> float:
    """American odds → implied (with-vig) probability. NaN-safe."""
    if odds is None or pd.isna(odds) or odds == 0:
        return float("nan")
    return 100.0 / (odds + 100.0) if odds > 0 else abs(odds) / (abs(odds) + 100.0)

# Odds API sport keys to log shadow picks for. Defaults to the in-season set;
# a sport with no games today returns empty (one cheap call) and is skipped.
DEFAULT_SPORTS = [
    "baseball_mlb",
    "basketball_wnba",
    "soccer_fifa_world_cup",
]


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
    before a dollar is risked. Moneyline only for now; the CLV close-capture is
    proven there. Totals/spread are the next step (fair_map already carries them).
    """
    if odds_df is None or odds_df.empty:
        return []
    # Three-way (draw) markets can't be devigged two-way — would print phantom EV.
    if any(tok in sport.lower() for tok in _DRAW_MARKET_TOKENS):
        return []
    home_ml = "HomeMoneyline" if "HomeMoneyline" in odds_df.columns else "HomeOdds"
    away_ml = "AwayMoneyline" if "AwayMoneyline" in odds_df.columns else "AwayOdds"
    needed = {"GameID", "HomeTeam", "AwayTeam", home_ml, away_ml, "Sportsbook"}
    if not needed.issubset(odds_df.columns):
        return []

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

        # Sanity-check this is a real two-way market. Vig is a PER-BOOK property,
        # so judge it by a single SHARP book's two-sided implied sum — Pinnacle if
        # present, else the median per-book overround (robust to one off book).
        # Don't use min(): an off soft book legitimately sums <1.0, and that's the
        # +EV signal, not a malformed market. A clean 2-way reference sits
        # ~1.02-1.10; a 3-way slice missing the draw (soccer) has EVERY book <1.0.
        sided = g.dropna(subset=[home_ml, away_ml])
        per_book = [
            _implied_from_american(r[home_ml]) + _implied_from_american(r[away_ml])
            for _, r in sided.iterrows()
        ]
        per_book = [o for o in per_book if not pd.isna(o)]
        if not per_book:
            continue
        pin = sided[sided["Sportsbook"] == "Pinnacle"]
        if not pin.empty:
            ref_overround = (_implied_from_american(pin.iloc[0][home_ml])
                             + _implied_from_american(pin.iloc[0][away_ml]))
        else:
            ref_overround = float(pd.Series(per_book).median())
        if not (_OVERROUND_MIN <= ref_overround <= _OVERROUND_MAX):
            continue

        for side, direction, odds_col in (("home", "HOME", home_ml),
                                          ("away", "AWAY", away_ml)):
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
            picks.append({
                "sport":      sport,
                "market":     "moneyline",
                "direction":  direction,
                "team":       home if side == "home" else away,
                "matchup":    f"{away} @ {home}",
                "odds":       best_odds,
                "sportsbook": book,
                # model_prob carries the devig FAIR prob here (not an ML pred) so
                # the CLV-by-strategy view shows what we thought was true.
                "model_prob": round(float(fair_p), 4),
                "edge_pct":   round(float(ev_pct), 2),
            })
    return picks


# name -> strategy function. Add new strategies here (see plan doc Phase 2).
STRATEGIES = {
    "fav_longshot": fav_longshot,
    "devig_ev":     devig_ev,
}


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
    sports = sports or DEFAULT_SPORTS
    strat_names = strategies or list(STRATEGIES)
    now_ts = datetime.now(tz=timezone.utc).isoformat()

    blob = _load_picks()
    all_picks = blob.setdefault("picks", [])
    existing_ids = {p.get("pick_id") for p in all_picks if isinstance(p, dict)}

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
                all_picks.append(pick)
                existing_ids.add(pick["pick_id"])
                added += 1

    if added:
        PICKS_FILE.write_text(json.dumps(blob, indent=2))
        # Snapshot opening lines for the new shadow picks (reuses CLV engine).
        try:
            from src.analytics.clv_tracker import snapshot_from_pnl
            snapshot_from_pnl(eff_date)
        except Exception as e:
            print(f"  [shadow] snapshot warning: {e}")

    return added

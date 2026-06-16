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
from src.tracking.schema import normalize_pick, make_pick_id

PICKS_FILE = Path("data/pnl/picks.json")

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


# name -> strategy function. Add new strategies here (see plan doc Phase 2).
STRATEGIES = {
    "fav_longshot": fav_longshot,
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
        if "CommenceTime" in odds_df.columns:
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

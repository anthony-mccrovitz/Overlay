"""
Value bet identification — multi-market.

Compares model predictions against sportsbook odds to find games
where the model disagrees with the market — these are potential edges.

Supports moneyline, spreads, totals, and prop bets.
"""
import pandas as pd
import numpy as np

from src.betting.markets import BetType
from src.models.bias import adjusted_edge
from src.analytics.calibration import apply_calibration

# Edges above this are almost always bad odds / wrong market in the feed, not real +EV.
_MAX_SANE_MONEYLINE_EDGE = 0.20


def find_value_bets(
    predictions: dict[tuple[str, str], float],
    odds_df: pd.DataFrame,
    min_edge: float = 0.03,
    market: BetType = BetType.MONEYLINE,
    fair_prob_map: dict | None = None,
    sport: str = "mlb",
) -> pd.DataFrame:
    """
    Find games where model disagrees with market odds.

    Args:
        predictions: Dict of (team_a, team_b) → P(team_a wins) for binary markets,
                     or (home, away) → predicted_total for totals,
                     or (home, away) → predicted_margin for spreads.
        odds_df: DataFrame from odds_api.get_best_odds(market=...)
        min_edge: Minimum edge to flag as value bet (default 3% for binary, 0.5 runs for continuous)
        market: Which market to detect value in
        fair_prob_map: Optional {GameID: {market: {side: fair_prob, ...}}} from
                       src.data.pinnacle_fair.build_fair_prob_map(raw_odds_df).
                       When provided, edge is computed against Pinnacle no-vig fair
                       prob instead of the best soft-book implied prob — eliminates
                       the systematic edge inflation that comes from comparing to a
                       book offering 4-8% vig.

    Returns:
        DataFrame with value bets, sorted by edge (highest first)
    """
    if odds_df.empty:
        print(f"  No odds data available for {market.value}. Skipping.")
        return pd.DataFrame()

    if market == BetType.MONEYLINE:
        return _find_moneyline_value(predictions, odds_df, min_edge, fair_prob_map, sport)
    elif market == BetType.SPREAD:
        return _find_spread_value(predictions, odds_df, min_edge, sport)
    elif market == BetType.TOTAL:
        return _find_totals_value(predictions, odds_df, min_edge, sport)
    else:
        return _find_moneyline_value(predictions, odds_df, min_edge, fair_prob_map, sport)


def flag_high_edge_picks(edges: list[dict], threshold_pct: float = 8.0) -> list[dict]:
    """Return edges that exceed threshold vs implied prob — flag for manual review.

    Any edge above threshold_pct is suspicious (stale line, data error, or genuine
    but rare alpha). Return the flagged list; caller decides whether to warn or block.
    """
    return [e for e in edges if abs(float(e.get("edge_pct") or 0)) > threshold_pct]


def model_recent_clv(sport: str, market: str, n: int = 30) -> float | None:
    """Return avg CLV cents over the last `n` settled picks for this (sport, market).

    Returns None if fewer than 10 picks — not enough signal to gate on.
    Used by runners to decide whether to set card_pick=True: if recent CLV is
    negative, the model is bleeding edge to the close and should stay shadow.

    Per 2026-05-19 plan: card_pick=True requires non-negative CLV on rolling sample.
    """
    import json
    from pathlib import Path

    clv_path = Path("data/clv/clv_records.json")
    if not clv_path.exists():
        return None
    try:
        records = json.loads(clv_path.read_text()).get("picks", [])
    except Exception:
        return None

    sport_n = (sport or "").lower()
    # Normalize MLB/NBA sport aliases
    for alias in ("baseball_", "basketball_", "icehockey_"):
        sport_n = sport_n.replace(alias, "")

    relevant = [
        r for r in records
        if (r.get("sport") or "").lower().replace("baseball_","").replace("basketball_","") == sport_n
        and r.get("clv_cents") is not None
    ]
    relevant.sort(key=lambda r: r.get("pick_time") or "", reverse=True)
    sample = relevant[:n]
    if len(sample) < 10:
        return None
    return sum(r["clv_cents"] for r in sample) / len(sample)


def _find_moneyline_value(
    predictions: dict[tuple[str, str], float],
    odds_df: pd.DataFrame,
    min_edge: float,
    fair_prob_map: dict | None = None,
    sport: str = "mlb",
) -> pd.DataFrame:
    bets = []

    for _, row in odds_df.iterrows():
        home = row.get("HomeTeam", "")
        away = row.get("AwayTeam", "")

        if (home, away) in predictions:
            model_prob_home = predictions[(home, away)]
            model_prob_away = 1 - model_prob_home
        elif (away, home) in predictions:
            model_prob_away = predictions[(away, home)]
            model_prob_home = 1 - model_prob_away
        else:
            continue

        # Apply Platt/isotonic calibration trained from settled picks so the
        # model_prob written to picks.json is the post-calibration number that
        # the edge was actually computed against.
        model_prob_home = apply_calibration(model_prob_home, sport, "moneyline")
        model_prob_away = 1.0 - model_prob_home

        best_home_ml = row.get("BestHomeML", 0)
        best_away_ml = row.get("BestAwayML", 0)

        # Skip games with no real moneyline (live games, books have pulled lines)
        if pd.isna(best_home_ml) or pd.isna(best_away_ml):
            continue

        # ── Pinnacle-anchored fair probability (preferred) ───────────────
        # Falls back to the best-book implied prob (which is inflated by vig)
        # only if Pinnacle/median devig isn't available for this game.
        implied_home = row.get("HomeImpliedProb", 0.5)
        implied_away = row.get("AwayImpliedProb", 0.5)
        if fair_prob_map:
            gid = row.get("GameID", "")
            g = fair_prob_map.get(gid)
            if g and "h2h" in g:
                implied_home = g["h2h"].get("home", implied_home)
                implied_away = g["h2h"].get("away", implied_away)

        # Sharp disagreement gate: if Pinnacle is confidently on the other side
        # (their fair prob < 45% for our pick), require 1.5x edge to go against
        # the sharpest book in the world. Most retail edges are noise vs Pinnacle.
        pin_source = "median"
        if fair_prob_map:
            gid = row.get("GameID", "")
            g = fair_prob_map.get(gid)
            if g and "h2h" in g:
                pin_source = g["h2h"].get("source", "median")
        _sharp_mult = 1.5 if (pin_source == "pinnacle" and implied_home < 0.45) else 1.0

        # FLS guard: heavy underdogs (implied < 0.33, i.e. longer than +200) require
        # Pinnacle source AND 2x edge. Longshot bias means these picks fail at high
        # rates regardless of model edge — Snowberg & Wolfers 2010 confirms no EV.
        if implied_home < 0.33:
            if pin_source != "pinnacle":
                # No Pinnacle anchor on a heavy dog → skip entirely (per 2026-05-19 plan)
                continue
            _sharp_mult = max(_sharp_mult, 2.0)

        edge_home = adjusted_edge(model_prob_home, implied_home) / 100
        _min_home = (min_edge * _sharp_mult) if implied_home >= 0.33 else max(0.10, min_edge * _sharp_mult)
        if edge_home >= _min_home:
            bets.append({
                "Team": home, "Opponent": away,
                "ModelProb": model_prob_home, "ImpliedProb": implied_home,
                "Edge": edge_home,
                "BestOdds": best_home_ml,
                "Sportsbook": row.get("BestHomeSportsbook", ""),
                "Spread": row.get("ConsensusSpread", 0),
                "CommenceTime": row.get("CommenceTime", ""),
                "Market": "moneyline",
                "pin_source": pin_source,
            })

        _sharp_mult_away = 1.5 if (pin_source == "pinnacle" and implied_away < 0.45) else 1.0
        if implied_away < 0.33:
            if pin_source != "pinnacle":
                continue  # plan: no Pinnacle anchor on heavy dog → no bet
            _sharp_mult_away = max(_sharp_mult_away, 2.0)
        edge_away = adjusted_edge(model_prob_away, implied_away) / 100
        _min_away = (min_edge * _sharp_mult_away) if implied_away >= 0.33 else max(0.10, min_edge * _sharp_mult_away)
        if edge_away >= _min_away:
            bets.append({
                "Team": away, "Opponent": home,
                "ModelProb": model_prob_away, "ImpliedProb": implied_away,
                "Edge": edge_away,
                "BestOdds": best_away_ml,
                "Sportsbook": row.get("BestAwaySportsbook", ""),
                "Spread": row.get("ConsensusSpread", 0),
                "CommenceTime": row.get("CommenceTime", ""),
                "Market": "moneyline",
                "pin_source": pin_source,
            })

    if not bets:
        print("  No moneyline value bets found above minimum edge threshold.")
        return pd.DataFrame()

    df = pd.DataFrame(bets)
    n0 = len(df)
    df = df[df["Edge"] <= _MAX_SANE_MONEYLINE_EDGE].reset_index(drop=True)
    if n0 > len(df):
        print(
            f"  Dropped {n0 - len(df)} ML row(s) with edge > {_MAX_SANE_MONEYLINE_EDGE:.0%} (likely bad odds)."
        )

    # Deduplicate: keep best edge per team per game matchup
    if not df.empty:
        df["_game_key"] = df.apply(
            lambda r: tuple(sorted([r["Team"], r["Opponent"]])), axis=1
        )
        df = (
            df.sort_values("Edge", ascending=False)
            .drop_duplicates(subset=["Team", "_game_key"])
            .drop(columns=["_game_key"])
            .reset_index(drop=True)
        )

    return df.sort_values("Edge", ascending=False).reset_index(drop=True)


def _find_spread_value(
    predictions: dict[tuple[str, str], float],
    odds_df: pd.DataFrame,
    min_edge: float,
    sport: str = "mlb",
) -> pd.DataFrame:
    """predictions values are model-implied margins (home - away)."""
    from src.models.mlb_spreads import win_prob_to_margin

    bets = []
    for _, row in odds_df.iterrows():
        home = row.get("HomeTeam", "")
        away = row.get("AwayTeam", "")
        market_spread = row.get("HomeSpread", row.get("ConsensusSpread"))
        if pd.isna(market_spread):
            continue

        if (home, away) in predictions:
            model_prob = predictions[(home, away)]
        elif (away, home) in predictions:
            model_prob = 1 - predictions[(away, home)]
        else:
            continue

        model_margin = win_prob_to_margin(model_prob)
        edge = model_margin - market_spread

        if abs(edge) >= min_edge:
            if edge > 0:
                team, opponent = home, away
                direction = f"{home} {market_spread:+.1f}"
                best_odds = row.get("BestHomeSpreadOdds", -110)
                best_book = row.get("BestHomeSpreadBook", "")
            else:
                team, opponent = away, home
                direction = f"{away} {-market_spread:+.1f}"
                best_odds = row.get("BestAwaySpreadOdds", -110)
                best_book = row.get("BestAwaySpreadBook", "")

            from src.data.odds_api import _american_to_prob
            implied = _american_to_prob(best_odds) if best_odds else 0.5

            bets.append({
                "Team": team, "Opponent": opponent,
                "ModelProb": round(model_prob if team == home else 1 - model_prob, 3),
                "ImpliedProb": implied,
                "Edge": abs(edge),
                "BestOdds": int(best_odds) if best_odds else -110,
                "Sportsbook": best_book or "",
                "Spread": market_spread,
                "Direction": direction,
                "ModelMargin": round(model_margin, 2),
                "CommenceTime": row.get("CommenceTime", ""),
                "Market": "spread",
            })

    if not bets:
        print("  No spread value bets found above minimum edge threshold.")
        return pd.DataFrame()

    df = pd.DataFrame(bets)
    return df.sort_values("Edge", ascending=False).reset_index(drop=True)


def _find_totals_value(
    predictions: dict[tuple[str, str], float],
    odds_df: pd.DataFrame,
    min_edge: float,
    sport: str = "mlb",
) -> pd.DataFrame:
    """predictions values are predicted game totals."""
    bets = []
    for _, row in odds_df.iterrows():
        home = row.get("HomeTeam", "")
        away = row.get("AwayTeam", "")
        market_total = row.get("Total")
        if pd.isna(market_total) or not market_total:
            continue

        pred_total = None
        if (home, away) in predictions:
            pred_total = predictions[(home, away)]
        elif (away, home) in predictions:
            pred_total = predictions[(away, home)]
        else:
            continue

        edge = abs(pred_total - market_total)
        if edge < min_edge:
            continue

        if pred_total > market_total:
            direction = "OVER"
            best_odds = row.get("BestOverOdds", -110)
            best_book = row.get("BestOverBook", "")
        else:
            direction = "UNDER"
            best_odds = row.get("BestUnderOdds", -110)
            best_book = row.get("BestUnderBook", "")

        from src.data.odds_api import _american_to_prob
        implied = _american_to_prob(best_odds) if best_odds else 0.5

        bets.append({
            "Team": f"{direction} {market_total}",
            "Opponent": f"{home} vs {away}",
            "ModelProb": 0.0,
            "ImpliedProb": implied,
            "Edge": edge,
            "BestOdds": int(best_odds) if best_odds else -110,
            "Sportsbook": best_book or "",
            "Spread": 0,
            "Direction": direction,
            "PredictedTotal": round(pred_total, 1),
            "MarketTotal": market_total,
            "CommenceTime": row.get("CommenceTime", ""),
            "Market": "total",
        })

    if not bets:
        print("  No totals value bets found above minimum edge threshold.")
        return pd.DataFrame()

    df = pd.DataFrame(bets)
    return df.sort_values("Edge", ascending=False).reset_index(drop=True)


def print_value_bets(bets_df: pd.DataFrame, bankroll: float = 0) -> str:
    """Pretty-print value bets to terminal."""
    if bets_df.empty:
        return "  No value bets identified.\n"

    lines = []
    market_label = ""
    if "Market" in bets_df.columns:
        market_label = f" ({bets_df['Market'].iloc[0].upper()})"

    lines.append(f"\n{'='*70}")
    lines.append(f"  VALUE BETS{market_label} — Model Edge vs Vegas")
    lines.append(f"{'='*70}")

    for _, bet in bets_df.iterrows():
        mkt = bet.get("Market", "moneyline")

        if mkt == "total":
            direction = bet.get("Direction", "")
            pred = bet.get("PredictedTotal", 0)
            line = bet.get("MarketTotal", 0)
            edge_val = bet["Edge"]
            lines.append(f"\n  {bet['Opponent']}")
            lines.append(
                f"    Model Total: {pred} | Market: {line} | "
                f"{direction} by {edge_val:.1f} runs"
            )
            lines.append(
                f"    Best odds: {bet['BestOdds']:+.0f} at {bet['Sportsbook']}"
            )
        elif mkt == "spread":
            lines.append(f"\n  {bet.get('Direction', bet['Team'])} vs {bet['Opponent']}")
            lines.append(
                f"    Model Margin: {bet.get('ModelMargin', 0):+.1f} | "
                f"Market Spread: {bet['Spread']:+.1f} | Edge: {bet['Edge']:.1f} runs"
            )
            lines.append(
                f"    Best odds: {bet['BestOdds']:+.0f} at {bet['Sportsbook']}"
            )
        else:
            edge_pct = bet['Edge'] * 100
            model_pct = bet['ModelProb'] * 100
            implied_pct = bet['ImpliedProb'] * 100
            stars = ""
            if edge_pct >= 10:
                stars = " *** STRONG ***"
            elif edge_pct >= 5:
                stars = " ** GOOD **"

            lines.append(f"\n  {bet['Team']} vs {bet['Opponent']}")
            lines.append(
                f"    Model: {model_pct:.1f}% | Vegas: {implied_pct:.1f}% | "
                f"Edge: +{edge_pct:.1f}%{stars}"
            )
            lines.append(
                f"    Best odds: {bet['BestOdds']:+.0f} at {bet['Sportsbook']}"
            )

    lines.append(f"\n  Total value bets: {len(bets_df)}")
    if "Market" in bets_df.columns and bets_df["Market"].iloc[0] in ("total", "spread"):
        lines.append(f"  Average edge: {bets_df['Edge'].mean():.2f} runs")
    else:
        lines.append(f"  Average edge: +{bets_df['Edge'].mean()*100:.1f}%")
    lines.append(f"{'='*70}\n")

    return "\n".join(lines)



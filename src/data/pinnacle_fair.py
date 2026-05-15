"""
src/data/pinnacle_fair.py — Pinnacle no-vig fair probability helper.

The sharp benchmark for "true" market price is Pinnacle. Soft-book odds carry
vig of 4-8%, so calculating an edge against the best soft price systematically
overstates the edge. Devigging Pinnacle's two-sided market gives the closest
thing to fair probability available pre-game.

This module produces a per-game lookup of Pinnacle fair probabilities for
moneyline, spread, and total markets, plus a fallback that devigs the
median of soft books when Pinnacle isn't present in the feed.

Used by predict.py and run_nba.py to replace soft-book implied probabilities
in edge calculations.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


PINNACLE_KEY = "Pinnacle"


def _american_to_prob(odds: float) -> float:
    if pd.isna(odds) or odds == 0:
        return float("nan")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _devig_two_way(p1: float, p2: float) -> tuple[float, float]:
    """Normalize a two-sided market to sum to 1.0."""
    if pd.isna(p1) or pd.isna(p2):
        return float("nan"), float("nan")
    total = p1 + p2
    if total <= 0:
        return float("nan"), float("nan")
    return p1 / total, p2 / total


def _pick_pinnacle_row(game_df: pd.DataFrame) -> Optional[pd.Series]:
    if game_df.empty or "Sportsbook" not in game_df.columns:
        return None
    pin = game_df[game_df["Sportsbook"] == PINNACLE_KEY]
    if pin.empty:
        return None
    return pin.iloc[0]


def _median_devig(
    game_df: pd.DataFrame, home_col: str, away_col: str
) -> tuple[float, float]:
    """Fallback when Pinnacle is missing: devig the median of soft prices."""
    if home_col not in game_df.columns or away_col not in game_df.columns:
        return float("nan"), float("nan")
    h_med = game_df[home_col].median()
    a_med = game_df[away_col].median()
    if pd.isna(h_med) or pd.isna(a_med):
        return float("nan"), float("nan")
    return _devig_two_way(_american_to_prob(h_med), _american_to_prob(a_med))


def build_fair_prob_map(odds_df: pd.DataFrame) -> dict[str, dict]:
    """
    Build a {GameID: {market: {side: fair_prob, ...}}} map from raw odds_df.

    Output schema per game:
        {
            "h2h":     {"home": p, "away": p, "source": "pinnacle"|"median"},
            "spread":  {"home": {"line": pt, "fair": p}, "away": {...}, "source": ...},
            "totals":  {"line": pt, "over": p, "under": p, "source": ...},
        }

    Missing markets are simply absent. Probabilities are NaN-safe.
    """
    if odds_df is None or odds_df.empty or "GameID" not in odds_df.columns:
        return {}

    out: dict[str, dict] = {}
    for game_id in odds_df["GameID"].unique():
        game = odds_df[odds_df["GameID"] == game_id]
        entry: dict[str, dict] = {}

        # ── Moneyline ──────────────────────────────────────────────────────
        if "HomeMoneyline" in game.columns and "AwayMoneyline" in game.columns:
            pin = _pick_pinnacle_row(game)
            source = "pinnacle"
            if pin is not None and not pd.isna(pin.get("HomeMoneyline")) and not pd.isna(pin.get("AwayMoneyline")):
                ph, pa = _devig_two_way(
                    _american_to_prob(pin["HomeMoneyline"]),
                    _american_to_prob(pin["AwayMoneyline"]),
                )
            else:
                ph, pa = _median_devig(game, "HomeMoneyline", "AwayMoneyline")
                source = "median"
            if not pd.isna(ph) and not pd.isna(pa):
                entry["h2h"] = {"home": float(ph), "away": float(pa), "source": source}

        # ── Spread ─────────────────────────────────────────────────────────
        if "HomeSpreadOdds" in game.columns and "AwaySpreadOdds" in game.columns:
            pin = _pick_pinnacle_row(game)
            source = "pinnacle"
            ph = pa = float("nan")
            home_line = away_line = float("nan")
            if (
                pin is not None
                and not pd.isna(pin.get("HomeSpreadOdds"))
                and not pd.isna(pin.get("AwaySpreadOdds"))
            ):
                ph, pa = _devig_two_way(
                    _american_to_prob(pin["HomeSpreadOdds"]),
                    _american_to_prob(pin["AwaySpreadOdds"]),
                )
                home_line = pin.get("HomeSpread", float("nan"))
                away_line = pin.get("AwaySpread", float("nan"))
            else:
                ph, pa = _median_devig(game, "HomeSpreadOdds", "AwaySpreadOdds")
                source = "median"
                if "HomeSpread" in game.columns:
                    home_line = game["HomeSpread"].median()
                if "AwaySpread" in game.columns:
                    away_line = game["AwaySpread"].median()
            if not pd.isna(ph) and not pd.isna(pa):
                entry["spread"] = {
                    "home": {"line": float(home_line) if not pd.isna(home_line) else None, "fair": float(ph)},
                    "away": {"line": float(away_line) if not pd.isna(away_line) else None, "fair": float(pa)},
                    "source": source,
                }

        # ── Totals ─────────────────────────────────────────────────────────
        if "OverOdds" in game.columns and "UnderOdds" in game.columns:
            pin = _pick_pinnacle_row(game)
            source = "pinnacle"
            po = pu = float("nan")
            line = float("nan")
            if (
                pin is not None
                and not pd.isna(pin.get("OverOdds"))
                and not pd.isna(pin.get("UnderOdds"))
            ):
                po, pu = _devig_two_way(
                    _american_to_prob(pin["OverOdds"]),
                    _american_to_prob(pin["UnderOdds"]),
                )
                line = pin.get("Total", float("nan"))
            else:
                po, pu = _median_devig(game, "OverOdds", "UnderOdds")
                source = "median"
                if "Total" in game.columns:
                    line = game["Total"].median()
            if not pd.isna(po) and not pd.isna(pu):
                entry["totals"] = {
                    "line": float(line) if not pd.isna(line) else None,
                    "over": float(po),
                    "under": float(pu),
                    "source": source,
                }

        if entry:
            out[game_id] = entry

    return out


def fair_prob_for(
    fair_map: dict[str, dict],
    game_id: str,
    market: str,
    side: str,
) -> Optional[float]:
    """
    Convenience getter. Returns None if market/side is missing.

    market in {"h2h", "spread", "totals"}
    side: for h2h/spread → "home"|"away"; for totals → "over"|"under"
    """
    g = fair_map.get(game_id)
    if not g:
        return None
    m = g.get(market)
    if not m:
        return None
    if market == "spread":
        side_entry = m.get(side)
        if isinstance(side_entry, dict):
            return side_entry.get("fair")
        return None
    return m.get(side)

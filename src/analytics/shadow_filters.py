"""Shadow A/B filters — Phase 2.5 thesis-validation gates.

Each filter takes a pick + its team_form snapshot and returns a recommendation
of 'keep' or 'skip'. We DO NOT change card_pick logic — these run in shadow so
we can A/B-compare the live record against "filter applied" on the same dataset.

Three filters, each born from the hot/cold analysis on settled picks:

  mlb_ml_neutral_skip
      MLB moneyline. Drop matchups where neither team is hot or cold.
      Evidence: neutral bucket = 12-18, -15.8% ROI (n=30). Other buckets +7 to +14%.

  mlb_f5_one_cold_only
      MLB F5 totals. Only keep picks where exactly one team is cold.
      Evidence: one_cold = 23-11, +18.3% ROI (n=34). Every other bucket negative.

  mlb_ks_one_hot_only
      MLB pitcher strikeouts. Only keep when exactly one offense is hot. Never fire
      when an offense is cold (strong negative signal).
      Evidence: one_hot = 15-3, +74.1% ROI (n=18). one_cold = 1-17, -80.8% (n=18).

To consume the recommendation in analysis:
    from src.analytics.shadow_filters import classify_form_filter
    rec = classify_form_filter(pick)
    # rec = {'name': 'mlb_ml_neutral_skip', 'recommendation': 'skip', 'reason': '...'}
    # rec = {'name': None, 'recommendation': 'na', 'reason': 'no filter for this market'}
"""
from __future__ import annotations

from typing import Any

HOT_THRESHOLD  = 1.10
COLD_THRESHOLD = 0.90


def _form_class(side: dict | None) -> str:
    """Return 'hot' | 'cold' | 'neutral' | 'unknown' for one team's form."""
    if not side or "form_7d" not in side or not side["form_7d"]:
        return "unknown"
    f7 = side["form_7d"]
    season = side.get("season_rs_per_g")
    if not season or season <= 0 or not f7.get("rs_per_game"):
        return "unknown"
    ratio = f7["rs_per_game"] / season
    if ratio >= HOT_THRESHOLD:
        return "hot"
    if ratio <= COLD_THRESHOLD:
        return "cold"
    return "neutral"


def _matchup_class(team_form: dict | None) -> str:
    """Classify matchup into hot_both / cold_both / mixed / one_hot / one_cold / neutral / unknown."""
    if not team_form:
        return "unknown"
    home_c = _form_class(team_form.get("home"))
    away_c = _form_class(team_form.get("away"))
    if home_c == "unknown" or away_c == "unknown":
        return "unknown"
    if home_c == "hot" and away_c == "hot":
        return "hot_both"
    if home_c == "cold" and away_c == "cold":
        return "cold_both"
    if "hot" in (home_c, away_c) and "cold" in (home_c, away_c):
        return "mixed"
    if "hot" in (home_c, away_c):
        return "one_hot"
    if "cold" in (home_c, away_c):
        return "one_cold"
    return "neutral"


def classify_form_filter(pick: dict[str, Any]) -> dict[str, Any]:
    """Return shadow-filter recommendation for a single pick.

    Output schema:
        {
          "name": filter slug (or None if not applicable),
          "matchup_class": form bucket the pick falls into,
          "recommendation": 'keep' | 'skip' | 'na',
          "reason": one-line human explanation,
        }

    'na' means no shadow filter applies to this market — the pick is unchanged.
    """
    sport  = (pick.get("sport") or "").lower()
    # Normalize odds-api sport keys ("baseball_mlb") to internal slug ("mlb")
    if sport.startswith("baseball_"):
        sport = "mlb"
    elif sport.startswith("basketball_"):
        sport = "nba"
    market = (pick.get("market") or "").lower()
    # Prop picks store the actual market type in prop_market — collapse so
    # the filter can target pitcher_strikeouts regardless of how it was logged.
    if market == "prop":
        market = (pick.get("prop_market") or "prop").lower()
    cls    = _matchup_class(pick.get("team_form"))

    if sport != "mlb":
        return {"name": None, "matchup_class": cls, "recommendation": "na",
                "reason": "no MLB shadow filter for this sport"}

    if cls == "unknown":
        return {"name": None, "matchup_class": cls, "recommendation": "na",
                "reason": "team_form missing or incomplete"}

    if market == "moneyline":
        if cls == "neutral":
            return {"name": "mlb_ml_neutral_skip", "matchup_class": cls,
                    "recommendation": "skip",
                    "reason": "neutral matchup: -15.8% ROI on n=30 in backtest"}
        return {"name": "mlb_ml_neutral_skip", "matchup_class": cls,
                "recommendation": "keep",
                "reason": f"{cls} matchup passes neutral-skip filter"}

    if market == "f5_total":
        if cls == "one_cold":
            return {"name": "mlb_f5_one_cold_only", "matchup_class": cls,
                    "recommendation": "keep",
                    "reason": "one_cold: +18.3% ROI on n=34 in backtest"}
        return {"name": "mlb_f5_one_cold_only", "matchup_class": cls,
                "recommendation": "skip",
                "reason": f"{cls} matchup: only one_cold validated for F5 totals"}

    if market == "pitcher_strikeouts":
        if cls == "one_hot":
            return {"name": "mlb_ks_one_hot_only", "matchup_class": cls,
                    "recommendation": "keep",
                    "reason": "one_hot: +74.1% ROI on n=18 in backtest"}
        if cls in ("one_cold", "cold_both"):
            return {"name": "mlb_ks_one_hot_only", "matchup_class": cls,
                    "recommendation": "skip",
                    "reason": f"{cls}: -80.8% ROI on one_cold in backtest"}
        return {"name": "mlb_ks_one_hot_only", "matchup_class": cls,
                "recommendation": "skip",
                "reason": f"{cls}: only one_hot validated for K props"}

    return {"name": None, "matchup_class": cls, "recommendation": "na",
            "reason": f"no shadow filter for market={market}"}

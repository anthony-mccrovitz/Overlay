"""
Model registry — controls which models post publicly and which incubate silently.

Status meanings:
  live       → picks marked card_pick=True, posted (cards, captions, Reddit), public record
  incubating → picks logged + graded silently (card_pick=False), no posts, private record
  retired    → model is not run at all

Promotion to live requires: >= 30 settled picks AND positive ROI on the settled sample.
Demotion to incubating: ROI drops below 0% on a rolling sample, or sample size dries up.

The (sport, market) key is the canonical model identifier used across the pipeline.
"""
from __future__ import annotations


MODELS: dict[tuple[str, str], dict] = {
    # ── NBA — only proven model so far ───────────────────────────────────────
    ("nba", "total"):     {"status": "live",       "label": "NBA Totals"},
    ("nba", "moneyline"): {"status": "incubating", "label": "NBA Moneyline"},
    ("nba", "spread"):    {"status": "incubating", "label": "NBA Spread"},
    ("nba", "prop"):      {"status": "incubating", "label": "NBA Props (legacy bucket)"},
    # NBA prop sub-models — tracked individually so each can graduate on its own
    ("nba", "player_points"):   {"status": "incubating", "label": "NBA Player Points"},
    ("nba", "player_rebounds"): {"status": "incubating", "label": "NBA Player Rebounds"},
    ("nba", "player_assists"):  {"status": "incubating", "label": "NBA Player Assists"},
    ("nba", "player_pra"):      {"status": "incubating", "label": "NBA Player PRA"},
    ("nba", "player_blocks"):   {"status": "incubating", "label": "NBA Player Blocks"},
    ("nba", "player_steals"):   {"status": "incubating", "label": "NBA Player Steals"},
    ("nba", "player_threes"):   {"status": "incubating", "label": "NBA Player 3PM"},

    # ── MLB — all incubating until they prove out ────────────────────────────
    ("mlb", "moneyline"): {"status": "incubating", "label": "MLB Moneyline"},
    ("mlb", "spread"):    {"status": "live",       "label": "MLB Run Line"},
    ("mlb", "total"):     {"status": "incubating", "label": "MLB Totals"},
    ("mlb", "f5_total"):  {"status": "incubating", "label": "MLB F5 Totals"},
    ("mlb", "nrfi"):      {"status": "incubating", "label": "MLB NRFI"},
    ("mlb", "prop"):      {"status": "incubating", "label": "MLB Props (legacy bucket)"},
    # MLB prop sub-models — tracked individually so each can graduate on its own
    ("mlb", "pitcher_strikeouts"): {"status": "incubating", "label": "MLB Pitcher Ks"},
    ("mlb", "batter_home_runs"):   {"status": "incubating", "label": "MLB Batter HR"},
    ("mlb", "batter_hits"):        {"status": "incubating", "label": "MLB Batter Hits"},
    ("mlb", "batter_total_bases"): {"status": "incubating", "label": "MLB Batter Total Bases"},
    ("mlb", "batter_rbis"):        {"status": "incubating", "label": "MLB Batter RBIs"},

    # ── WNBA — port of NBA efficiency model, same methodology ───────────────────
    ("wnba", "total"):     {"status": "incubating", "label": "WNBA Totals"},
    ("wnba", "spread"):    {"status": "incubating", "label": "WNBA Spread"},
    ("wnba", "moneyline"): {"status": "incubating", "label": "WNBA Moneyline"},

    # ── NHL — trained logreg model on 3 seasons (2022-25), holdout Brier 0.240 ─
    ("nhl", "moneyline"): {"status": "incubating", "label": "NHL Moneyline"},
    ("nhl", "puck_line"): {"status": "incubating", "label": "NHL Puck Line"},
    ("nhl", "total"):     {"status": "incubating", "label": "NHL Totals"},

    # ── PGA — event-driven, no daily slate ───────────────────────────────────
    ("pga", "outright"):  {"status": "incubating", "label": "PGA Outright"},

    # ── Tennis — surface Elo + Markov chain, Roland-Garros May 25 ─────────────
    ("tennis", "moneyline"): {"status": "incubating", "label": "Tennis Moneyline"},

    # ── Soccer / World Cup — Dixon-Coles model, WC 2026 starts June 11 ────────
    ("soccer", "moneyline"): {"status": "incubating", "label": "Soccer Moneyline"},
    ("soccer", "total"):     {"status": "incubating", "label": "Soccer Totals"},
    ("soccer", "draw"):      {"status": "incubating", "label": "Soccer Draw"},
}


def _key(sport: str, market: str) -> tuple[str, str]:
    """Normalize sport/market keys to lowercase canonical form."""
    raw = (sport or "").lower()
    for prefix in ("baseball_", "basketball_", "icehockey_"):
        raw = raw.replace(prefix, "")
    if raw.startswith("soccer"):
        raw = "soccer"
    elif raw.startswith("tennis"):
        raw = "tennis"
    s = raw
    m = (market or "").lower()
    return (s, m)


def model_status(sport: str, market: str) -> str:
    """Return 'live', 'incubating', or 'retired'. Unknown models default to incubating."""
    return MODELS.get(_key(sport, market), {}).get("status", "incubating")


def is_live(sport: str, market: str, prop_market: str | None = None) -> bool:
    """True if this model's picks should be posted publicly (card_pick=True).

    For props, prefer the specific sub-market (e.g. pitcher_strikeouts) over the
    generic 'prop' bucket so each prop type can graduate independently.
    """
    if market == "prop" and prop_market:
        return model_status(sport, prop_market) == "live"
    return model_status(sport, market) == "live"


def is_retired(sport: str, market: str) -> bool:
    """True if this model should not run at all."""
    return model_status(sport, market) == "retired"


def model_label(sport: str, market: str) -> str:
    """Human-readable label, e.g. 'NBA Totals'."""
    return MODELS.get(_key(sport, market), {}).get("label", f"{sport.upper()} {market}")


def live_models() -> list[tuple[str, str]]:
    """List of (sport, market) tuples currently posting."""
    return [k for k, v in MODELS.items() if v["status"] == "live"]


def incubating_models() -> list[tuple[str, str]]:
    """List of (sport, market) tuples currently incubating (silent)."""
    return [k for k, v in MODELS.items() if v["status"] == "incubating"]

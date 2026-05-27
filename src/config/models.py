"""
Model registry — controls which models post publicly and which incubate silently.

Source-of-truth for the model selection plan agreed 2026-05-19, grounded in
the research pass on academically + practitioner-proven betting edges.

Status meanings:
  live       → picks marked card_pick=True, posted (cards, captions, Reddit), public record
  incubating → picks logged + graded silently (card_pick=False), no posts, private record
  retired    → model is not run at all

Tier meanings (display + customer-facing grouping):
  t1     → "Proven" — peer-reviewed academic or documented professional results
  t2     → "Theoretically sound" — strong practitioner backing, mechanically defensible
  shadow → tracking only — building sample for promotion / sanity-checking model health
  paused → explicitly paused per research (high vig, no documented edge, persistent losses)

Paused models are also listed in predict.py:PAUSED_MARKETS / run_nba.py:_NBA_PAUSED so
they're not even logged to picks.json — keep the two in sync.

Promotion: shadow → t1/t2 requires ≥ 30 settled picks AND positive ROI on the settled
sample AND non-negative CLV. Demotion: ROI drops below 0% on a rolling 60-pick window.

Research backing for the tiers:
  NBA Totals          — Voulgaris documented, pace/tempo mispricing
  Tennis Elo          — Kovalchik 2016, Angelini 2022 (peer-reviewed)
  MLB Totals+Weather  — 14+ years wind-direction data, Pinnacle/Action analyses
  Dixon-Coles Soccer  — Dixon & Coles 1997 (JRSS) — edge lives in mid/lower leagues
  PGA SG model        — Strokes-Gained predictive of outright odds (practitioner)
  Auto-racing Elo     — Outright winner Elo (practitioner backtests)
  MLB Pitcher Ks      — Mechanically sound; current model -11.8% ROI → REBUILD in shadow
  MLB Moneyline       — Bias-fixed (penalize longshots per Snowberg & Wolfers 2010)
"""
from __future__ import annotations


MODELS: dict[tuple[str, str], dict] = {
    # ── Tier 1 (proven) — these go on the card ────────────────────────────────
    ("nba",    "total"):     {"status": "live",       "tier": "t1", "label": "NBA Totals"},
    ("mlb",    "total"):     {"status": "live",       "tier": "t1", "label": "MLB Totals (Weather)"},
    ("tennis", "moneyline"): {"status": "incubating", "tier": "shadow", "label": "Tennis Elo (4W-27L shadow, rebuilding)"},
    ("soccer", "moneyline"): {"status": "live",       "tier": "t1", "label": "Soccer Dixon-Coles"},

    # ── Tier 2 (theoretically sound) — also on the card, smaller stake ────────
    ("mlb",    "moneyline"): {"status": "live",       "tier": "t2", "label": "MLB Moneyline (bias-fixed)"},
    ("pga",    "outright"):  {"status": "live",       "tier": "t2", "label": "PGA Outright (SG)"},
    ("nascar", "outright"):  {"status": "retired",    "tier": "shadow", "label": "NASCAR Outright Elo"},
    ("indycar","outright"):  {"status": "retired",    "tier": "shadow", "label": "IndyCar Outright Elo"},
    ("f1",     "outright"):  {"status": "retired",    "tier": "shadow", "label": "F1 Outright Elo"},

    # ── Shadow (tracking only — building sample / rebuilding) ────────────────
    ("mlb", "pitcher_strikeouts"): {"status": "incubating", "tier": "shadow", "label": "MLB Pitcher Ks (rebuild)"},
    ("mlb", "f5_total"):           {"status": "incubating", "tier": "shadow", "label": "MLB F5 Totals (line-validated, building sample)"},
    ("mlb", "nrfi"):               {"status": "incubating", "tier": "shadow", "label": "MLB NRFI"},
    ("nba", "moneyline"):          {"status": "incubating", "tier": "shadow", "label": "NBA Moneyline"},
    ("nba", "player_points"):      {"status": "incubating", "tier": "shadow", "label": "NBA Player Points"},
    ("nba", "player_rebounds"):    {"status": "incubating", "tier": "shadow", "label": "NBA Player Rebounds"},
    ("nba", "player_assists"):     {"status": "incubating", "tier": "shadow", "label": "NBA Player Assists"},
    ("nba", "player_pra"):         {"status": "incubating", "tier": "shadow", "label": "NBA Player PRA"},
    ("nba", "player_blocks"):      {"status": "incubating", "tier": "shadow", "label": "NBA Player Blocks"},
    ("nba", "player_steals"):      {"status": "incubating", "tier": "shadow", "label": "NBA Player Steals"},
    ("nba", "player_threes"):      {"status": "incubating", "tier": "shadow", "label": "NBA Player 3PM"},
    ("nhl", "moneyline"):           {"status": "live",       "tier": "t2",     "label": "NHL Moneyline"},
    ("nhl", "puck_line"):           {"status": "live",       "tier": "t2",     "label": "NHL Puck Line"},
    ("nhl", "total"):               {"status": "live",       "tier": "t2",     "label": "NHL Totals"},
    ("nhl", "player_points"):       {"status": "incubating", "tier": "shadow", "label": "NHL Player Points"},
    ("nhl", "player_goals"):        {"status": "incubating", "tier": "shadow", "label": "NHL Player Goals"},
    ("nhl", "player_assists"):      {"status": "incubating", "tier": "shadow", "label": "NHL Player Assists"},
    ("nhl", "player_shots_on_goal"):{"status": "incubating", "tier": "shadow", "label": "NHL Shots on Goal"},
    ("nhl", "player_blocked_shots"):{"status": "incubating", "tier": "shadow", "label": "NHL Blocked Shots"},
    ("ufc", "moneyline"):           {"status": "incubating", "tier": "shadow", "label": "UFC Moneyline"},

    # ── Paused (research says don't bet) — also in PAUSED_MARKETS gate ───────
    ("mlb",  "spread"):            {"status": "incubating", "tier": "paused", "label": "MLB Run Line"},
    ("mlb",  "prop"):              {"status": "incubating", "tier": "paused", "label": "MLB Batter Props (generic)"},
    ("mlb",  "batter_home_runs"):  {"status": "incubating", "tier": "paused", "label": "MLB Batter HR"},
    ("mlb",  "batter_hits"):       {"status": "incubating", "tier": "paused", "label": "MLB Batter Hits"},
    ("mlb",  "batter_total_bases"):{"status": "incubating", "tier": "paused", "label": "MLB Batter Total Bases"},
    ("mlb",  "batter_rbis"):       {"status": "incubating", "tier": "paused", "label": "MLB Batter RBIs"},
    ("nba",  "spread"):            {"status": "incubating", "tier": "paused", "label": "NBA Spread"},
    ("nba",  "prop"):              {"status": "incubating", "tier": "paused", "label": "NBA Props (generic bucket)"},
    ("wnba", "moneyline"):         {"status": "incubating", "tier": "shadow", "label": "WNBA Moneyline"},
    ("wnba", "spread"):            {"status": "incubating", "tier": "shadow", "label": "WNBA Spread"},
    ("wnba", "total"):             {"status": "incubating", "tier": "shadow", "label": "WNBA Totals"},
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
    elif raw.startswith("auto_racing_nascar"):
        raw = "nascar"
    elif raw.startswith("auto_racing_indycar"):
        raw = "indycar"
    elif raw.startswith("auto_racing_formula"):
        raw = "f1"
    elif raw.startswith("mma") or raw == "mma_mixed_martial_arts":
        raw = "ufc"
    elif raw.startswith("golf_pga"):
        raw = "pga"
    s = raw
    m = (market or "").lower()
    return (s, m)


def model_status(sport: str, market: str) -> str:
    """Return 'live', 'incubating', or 'retired'. Unknown models default to incubating."""
    return MODELS.get(_key(sport, market), {}).get("status", "incubating")


def model_tier(sport: str, market: str) -> str:
    """Return 't1', 't2', 'shadow', or 'paused'. Unknown models default to 'shadow'."""
    return MODELS.get(_key(sport, market), {}).get("tier", "shadow")


def is_live(sport: str, market: str, prop_market: str | None = None) -> bool:
    """True if this model's picks should be posted publicly (card_pick=True).

    For props, prefer the specific sub-market (e.g. pitcher_strikeouts) over the
    generic 'prop' bucket so each prop type can graduate independently.
    """
    if market == "prop" and prop_market:
        return model_status(sport, prop_market) == "live"
    return model_status(sport, market) == "live"


def is_paused(sport: str, market: str) -> bool:
    """True if this market is explicitly paused per research — don't log to PNL."""
    return model_tier(sport, market) == "paused"


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


def models_by_tier(tier: str) -> list[tuple[str, str]]:
    """List of (sport, market) tuples in the given tier."""
    return [k for k, v in MODELS.items() if v.get("tier") == tier]


# New-model shadow stake caps: 0.5u until N≥30 settled with positive CLV
_NEW_SPORTS = {"wnba", "tennis", "soccer", "pga",
               "auto_racing_nascar_cup_series",
               "auto_racing_indycar_series",
               "auto_racing_formula_one",
               "nascar", "indycar", "f1",
               "mma_mixed_martial_arts", "ufc", "mma"}

def shadow_stake(sport: str, market: str) -> float:
    """Return appropriate stake for a shadow pick.

    New sport models (WNBA, tennis, soccer, PGA) use 0.5u until they prove
    out (N≥30 settled + positive CLV). All other incubating models use 1.0u.
    Tier-2 live models also use 0.5u stake until they hit the 30-pick threshold.
    """
    s, _ = _key(sport, market)
    if s in _NEW_SPORTS:
        return 0.5
    if model_tier(sport, market) == "t2":
        return 0.5
    return 1.0

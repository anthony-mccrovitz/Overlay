"""
Model registry — controls which models post publicly and which incubate silently.

Source-of-truth for the model selection plan agreed 2026-05-19, grounded in
the research pass on academically + practitioner-proven betting edges.

Status meanings:
  live       → picks marked card_pick=True, posted (cards, captions, Reddit), public record
  incubating → picks logged + graded silently (card_pick=False), no posts, private record
  retired    → model is not run at all (AVOID — lose all signal; prefer incubating)

  Convention: when a live model underperforms, demote to incubating (not retired).
  We keep collecting silent picks so we can detect recovery, drift, or sustained loss.

Tier meanings (display + customer-facing grouping):
  t1     → "Proven" — peer-reviewed academic or documented professional results
  t2     → "Theoretically sound" — strong practitioner backing, mechanically defensible
  shadow → tracking only — building sample for promotion / sanity-checking model health
  paused → explicitly paused per research (high vig, no documented edge, persistent losses)

Paused models are also listed in predict.py:PAUSED_MARKETS / run_nba.py:_NBA_PAUSED so
they're not even logged to picks.json — keep the two in sync.

Promotion: shadow → t1/t2 requires ≥ 30 settled picks AND positive ROI on the settled
sample AND non-negative CLV. Demotion: ROI drops below 0% on a rolling 60-pick window.

Calibration gate (2026-07-15, src/analytics/calibration_gate.py): the registry says
WHETHER a market may card; the gate independently shrinks each pick's edge to what has
historically materialized and centrally DE-cards any pending pick whose calibrated edge
no longer clears the threshold — so even a 'live' model cannot post a phantom edge.
CLV/outcome split found that day: MLB moneyline and NRFI have positive CLV but ~zero
realized outcome edge (k≈0), so they are NOT proven winners; MLB totals is the single
outcome-verified market (k=1.0).

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
    # Calibration gate (2026-07-15): NBA totals realize ~60% of claimed edge
    # (k≈0.60) — kept live but do NOT scale until CLV turns positive (currently
    # -0.3%). MLB totals are the one outcome-VERIFIED edge: claimed +4.8pp,
    # realized +6.7pp (k=1.0). This is the core of the product.
    ("nba",    "total"):     {"status": "live",       "tier": "t1", "label": "NBA Totals (k≈0.60 realized; watch CLV, don't scale)"},
    ("mlb",    "total"):     {"status": "live",       "tier": "t1", "label": "MLB Totals (Weather) — outcome-verified, k=1.0, realized +6.7pp"},
    ("tennis", "moneyline"): {"status": "incubating", "tier": "shadow", "label": "Tennis Elo v2 (rebuilt 2026-07-13: dual-tour 538-Elo, market-anchored; v1 shadow record was 39-77 -13u — stay shadow until v2 proves out)"},
    ("soccer", "moneyline"): {"status": "incubating", "tier": "shadow", "label": "Soccer Dixon-Coles (4-8 -1.5u, rebuilding)"},

    # ── World Cup 2026 — own unit, all incubating until the CLV gate confirms ──
    # (promote with `chef.py promote wc <market>`; the gate refuses until proven).
    ("wc", "moneyline"):      {"status": "incubating", "tier": "shadow", "label": "World Cup 1X2 (Dixon-Coles, CLV-incubating)"},
    ("wc", "total"):          {"status": "incubating", "tier": "shadow", "label": "World Cup Totals (CLV-incubating)"},
    ("wc", "spread"):         {"status": "incubating", "tier": "shadow", "label": "World Cup Asian Handicap (CLV-incubating)"},
    ("wc", "anytime_scorer"): {"status": "incubating", "tier": "shadow", "label": "World Cup Anytime Scorer (CLV-incubating)"},

    # ── Tier 2 (theoretically sound) — also on the card, smaller stake ────────
    ("mlb",    "moneyline"): {"status": "incubating", "tier": "shadow", "label": "MLB Moneyline (41-39 +4u, shadowed 2026-05-30 — soft-book edge inflation)"},
    ("pga",    "outright"):  {"status": "live",       "tier": "t2", "label": "PGA Outright (SG)"},
    ("nascar", "outright"):  {"status": "incubating", "tier": "shadow", "label": "NASCAR Outright Elo (shadow)"},
    ("indycar","outright"):  {"status": "incubating", "tier": "shadow", "label": "IndyCar Outright Elo (shadow)"},
    ("f1",     "outright"):  {"status": "incubating", "tier": "shadow", "label": "F1 Outright Elo (shadow)"},

    # ── Shadow (tracking only — building sample / rebuilding) ────────────────
    ("mlb", "pitcher_strikeouts"): {"status": "incubating", "tier": "shadow", "label": "MLB Pitcher Ks (83-108 -16u, shadow — rebuild)"},
    ("mlb", "f5_total"):           {"status": "incubating", "tier": "shadow", "label": "MLB F5 Totals (63-47 shadow, promoting after first 30 live picks)"},
    ("mlb", "nrfi"):               {"status": "incubating", "tier": "paused", "label": "MLB NRFI (81-82 -7u, paused)"},
    ("nba", "moneyline"):          {"status": "incubating", "tier": "paused", "label": "NBA Moneyline (28-24 -4u, paused)"},
    ("nba", "player_points"):      {"status": "incubating", "tier": "shadow", "label": "NBA Player Points"},
    ("nba", "player_rebounds"):    {"status": "incubating", "tier": "shadow", "label": "NBA Player Rebounds"},
    ("nba", "player_assists"):     {"status": "incubating", "tier": "shadow", "label": "NBA Player Assists"},
    ("nba", "player_pra"):         {"status": "incubating", "tier": "shadow", "label": "NBA Player PRA"},
    ("nba", "player_blocks"):      {"status": "incubating", "tier": "shadow", "label": "NBA Player Blocks"},
    ("nba", "player_steals"):      {"status": "incubating", "tier": "shadow", "label": "NBA Player Steals"},
    ("nba", "player_threes"):      {"status": "incubating", "tier": "shadow", "label": "NBA Player 3PM"},
    ("nhl", "moneyline"):           {"status": "live",       "tier": "t2",     "label": "NHL Moneyline"},
    ("nhl", "puck_line"):           {"status": "live",       "tier": "t2",     "label": "NHL Puck Line"},
    # Demoted 2026-07-15: 36% win, CLV -2.21% — overconfident AND losing to the
    # close. Incubate until the model recalibrates and CLV turns non-negative.
    ("nhl", "total"):               {"status": "incubating", "tier": "shadow", "label": "NHL Totals (36% win, CLV -2.2% — demoted, recalibrating)"},
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
    ("wnba", "moneyline"):         {"status": "incubating", "tier": "shadow", "label": "WNBA Moneyline (3-2 shadow, need 30+ picks)"},
    ("wnba", "spread"):            {"status": "incubating", "tier": "paused", "label": "WNBA Spread (0-8 -6u, paused)"},
    ("wnba", "total"):             {"status": "incubating", "tier": "shadow", "label": "WNBA Totals"},
}


def _key(sport: str, market: str) -> tuple[str, str]:
    """Normalize sport/market keys to lowercase canonical form."""
    raw = (sport or "").lower()
    for prefix in ("baseball_", "basketball_", "icehockey_"):
        raw = raw.replace(prefix, "")
    if raw.startswith("soccer_fifa_world_cup") or raw == "wc":
        # World Cup is gated/promoted as its OWN unit (matches chef.py edge's
        # 'wc' label) — promoting it must NOT also flip MLS/La Liga/etc. live.
        raw = "wc"
    elif raw.startswith("soccer"):
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


# ── Promotion overrides (CLV-gated, set via `chef.py promote`) ───────────────
# A market is promoted shadow→live ONLY after it clears the CLV gate (chef.py
# edge). Rather than hand-edit MODELS above, promotions are recorded in this
# git-committed JSON so every flip is auditable (who/when/on what evidence) and
# reversible (`chef.py demote`). model_status/model_tier consult it first.
import json as _json
from pathlib import Path as _Path

_PROMOTIONS_FILE = _Path("data/models/promotions.json")


def _load_promotions() -> dict:
    try:
        data = _json.loads(_PROMOTIONS_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _promotion(sport: str, market: str) -> dict | None:
    """The promotion override record for this market, if one exists."""
    s, m = _key(sport, market)
    return _load_promotions().get(f"{s}::{m}")


def model_status(sport: str, market: str) -> str:
    """Return 'live', 'incubating', or 'retired'. Unknown models default to incubating.

    A CLV-gated promotion override (data/models/promotions.json) wins over the
    static registry, so a proven market goes live without a source edit.
    """
    p = _promotion(sport, market)
    if p and p.get("status"):
        return p["status"]
    return MODELS.get(_key(sport, market), {}).get("status", "incubating")


def model_tier(sport: str, market: str) -> str:
    """Return 't1', 't2', 'shadow', or 'paused'. Unknown models default to 'shadow'."""
    p = _promotion(sport, market)
    if p and p.get("tier"):
        return p["tier"]
    return MODELS.get(_key(sport, market), {}).get("tier", "shadow")


def set_promotion(sport: str, market: str, status: str, tier: str,
                  evidence: dict | None = None) -> tuple[str, str]:
    """Record a promotion/demotion override. Returns the canonical (sport, market).

    Callers MUST gate this on the CLV edge check — this function only persists
    the decision; it does not re-verify the edge.
    """
    s, m = _key(sport, market)
    proms = _load_promotions()
    rec = {"status": status, "tier": tier}
    if evidence:
        rec.update(evidence)
    proms[f"{s}::{m}"] = rec
    _PROMOTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROMOTIONS_FILE.write_text(_json.dumps(proms, indent=2, sort_keys=True))
    return (s, m)


def is_clv_validated(sport: str, market: str) -> bool:
    """True ONLY if this market passed the CLV gate (promoted via `chef.py promote`).

    Static-registry 'live' markets (mlb total, nba total, …) are research- and
    calibration-backed but NOT CLV-proven, so they do NOT count here — only an
    actual gate-passing promotion (which records clv evidence) does. This is the
    line between "we proved a closing-line edge" and "this is a model heuristic."
    """
    p = _promotion(sport, market)
    return bool(p and p.get("status") == "live"
                and (p.get("clv_n") is not None or p.get("clv_mean") is not None))


def clv_status(sport: str, market: str) -> str:
    """'validated' if CLV-gate-proven, else 'heuristic'. Stamped on every pick so
    the record never implies a proven edge it hasn't earned."""
    return "validated" if is_clv_validated(sport, market) else "heuristic"


def clear_promotion(sport: str, market: str) -> bool:
    """Remove a promotion override (revert to the static registry). True if removed."""
    s, m = _key(sport, market)
    proms = _load_promotions()
    if f"{s}::{m}" in proms:
        del proms[f"{s}::{m}"]
        _PROMOTIONS_FILE.write_text(_json.dumps(proms, indent=2, sort_keys=True))
        return True
    return False


# Minimum edge to post publicly (card_pick=True) per market.
# Models with a different edge metric (totals use run differential, not %)
# are marked None — they always post if the model is live.
_CARD_EDGE_MIN: dict[str, float | None] = {
    "moneyline":  12.0,   # 54% WR model — only high-conviction edges
    "ml":         12.0,
    "total":      3.0,    # 66-68% WR — minimum 3% edge; sub-3% is statistical noise
    "f5_total":   None,   # shadow — handled by model status
    "spread":     12.0,
    "run_line":   12.0,
    "puck_line":  10.0,
    "nrfi":       None,   # paused
    "outright":   10.0,
    "anytime_scorer": 8.0,  # scorer props: only post a real, sizable edge
}


def is_live(sport: str, market: str, prop_market: str | None = None) -> bool:
    """True if this model's picks should be posted publicly (card_pick=True).

    Checks both model status AND edge threshold — call is_card_pick() instead
    if you have an edge value and want the full gate.
    """
    if market == "prop" and prop_market:
        return model_status(sport, prop_market) == "live"
    return model_status(sport, market) == "live"


def is_card_pick(sport: str, market: str, edge_pct: float | None,
                 prop_market: str | None = None) -> bool:
    """Full card_pick gate: model must be live AND edge must meet the threshold.

    Use this everywhere a pick is logged to picks.json.
    """
    if not is_live(sport, market, prop_market):
        return False
    mkt_key = (market or "").lower()
    min_edge = _CARD_EDGE_MIN.get(mkt_key)
    if min_edge is None:
        return True   # no edge threshold for this market type
    if edge_pct is None:
        return False  # can't confirm edge — don't post
    return float(edge_pct) >= min_edge


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
_NEW_SPORTS = {"wnba", "tennis", "soccer", "wc", "pga",
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

"""
Best Picks Recommender — Overlay

For each prop market (and game market), selects the single highest-conviction
bet using a composite score:

    score = edge_pct * confidence_weight * kelly_fraction

Where:
  - edge_pct        — model edge over the book line
  - confidence_weight — penalizes low-confidence props (model_prob near 50%)
  - kelly_fraction  — implied Kelly stake at this edge (caps greed)

Usage:
    from src.analytics.best_picks import best_pick_per_market, best_picks_report
    from src.analytics.best_picks import best_picks_for_date

    picks = best_picks_for_date("2026-05-17")
    print(best_picks_report(picks))

CLI:
    python3 src/analytics/best_picks.py
    python3 src/analytics/best_picks.py --date 20260517
    python3 src/analytics/best_picks.py --sport mlb
    python3 src/analytics/best_picks.py --top 3   # top-N per market instead of top-1
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Scoring ───────────────────────────────────────────────────────────────────

def _american_to_decimal(american: float) -> float:
    if american >= 0:
        return american / 100 + 1.0
    return 100 / abs(american) + 1.0


def _kelly_fraction(edge_pct: float, american_odds: float) -> float:
    """Full Kelly fraction (0–1). Clamp at 0."""
    decimal = _american_to_decimal(american_odds)
    b = decimal - 1.0          # net profit per unit
    p = edge_pct / 100 + (1.0 / decimal)   # implied model win prob
    q = 1.0 - p
    if b <= 0:
        return 0.0
    return max(0.0, (b * p - q) / b)


def _confidence_weight(model_prob: float | None) -> float:
    """
    Weight that rewards picks where the model is decisive.
    Returns 1.0 at model_prob=0.70+, scales down toward 0.5 near coin-flip.
    """
    if model_prob is None:
        return 0.75  # neutral default
    p = max(0.01, min(0.99, model_prob))
    distance = abs(p - 0.5)           # 0 = coin-flip, 0.5 = certainty
    return 0.5 + distance             # maps to [0.5, 1.0]


def score_edge(edge: dict) -> float:
    """
    Composite score for a single edge pick. Higher = better.
    Used to rank within a market and select the best pick.
    """
    edge_pct   = float(edge.get("edge_pct", 0))
    model_prob = edge.get("model_prob")
    odds       = float(edge.get("odds", -110))

    if edge_pct <= 0:
        return 0.0

    cw = _confidence_weight(model_prob)
    kf = _kelly_fraction(edge_pct, odds)

    return edge_pct * cw * (1.0 + kf)


# ── Market grouping ───────────────────────────────────────────────────────────

_MARKET_LABELS = {
    "pitcher_strikeouts":            "Pitcher Strikeouts",
    "batter_hits":                   "Batter Hits",
    "batter_total_bases":            "Batter Total Bases",
    "batter_home_runs":              "Batter Home Runs",
    "batter_runs":                   "Batter Runs",
    "batter_rbis":                   "Batter RBIs",
    "player_points":                 "NBA Points",
    "player_rebounds":               "NBA Rebounds",
    "player_assists":                "NBA Assists",
    "player_threes":                 "NBA 3-Pointers",
    "player_blocks":                 "NBA Blocks",
    "player_steals":                 "NBA Steals",
    "player_points_rebounds_assists":"NBA PRA",
    "total":                         "Game Total",
    "spreads":                       "Spread",
    "h2h":                           "Moneyline",
    "moneyline":                     "Moneyline",
    "spread":                        "Spread",
    "outrights":                     "Outright Winner",
    "win":                           "Race Winner",
    "nrfi":                          "NRFI",
    "pitcher_ks":                    "Pitcher Strikeouts",
}


# ── Core selector ─────────────────────────────────────────────────────────────

def best_pick_per_market(
    edges: list[dict],
    top_n: int = 1,
    min_edge: float = 0.0,
) -> dict[str, list[dict]]:
    """
    Given a flat list of edge dicts, return the top-N pick(s) per market.

    Returns: {market_key: [edge_dict, ...]} sorted by composite score desc.
    """
    filtered = [e for e in edges if float(e.get("edge_pct", 0)) >= min_edge]

    by_market: dict[str, list[dict]] = defaultdict(list)
    for e in filtered:
        market = e.get("market") or e.get("prop_type") or "unknown"
        by_market[market].append(e)

    result: dict[str, list[dict]] = {}
    for market, candidates in by_market.items():
        ranked = sorted(candidates, key=score_edge, reverse=True)
        for pick in ranked[:top_n]:
            pick = dict(pick)
            pick["_best_pick_score"] = round(score_edge(pick), 4)
        result[market] = ranked[:top_n]

    return result


# ── Loaders ───────────────────────────────────────────────────────────────────

def _load_output_edges(date_str: str, sport_filter: str | None = None) -> list[dict]:
    """
    Load all edge JSON files from output/picks/ for a given date (YYYYMMDD).
    Merges props.json, picks.json across all sport directories.
    """
    out_root = Path("output/picks")
    all_edges: list[dict] = []

    if not out_root.exists():
        return []

    for sport_dir in sorted(out_root.iterdir()):
        if not sport_dir.is_dir():
            continue
        if sport_filter and sport_filter.lower() not in sport_dir.name.lower():
            continue

        date_dir = sport_dir / date_str
        if not date_dir.exists():
            continue

        for fname in ("props.json", "picks.json"):
            fpath = date_dir / fname
            if not fpath.exists():
                continue
            try:
                data = json.loads(fpath.read_text())
                if isinstance(data, list):
                    for e in data:
                        e.setdefault("_source_sport", sport_dir.name)
                        e.setdefault("_source_file", fname)
                    all_edges.extend(data)
            except (json.JSONDecodeError, OSError):
                continue

    return all_edges


def best_picks_for_date(
    date_str: str | None = None,
    sport_filter: str | None = None,
    top_n: int = 1,
    min_edge: float = 0.0,
) -> dict[str, list[dict]]:
    """
    Load all output edges for a date and return best pick(s) per market.

    date_str: YYYYMMDD (default: today)
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    edges = _load_output_edges(date_str, sport_filter=sport_filter)
    return best_pick_per_market(edges, top_n=top_n, min_edge=min_edge)


# ── Report formatter ──────────────────────────────────────────────────────────

def best_picks_report(
    best: dict[str, list[dict]],
    top_n: int = 1,
    date_label: str = "",
) -> str:
    if not best:
        return "  No picks found."

    lines = []
    if date_label:
        lines.append(f"\n  {'='*60}")
        lines.append(f"  BEST PICKS — {date_label}")
        lines.append(f"  {'='*60}")

    for market, picks in sorted(best.items()):
        label = _MARKET_LABELS.get(market, market.replace("_", " ").title())
        lines.append(f"\n  [{label}]")

        for i, e in enumerate(picks, 1):
            rank  = f"#{i} " if top_n > 1 else ""
            score = e.get("_best_pick_score", score_edge(e))

            # Derive display name: props have player, game picks have team
            name   = e.get("player") or e.get("team") or e.get("driver") or "?"
            dirn   = e.get("direction", "")
            line   = e.get("line")
            odds   = e.get("odds")
            edge   = e.get("edge_pct")
            mprob  = e.get("model_prob")
            book   = e.get("sportsbook", "")
            matchup = e.get("matchup", "")
            mu     = e.get("model_mu")

            # Build pick string
            pick_str = name
            if dirn:
                pick_str += f"  {dirn}"
            if line is not None:
                pick_str += f" {line}"

            stats = []
            if edge is not None:
                stats.append(f"edge={edge:+.1f}%")
            if odds is not None:
                odds_str = f"+{int(odds)}" if float(odds) >= 0 else str(int(odds))
                stats.append(f"odds={odds_str}")
            if mprob is not None:
                stats.append(f"model={mprob:.1%}")
            if mu is not None:
                stats.append(f"mu={mu:.1f}")
            stats.append(f"score={score:.2f}")

            lines.append(f"    {rank}{pick_str}")
            lines.append(f"    {'  '.join(stats)}")
            if matchup:
                lines.append(f"    {matchup}  [{book}]")
            elif book:
                lines.append(f"    [{book}]")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Best pick per prop market")
    parser.add_argument("--date",      type=str, default=None, help="YYYYMMDD (default: today)")
    parser.add_argument("--sport",     type=str, default=None, help="Filter by sport (e.g. mlb, nba)")
    parser.add_argument("--top",       type=int, default=1,    help="Top N picks per market (default: 1)")
    parser.add_argument("--min-edge",  type=float, default=0.0, help="Minimum edge% to include")
    args = parser.parse_args()

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    best = best_picks_for_date(
        date_str=date_str,
        sport_filter=args.sport,
        top_n=args.top,
        min_edge=args.min_edge,
    )

    label = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    if args.sport:
        label += f"  |  {args.sport.upper()}"

    print(best_picks_report(best, top_n=args.top, date_label=label))
    print()

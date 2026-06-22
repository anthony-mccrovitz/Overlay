"""
World Cup anytime-goalscorer model — Overlay.

Method (Poisson thinning of team expected goals):
  1. Team expected goals (λ_team) comes from the Dixon-Coles model (matchup()).
  2. Each player's recent share of his national team's goals (s_p) is computed
     from the historical goalscorer log (last N years, own goals excluded).
  3. Player expected goals this match: λ_p = s_p · λ_team.
  4. P(player scores ≥1) = 1 − exp(−λ_p)   (Poisson, anytime scorer).
  5. Edge = model P − de-vigged book implied P.

KNOWN LIMITATIONS (model is shadow-only, CLV-validated before any bet):
  - Goal share is historical, not lineup-aware: an injured/benched/rotated star
    is overestimated; a player who didn't score in the window (new call-up) gets
    ~0 and is missed. No team-sheet feed exists yet.
  - Designated penalty-takers' share is inflated (penalties counted).
  - Shares assume a stable role; tournament form/rotation isn't modelled.
These bias toward established scorers. The market (which knows the lineup) will
beat us on rotation games — exactly what CLV will reveal.

Data: data/cache/soccer/goalscorers_csv.json (intl goals since 1916, CSV).
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from collections import defaultdict
from datetime import date, timedelta

_GOALSCORERS_CSV = Path("data/cache/soccer/goalscorers_csv.json")
_WINDOW_YEARS = 3            # how far back to measure a player's goal share
_MIN_TEAM_GOALS = 15         # need this many team goals in-window to trust shares
_MIN_SHARE = 0.03            # ignore long-tail players below this share (noise)


def _american_to_imp(odds: float) -> float:
    odds = float(odds)
    return (100.0 / (odds + 100.0)) if odds > 0 else (abs(odds) / (abs(odds) + 100.0))


def load_scorer_shares(window_years: int = _WINDOW_YEARS) -> dict[str, dict[str, float]]:
    """Return {team: {player: goal_share}} from the recent goalscorer window.

    Share = player's non-own goals / team's non-own goals in the window. Only
    teams with >= _MIN_TEAM_GOALS are returned (else shares are too noisy).
    """
    if not _GOALSCORERS_CSV.exists():
        return {}
    cutoff = (date.today() - timedelta(days=365 * window_years)).isoformat()
    team_goals: dict[str, int] = defaultdict(int)
    player_goals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    try:
        with _GOALSCORERS_CSV.open() as f:
            for row in csv.DictReader(f):
                if row.get("date", "") < cutoff:
                    continue
                if str(row.get("own_goal", "")).upper() == "TRUE":
                    continue  # own goals don't settle the anytime-scorer market
                team = (row.get("team") or "").strip()
                scorer = (row.get("scorer") or "").strip()
                if not team or not scorer:
                    continue
                team_goals[team] += 1
                player_goals[team][scorer] += 1
    except (OSError, csv.Error):
        return {}

    shares: dict[str, dict[str, float]] = {}
    for team, total in team_goals.items():
        if total < _MIN_TEAM_GOALS:
            continue
        ps = {p: g / total for p, g in player_goals[team].items() if g / total >= _MIN_SHARE}
        if ps:
            shares[team] = ps
    return shares


def scorer_probs(team: str, team_xg: float,
                 shares: dict[str, dict[str, float]]) -> dict[str, float]:
    """{player: P(scores >=1)} for one team given its expected goals this match."""
    team_shares = shares.get(team)
    if not team_shares or team_xg <= 0:
        return {}
    out: dict[str, float] = {}
    for player, s in team_shares.items():
        lam_p = s * team_xg
        out[player] = 1.0 - math.exp(-lam_p)
    return out


def find_scorer_edges(event: dict, model_v2, shares: dict[str, dict[str, float]],
                      min_edge_pct: float = 4.0,
                      host_nations: set[str] | None = None) -> list[dict]:
    """Find anytime-scorer edges for one event (per-event Odds API response with
    the player_goal_scorer_anytime market). Returns pnl-schema edge dicts.
    """
    from src.data.soccer_data import normalize_team_name
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    if not home or not away:
        return []

    hosts = {normalize_team_name(h) for h in (host_nations or set())}
    host_adv = 0.0
    if hosts:
        nh, na = normalize_team_name(home), normalize_team_name(away)
        if nh in hosts and na not in hosts:
            host_adv = getattr(model_v2, "HOST_BONUS", 0.0)
        elif na in hosts and nh not in hosts:
            host_adv = -getattr(model_v2, "HOST_BONUS", 0.0)

    m = model_v2.matchup(home, away, neutral=event.get("neutral", True),
                         home_adv_elo=host_adv)
    # P(score) per player for both teams
    probs: dict[str, float] = {}
    probs.update(scorer_probs(home, m["exp_home"], shares))
    probs.update(scorer_probs(away, m["exp_away"], shares))
    if not probs:
        return []
    lower = {p.lower(): (p, v) for p, v in probs.items()}

    edges: list[dict] = []
    for bookmaker in event.get("bookmakers", []):
        book = bookmaker.get("title", "")
        for market in bookmaker.get("markets", []):
            if market.get("key") != "player_goal_scorer_anytime":
                continue
            for o in market.get("outcomes", []):
                name = str(o.get("description") or o.get("name") or "").strip()
                price = o.get("price")
                if not name or price is None:
                    continue
                hit = lower.get(name.lower())
                if not hit:  # fuzzy: match on surname
                    surname = name.lower().split()[-1] if name.split() else ""
                    hit = next((v for k, v in lower.items()
                                if len(surname) > 3 and k.split()[-1] == surname), None)
                if not hit:
                    continue
                player, model_p = hit
                # Calibrate against realized scorer hit rates (no-op until fitted).
                try:
                    from src.analytics.calibration import apply_calibration
                    model_p = apply_calibration(model_p, "soccer", "anytime_scorer")
                except Exception:
                    pass
                imp = _american_to_imp(float(price))
                edge = (model_p - imp) * 100.0
                if edge >= min_edge_pct:
                    edges.append({
                        "sport":        "soccer",
                        "market":       "anytime_scorer",
                        "direction":    "YES",
                        "team":         player,
                        "player":       player,
                        "matchup":      f"{away} @ {home}",
                        "odds":         int(price),
                        "best_odds":    int(price),
                        "model_prob":   round(model_p, 4),
                        "implied_prob": round(imp, 4),
                        "edge_pct":     round(edge, 2),
                        "sportsbook":   book,
                    })
    # best price per player
    best: dict[str, dict] = {}
    for e in edges:
        k = e["player"]
        if k not in best or e["edge_pct"] > best[k]["edge_pct"]:
            best[k] = e
    return sorted(best.values(), key=lambda x: x["edge_pct"], reverse=True)

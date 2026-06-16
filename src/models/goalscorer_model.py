"""
Goalscorer model — player-level anytime-scorer + Golden Boot projections.

The match model (SoccerModelV2) gives each team's expected goals for a fixture.
This module distributes those goals across players using each player's
recency-weighted share of their nation's goals, then converts to:

    anytime scorer:  P(player scores ≥1) = 1 - exp(-λ_player)
        where λ_player = team_expected_goals × player_goal_share
    Golden Boot:     Σ over the player's projected tournament matches of
        team_xg_per_match × share × P(team still alive that round)

Data source: martj42/international_results goalscorers.csv (same ecosystem as
the match model's training data). Players are derived from *recent* scorers —
this self-filters to active, in-form squads and needs no official roster feed.
The share is recency-weighted (2-year half-life) so current form dominates.

This is the subscription differentiator — "Ballpark Pal" player props for the
World Cup. Anytime-scorer odds are the single most-bet WC market.

Usage:
    gm = GoalscorerModel().fit()
    gm.anytime_scorer("Argentina", team_exp_goals=1.8)   # → ranked players
    gm.golden_boot(advance_probs, team_xg)               # → tournament leaders
"""
from __future__ import annotations

import csv
import io
import math
import unicodedata
from collections import defaultdict
from datetime import date

import requests

from src.data.soccer_data import _cache_path, normalize_team_name

GOALSCORERS_URL = ("https://raw.githubusercontent.com/martj42/"
                   "international_results/master/goalscorers.csv")

HALF_LIFE_YEARS = 2.0      # recency: a goal's weight halves every 2 years
ACTIVE_WINDOW_YEARS = 3.0  # a player must have scored within this window to count
MIN_YEAR = 2015            # ignore ancient history entirely


def _canon_key(name: str) -> str:
    """Diacritic-insensitive key so 'Julián Álvarez' == 'Julian Alvarez'."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _load_goalscorers_csv() -> list[dict]:
    """Fetch + cache goalscorers.csv (daily)."""
    cache = _cache_path("goalscorers_csv")
    raw: str | None = None
    if cache.exists():
        age = (date.today() - date.fromtimestamp(cache.stat().st_mtime)).days
        if age <= 1:
            raw = cache.read_text(encoding="utf-8")
    if raw is None:
        try:
            r = requests.get(GOALSCORERS_URL, timeout=30)
            r.raise_for_status()
            raw = r.text
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(raw, encoding="utf-8")
        except Exception as e:
            if cache.exists():
                raw = cache.read_text(encoding="utf-8")
            else:
                raise RuntimeError(f"Could not load goalscorers.csv: {e}")
    return list(csv.DictReader(io.StringIO(raw)))


class GoalscorerModel:
    """Recency-weighted goal-share model over international scorers."""

    def __init__(self) -> None:
        # team -> { player -> weighted goals }
        self._player_w: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        # team -> total weighted goals
        self._team_w: dict[str, float] = defaultdict(float)
        # team -> { player -> last goal date }
        self._last: dict[str, dict[str, date]] = defaultdict(dict)
        # team -> { player -> {"goals": raw count, "pens": pen count} }
        self._raw: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"goals": 0, "pens": 0}))
        # team -> { canon_key -> {original spelling -> count} } for display resolution
        self._disp: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        self.fitted = False

    def _display_name(self, team: str, key: str) -> str:
        """Most-frequent original spelling for a canonical player key."""
        counts = self._disp.get(team, {}).get(key)
        return max(counts, key=counts.get) if counts else key

    def fit(self, verbose: bool = False) -> "GoalscorerModel":
        rows = _load_goalscorers_csv()
        today = date.today()
        decay = math.log(2.0) / HALF_LIFE_YEARS
        kept = 0
        for row in rows:
            if row.get("own_goal", "FALSE").upper() == "TRUE":
                continue  # own goals don't credit a scorer
            try:
                d = date.fromisoformat(row["date"])
            except (ValueError, KeyError):
                continue
            if d.year < MIN_YEAR:
                continue
            scorer = (row.get("scorer") or "").strip()
            if not scorer:
                continue
            team = normalize_team_name((row.get("team") or "").strip())
            key = _canon_key(scorer)
            age_years = (today - d).days / 365.25
            w = math.exp(-decay * age_years)

            self._player_w[team][key] += w
            self._team_w[team] += w
            self._disp[team][key][scorer] += 1
            prev = self._last[team].get(key)
            if prev is None or d > prev:
                self._last[team][key] = d
            self._raw[team][key]["goals"] += 1
            if row.get("penalty", "FALSE").upper() == "TRUE":
                self._raw[team][key]["pens"] += 1
            kept += 1

        self.fitted = True
        if verbose:
            print(f"  [goalscorer] {kept:,} goals since {MIN_YEAR} across "
                  f"{len(self._player_w)} teams.")
        return self

    def _shares(self, team: str) -> list[tuple[str, float]]:
        """Active players' goal shares for a team, sorted desc. Sums ~1.0."""
        team = normalize_team_name(team)
        total = self._team_w.get(team, 0.0)
        if total <= 0:
            return []
        today = date.today()
        out = []
        for player, w in self._player_w[team].items():
            last = self._last[team].get(player)
            if last is None:
                continue
            if (today - last).days / 365.25 > ACTIVE_WINDOW_YEARS:
                continue  # inactive — likely retired / out of squad
            out.append((player, w))
        active_total = sum(w for _, w in out)
        if active_total <= 0:
            return []
        return sorted(((p, w / active_total) for p, w in out),
                      key=lambda x: x[1], reverse=True)

    def anytime_scorer(self, team: str, team_exp_goals: float,
                       top_n: int = 8,
                       market_anytime: dict[str, float] | None = None,
                       blend_alpha: float = 0.40) -> list[dict]:
        """
        Anytime-scorer projections for a team given its expected goals in a match.
        Returns ranked [{player, share, exp_goals, anytime_prob_raw, anytime_prob, pen_rate}].

        `anytime_prob` is the calibrated, market-blended value used for edge math:
            anytime_prob = alpha * raw_model + (1 - alpha) * market_implied
        `anytime_prob_raw` is preserved for transparency. If no market price is
        passed for a player, anytime_prob == anytime_prob_raw (no shrinkage).

        The blend is the same analytic Platt-equivalent we apply to WC moneylines
        (see scripts/wc_data.py): without a fitted goalscorer calibrator yet, the
        market is the strongest available prior to shrink raw model output toward.
        """
        team = normalize_team_name(team)
        shares = self._shares(team)
        if not shares:
            return []
        market_anytime = market_anytime or {}
        out = []
        for key, share in shares[:top_n]:
            lam = team_exp_goals * share
            anytime_raw = 1.0 - math.exp(-lam)
            raw = self._raw[team].get(key, {"goals": 0, "pens": 0})
            pen_rate = raw["pens"] / raw["goals"] if raw["goals"] else 0.0
            display = self._display_name(team, key)
            mp = market_anytime.get(display) or market_anytime.get(key)
            if mp is not None and 0 < mp < 1:
                anytime = blend_alpha * anytime_raw + (1 - blend_alpha) * mp
            else:
                anytime = anytime_raw
            out.append({
                "player": display,
                "share": round(share, 4),
                "exp_goals": round(lam, 3),
                "anytime_prob": round(anytime, 4),
                "anytime_prob_raw": round(anytime_raw, 4),
                "career_goals": raw["goals"],
                "pen_rate": round(pen_rate, 2),
            })
        return out

    def golden_boot(self, advance_probs: dict[str, float],
                    team_xg: dict[str, float],
                    n_teams: int = 25, top_n: int = 20) -> list[dict]:
        """
        Tournament expected-goals leaderboard.

        advance_probs: team -> P(advance from group) — proxy for how deep a team
            is expected to go (rough # of knockout matches scales with it).
        team_xg: team -> expected goals per match (group-stage average).
        Each player's expected tournament goals ≈ share × xg_per_match ×
            expected_matches, where expected_matches grows with advance prob.
        """
        rows: list[dict] = []
        # base 3 group games for everyone; extra knockout games scale with depth
        for team, adv in sorted(advance_probs.items(), key=lambda x: x[1], reverse=True)[:n_teams]:
            xg = team_xg.get(team)
            if not xg:
                continue
            exp_matches = 3.0 + adv * 3.0   # advancing teams play up to ~6-7 games
            for s in self.anytime_scorer(team, xg, top_n=10):
                rows.append({
                    "player": s["player"],
                    "team": team,
                    "exp_goals": round(s["share"] * xg * exp_matches, 2),
                    "share": s["share"],
                })
        rows.sort(key=lambda r: r["exp_goals"], reverse=True)
        return rows[:top_n]


def load_or_fit_goalscorer(verbose: bool = False) -> GoalscorerModel:
    return GoalscorerModel().fit(verbose=verbose)

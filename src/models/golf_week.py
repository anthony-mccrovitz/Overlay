"""Price THIS WEEK'S PGA Tour event, whatever it is — not just the majors.

WHY. The PGA model only ever ran four weeks a year, and not because the model
was majors-specific — the simulation prices win/top-N/make-cut/matchups for any
field. It ran on majors because it derived the FIELD from the Odds API board,
and the Odds API only carries the four majors. The field and the odds were
welded together, so no board meant no tournament.

This module separates them:

  field   ESPN scoreboard (src/data/golf_field.py) — every week, free
  skill   the existing live SG ratings + static PLAYER_DB fallback
  prices  the existing Monte Carlo simulation, unchanged
  odds    the Odds API board IF one exists for this event; otherwise the
          output is clearly a set of reads, not edges

HONESTY RULES, stated because each one is a bug this repo has already paid for:
  - A player with no SG data is priced at a measured-low default and LABELLED
    unrated — never silently given the field average (the UFC lane priced
    unknown fighters as average for months).
  - Weekly venues get NO course adjustment. The course profiles that exist are
    fitted to four specific major venues; applying quail_hollow weights to the
    Rocket Classic would be a made-up number wearing a fitted one's clothes.
  - If the event is in progress, the sim still prices the PRE-tournament
    question and says so — live repricing is a different model, not a flag.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from src.data.golf_field import GolfEvent
from src.models.pga_championship import (
    PLAYER_DB,
    SimulationOutput,
    _fetch_pgatour_sg_ratings,
    _merge_live_ratings,
    run_simulation,
)

# Skill (expected strokes-gained/round vs field) for a field player with no SG
# record anywhere. Weekly fields carry 40-60 such players — Korn Ferry
# graduates, sponsor exemptions, Monday qualifiers. 0.15 sits at roughly the
# 15th percentile of rated tour players: measurably worse than anyone with a
# rating, not a coin-flip zero. The exact value moves win probabilities for
# RATED players by <0.3pp either way — it prices the tail, not the winners.
UNRATED_SKILL = 0.15

# Form multiplier bounds applied to sg_total, same shape the majors model uses.
_FORM_CLAMP = (0.85, 1.15)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    for ch in ("'", "’", ".", "-"):
        s = s.replace(ch, "")
    return " ".join(s.lower().split())


@dataclass(frozen=True)
class WeeklyRead:
    player: str
    source: str              # "sg" | "owgr" | "none"
    skill: float
    win_pct: float
    top5_pct: float
    top10_pct: float
    top20_pct: float
    make_cut_pct: float
    live_score: str = ""

    @property
    def rated(self) -> bool:
        return self.source != "none"


def build_skill_map(field_names: list[str], *, refresh: bool = False,
                    ratings: dict | None = None,
                    owgr: dict[str, float] | None = None,
                    ) -> tuple[dict[str, float], dict[str, str]]:
    """{field player -> skill} plus {player -> rating source}.

    Three tiers, best available per player, each labelled:

      sg    real strokes-gained data (live feed when it exists, else the
            static DB). The live feed's host — statdata.pgatour.com — is
            currently DEAD; the code path stays because the fetch fails soft
            and will simply resume if the feed returns.
      owgr  world-ranking points through the fitted log-linear map
            (src/data/owgr.py, r²=0.52 on the 51-player overlap). Covers the
            world top ~300 — the entire rated population of a weekly field.
      none  UNRATED_SKILL, visibly labelled. Sponsor exemptions and Monday
            qualifiers, mostly.

    Ratings are keyed by pgatour/OWGR spellings, the field by ESPN's. Joined
    on a normalised form (accents/punctuation folded) — exact after folding,
    never fuzzy: this repo has both the L'udovit Klein bug (too strict) and
    the Michael Chandler/Page bug (too loose) in its history, and folded-exact
    is the point between them that has not yet produced a wrong person.
    """
    from src.data.owgr import fetch_rankings, skill_from_points

    if ratings is None:
        live = _fetch_pgatour_sg_ratings(refresh=refresh)
        ratings = _merge_live_ratings(PLAYER_DB, live)
    if owgr is None:
        owgr = fetch_rankings()
    by_norm = {_norm(k): v for k, v in ratings.items()}
    owgr_norm = {_norm(k): v for k, v in owgr.items()}

    skills: dict[str, float] = {}
    source: dict[str, str] = {}
    for name in field_names:
        p = by_norm.get(_norm(name))
        if p and "sg_total" in p:
            base = float(p["sg_total"])
            form = min(max(float(p.get("form", 1.0)), _FORM_CLAMP[0]),
                       _FORM_CLAMP[1])
            # base * form only. No course adjustment on purpose — the fitted
            # course profiles belong to four major venues, and a generic week
            # gets the honest number rather than a borrowed fit.
            skills[name] = base * form
            source[name] = "sg"
            continue
        pts = owgr_norm.get(_norm(name))
        if pts:
            skills[name] = skill_from_points(pts)
            source[name] = "owgr"
            continue
        skills[name] = UNRATED_SKILL
        source[name] = "none"
    return skills, source


def read_week(event: GolfEvent, *, n_sim: int = 100_000,
              ratings: dict | None = None,
              owgr: dict[str, float] | None = None,
              ) -> tuple[list[WeeklyRead], SimulationOutput]:
    """Model reads for every player in this week's field, best first."""
    names = [p.name for p in event.players]
    skills, source = build_skill_map(names, ratings=ratings, owgr=owgr)
    sim = run_simulation(names, skills, n_sim=n_sim)

    live = {p.name: p.score for p in event.players}
    reads = [
        WeeklyRead(
            player=n,
            source=source[n],
            skill=round(skills[n], 3),
            win_pct=round(sim.win_prob(n) * 100, 2),
            top5_pct=round(sim.top_n_prob(n, 5) * 100, 2),
            top10_pct=round(sim.top_n_prob(n, 10) * 100, 2),
            top20_pct=round(sim.top_n_prob(n, 20) * 100, 2),
            make_cut_pct=round(sim.make_cut_prob(n) * 100, 1),
            live_score=live.get(n, ""),
        )
        for n in names
    ]
    reads.sort(key=lambda r: -r.win_pct)
    return reads, sim


def market_for_event(event: GolfEvent) -> dict[str, dict]:
    """Winner odds for THIS event from any golf board that actually matches it.

    The Odds API's golf keys are majors-only futures. Most weeks nothing
    matches and this returns {} — which the caller must surface as "no market
    for this event", never silently price against the wrong tournament's board.
    Matching is by name token overlap between the event title and the board
    key, demanding a distinctive word in common (never just "golf"/"winner").
    """
    import os

    import requests

    from src.models.pga_championship import fetch_odds

    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        return {}
    try:
        r = requests.get("https://api.the-odds-api.com/v4/sports",
                         params={"apiKey": key}, timeout=15)
        r.raise_for_status()
        boards = [s["key"] for s in r.json()
                  if str(s.get("key", "")).startswith("golf") and s.get("active")]
    except Exception:
        return {}

    # len >= 3, not > 3: "PGA Championship" reduces to the token "pga", and a
    # 4-char floor silently unmatched the one board that SHOULD join. Found by
    # the positive-match test, which exists because the negative-match test
    # alone was satisfiable by matching nothing ever.
    stop = {"golf", "winner", "the", "tournament", "championship", "open"}
    ev_tokens = {t for t in _norm(event.name).split() if t not in stop and len(t) >= 3}
    for board in boards:
        board_tokens = {t for t in board.replace("golf_", "").split("_")
                        if t not in stop and len(t) >= 3}
        if ev_tokens & board_tokens:
            return fetch_odds(board)
    return {}

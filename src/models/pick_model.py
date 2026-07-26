"""
PickModel — the common contract every sport×market model implements.

This is the first brick of "the factory" (see the framework design): one
interface so a single runner can drive every model uniformly, and one gate
(`finalize_picks`) that every raw model output funnels through to become a
canonical, correctly-staked, correctly-carded pick.

Flow:
    SportContext (odds + matchups, fetched once per sport/date)
        → PickModel.generate_picks(ctx) → list[RawPick]      (model's job)
        → finalize_picks(raw, date)      → list[canonical dict]  (the gate)
        → append_picks_safe(...)                                  (the ledger)

A model author only implements generate_picks(). Card/shadow status, stake
sizing, edge storage, pick_id, and CLV stamping are handled centrally so no
model can accidentally post a phantom edge or mis-size a bet.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.config.models import is_card_pick, shadow_stake
from src.tracking.schema import normalize_pick


@dataclass
class SportContext:
    """Per-sport, per-date data the runner fetches ONCE and hands to every model
    for that sport — so N market-models don't each re-pull the odds board."""

    date: str  # YYYY-MM-DD (the game/slate date)
    odds_df: pd.DataFrame | None = None
    matchups: list = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawPick:
    """A model's raw output for a single bet, BEFORE the gate.

    `edge` is the market's own edge metric in that market's native units
    (run differential for totals, percentage points for moneyline). The gate
    stores it in `edge_pct` and uses it for the card threshold, exactly as the
    existing pipeline does.
    """

    sport: str
    market: str
    direction: str  # OVER / UNDER / HOME / AWAY / COVER / ...
    odds: int
    team: str = ""  # side label; totals use "OVER 7.5". Auto-derived if blank.
    matchup: str = ""
    line: float | None = None
    model_prob: float | None = None
    edge: float | None = None
    sportsbook: str = ""
    prop_market: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class PickModel(ABC):
    """Base contract. Subclasses set `sport`/`market` and implement generate_picks."""

    sport: str = ""
    market: str = ""

    @abstractmethod
    def generate_picks(self, ctx: SportContext) -> list[RawPick]:
        """Return this model's raw picks for the slate described by `ctx`."""
        raise NotImplementedError

    def fit(self) -> None:
        """Optional: (re)train the model. Default no-op for models fit elsewhere."""
        return None

    @property
    def key(self) -> tuple[str, str]:
        return (self.sport, self.market)


# ── The gate ─────────────────────────────────────────────────────────────────
# Every raw pick becomes a canonical pick here. This is the single chokepoint
# that decides card vs shadow, sizes the stake, and stamps the record — so the
# discipline ("nothing bets real money until the registry says it's live AND the
# edge clears the threshold") holds for every model, present and future.

def _default_team(rp: RawPick) -> str:
    if rp.team:
        return rp.team
    if rp.market in ("total", "f5_total") and rp.line is not None:
        # Match the existing convention, e.g. "OVER 7.5".
        line = rp.line
        line_s = f"{line:g}" if float(line) != int(line) else f"{int(line):d}.0"
        return f"{rp.direction} {line_s}"
    return rp.team


def finalize_picks(raw_picks: list[RawPick], date: str) -> list[dict]:
    """Turn model RawPicks into canonical, gated, schema-valid pick dicts.

    - `card_pick` = registry says live AND edge clears the market threshold
      (via is_card_pick — the same gate _auto_log_picks uses).
    - `stake` = shadow_stake (0.5u for unproven new sports, else 1.0u).
    - `edge_pct` stores the model's native edge, matching the current schema.
    - Skips picks with no real odds (unbettable), exactly like the pipeline.
    """
    out: list[dict] = []
    for rp in raw_picks:
        try:
            odds = int(float(rp.odds))
        except (TypeError, ValueError):
            odds = 0
        if not odds:
            continue  # model-only pick, not bettable — don't log

        card = is_card_pick(rp.sport, rp.market, rp.edge, rp.prop_market)
        raw = {
            "sport": rp.sport,
            "market": rp.market,
            "team": _default_team(rp),
            "matchup": rp.matchup,
            "direction": rp.direction,
            "date": date,
            "odds": odds,
            "line": rp.line,
            "sportsbook": rp.sportsbook,
            "model_prob": rp.model_prob,
            "edge_pct": rp.edge,
            "stake": shadow_stake(rp.sport, rp.market),
            "card_pick": bool(card),
            "prop_market": rp.prop_market,
        }
        # Carry through display extras the schema knows about (weather, proj).
        for k in ("weather_context", "proj_total", "team_form"):
            if k in rp.extras:
                raw[k] = rp.extras[k]

        norm = normalize_pick(raw)
        if norm is not None:
            out.append(norm)
    return out

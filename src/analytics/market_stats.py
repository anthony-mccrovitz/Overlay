"""
market_stats — per (sport, market) health computed from the ledger.

The flat-unit grade that powers `chef.py grid`: every settled pick counted as
1 unit risked, so markets are comparable regardless of the dollar/unit stakes
they were actually logged at. Same math as the model & market audit.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from src.config.models import _key

_PNL_FILE = Path("data/pnl/picks.json")


@dataclass
class MarketStat:
    sport: str
    market: str
    n: int = 0          # settled picks
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    roi: float | None = None      # flat-unit ROI %
    pnl: float = 0.0              # flat-unit P&L
    avg_odds: str = "—"
    clv: float | None = None      # mean clv_pct where available
    clv_n: int = 0
    beat: float | None = None     # % of clv samples > 0
    total_logged: int = 0         # includes still-pending

    @property
    def record(self) -> str:
        r = f"{self.wins}-{self.losses}"
        return r + (f"-{self.pushes}" if self.pushes else "")

    @property
    def wr(self) -> float | None:
        d = self.wins + self.losses
        return (self.wins / d * 100) if d else None


def _imp(o: float) -> float:
    o = float(o)
    return 100 / (o + 100) if o > 0 else (-o) / ((-o) + 100)


def _dec(o: float) -> float:
    o = float(o)
    return 1 + (o / 100 if o > 0 else 100 / (-o))


def _amer_from_imp(p: float) -> str:
    if p <= 0 or p >= 1:
        return "—"
    return f"+{round(100 * (1 - p) / p)}" if p <= 0.5 else f"-{round(100 * p / (1 - p))}"


def _load_picks(pnl_file: Path) -> list[dict]:
    try:
        raw = json.loads(pnl_file.read_text())
    except (OSError, ValueError):
        return []
    return raw.get("picks", raw) if isinstance(raw, dict) else raw


def market_stats(pnl_file: Path = _PNL_FILE) -> dict[tuple[str, str], MarketStat]:
    """Return {(canonical_sport, market): MarketStat} across the whole ledger."""
    picks = _load_picks(pnl_file)
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in picks:
        key = (_key(p.get("sport", ""), "")[0], (p.get("market") or "").lower())
        groups.setdefault(key, []).append(p)

    stats: dict[tuple[str, str], MarketStat] = {}
    for (sport, market), ps in groups.items():
        graded = [p for p in ps
                  if p.get("result") in ("win", "loss", "push", "void")
                  and p.get("odds") not in (None, 0)]
        st = MarketStat(sport=sport, market=market, total_logged=len(ps))
        if graded:
            st.n = len(graded)
            st.wins = sum(1 for p in graded if p["result"] == "win")
            st.losses = sum(1 for p in graded if p["result"] == "loss")
            st.pushes = sum(1 for p in graded if p["result"] in ("push", "void"))
            pnl = 0.0
            for p in graded:
                if p["result"] == "win":
                    pnl += _dec(p["odds"]) - 1
                elif p["result"] == "loss":
                    pnl -= 1
            st.pnl = pnl
            st.roi = pnl / len(graded) * 100
            st.avg_odds = _amer_from_imp(
                statistics.mean([_imp(p["odds"]) for p in graded]))
        clvs = [p.get("clv_pct") for p in ps if isinstance(p.get("clv_pct"), (int, float))]
        if clvs:
            st.clv = statistics.mean(clvs)
            st.clv_n = len(clvs)
            st.beat = sum(1 for c in clvs if c > 0) / len(clvs) * 100
        stats[(sport, market)] = st
    return stats

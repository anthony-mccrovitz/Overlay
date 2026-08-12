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
    # CLV comes from the snapshot ledger via clv_gate, NOT from the pick.
    # `clv` is in `clv_unit`: "%" for probability markets (moneyline/nrfi),
    # "pt" for line markets (spread/total/props). The two are NOT comparable
    # and must never be averaged or thresholded together — +0.23pt on
    # batter_total_bases coexists with a -2.9% ROI.
    clv: float | None = None      # mean CLV in clv_unit, or None if un-scored
    clv_unit: str | None = None   # "%" | "pt" | None
    clv_n: int = 0
    beat: float | None = None     # % of NON-FLAT clv samples > 0
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


def market_stats(pnl_file: Path = _PNL_FILE,
                 include_tainted: bool = False) -> dict[tuple[str, str], MarketStat]:
    """Return {(canonical_sport, market): MarketStat} across the whole ledger.

    TAINTED picks are excluded by default. They came from a known-broken
    mechanism (a degenerate calibrator that flattened every game to one
    probability, team-blind ratings), and this function is the ROI source for
    `chef.py record`, the build standard's promotion gate, the triage table and
    the dashboard — so including them let a broken model's output decide whether
    its own lane was profitable enough to promote.

    It also made `triage` self-inconsistent: it counted untainted picks for n
    while reading ROI from here, so a single row mixed two different samples.

    Pass include_tainted=True only for an audit view that deliberately wants the
    polluted history.
    """
    picks = _load_picks(pnl_file)
    if not include_tainted:
        picks = [p for p in picks if not p.get("tainted")]
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
        stats[(sport, market)] = st

    # CLV snapshots describe the REAL ledger only. Attaching them to a caller's
    # synthetic ledger would inject production numbers into unrelated picks —
    # a two-row fixture came back reporting clv_n=802.
    if pnl_file == _PNL_FILE:
        _attach_clv(stats)
    return stats


def _attach_clv(stats: dict[tuple[str, str], MarketStat]) -> None:
    """Fill clv/clv_unit/clv_n/beat from the snapshot ledger, in place.

    This used to read `p["clv_pct"]` off each pick — a field NO pick has ever
    carried. `clv_pct` is written onto CLV *snapshots*
    (src/analytics/clv_tracker.py), never back onto the pick, so the
    comprehension matched zero rows for all 16,111 picks and every lane
    reported clv=None, clv_n=0.

    That silence was not inert. `experiment_log._triage_call` computes
    `beats_close = clv is not None and clv > 0.5`, so the flag was
    unconditionally False and the triage screen printed verdicts of the form
    "CUT/REBUILD — no signal, losing on ROI + CLV" for lanes whose CLV it had
    never actually looked at. mlb/moneyline holds 802 scored snapshots at
    +0.51%; it was being judged as though it held none.

    The fix is to DELEGATE to src.analytics.clv_gate, which is already the one
    per-lane CLV implementation (shared by `chef.py edge` and `chef.py
    promote`). It keys lanes by src.config.models._key exactly as this function
    does — the two agree on 38 of 39 lanes — filters TAINTED snapshots, and
    picks the vig-consistent metric (novig → raw → legacy clv_pct). Computing
    CLV a second time here is precisely the duplication CLAUDE.md forbids.

    Note the unit split: clv_gate reports probability markets in % and line
    markets in points, so `clv_unit` travels with the number. Callers that
    threshold CLV must branch on it.

    Snapshots unreadable → clv_gate returns None → every lane keeps clv=None.
    That is the honest answer ("not measured"), and the closing-capture section
    of `chef.py monitor` is what alarms on it.
    """
    try:
        from src.analytics.clv_gate import clv_gate
        result = clv_gate()
    except Exception:
        return
    if not result:
        return
    rows, _meta = result
    for r in rows:
        st = stats.get((r["sport"], r["market"]))
        if st is None:
            continue
        st.clv = r["mean"]
        st.clv_unit = r["unit"]
        st.clv_n = r["n"]
        st.beat = r["beat_pct"]

"""
coverage.py — is the pipeline actually running?

Every measurement in this repo assumes picks get logged and closing lines get
captured. When that assumption quietly breaks, nothing errors: the ledger just
gets thinner, and every downstream number keeps reporting confidently on a
sample that stopped growing.

That has now happened three times. WNBA grading drifted for four weeks after a
field rename. Thousands of batter props accumulated with no grader at all. And
mlb/total — the one lane clearing both promotion gates — missed 15 of the last
45 days while its 58% beat-close figure went on being quoted.

The failure decomposes into two very different problems, so this module reports
them separately:

  PIPELINE GAP    the sport logged nothing at all that day. The run died, the
                  cron didn't fire, the API key expired.

  MARKET GAP      the sport logged fine, but THIS market produced nothing. The
                  pipeline is healthy and one model silently stopped emitting —
                  which is far easier to miss and was 9 of mlb/total's 15 days.

Capture rate is the third axis: a snapshot with no closing line joined can never
be scored, so a lane can look instrumented while being unmeasurable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

PICKS_PATH     = Path("data/pnl/picks.json")
SNAPSHOTS_PATH = Path("data/clv/snapshots.json")

DEFAULT_WINDOW = 30

# A live lane should be emitting on nearly every day its sport is active. Below
# this, something is broken even if the numbers still look fine.
MIN_MARKET_COVERAGE = 0.70
MIN_CAPTURE_RATE    = 0.60


@dataclass
class LaneCoverage:
    sport: str
    market: str
    window_days: int
    sport_active_days: int      # days the sport logged ANYTHING
    market_days: int            # days this market logged
    pipeline_gap_days: list[str] = field(default_factory=list)
    market_gap_days: list[str] = field(default_factory=list)
    last_logged: str | None = None

    @property
    def market_coverage(self) -> float:
        """Of the days the pipeline ran for this sport, how many produced picks
        in this market? Isolates a silent model failure from a dead pipeline."""
        if not self.sport_active_days:
            return 0.0
        return self.market_days / self.sport_active_days

    @property
    def pipeline_coverage(self) -> float:
        if not self.window_days:
            return 0.0
        return self.sport_active_days / self.window_days

    @property
    def longest_gap(self) -> int:
        """Longest consecutive run of days with no pick in this market."""
        gaps = sorted(set(self.pipeline_gap_days) | set(self.market_gap_days))
        if not gaps:
            return 0
        best = run = 1
        prev = date.fromisoformat(gaps[0])
        for g in gaps[1:]:
            cur = date.fromisoformat(g)
            run = run + 1 if (cur - prev).days == 1 else 1
            best = max(best, run)
            prev = cur
        return best


def canon_sport(sport) -> str:
    """Canonical registry label for a sport key.

    Picks and snapshots store tournament-scoped keys (tennis_atp_wimbledon,
    mma_mixed_martial_arts, golf_us_open_winner) while the registry holds one
    lane per sport. Normalising through the SAME function the registry uses is
    the whole fix — a local re-implementation of this mapping is what left the
    CLV gate reporting tennis as six truncated fragments, none of which ever
    reached the n=30 floor.
    """
    try:
        from src.config.models import _key
        return _key(str(sport or ""), "")[0]
    except Exception:
        return str(sport or "")


def _load(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    rows = data.get("picks", data) if isinstance(data, dict) else data
    return [r for r in rows if isinstance(r, dict)]


@lru_cache(maxsize=4)
def _picks_cached() -> tuple:
    return tuple(_load(PICKS_PATH))


def _window(days: int, today: date | None = None) -> list[str]:
    end = today or date.today()
    return [(end - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def lane_coverage(sport: str, market: str, days: int = DEFAULT_WINDOW,
                  picks: list[dict] | None = None,
                  today: date | None = None) -> LaneCoverage:
    rows = list(_picks_cached()) if picks is None else picks
    window = set(_window(days, today))

    sport_days: set[str] = set()
    market_days: set[str] = set()
    last: str | None = None
    target = canon_sport(sport)
    for r in rows:
        if canon_sport(r.get("sport")) != target:
            continue
        d = r.get("date")
        if not d:
            continue
        if r.get("market") == market:
            if last is None or d > last:
                last = d
            if d in window:
                market_days.add(d)
        if d in window:
            sport_days.add(d)

    # A day the sport was silent is a PIPELINE gap; a day it ran without this
    # market is a MARKET gap. Conflating them sends you debugging the wrong thing.
    pipeline_gaps = sorted(window - sport_days)
    market_gaps   = sorted(sport_days - market_days)

    return LaneCoverage(
        sport=sport, market=market, window_days=days,
        sport_active_days=len(sport_days), market_days=len(market_days),
        pipeline_gap_days=pipeline_gaps, market_gap_days=market_gaps,
        last_logged=last,
    )


def capture_rate(sport_prefix: str, days: int = DEFAULT_WINDOW,
                 today: date | None = None) -> tuple[int, int, float]:
    """(snapshots, with_closing, rate) for snapshots in the window.

    A snapshot with no closing line joined can never be scored, so a lane can
    look instrumented while being entirely unmeasurable — which is exactly how
    tennis reported 266 snapshots and zero usable CLV.
    """
    window = set(_window(days, today))
    n = closed = 0
    for s in _load(SNAPSHOTS_PATH):
        if canon_sport(s.get("sport")) != canon_sport(sport_prefix):
            continue
        if s.get("date") not in window:
            continue
        n += 1
        if s.get("closing_odds") is not None:
            closed += 1
    return n, closed, (closed / n if n else 0.0)


def healthy(cov: LaneCoverage) -> tuple[bool, str]:
    """Is this lane's pipeline in a state where its numbers can be trusted?"""
    if cov.sport_active_days == 0:
        return False, f"sport logged nothing in {cov.window_days}d — pipeline down or off-season"
    if cov.market_coverage < MIN_MARKET_COVERAGE:
        return False, (
            f"market emitted on {cov.market_days}/{cov.sport_active_days} active days "
            f"({cov.market_coverage:.0%}) — pipeline healthy, this model is not"
        )
    return True, (
        f"{cov.market_days}/{cov.sport_active_days} active days "
        f"({cov.market_coverage:.0%}), longest gap {cov.longest_gap}d"
    )


def report(days: int = DEFAULT_WINDOW, today: date | None = None) -> list[LaneCoverage]:
    """Coverage for every (sport, market) that has ever logged a pick."""
    rows = list(_picks_cached())
    lanes = sorted({(canon_sport(r.get("sport")), r.get("market")) for r in rows
                    if r.get("sport") and r.get("market")})
    return [lane_coverage(s, m, days, picks=rows, today=today) for s, m in lanes]

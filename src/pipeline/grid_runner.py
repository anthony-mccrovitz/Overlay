"""
grid_runner — the one loop that drives the model grid.

Walks the adapter registry, builds each sport's context (odds + matchups) ONCE,
runs every registered PickModel through the gate (finalize_picks), and logs the
canonical picks. This replaces the per-sport bespoke run_*.py dispatch with a
single uniform path — the factory's assembly line.

Step 2 of the rebuild. Only markets with a registered adapter run here; the rest
still flow through the legacy pipeline until migrated. Retired markets are
skipped. `dry_run=True` computes picks without touching the ledger — used to
prove parity against the live pipeline before cutting anything over.

CLI:
    python3 -m src.pipeline.grid_runner mlb --date 20260726 --dry-run
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path

from functools import partial
from typing import Callable

from src.config.models import is_retired, model_status
from src.models.pick_model import PickModel, SportContext, finalize_picks
from src.models.adapters.mlb_totals_model import MlbTotalsModel
from src.models.adapters.mlb_f5_totals_model import MlbF5TotalsModel
from src.models.adapters.soccer_model import SoccerModel, SOCCER_LEAGUES, league_label

# ── The plug-in registry ──────────────────────────────────────────────────────
# (sport, market) → factory returning a PickModel. Adding a market is one entry
# here plus its adapter. Everything downstream (gate, logging, promotion) is
# automatic. Soccer registers ONE entry per league (its own model/cell).
ADAPTERS: dict[tuple[str, str], Callable[[], PickModel]] = {
    ("mlb", "total"): MlbTotalsModel,
    ("mlb", "f5_total"): MlbF5TotalsModel,
}
for _lg in SOCCER_LEAGUES:
    ADAPTERS[(league_label(_lg), "moneyline")] = partial(SoccerModel, _lg)

_PNL_FILE = Path("data/pnl/picks.json")


@dataclass
class RunResult:
    sport: str
    date: str
    picks: list[dict] = field(default_factory=list)
    logged: int = 0
    dry_run: bool = False

    @property
    def card(self) -> int:
        return sum(1 for p in self.picks if p.get("card_pick"))

    @property
    def shadow(self) -> int:
        return len(self.picks) - self.card

    def by_market(self) -> dict[str, int]:
        return dict(Counter(p.get("market") for p in self.picks))

    def summary(self) -> str:
        verb = "would log" if self.dry_run else f"logged {self.logged} new,"
        bits = ", ".join(f"{m}={n}" for m, n in sorted(self.by_market().items()))
        return (f"[grid] {self.sport} {self.date}: {len(self.picks)} pick(s) "
                f"({self.card} card / {self.shadow} shadow) — {verb} [{bits}]")


def models_for_sport(sport: str) -> list[PickModel]:
    """Instantiate every registered, non-retired model for this sport."""
    models: list[PickModel] = []
    for (s, m), factory in ADAPTERS.items():
        if s != sport or is_retired(s, m):
            continue
        models.append(factory())
    return models


def build_context(sport: str, date_str: str) -> SportContext:
    """Fetch the shared odds + matchups for a sport/date once."""
    if sport == "mlb":
        return _build_mlb_context(date_str)
    if f"soccer_{sport}" in SOCCER_LEAGUES:
        return _build_soccer_league_context(f"soccer_{sport}", date_str)
    raise ValueError(f"grid_runner has no context builder for {sport!r} yet")


def _build_mlb_context(date_str: str) -> SportContext:
    # Reuses the exact loaders _run_mlb_daily uses, so the runner sees the same
    # board the legacy pipeline does.
    from src.data.mlb_stats import get_todays_matchups
    from src.data import odds_api
    from src.data.slate import filter_df_to_slate

    gd = _date.fromisoformat(date_str)
    matchups = get_todays_matchups(game_date=gd)
    raw_odds = odds_api.fetch_odds(
        markets="h2h,spreads,totals", sport="baseball_mlb", refresh=True
    )
    raw_odds = filter_df_to_slate(raw_odds, gd)
    return SportContext(date=date_str, odds_df=raw_odds, matchups=matchups)


def _build_soccer_league_context(league: str, date_str: str) -> SportContext:
    # One league's events. Reuses run_soccer's fetcher + slate filter so the
    # runner sees the same board.
    from run_soccer import fetch_soccer_odds
    from src.data.slate import filter_to_slate

    gd = _date.fromisoformat(date_str)
    events = filter_to_slate(fetch_soccer_odds(league) or [], gd)
    return SportContext(date=date_str, extras={"events": events})


def run_models(models: list[PickModel], ctx: SportContext) -> list[dict]:
    """Run each model → gate → canonical picks. The gate is the only chokepoint."""
    raw = []
    for model in models:
        raw.extend(model.generate_picks(ctx))
    return finalize_picks(raw, ctx.date)


def run_sport(
    sport: str,
    date_str: str,
    ctx: SportContext | None = None,
    dry_run: bool = False,
    pnl_file: Path = _PNL_FILE,
) -> RunResult:
    """Full path for one sport: build context → run models → (optionally) log."""
    if ctx is None:
        ctx = build_context(sport, date_str)
    picks = run_models(models_for_sport(sport), ctx)

    logged = 0
    if picks and not dry_run:
        from src.tracking.schema import append_picks_safe
        logged = append_picks_safe(pnl_file, picks)

    return RunResult(sport=sport, date=date_str, picks=picks,
                     logged=logged, dry_run=dry_run)


def sports_with_adapters() -> list[str]:
    """Distinct, non-retired sports that have at least one registered adapter."""
    seen: list[str] = []
    for (s, m) in ADAPTERS:
        if s not in seen and not is_retired(s, m):
            seen.append(s)
    return seen


def run_all(
    date_str: str, dry_run: bool = False, pnl_file: Path = _PNL_FILE
) -> list[RunResult]:
    """Run every registered sport's models for a date — the daily factory sweep.

    One sport's context/fetch failing never blocks the rest; that lane just
    returns no picks. This is the single entry point a daily cron calls to keep
    every shadow lane accumulating the CLV it needs to earn promotion.
    """
    results: list[RunResult] = []
    for sport in sports_with_adapters():
        try:
            results.append(run_sport(sport, date_str, dry_run=dry_run, pnl_file=pnl_file))
        except Exception as e:  # a dead odds feed for one league can't sink the sweep
            print(f"[grid] {sport} {date_str}: skipped ({type(e).__name__}: {e})")
    return results


def _normalize_date(raw: str | None) -> str:
    if not raw:
        return _date.today().isoformat()
    raw = raw.strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the model grid for a sport.")
    ap.add_argument("sport")
    ap.add_argument("--date", default=None, help="YYYYMMDD or YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute picks without writing to the ledger.")
    args = ap.parse_args(argv)

    date_str = _normalize_date(args.date)

    if args.sport in ("all", "grid"):
        results = run_all(date_str, dry_run=args.dry_run)
        for r in results:
            print(r.summary())
        total = sum(len(r.picks) for r in results)
        print(f"[grid] sweep: {total} pick(s) across {len(results)} sport(s).")
        return 0

    models = models_for_sport(args.sport)
    if not models:
        print(f"[grid] no registered adapters for {args.sport!r} "
              f"(registry has: {sorted({s for s, _ in ADAPTERS})}).")
        return 0

    print(f"[grid] models: " + ", ".join(
        f"{m.sport}/{m.market} ({model_status(m.sport, m.market)})" for m in models))
    result = run_sport(args.sport, date_str, dry_run=args.dry_run)
    print(result.summary())
    for p in result.picks:
        flag = "CARD " if p.get("card_pick") else "shadow"
        print(f"   [{flag}] {p['team']:12s} {p['matchup']:36s} "
              f"{p['odds']:>5} edge={p.get('edge_pct')} mp={p.get('model_prob')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

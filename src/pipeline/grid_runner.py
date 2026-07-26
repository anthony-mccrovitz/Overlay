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

from src.config.models import is_retired, model_status
from src.models.pick_model import PickModel, SportContext, finalize_picks
from src.models.adapters.mlb_totals_model import MlbTotalsModel
from src.models.adapters.soccer_model import SoccerModel, LEAGUES as _SOCCER_LEAGUES

# ── The plug-in registry ──────────────────────────────────────────────────────
# (sport, market) → PickModel factory. Adding a market to the factory is one
# line here plus its adapter. Everything downstream (gate, logging, promotion)
# is automatic.
ADAPTERS: dict[tuple[str, str], type[PickModel]] = {
    ("mlb", "total"): MlbTotalsModel,
    ("soccer", "moneyline"): SoccerModel,
}

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
    if sport == "soccer":
        return _build_soccer_context(date_str)
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


def _build_soccer_context(date_str: str) -> SportContext:
    # Reuses run_soccer's per-league odds fetcher + slate filter, so the runner
    # sees the same board. Events are grouped by league for the adapter.
    from run_soccer import fetch_soccer_odds
    from src.data.slate import filter_to_slate

    gd = _date.fromisoformat(date_str)
    events_by_league: dict[str, list] = {}
    for league in _SOCCER_LEAGUES:
        events = fetch_soccer_odds(league) or []
        events_by_league[league] = filter_to_slate(events, gd)
    return SportContext(date=date_str, extras={"events_by_league": events_by_league})


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

"""
Tests for grid_runner — the factory's assembly line (Step 2).

Deterministic: a fake adapter + synthetic context, so no odds/network needed.
Proves the loop runs registered models through the gate, skips retired markets,
filters by sport, and honors dry-run.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.models.pick_model import PickModel, RawPick, SportContext
from src.pipeline import grid_runner


class _FakeTotals(PickModel):
    sport = "mlb"
    market = "total"

    def generate_picks(self, ctx: SportContext):
        return [
            RawPick(sport="mlb", market="total", direction="OVER", odds=100,
                    matchup="Colorado Rockies @ Milwaukee Brewers",
                    line=7.5, model_prob=0.76, edge=2.0, sportsbook="BetRivers"),
            RawPick(sport="mlb", market="total", direction="UNDER", odds=-110,
                    matchup="A @ B", line=9.0, model_prob=0.7, edge=3.5,
                    sportsbook="Pinnacle"),
        ]


@pytest.fixture
def registered_fake(monkeypatch):
    monkeypatch.setattr(grid_runner, "ADAPTERS", {("mlb", "total"): _FakeTotals})


def test_runs_registered_model_through_gate(registered_fake):
    ctx = SportContext(date="2026-07-26", odds_df=pd.DataFrame({"x": [1]}))
    result = grid_runner.run_sport("mlb", "2026-07-26", ctx=ctx, dry_run=True)
    assert len(result.picks) == 2
    # Gate applied: 2.0-run edge < 3.0 → shadow; 3.5 ≥ 3.0 → card.
    assert result.card == 1 and result.shadow == 1
    assert result.by_market() == {"total": 2}
    assert result.logged == 0  # dry-run never writes


def test_dry_run_does_not_touch_ledger(registered_fake, tmp_path):
    pnl = tmp_path / "picks.json"
    pnl.write_text('{"picks": []}')
    ctx = SportContext(date="2026-07-26", odds_df=pd.DataFrame({"x": [1]}))
    grid_runner.run_sport("mlb", "2026-07-26", ctx=ctx, dry_run=True, pnl_file=pnl)
    assert pnl.read_text() == '{"picks": []}'


def test_live_run_appends_to_ledger(registered_fake, tmp_path):
    pnl = tmp_path / "picks.json"
    pnl.write_text('{"picks": []}')
    ctx = SportContext(date="2026-07-26", odds_df=pd.DataFrame({"x": [1]}))
    res = grid_runner.run_sport("mlb", "2026-07-26", ctx=ctx, pnl_file=pnl)
    assert res.logged == 2
    import json
    saved = json.loads(pnl.read_text())["picks"]
    assert len(saved) == 2
    # Idempotent: re-running the same slate adds nothing (pick_id dedup).
    res2 = grid_runner.run_sport("mlb", "2026-07-26", ctx=ctx, pnl_file=pnl)
    assert res2.logged == 0


def test_retired_market_is_skipped(monkeypatch):
    monkeypatch.setattr(grid_runner, "ADAPTERS", {("nascar", "outright"): _FakeTotals})
    # nascar/outright is retired in the registry.
    assert grid_runner.models_for_sport("nascar") == []


def test_filters_by_sport(registered_fake):
    assert len(grid_runner.models_for_sport("mlb")) == 1
    assert grid_runner.models_for_sport("nba") == []


class _FakeSoccer(PickModel):
    sport = "epl"
    market = "moneyline"

    def generate_picks(self, ctx: SportContext):
        return []


def test_sports_with_adapters_is_distinct_and_skips_retired(monkeypatch):
    monkeypatch.setattr(grid_runner, "ADAPTERS", {
        ("mlb", "total"): _FakeTotals,
        ("mlb", "f5_total"): _FakeTotals,   # same sport twice → one entry
        ("epl", "moneyline"): _FakeSoccer,
        ("nascar", "outright"): _FakeTotals,  # retired → excluded
    })
    assert grid_runner.sports_with_adapters() == ["mlb", "epl"]


def test_run_all_sweeps_every_sport_and_survives_a_bad_lane(monkeypatch, tmp_path):
    pnl = tmp_path / "picks.json"
    pnl.write_text('{"picks": []}')
    monkeypatch.setattr(grid_runner, "ADAPTERS", {
        ("mlb", "total"): _FakeTotals,
        ("epl", "moneyline"): _FakeSoccer,
    })
    # mlb builds its context via the real builder; stub both to avoid network.
    ctxs = {
        "mlb": SportContext(date="2026-07-26", odds_df=pd.DataFrame({"x": [1]})),
        "epl": SportContext(date="2026-07-26", extras={"events": []}),
    }
    def _ctx(sport, date_str):
        if sport == "epl":
            raise RuntimeError("dead odds feed")  # one lane blows up
        return ctxs[sport]
    monkeypatch.setattr(grid_runner, "build_context", _ctx)
    results = grid_runner.run_all("2026-07-26", pnl_file=pnl)
    # epl raised but the sweep still returned mlb's result.
    assert [r.sport for r in results] == ["mlb"]
    assert results[0].logged == 2

"""
Tests for the model grid (Step 3): state resolution + market stats.
"""
from __future__ import annotations

import json

from src.config.grid import GRID, cell_state, iter_grid, grid_counts, is_registered
from src.analytics.market_stats import market_stats


class TestGridState:
    def test_live_lane_resolves_live(self):
        # mlb total is a live registry model.
        assert cell_state("mlb", ["total"]) == "live"

    def test_unbuilt_lane_is_planned(self):
        # NFL game lines were this test's example until 2026-07-31, when the
        # lane was wired for the season (registry incubating/shadow). Its PROP
        # markets remain genuinely unbuilt — in the grid, absent from the
        # registry — which is exactly the state this test pins.
        assert cell_state("nfl", ["player_pass_yds"]) == "planned"
        # And the game lines now read shadow, not planned: wired, unproven.
        assert cell_state("nfl", ["total"]) == "shadow"

    def test_retired_lane_resolves_retired(self):
        # nascar/outright is registered but status=retired (dropped 2026-07-26).
        assert is_registered("nascar", "outright") is True
        assert cell_state("nascar", ["outright"]) == "retired"

    def test_priority_prefers_furthest_along(self):
        # A folded lane with one live + one planned key shows live.
        assert cell_state("mlb", ["total", "not_a_real_market"]) == "live"

    def test_every_cell_has_a_valid_state(self):
        valid = {"live", "shadow", "paused", "planned", "retired"}
        for _sport, _label, _keys, state in iter_grid():
            assert state in valid

    def test_counts_sum_to_cell_total(self):
        total_cells = sum(len(v) for v in GRID.values())
        assert sum(grid_counts().values()) == total_cells


class TestMarketStats:
    def test_flat_unit_roi(self, tmp_path):
        pnl = tmp_path / "picks.json"
        picks = [
            {"sport": "mlb", "market": "total", "odds": 100, "result": "win"},
            {"sport": "mlb", "market": "total", "odds": -110, "result": "loss"},
            {"sport": "mlb", "market": "total", "odds": 100, "result": "win"},
        ]
        pnl.write_text(json.dumps({"picks": picks}))
        st = market_stats(pnl)[("mlb", "total")]
        assert st.n == 3
        assert st.record == "2-1"
        # +1.0 (win @+100) -1.0 (loss) +1.0 (win) = +1.0 over 3 = +33.3%
        assert round(st.pnl, 2) == 1.0
        assert round(st.roi, 1) == 33.3

    def test_canonical_sport_folding(self, tmp_path):
        pnl = tmp_path / "picks.json"
        # 'baseball_mlb' and 'mlb' must fold to the same cell.
        picks = [
            {"sport": "baseball_mlb", "market": "total", "odds": 100, "result": "win"},
            {"sport": "mlb", "market": "total", "odds": 100, "result": "win"},
        ]
        pnl.write_text(json.dumps({"picks": picks}))
        stats = market_stats(pnl)
        assert ("mlb", "total") in stats
        assert stats[("mlb", "total")].n == 2

    def test_clv_is_not_read_off_the_pick(self, tmp_path):
        """CLV comes from the snapshot ledger, never from a field on the pick.

        This test previously fed picks carrying `clv_pct` and asserted they were
        summarised. That contract was fiction: `clv_pct` is written onto CLV
        *snapshots*, and no pick in the real ledger has ever carried it — so the
        code path under test never fired in production, and every lane reported
        clv=None while the test went green. See tests/test_market_stats_clv.py.

        A custom pnl_file also must NOT pick up the global snapshot ledger:
        those snapshots describe the real ledger, not this fixture.
        """
        pnl = tmp_path / "picks.json"
        picks = [
            {"sport": "mlb", "market": "moneyline", "odds": -110, "result": "win", "clv_pct": 2.0},
            {"sport": "mlb", "market": "moneyline", "odds": -110, "result": "loss", "clv_pct": -1.0},
        ]
        pnl.write_text(json.dumps({"picks": picks}))
        st = market_stats(pnl)[("mlb", "moneyline")]
        assert st.n == 2                     # the ROI half still reads the fixture
        assert st.clv is None and st.clv_n == 0, (
            "a synthetic ledger reported CLV — either clv_pct is being read off "
            "the pick again, or the real snapshot file leaked into this fixture"
        )

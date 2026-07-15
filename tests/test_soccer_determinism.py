"""
tests/test_soccer_determinism.py — World Cup / soccer reproducibility guard.

The WC model once printed Argentina 45.7% on one run and England 41.6% on the
next for the identical fixture. Root cause: seed_from_eloratings() fetched live
Elo on every run and, on intermittent fetch failure, silently fell back to a
DIFFERENT rating basis (the computed Elo in the pickle). These tests pin the two
invariants that make picks reproducible:

  1. matchup()/find_edges() are deterministic given fixed model state.
  2. A failed live fetch reuses the last-good cached snapshot, not a divergent
     rating basis — so same-day re-runs land on the same numbers.

Run: python3 -m pytest tests/test_soccer_determinism.py -v
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.models.soccer_model_v2 as sm
from src.models.soccer_model_v2 import SoccerModelV2


def _fixed_model() -> SoccerModelV2:
    """A model with hand-set state — no fit, no network, fully determined."""
    m = SoccerModelV2()
    m.mu, m.alpha, m.beta, m.delta = 0.30, 1.00, 0.30, 0.30
    m.temperature = 1.0
    m.league_avg = 1.30
    m.elo_ratings = {"England": 1890.0, "Argentina": 1858.0}
    m.atk_ratings = {}
    m.dfn_ratings = {}
    m.fitted_on = date(2026, 7, 1)
    return m


class TestMatchupDeterminism:
    def test_matchup_is_reproducible(self):
        m = _fixed_model()
        a = m.matchup("England", "Argentina", neutral=True)
        b = m.matchup("England", "Argentina", neutral=True)
        assert a == b

    def test_higher_elo_is_favored(self):
        # Sanity: England (higher Elo) must not be the underdog on a neutral field.
        m = _fixed_model()
        r = m.matchup("England", "Argentina", neutral=True)
        assert r["home_win"] >= r["away_win"]


class TestEloSnapshotFallback:
    def test_failed_fetch_reuses_cached_snapshot(self, tmp_path, monkeypatch):
        # Point the snapshot at a temp file and pre-seed a known-good snapshot.
        snap = tmp_path / "eloratings_snapshot.json"
        snap.write_text(json.dumps(
            {"fetched_at": "2026-07-14", "ratings": {"Brazil": 2050.0}}))
        monkeypatch.setattr(sm, "ELO_SNAPSHOT_PATH", snap)
        # Force the live fetch to fail.
        monkeypatch.setattr(SoccerModelV2, "_fetch_eloratings",
                            staticmethod(lambda: None))
        m = SoccerModelV2()
        m.elo_ratings = {"Brazil": 1500.0}
        m.seed_from_eloratings(allow_network=True)
        # Must have taken Brazil from the cache, not left the stale 1500.
        assert m.elo_ratings["Brazil"] == 2050.0

    def test_successful_fetch_writes_snapshot(self, tmp_path, monkeypatch):
        snap = tmp_path / "eloratings_snapshot.json"
        monkeypatch.setattr(sm, "ELO_SNAPSHOT_PATH", snap)
        monkeypatch.setattr(SoccerModelV2, "_fetch_eloratings",
                            staticmethod(lambda: {"Spain": 2000.0}))
        m = SoccerModelV2()
        m.elo_ratings = {}
        m.seed_from_eloratings(allow_network=True)
        assert snap.exists()
        cached = json.loads(snap.read_text())["ratings"]
        assert cached["Spain"] == 2000.0

    def test_no_network_no_cache_is_safe(self, tmp_path, monkeypatch):
        # No snapshot on disk + no network must not crash and must leave state intact.
        monkeypatch.setattr(sm, "ELO_SNAPSHOT_PATH", tmp_path / "missing.json")
        m = SoccerModelV2()
        m.elo_ratings = {"Italy": 1700.0}
        m.seed_from_eloratings(allow_network=False)
        assert m.elo_ratings["Italy"] == 1700.0

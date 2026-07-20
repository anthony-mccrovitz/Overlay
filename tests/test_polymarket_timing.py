"""
tests/test_polymarket_timing.py — price discovery by lead time.

This module decides WHEN the scanner should look, so a bug here sends every
future entry to the wrong moment. The traps it has to avoid are all about
reading a price series correctly:

  - "price at T-12h" means the last price at or before that instant, not the
    nearest one — a resting order sees the last trade, never a future one
  - a market already resolved to 0/1 is not evidence about pre-game discovery
  - move-remaining is an absolute distance; drift keeps its sign, because a
    systematic direction is tradeable and an average of absolutes hides it

Run: python3 -m pytest tests/test_polymarket_timing.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from scripts.polymarket_timing import _epoch, _price_at, analyse

START = 1784548800          # 2026-07-20T12:00:00Z


def _hist(points):
    """[(hours_before_start, price)] → ascending history rows."""
    return sorted(({"t": START - int(h * 3600), "p": p} for h, p in points),
                  key=lambda x: x["t"])


def _market(token="tok"):
    return {"question": "A vs. B", "game_start": "2026-07-20T12:00:00Z",
            "token": token}


class TestPriceAt:
    HIST = _hist([(48, 0.30), (24, 0.35), (12, 0.40), (0, 0.45)])

    def test_uses_last_price_at_or_before(self):
        assert _price_at(self.HIST, START - 20 * 3600) == 0.35   # 24h reading
        assert _price_at(self.HIST, START - 12 * 3600) == 0.40   # exact hit

    def test_never_looks_into_the_future(self):
        """A price 6h before kickoff cannot know the 1h price."""
        assert _price_at(self.HIST, START - 30 * 3600) == 0.30

    def test_before_any_data_is_none(self):
        assert _price_at(self.HIST, START - 100 * 3600) is None

    def test_empty_history_is_none(self):
        assert _price_at([], START) is None


class TestAnalyse:
    def _patch(self, monkeypatch, hist):
        import scripts.polymarket_timing as t
        monkeypatch.setattr(t, "fetch_price_history", lambda tok, **k: hist)

    def test_move_remaining_shrinks_as_kickoff_approaches(self, monkeypatch):
        """The core shape: less is left to discover the closer you get."""
        self._patch(monkeypatch, _hist([(48, 0.20), (24, 0.30),
                                        (12, 0.36), (1, 0.39), (0, 0.40)]))
        rows = {r["lead_hours"]: r for r in
                analyse([_market()], leads=(48, 24, 12, 1))["rows"]}
        assert rows[48]["move_remaining"] == pytest.approx(0.20)
        assert rows[24]["move_remaining"] == pytest.approx(0.10)
        assert rows[12]["move_remaining"] == pytest.approx(0.04)
        assert rows[1]["move_remaining"] == pytest.approx(0.01)

    def test_drift_keeps_its_sign(self, monkeypatch):
        """Direction is tradeable; averaging absolutes would erase it."""
        self._patch(monkeypatch, _hist([(24, 0.60), (0, 0.40)]))
        row = analyse([_market()], leads=(24,))["rows"][0]
        assert row["drift"] == pytest.approx(-0.20)
        assert row["move_remaining"] == pytest.approx(0.20)

    def test_resolved_market_is_not_counted(self, monkeypatch):
        """A track pinned at 0/1 has already settled and says nothing about
        pre-game price discovery."""
        self._patch(monkeypatch, _hist([(24, 1.0), (0, 1.0)]))
        assert analyse([_market()], leads=(24,))["rows"] == []

    def test_pct_moving_over_two_cents(self, monkeypatch):
        self._patch(monkeypatch, _hist([(24, 0.50), (0, 0.55)]))
        row = analyse([_market()], leads=(24,))["rows"][0]
        assert row["pct_moving_over_2c"] == 100.0

    def test_market_without_history_is_skipped(self, monkeypatch):
        self._patch(monkeypatch, [])
        out = analyse([_market()], leads=(24,))
        assert out["n_markets"] == 0 and out["rows"] == []

    def test_unparseable_start_is_skipped(self, monkeypatch):
        self._patch(monkeypatch, _hist([(24, 0.5), (0, 0.5)]))
        m = _market()
        m["game_start"] = "not-a-date"
        assert analyse([m], leads=(24,))["n_markets"] == 0


class TestEpoch:
    def test_handles_both_timestamp_shapes(self):
        """Polymarket returns "2026-07-21 10:30:00+00"; ISO uses a T."""
        assert _epoch("2026-07-20T12:00:00Z") == START
        assert _epoch("2026-07-20 12:00:00+00") == START

    def test_naive_timestamps_are_treated_as_utc(self):
        assert _epoch("2026-07-20T12:00:00") == START

    def test_garbage_is_none(self):
        assert _epoch("nonsense") is None
        assert _epoch(None) is None

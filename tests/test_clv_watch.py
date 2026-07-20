"""
tests/test_clv_watch.py — Weekly CLV watcher classification guard.

The watcher decides which markets are PROVEN edge candidates vs mirages vs
outlier-driven noise. On a real-money bankroll those labels must be right: a
positive mean that <50% of picks beat, or an "edge" that loses to Pinnacle's
close, must NEVER show up as bettable. These tests pin that logic.

Run: python3 -m pytest tests/test_clv_watch.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.clv_watch as cw


def _row(**kw):
    base = dict(sport="mlb", market="total", label="mlb · total", n=250,
                mean=0.3, unit="pt", beat_pct=58.0, sharp_mean=0.25, sharp_n=200,
                p_pos=0.001, is_candidate=True, verdict="✅ EDGE CANDIDATE")
    base.update(kw)
    return base


def _patch(monkeypatch, rows, vel=None, prev=None):
    monkeypatch.setattr(cw, "_rows", lambda min_n: (rows, {
        "min_n": 200, "alpha": 0.00625, "m_tests": 8}))
    monkeypatch.setattr(cw, "_velocity", lambda: vel or {})
    monkeypatch.setattr(cw, "_last_history", lambda: prev)


class TestEta:
    def test_at_floor(self):
        assert cw._eta_weeks(250, 200, 10) == 0.0

    def test_building(self):
        assert cw._eta_weeks(100, 200, 20) == 5.0

    def test_no_accrual_is_none(self):
        assert cw._eta_weeks(100, 200, 0) is None


class TestSportLabel:
    def test_known_maps(self):
        assert cw._sport_label("baseball_mlb") == "mlb"
        assert cw._sport_label("soccer_fifa_world_cup") == "wc"


class TestClassification:
    def test_clean_positive_is_real_candidate(self, monkeypatch):
        _patch(monkeypatch, [_row()], vel={"mlb·total": {"per_week": 15}})
        m = cw.build(200)["markets"][0]
        assert m["real_candidate"] is True
        assert m["mirage"] is False and m["outlier_driven"] is False

    def test_sub50_beat_is_outlier_not_candidate(self, monkeypatch):
        # t-test positive but only 27% beat the close -> outlier-driven, NOT bettable
        _patch(monkeypatch, [_row(beat_pct=27.0)])
        m = cw.build(200)["markets"][0]
        assert m["outlier_driven"] is True
        assert m["real_candidate"] is False

    def test_positive_best_negative_sharp_is_mirage(self, monkeypatch):
        # beats best book but loses to Pinnacle's close -> mirage, NOT bettable
        _patch(monkeypatch, [_row(sharp_mean=-0.2)])
        m = cw.build(200)["markets"][0]
        assert m["mirage"] is True
        assert m["real_candidate"] is False

    def test_below_floor_never_candidate(self, monkeypatch):
        _patch(monkeypatch, [_row(n=120, is_candidate=False,
                                  verdict="insufficient (need 200)")],
               vel={"mlb·total": {"per_week": 20}})
        m = cw.build(200)["markets"][0]
        assert m["real_candidate"] is False
        assert m["eta_weeks"] == 4.0   # (200-120)/20

    def test_crossing_up_detected(self, monkeypatch):
        prev = {"date": "2026-07-08", "markets": [
            {"key": "mlb·total", "n": 190, "is_candidate": False}]}
        _patch(monkeypatch, [_row()], vel={"mlb·total": {"per_week": 15}}, prev=prev)
        m = cw.build(200)["markets"][0]
        assert m["crossed"] == "up"
        assert m["delta_n"] == 60      # 250 - 190

    def test_crossing_down_detected(self, monkeypatch):
        prev = {"date": "2026-07-08", "markets": [
            {"key": "mlb·total", "n": 240, "is_candidate": True}]}
        _patch(monkeypatch, [_row(mean=-0.1, is_candidate=False, beat_pct=44.0)],
               prev=prev)
        m = cw.build(200)["markets"][0]
        assert m["crossed"] == "down"

    def test_history_stores_real_flag_not_raw(self, monkeypatch, tmp_path):
        # An outlier row (raw is_candidate True) must be recorded as NOT a
        # candidate, so next week doesn't falsely see a "crossed down".
        monkeypatch.setattr(cw, "HISTORY", tmp_path / "h.jsonl")
        monkeypatch.setattr(cw, "LATEST", tmp_path / "l.json")
        _patch(monkeypatch, [_row(beat_pct=27.0)])
        report = cw.build(200)
        cw.record(report)
        import json
        line = json.loads((tmp_path / "h.jsonl").read_text().strip())
        assert line["markets"][0]["is_candidate"] is False

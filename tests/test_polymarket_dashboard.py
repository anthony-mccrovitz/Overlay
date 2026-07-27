"""
tests/test_polymarket_dashboard.py — the daily screen.

A dashboard is read at a glance and believed, so its failure mode is quiet:
a wrong lead time or a miscounted open position looks exactly like a right
one. It also has to survive missing inputs — the fills, timing and paper
files legitimately do not exist on a fresh clone, and a dashboard that
crashes when a sibling report has not run yet is a dashboard nobody keeps.

Run: python3 -m pytest tests/test_polymarket_dashboard.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import scripts.polymarket_dashboard as db


@pytest.fixture
def picks_file(tmp_path, monkeypatch):
    f = tmp_path / "picks.json"
    f.write_text(json.dumps({"picks": []}))
    monkeypatch.setattr(db, "PICKS_FILE", f)
    monkeypatch.setattr(db, "FILLS_FILE", tmp_path / "missing_fills.json")
    monkeypatch.setattr(db, "TIMING_FILE", tmp_path / "missing_timing.json")

    def _write(rows):
        f.write_text(json.dumps({"picks": list(rows)}))
    return _write


def _pick(**over):
    p = {"strategy": "polymarket_ev", "date": "2026-07-20", "team": "X",
         "recorded_at": "2026-07-20T12:00:00+00:00",
         "poly_game_start": "2026-07-21T00:00:00Z"}
    p.update(over)
    return p


class TestLeadTime:
    def test_lead_is_hours_from_entry_to_kickoff(self):
        assert db._hours_before_start(_pick()) == pytest.approx(12.0)

    def test_polymarket_space_separated_timestamp_parses(self):
        """Gamma returns "2026-07-21 00:00:00+00", not ISO with a T. Silently
        returning None here would blank the whole timing column."""
        assert db._hours_before_start(
            _pick(poly_game_start="2026-07-21 00:00:00+00")) == pytest.approx(12.0)

    def test_missing_either_timestamp_is_none(self):
        assert db._hours_before_start(_pick(poly_game_start=None)) is None
        assert db._hours_before_start(_pick(recorded_at=None)) is None

    def test_garbage_timestamp_is_none_not_an_exception(self):
        assert db._hours_before_start(_pick(recorded_at="nope")) is None

    def test_entry_after_kickoff_is_negative(self):
        """In-play entries should read as negative, never silently absolute."""
        late = _pick(recorded_at="2026-07-21T02:00:00+00:00")
        assert db._hours_before_start(late) == pytest.approx(-2.0)


class TestBuild:
    def test_only_polymarket_picks_are_counted(self, picks_file):
        picks_file([_pick(), _pick(strategy="devig_ev"), _pick(strategy=None)])
        assert len(db.build("2026-07-20")["picks"]) == 1

    def test_settled_and_open_partition_cleanly(self, picks_file):
        picks_file([_pick(result="win"), _pick(result="loss"),
                    _pick(result=None), _pick()])
        d = db.build("2026-07-20")
        assert len(d["settled"]) == 2
        assert len(d["open"]) == 2
        assert len(d["settled"]) + len(d["open"]) == len(d["picks"])

    def test_today_filter_respects_the_slate_date(self, picks_file):
        picks_file([_pick(date="2026-07-20"), _pick(date="2026-07-21")])
        assert len(db.build("2026-07-20")["today"]) == 1
        assert len(db.build("2026-07-21")["today"]) == 1

    def test_fill_status_partitions_by_the_flag(self, picks_file):
        picks_file([_pick(poly_filled=True), _pick(poly_filled=False),
                    _pick()])            # unchecked
        d = db.build("2026-07-20")
        assert len(d["filled"]) == 1
        assert len(d["unfilled"]) == 1   # unchecked counts as neither

    def test_push_and_void_count_as_settled(self, picks_file):
        picks_file([_pick(result="push"), _pick(result="void")])
        assert len(db.build("2026-07-20")["settled"]) == 2


class TestMissingInputs:
    def test_runs_with_no_sibling_reports(self, picks_file, capsys):
        """Fresh clone: fills/timing/paper files absent. Must not crash."""
        picks_file([_pick()])
        db.run("2026-07-20")
        out = capsys.readouterr().out
        assert "POLYMARKET PILOT" in out
        assert "not measured" in out

    def test_runs_with_no_picks_at_all(self, picks_file, capsys):
        picks_file([])
        db.run("2026-07-20")
        assert "nothing cleared the bar" in capsys.readouterr().out

    def test_corrupt_picks_file_does_not_crash(self, tmp_path, monkeypatch):
        f = tmp_path / "picks.json"
        f.write_text("{not json")
        monkeypatch.setattr(db, "PICKS_FILE", f)
        assert db.build("2026-07-20")["picks"] == []

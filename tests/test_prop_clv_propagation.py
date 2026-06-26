"""Regression test for the prop-CLV market-propagation bug.

Prop picks carry the specific Odds API market in `prop_market`
(pitcher_strikeouts, player_threes, …) but used to be snapshotted with the
generic market="prop", which the closing-line join can't match — so 1,400+
prop picks silently never scored. snapshot_from_pnl must promote prop_market
onto the snapshot so the join works. This locks that in.
"""
import json

from src.analytics import clv_tracker


def _run_snapshot(tmp_path, monkeypatch, pick):
    """Run snapshot_from_pnl against a one-pick picks.json and return snapshots."""
    pnl = tmp_path / "picks.json"
    pnl.write_text(json.dumps({"picks": [pick]}))
    snaps_file = tmp_path / "snapshots.json"

    # Point the tracker's file constants at the temp files.
    monkeypatch.setattr(clv_tracker, "SNAPSHOTS_FILE", snaps_file)
    monkeypatch.chdir(tmp_path)
    # snapshot_from_pnl reads the literal data/pnl/picks.json path.
    (tmp_path / "data" / "pnl").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "pnl" / "picks.json").write_text(json.dumps({"picks": [pick]}))
    (tmp_path / "data" / "clv").mkdir(parents=True, exist_ok=True)

    clv_tracker.snapshot_from_pnl(pick["date"])
    return json.loads(snaps_file.read_text())


def test_prop_market_promoted_to_specific_type(tmp_path, monkeypatch):
    pick = {
        "date": "2026-06-25", "sport": "baseball_mlb", "market": "prop",
        "prop_market": "pitcher_strikeouts", "player": "Davis Martin",
        "team": "Davis Martin UNDER 6.5", "direction": "UNDER",
        "line": 6.5, "odds": -115, "matchup": "A @ B",
    }
    snaps = _run_snapshot(tmp_path, monkeypatch, pick)
    assert len(snaps) == 1
    # The snapshot must carry the SPECIFIC market, not the generic "prop".
    assert snaps[0]["market"] == "pitcher_strikeouts"


def test_generic_prop_without_prop_market_stays_prop(tmp_path, monkeypatch):
    # No prop_market recorded → nothing to promote → stays "prop" (unscoreable,
    # but must not crash or invent a market).
    pick = {
        "date": "2026-06-25", "sport": "baseball_mlb", "market": "prop",
        "player": "Some Guy", "team": "Some Guy OVER 1.5", "direction": "OVER",
        "line": 1.5, "odds": -110, "matchup": "A @ B",
    }
    snaps = _run_snapshot(tmp_path, monkeypatch, pick)
    assert snaps[0]["market"] == "prop"


def test_relabel_is_dedup_safe(tmp_path, monkeypatch):
    # relabel must never create a duplicate when a specific-market snapshot
    # already exists for the same pick.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "pnl").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "clv").mkdir(parents=True, exist_ok=True)
    pick = {
        "date": "2026-06-25", "team": "Davis Martin UNDER 6.5",
        "market": "prop", "prop_market": "pitcher_strikeouts",
    }
    (tmp_path / "data" / "pnl" / "picks.json").write_text(json.dumps({"picks": [pick]}))
    snaps_file = tmp_path / "snapshots.json"
    # Pre-seed BOTH a generic and the specific snapshot for the same pick.
    snaps_file.write_text(json.dumps([
        {"date": "2026-06-25", "team": "Davis Martin UNDER 6.5", "market": "prop", "strategy": None},
        {"date": "2026-06-25", "team": "Davis Martin UNDER 6.5", "market": "pitcher_strikeouts", "strategy": None},
    ]))
    monkeypatch.setattr(clv_tracker, "SNAPSHOTS_FILE", snaps_file)
    clv_tracker.relabel_prop_snapshots()
    out = json.loads(snaps_file.read_text())
    specific = [s for s in out if s["market"] == "pitcher_strikeouts"]
    # Must not have duplicated the specific-market row.
    assert len(specific) == 1

from pathlib import Path

from src.tracking.pnl import PnLTracker


def test_record_pick_and_summary(tmp_path: Path):
    tracker = PnLTracker(path=tmp_path / "picks.json")
    tracker.record_pick(
        game_id="game-1",
        team="Purdue",
        opponent="UCLA",
        odds=-120,
        model_prob=0.58,
        bet_size=10.0,
    )
    summary = tracker.get_summary()
    assert summary["total_picks"] == 1
    assert summary["settled_picks"] == 0
    assert summary["roi"] == 0.0


def test_duplicate_pick_rejected(tmp_path: Path):
    tracker = PnLTracker(path=tmp_path / "picks.json")
    tracker.record_pick(
        game_id="game-1",
        team="Purdue",
        opponent="UCLA",
        odds=-120,
        model_prob=0.58,
        bet_size=10.0,
    )
    try:
        tracker.record_pick(
            game_id="game-1",
            team="Purdue",
            opponent="UCLA",
            odds=-120,
            model_prob=0.58,
            bet_size=10.0,
        )
        assert False, "Expected duplicate pick ValueError"
    except ValueError:
        pass


def test_record_result_updates_roi(tmp_path: Path):
    tracker = PnLTracker(path=tmp_path / "picks.json")
    tracker.record_pick(
        game_id="game-2",
        team="Duke",
        opponent="UNC",
        odds=150,
        model_prob=0.47,
        bet_size=20.0,
    )
    tracker.record_result(game_id="game-2", team="Duke", won=True)
    summary = tracker.get_summary()
    assert summary["wins"] == 1
    assert summary["losses"] == 0
    assert summary["units_profit"] == 30.0
    assert summary["roi"] == 1.5


def test_corrupt_json_auto_recovers(tmp_path: Path):
    path = tmp_path / "picks.json"
    path.write_text("{bad json", encoding="utf-8")
    tracker = PnLTracker(path=path)
    summary = tracker.get_summary()
    assert summary["total_picks"] == 0
    assert (tmp_path / "picks.corrupt.json").exists()

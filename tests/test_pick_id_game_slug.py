"""One wager, one pick_id — the game slug is not optional.

THE BUG THIS PINS. make_pick_id grew an optional game= qualifier so two games
sharing a line label ("OVER 7.5") could not dedup each other away. But three
writers (predict.py x2, run_nba.py) kept minting WITHOUT it, while
normalize_pick minted WITH it for the same wagers. Same bet, two ids —
append_picks_safe's dedup is blind to the pair, and on 2026-08-02 all three
live card totals sat in the ledger twice, which would have double-counted the
public record at grading time. 29 twin pairs existed ledger-wide.

Two guards:
  1. Every make_pick_id call site must pass game= (AST scan — same approach
     as test_sport_key_single_source.py: kill the drift class, not instances).
  2. migrate_picks_file collapses existing twins, but ONLY when the matchups
     match — an unqualified "OVER 7.5" from a different game is a distinct
     wager, and merging it would fabricate a graded result for the wrong game.
"""
import ast
import json
from pathlib import Path

from src.tracking.schema import migrate_picks_file

ROOT = Path(__file__).resolve().parent.parent

_SCAN_DIRS = ["src", "scripts"]
_SCAN_ROOT_GLOBS = ["*.py"]


def _make_pick_id_calls(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else (
            fn.attr if isinstance(fn, ast.Attribute) else "")
        if name == "make_pick_id":
            yield node


def test_every_make_pick_id_call_passes_game():
    files = []
    for pat in _SCAN_ROOT_GLOBS:
        files += ROOT.glob(pat)
    for d in _SCAN_DIRS:
        files += (ROOT / d).rglob("*.py")

    offenders = []
    for f in files:
        for call in _make_pick_id_calls(f):
            kw = {k.arg for k in call.keywords}
            # 6th positional arg is game — allow it, though keyword is the norm
            if "game" not in kw and len(call.args) < 6:
                offenders.append(f"{f.relative_to(ROOT)}:{call.lineno}")

    assert not offenders, (
        "make_pick_id called without game= — this re-splits ids from the ones "
        "normalize_pick mints for the same wager and the ledger double-logs "
        "(or dedups away a real second game). Pass game=<matchup>:\n  "
        + "\n  ".join(offenders)
    )


# ─────────────────────── migration twin collapse ────────────────────────────

def _row(pick_id, matchup, **over):
    base = {
        "pick_id": pick_id, "date": "2026-08-02", "sport": "mlb",
        "market": "total", "direction": "OVER", "team": "OVER 6.5",
        "matchup": matchup, "odds": -110, "line": 6.5, "stake": 1.0,
        "sportsbook": "Hard Rock Bet", "card_pick": True,
        "recorded_at": "2026-08-02T04:53:52+00:00",
    }
    base.update(over)
    return base


def _migrate(tmp_path, rows):
    f = tmp_path / "picks.json"
    f.write_text(json.dumps({"picks": rows}))
    migrate_picks_file(str(f))
    return json.loads(f.read_text())["picks"]


def test_same_matchup_twins_collapse_to_the_g_id(tmp_path):
    out = _migrate(tmp_path, [
        _row("mlb_20260802_over-6-5_total_over",
             "New York Yankees @ Chicago Cubs", model_tier="tier1"),
        _row("mlb_20260802_over-6-5_g-newyan-chicub_total_over",
             "New York Yankees @ Chicago Cubs", recorded_at="",
             weather_context="wind in"),
    ])
    assert len(out) == 1
    only = out[0]
    assert only["pick_id"] == "mlb_20260802_over-6-5_g-newyan-chicub_total_over"
    # merged row keeps the richer logger's fields AND the twin's extras
    assert only["model_tier"] == "tier1"
    assert only["weather_context"] == "wind in"
    assert only["recorded_at"] == "2026-08-02T04:53:52+00:00"


def test_different_matchups_are_not_twins(tmp_path):
    out = _migrate(tmp_path, [
        _row("mlb_20260802_over-6-5_total_over",
             "Boston Red Sox @ Los Angeles Dodgers"),
        _row("mlb_20260802_over-6-5_g-newyan-chicub_total_over",
             "New York Yankees @ Chicago Cubs"),
    ])
    assert len(out) == 2, "same line label, different games — two real wagers"


def test_graded_twin_wins_regardless_of_id_form(tmp_path):
    out = _migrate(tmp_path, [
        _row("mlb_20260802_over-6-5_total_over",
             "New York Yankees @ Chicago Cubs",
             result="win", profit=0.909),
        _row("mlb_20260802_over-6-5_g-newyan-chicub_total_over",
             "New York Yankees @ Chicago Cubs"),
    ])
    assert len(out) == 1
    assert out[0]["result"] == "win"
    assert out[0]["profit"] == 0.909
    assert "_g-" in out[0]["pick_id"]

"""The canonical ledger must never be rewritten from a stale in-memory snapshot.

WHY THIS FILE EXISTS. `log_shadow_strategies` used to do a lock-free,
non-atomic read-modify-write of picks.json:

    blob = _load_picks()          # snapshot, no lock
    ...                           # minutes of network I/O per sport
    PICKS_FILE.write_text(blob)   # whole file replaced

Two silent catastrophes live in those three lines. A concurrent
`append_picks_safe` writer (grid_runner, chef) lands between the read and the
write and is simply erased — last writer wins, no error. And because
`_load_picks()` answers a corrupt/truncated file with `{"picks": []}`, a crash
mid-write is self-propagating: the next run reads nothing, "appends" today's
picks to nothing, and writes the entire betting history away.

These tests fail if any writer goes back to snapshot-and-overwrite. They are
about the WRITE CONTRACT, not about which strategies fire.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tracking.schema import append_picks_safe


def _pick(pid: str, team: str = "Team A") -> dict:
    return {
        "pick_id": pid, "date": "2026-08-01", "sport": "mlb",
        "market": "moneyline", "direction": "HOME", "team": team,
        "matchup": "Team B @ Team A", "odds": -110, "stake": 0.0,
        "card_pick": False, "result": None,
    }


def _read(path: Path) -> list[dict]:
    return json.loads(path.read_text())["picks"]


def test_shadow_logger_does_not_rewrite_the_whole_ledger(tmp_path, monkeypatch):
    """A write that lands while the logger is mid-run must survive it.

    Simulates the real race: the logger snapshots the ledger, another process
    appends, then the logger writes its own picks. The interleaved pick must
    still be there afterwards.
    """
    import src.strategies.shadow_strategies as ss

    ledger = tmp_path / "picks.json"
    ledger.write_text(json.dumps({"picks": [_pick("pre_existing")]}))
    monkeypatch.setattr(ss, "PICKS_FILE", ledger)

    # 1. The logger reads the ledger (its snapshot is now stale-in-waiting).
    snapshot_ids = {p["pick_id"] for p in ss._load_picks()["picks"]}
    assert snapshot_ids == {"pre_existing"}

    # 2. A concurrent writer appends — invisible to the snapshot above.
    append_picks_safe(ledger, [_pick("concurrent_writer", "Team C")])

    # 3. The logger writes its own new pick. The contract: append, never
    #    replace-from-snapshot.
    append_picks_safe(ledger, [_pick("shadow_new", "Team D")])

    ids = {p["pick_id"] for p in _read(ledger)}
    assert ids == {"pre_existing", "concurrent_writer", "shadow_new"}, (
        "a concurrent write was erased — the ledger was rebuilt from a stale "
        "snapshot instead of appended to under the lock")


def test_corrupt_ledger_is_never_silently_replaced_with_only_new_picks(tmp_path):
    """A truncated ledger must not become the excuse to write history away.

    This test used to tolerate exactly what its docstring decried: on a torn
    file, append fell back to {"picks": []} and produced a clean-looking
    one-pick ledger — and on 2026-08-02 that path replaced 14,609 picks with
    6 in production. The contract is now REFUSAL: a non-empty file that does
    not parse is corruption, appending to it erases history, so the append
    returns 0, the bytes stay untouched, and a .corrupt copy preserves the
    evidence recovery starts from.
    """
    ledger = tmp_path / "picks.json"
    ledger.write_text('{"picks": [{"pick_id": "old_1", "date": "2026-07-01"')  # truncated
    torn = ledger.read_bytes()

    added = append_picks_safe(ledger, [_pick("todays_pick")])

    assert added == 0, "appending to corruption must refuse, not improvise"
    assert ledger.read_bytes() == torn, "refusal must not touch the file"
    corrupt = tmp_path / "picks.json.corrupt"
    assert corrupt.exists() and corrupt.read_bytes() == torn


def test_zero_byte_ledger_is_still_a_fresh_start(tmp_path):
    """Refusal is for corruption, not for genuinely empty files."""
    ledger = tmp_path / "picks.json"
    ledger.write_text("")
    assert append_picks_safe(ledger, [_pick("first_pick")]) == 1
    assert {p["pick_id"] for p in _read(ledger)} == {"first_pick"}


def test_grader_overlay_preserves_concurrent_append(tmp_path):
    """grade.py's save is an overlay, not a snapshot.

    Its flow is load → fetch scores (minutes pass) → mutate rows → save. The
    old `_save` wrote the stale snapshot whole: every pick appended in that
    window was erased, silently. The overlay re-reads under the lock and
    replaces only the rows the grader actually has.
    """
    from src.tracking.schema import overlay_graded_picks

    ledger = tmp_path / "picks.json"
    append_picks_safe(ledger, [_pick("graded_row"), _pick("untouched_row", "Team U")])

    snapshot = _read(ledger)                                   # grader loads
    append_picks_safe(ledger, [_pick("landed_mid_grade", "Team C")])  # concurrent append
    for p in snapshot:                                         # grader settles a row
        if p["pick_id"] == "graded_row":
            p["result"], p["profit"] = "win", 0.909

    replaced, dropped = overlay_graded_picks(ledger, snapshot)

    ids = {p["pick_id"] for p in _read(ledger)}
    assert "landed_mid_grade" in ids, "the snapshot-save erased a concurrent append"
    assert replaced == 2 and dropped == 0
    graded = next(p for p in _read(ledger) if p["pick_id"] == "graded_row")
    assert graded["result"] == "win" and graded["profit"] == 0.909


def test_grader_overlay_never_resurrects_migrated_rows(tmp_path):
    """Rows a concurrent migrate collapsed stay gone — a lost grade re-runs
    on the next sweep, a resurrected duplicate never dies."""
    from src.tracking.schema import overlay_graded_picks

    ledger = tmp_path / "picks.json"
    append_picks_safe(ledger, [_pick("kept_row"), _pick("collapsed_row", "Team X")])
    snapshot = _read(ledger)

    data = json.loads(ledger.read_text())                      # concurrent migrate
    data["picks"] = [p for p in data["picks"] if p["pick_id"] != "collapsed_row"]
    ledger.write_text(json.dumps(data))

    for p in snapshot:
        p["result"], p["profit"] = "loss", -1.0
    replaced, dropped = overlay_graded_picks(ledger, snapshot)

    assert (replaced, dropped) == (1, 1)
    assert [p["pick_id"] for p in _read(ledger)] == ["kept_row"]


def test_grader_overlay_refuses_unreadable_ledger(tmp_path):
    from src.tracking.schema import overlay_graded_picks

    ledger = tmp_path / "picks.json"
    ledger.write_text("{torn")
    replaced, dropped = overlay_graded_picks(ledger, [_pick("any_row")])
    assert (replaced, dropped) == (0, 1)
    assert ledger.read_text() == "{torn", "never write a snapshot over corruption"


def test_grader_overlay_preserves_bare_list_shape(tmp_path):
    """grade.py has always persisted a bare list; the overlay must not flip
    the on-disk shape out from under readers that sniff it."""
    from src.tracking.schema import overlay_graded_picks

    ledger = tmp_path / "picks.json"
    rows = [_pick("list_row")]
    ledger.write_text(json.dumps(rows))
    rows[0]["result"] = "win"
    overlay_graded_picks(ledger, rows)
    raw = json.loads(ledger.read_text())
    assert isinstance(raw, list)
    assert raw[0]["result"] == "win"


def test_migrate_roundtrip_still_works_under_the_ledger_lock(tmp_path):
    """migrate now takes the same lock as every other writer — this pins that
    the locked wrapper still migrates (a deadlock would hang, a bad delegate
    would error)."""
    from src.tracking.schema import migrate_picks_file

    ledger = tmp_path / "picks.json"
    append_picks_safe(ledger, [_pick("alpha"), _pick("beta", "Team B2")])
    result = migrate_picks_file(str(ledger))
    assert result["total_out"] == 2
    assert len(_read(ledger)) == 2


def test_shadow_logger_delegates_to_the_locked_writer(tmp_path, monkeypatch):
    """Structural: the shadow logger must call append_picks_safe, not write_text.

    A behavioural test cannot easily distinguish "wrote correctly by luck" from
    "wrote through the choke point", and the choke point is what applies
    normalization + the calibration gate. Assert the delegation directly.
    """
    import inspect
    import src.strategies.shadow_strategies as ss

    # Strip comments and docstring prose: this asserts what the function DOES,
    # and a comment describing the old bug must not read as the bug itself.
    code = "\n".join(line.split("#", 1)[0]
                     for line in inspect.getsource(ss.log_shadow_strategies).splitlines())
    assert "append_picks_safe" in code, (
        "shadow logger no longer delegates to the locked, atomic writer")
    assert "PICKS_FILE.write_text" not in code, (
        "shadow logger writes the ledger directly again — that is the "
        "lock-free read-modify-write this test exists to prevent")

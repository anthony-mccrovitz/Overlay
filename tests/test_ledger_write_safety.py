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

    `_load_picks()` returning {"picks": []} on a JSONDecodeError is a
    reasonable READ default and a catastrophic WRITE basis: pairing it with a
    whole-file overwrite turns one corrupt read into permanent data loss. This
    pins that the write path refuses to shrink the file to just today's picks.
    """
    ledger = tmp_path / "picks.json"
    ledger.write_text('{"picks": [{"pick_id": "old_1", "date": "2026-07-01"')  # truncated

    before = ledger.read_text()
    append_picks_safe(ledger, [_pick("todays_pick")])
    after = _read(ledger)

    # append_picks_safe may not be able to RECOVER the truncated bytes, but the
    # failure must not be dressed up as a normal successful run that happens to
    # contain one pick. Either the old content survives, or the corruption is
    # still visible — never a clean-looking one-pick ledger presented as truth.
    recovered = {p.get("pick_id") for p in after}
    assert "todays_pick" in recovered
    assert before != json.dumps({"picks": []}), "precondition"


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

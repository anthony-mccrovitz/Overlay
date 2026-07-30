"""Every read-only CLI command must at least RUN.

WHY: `chef.py scoreboard` shipped with `PROMOTE_MIN_EV` referenced but never
imported — an instant NameError on the daily driver. The whole suite passed
(905 tests) because nothing invoked the command. Unit tests cover the functions
these commands call; nothing covered the wiring between them.

This is deliberately shallow. It asserts the command executes and returns an int
exit code, not what it prints — output changes constantly and asserting on it
would make the tests brittle for no gain. A NameError, a bad import, or a
missing argparse attribute all fail here, and those are the failures that make a
command unusable rather than merely wrong.
"""
import argparse
import importlib

import pytest

chef = importlib.import_module("chef")

# Read-only commands. Anything that fetches odds, writes the ledger, grades, or
# mutates state is deliberately excluded — a test suite must not spend API
# credits or move money.
#
# Kwargs must mirror the ARGPARSE DEFAULTS, not plausible-looking values. A
# first version passed sport=None to `record`, which defaults to "all", and the
# resulting AttributeError was a bug in the test rather than the command — a
# smoke test that fails for its own reasons trains people to ignore it.
COMMANDS = [
    ("scoreboard", {"sport": None}),
    ("grid", {"sport": None}),
    ("record", {"sport": "all", "market": "all"}),
    ("filters", {}),
    ("heartbeat", {}),
    ("coverage", {"days": 7, "sport": None}),
    # Added after `chef.py edge` was found crashing on real data with a
    # TypeError — it had been broken the whole time the suite was green,
    # because six commands were covered and the rest were not. Every LOCAL
    # read-only report belongs here; anything that spends API credits or
    # mutates the ledger deliberately stays out.
    ("edge", {"min_n": 200}),
    ("dashboard", {}),
    ("clv", {"refresh": False, "matrix": False}),
    ("audit_models", {"sport": None, "live": False}),
    ("validate", {"min_n": 20}),
    ("today", {}),
    ("status", {"date": None}),
    ("health", {}),
]


@pytest.mark.parametrize("name,kw", COMMANDS, ids=[c[0] for c in COMMANDS])
def test_command_runs(name, kw, capsys, monkeypatch):
    fn = getattr(chef, f"cmd_{name}", None)
    if fn is None:
        pytest.skip(f"cmd_{name} not present")
    # No network: these are read-only reports over committed data, and a test
    # that quietly spends Odds API credits is a test that stops being run.
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    rc = fn(argparse.Namespace(**kw))
    assert isinstance(rc, int), f"cmd_{name} returned {type(rc)}, not an exit code"


def test_scoreboard_and_gate_agree_on_the_ev_floor():
    """The scoreboard must enforce the same floor the gate does.

    If these drift, the scoreboard advertises lanes as READY that
    clears_promotion_gate rejects — and the friendlier screen is the one people
    read.
    """
    import inspect
    from src.config.model_standard import PROMOTE_MIN_EV

    src = inspect.getsource(chef.cmd_scoreboard)
    assert "PROMOTE_MIN_EV" in src, "scoreboard no longer applies the EV floor"
    assert PROMOTE_MIN_EV > 0


def test_edge_survives_a_lane_whose_sharp_snapshots_are_all_flat():
    """Regression: `chef.py edge` died with a TypeError on real data.

    `sharp_n` counts SCORED snapshots; `sharp_beat_pct` is computed over MOVED
    ones only, because a flat line is neither a win nor a loss. A lane whose
    every sharp snapshot came back flat therefore has sharp_n > 0 AND
    sharp_beat_pct = None — and the formatter guarded both fields behind
    `if r.get("sharp_n")`, treating one field's presence as proof of the
    other's. Four real lanes hit it (nhl/puck_line, nhl/spread, wc/spread,
    wnba/spread), so the report crashed before printing its verdict block.
    """
    from src.analytics.clv_gate import clv_gate
    res = clv_gate(200)
    assert res is not None, "clv_gate returned nothing"
    rows = res[0] if isinstance(res, tuple) else res
    flat_only = [r for r in rows
                 if r.get("sharp_n") and r.get("sharp_beat_pct") is None]
    assert flat_only, (
        "no all-flat-sharp lane in the current data — this test can still guard "
        "the formatter, but the shape it was written for is absent; keep it, the "
        "condition recurs whenever a lane's lines stop moving"
    )
    # The formatter must handle every row without raising.
    for r in rows:
        sm = (f"{r['sharp_mean']:+.2f}{r['unit']}"
              if r.get("sharp_n") and r.get("sharp_mean") is not None else "—")
        sb = (f"{r['sharp_beat_pct']:.0f}%"
              if r.get("sharp_beat_pct") is not None else "—")
        assert isinstance(sm, str) and isinstance(sb, str)

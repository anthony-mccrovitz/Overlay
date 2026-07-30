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

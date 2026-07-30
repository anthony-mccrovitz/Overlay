"""A typo should get a one-line answer, not a wall of text.

MEASURED BEFORE (2026-07-30): `chef.py mnoeypath` printed the full sixty-name
choice list TWICE — once in usage, once in the error — for a single
transposition. Roughly 1,000 characters where a suggestion belonged, and no hint
about which command was meant.

The CLI has 60 commands and 52 of them see real use, so the problem was never
bloat. It was that argparse's default failure mode buries the answer.

AFTER: 97 characters, naming the intended command.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run([sys.executable, "chef.py", *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)


def test_a_typo_suggests_the_real_command():
    r = _run("mnoeypath")
    out = r.stdout + r.stderr
    assert "moneypath" in out, "no suggestion for an obvious transposition"
    assert "unknown command" in out


def test_a_typo_does_not_dump_the_whole_command_list():
    """The regression that matters. A 60-name dump for a one-character slip is
    how a CLI teaches you not to read its errors."""
    out = _run("mnoeypath").stdout + _run("mnoeypath").stderr
    assert len(out) < 400, f"typo produced {len(out)} chars — the wall is back"
    # A few command names may appear as suggestions; the full roster must not.
    assert out.count("polytiming") == 0 and out.count("wc-breakdown") == 0


def test_unrecognisable_input_points_at_the_entry_points():
    """No near match? Then say where to start, rather than listing everything."""
    out = _run("zzzzz").stdout + _run("zzzzz").stderr
    assert "today" in out and "moneypath" in out
    assert len(out) < 400


def test_help_leads_with_where_to_start():
    out = _run("--help").stdout
    assert "START HERE" in out
    i_start, i_today = out.index("START HERE"), out.index("today")
    assert i_start < out.index("positional arguments"), "START HERE is buried"
    assert i_today > 0


def test_usage_line_is_not_a_sixty_name_wall():
    out = _run("--help").stdout
    first = out.splitlines()[0]
    assert "COMMAND" in first, f"usage line still enumerates commands: {first[:120]}"
    assert len(first) < 120


def test_real_commands_still_dispatch():
    """Ergonomics must not cost function — the suggestion path sits in front of
    argparse, so a bug there would break every command at once."""
    for cmd in ("today", "moneypath", "scoreboard"):
        r = _run(cmd)
        assert r.returncode in (0, 1), f"{cmd} exited {r.returncode}"
        assert "unknown command" not in (r.stdout + r.stderr)


def test_flags_still_parse():
    r = _run("record", "--sport", "mlb")
    assert "unknown command" not in (r.stdout + r.stderr)
    assert r.returncode == 0

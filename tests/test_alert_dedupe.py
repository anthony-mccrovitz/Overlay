"""Alert frequency must match the workflow's cadence.

Two opposite failure modes, and the fix for one is the cause of the other:

  · monitor.yml runs DAILY. A persistent problem should re-ping, so a red week
    is one issue with seven comments — silence there is how twelve consecutive
    red days felt like twelve quiet days.
  · capture-closing.yml runs every 15 MINUTES (~13 surviving runs/day). Re-pinging
    each failure would post a dozen notifications a day and train the label to be
    filtered, which arrives at the same place from the other direction.

ALERT_ONCE picks the behaviour per caller. These tests pin both, because a change
that fixes the noisy case by suppressing everything would silently disarm the
daily alarm.
"""
import re
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/alert_issue.sh")
CAPTURE_WF = Path(".github/workflows/capture-closing.yml")
MONITOR_WF = Path(".github/workflows/monitor.yml")


def test_script_is_valid_shell():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_alert_once_short_circuits_on_an_existing_issue():
    """The suppression must happen BEFORE the comment call, not after."""
    src = SCRIPT.read_text()
    once = src.index('ALERT_ONCE')
    comment = src.index("gh issue comment")
    assert once < comment, "ALERT_ONCE is checked after the comment is posted"


def test_default_still_reping():
    """Absent ALERT_ONCE, an existing open issue gets a comment — the daily
    monitor depends on this to keep a persistent alarm visible."""
    src = SCRIPT.read_text()
    assert 'ALERT_ONCE:-0' in src, "ALERT_ONCE must default to OFF"
    assert "gh issue comment" in src


def test_capture_closing_alerts_and_uses_once():
    """The high-frequency workflow must alert, and must not spam."""
    wf = CAPTURE_WF.read_text()
    assert "alert_issue.sh" in wf, "capture-closing has no alert step"
    assert "issues: write" in wf, "capture-closing cannot open an issue"
    assert re.search(r'ALERT_ONCE:\s*"1"', wf), "capture-closing would ping every 15 min"
    assert "if: failure()" in wf


def test_capture_step_uses_pipefail():
    """Output is teed for the alert to quote. Without pipefail the pipeline
    reports tee's exit code and a dead capture looks GREEN — exactly the silent
    failure this workflow was rebuilt to eliminate."""
    wf = CAPTURE_WF.read_text()
    assert "set -o pipefail" in wf
    assert "tee /tmp/capture.out" in wf


def test_monitor_does_not_use_once():
    """The daily alarm must keep re-pinging while it is red."""
    wf = MONITOR_WF.read_text()
    assert "alert_issue.sh" in wf
    assert "ALERT_ONCE" not in wf, "the daily monitor would stop re-pinging"

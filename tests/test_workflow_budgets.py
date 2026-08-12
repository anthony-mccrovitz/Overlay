"""A job must have a time budget that fits the work inside it.

The failure this locks down: night.yml carried a weekly NB prop-model retrain
behind a `date -u +%u = 7` branch. A normal night run takes ~6 minutes, but the
retrain pushed it past _pipeline.yml's 20-minute job timeout. The only two
Sundays it was ever scheduled — 2026-08-02 (20m23s) and 2026-08-09 (20m24s) —
were both CANCELLED at the cap. So:

  - the retrain never once completed, and the prop artifacts stayed frozen at
    the 2026-07-08 fit the branch had been added to refresh;
  - the deploy steps that followed it in night.yml were killed mid-run on both
    Sundays;
  - nothing alarmed, because GitHub reports a timeout as "cancelled", which
    reads like a human pressed stop.

Two invariants follow: heavy/periodic work does not hide inside a daily job,
and a job that opts into more work opts into more time.

pytest.importorskip keeps this from becoming another undeclared dependency —
pyyaml is not in requirements.txt (see tests/test_pipeline_deps.py for why that
matters), so this file must degrade rather than fail on a clean checkout.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# Calls whose cost scales with history rather than with one slate. These belong
# in a job scheduled for them, never in a daily pipeline.
TRAINING_CALLS = ("train_all_prop_models", "recalibrate_all(", "train_ufc")


def _load(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) or {}


def _crons(wf: dict) -> list[str]:
    # PyYAML parses the bare key `on:` as the boolean True.
    trig = wf.get("on", wf.get(True)) or {}
    if not isinstance(trig, dict):
        return []
    sched = trig.get("schedule") or []
    return [s.get("cron", "") for s in sched if isinstance(s, dict)]


def _is_daily(cron: str) -> bool:
    """A cron that fires every day (day-of-week field is unrestricted)."""
    parts = cron.split()
    return len(parts) == 5 and parts[4].strip() in ("*", "?")


def _command(wf: dict) -> str:
    out = []
    for job in (wf.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        with_ = job.get("with") or {}
        if isinstance(with_, dict) and with_.get("command"):
            out.append(str(with_["command"]))
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("run"):
                out.append(str(step["run"]))
    return "\n".join(out)


ALL_WORKFLOWS = sorted(WORKFLOWS.glob("*.yml"))


@pytest.mark.parametrize("path", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_workflow_parses(path):
    assert _load(path) is not None


@pytest.mark.parametrize("path", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_no_training_inside_a_daily_job(path):
    wf = _load(path)
    if not any(_is_daily(c) for c in _crons(wf)):
        return
    cmd = _command(wf)
    for call in TRAINING_CALLS:
        assert call not in cmd, (
            f"{path.name} runs {call!r} inside a DAILY job.\n\n"
            f"Training cost scales with history, not with one slate, so it "
            f"eventually exceeds the daily job's timeout — and a timeout is "
            f"reported as 'cancelled', not 'failed', so nothing alarms. That is "
            f"exactly how the NB prop retrain silently never ran: both Sundays "
            f"it was scheduled died at the 20-minute cap.\n\n"
            f"Give it its own workflow (see retrain.yml) with its own "
            f"timeout_minutes."
        )


def test_pipeline_timeout_is_configurable_and_used():
    """A caller that takes on more work must be able to buy more time."""
    text = (WORKFLOWS / "_pipeline.yml").read_text()
    assert "timeout_minutes" in text, "_pipeline.yml has no timeout input"
    assert "timeout-minutes: ${{ inputs.timeout_minutes }}" in text, (
        "the timeout input exists but the job still hard-codes its own value"
    )


def test_the_retrain_workflow_exists_and_buys_more_time():
    retrain = WORKFLOWS / "retrain.yml"
    assert retrain.exists(), "the retrain was removed from night.yml with no home"
    wf = _load(retrain)
    crons = _crons(wf)
    assert crons and not any(_is_daily(c) for c in crons), (
        f"retrain.yml should be periodic, not daily: {crons}"
    )
    budget = None
    for job in (wf.get("jobs") or {}).values():
        budget = (job.get("with") or {}).get("timeout_minutes")
    assert budget and int(budget) > 20, (
        f"retrain.yml asks for {budget} minutes — it must exceed the 20-minute "
        f"default it was previously being truncated by"
    )

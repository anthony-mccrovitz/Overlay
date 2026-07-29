"""A lane that logs picks must have its closing lines captured.

The defect this locks out: `scripts/capture_closing.py` keeps a static SPORTS
dict, while the dynamic event scanner discovers leagues at runtime and starts
logging picks for them. When the scanner found `soccer_brazil_campeonato` and
`soccer_korea_kleague1`, nothing added them to SPORTS — so both accrued CLV
snapshots for weeks that could never be scored, sitting at 0/13 with no closing
line ever fetched.

That failure is invisible in every obvious place. Picks generate, the pipeline
is green, the lane fills with rows, and `chef.py grid` shows a growing sample.
The lane simply can never clear a promotion gate, because the number that would
promote it is not being collected. It looks like patience and it is a dead end.

So: every sport that has logged a CLV snapshot recently must be capturable. The
next league the scanner discovers fails the build here instead of quietly
disqualifying itself.
"""
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "clv" / "snapshots.json"

# Prefix families are enumerated dynamically at capture time rather than listed
# in SPORTS: tennis runs many concurrent tournament keys, and golf outrights are
# discovered from the active-events board.
DYNAMIC_PREFIXES = ("tennis_", "golf_")

# How far back to look, and how many snapshots a sport needs before its absence
# counts as a real gap rather than a one-off stray row.
WINDOW_DAYS = 30
MIN_SNAPSHOTS = 5


def _covered_keys() -> set[str]:
    from scripts.capture_closing import SPORTS
    return set(SPORTS.keys()) | set(SPORTS.values())


def _recent_sports() -> Counter:
    if not SNAPSHOTS.exists():
        pytest.skip("no snapshots.json in this checkout")
    raw = json.loads(SNAPSHOTS.read_text().replace("NaN", "null"))
    rows = raw.get("snapshots", raw) if isinstance(raw, dict) else raw
    lo = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()
    seen: Counter = Counter()
    for s in rows:
        if not isinstance(s, dict) or not s.get("sport"):
            continue
        if str(s.get("date") or "")[:10] >= lo:
            seen[str(s["sport"])] += 1
    return seen


def test_every_logging_sport_is_capturable():
    """No sport may accrue snapshots that capture_closing can never fetch."""
    covered = _covered_keys()
    missing = {
        sport: n for sport, n in _recent_sports().items()
        if n >= MIN_SNAPSHOTS
        and sport not in covered
        and not sport.startswith(DYNAMIC_PREFIXES)
    }
    assert not missing, (
        "These sports logged CLV snapshots but are absent from "
        "scripts/capture_closing.py SPORTS, so their closing lines are never "
        "fetched and their CLV can never be scored:\n  "
        + "\n  ".join(f"{s} ({n} snapshots in {WINDOW_DAYS}d)"
                      for s, n in sorted(missing.items(), key=lambda kv: -kv[1]))
        + "\n\nAdd each to SPORTS (key == Odds API key for club leagues, so the "
          "archive filename matches what compute_clv looks up)."
    )


def test_the_two_leagues_that_caused_this_are_covered():
    """Regression pin for the specific lanes found at 0% capture on 2026-07-29."""
    covered = _covered_keys()
    for sport in ("soccer_brazil_campeonato", "soccer_korea_kleague1"):
        assert sport in covered, f"{sport} dropped out of capture_closing.SPORTS"


class _Resp:
    def __init__(self, headers, status=200):
        self.headers, self.status_code, self.text = headers, status, ""
        self.ok = status == 200

    def json(self):
        return []


def test_exhausted_quota_exits_red_instead_of_capturing_nothing(monkeypatch):
    """An out-of-credit key must fail the run, not quietly archive zero games.

    This is the worst-shaped failure in the pipeline. /v4/sports is free, so it
    answers 200 with a full sports list while every paid odds call 401s; the
    fetch layer converts that into an empty frame, capture reads empty as "no
    odds for this game", and the workflow ends green having captured nothing.
    Closing lines cannot be backfilled — a quiet failure here destroys that
    night's CLV permanently.
    """
    import requests
    from scripts import capture_closing as cc

    monkeypatch.setenv("ODDS_API_KEY", "some-key")
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: _Resp({"x-requests-remaining": "0"}))
    with pytest.raises(SystemExit) as exc:
        cc._preflight_quota()
    assert exc.value.code != 0, "exhausted quota did not fail the capture run"


def test_healthy_quota_does_not_block_capture(monkeypatch):
    """The converse: plenty of credit must not stop the run."""
    import requests
    from scripts import capture_closing as cc

    monkeypatch.setenv("ODDS_API_KEY", "some-key")
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: _Resp({"x-requests-remaining": "5000"}))
    cc._preflight_quota()   # must not raise

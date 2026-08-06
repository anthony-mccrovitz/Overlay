"""The outright grader must be able to SEE the picks it is responsible for.

`grade_completed.py` deliberately skips outright markets and defers to
`scripts/grade_outrights.py`. That delegation is only safe while the delegate
can actually find the rows, and for months it could not:

  · Its market filter accepted ("outrights", "winner", None, "") while the
    ledger writes "outright" (golf) and "win" (racing). It matched 0 of 115
    rows and printed "No ungraded outright picks — skipping", which is
    character-for-character what it prints on a day with genuinely nothing to
    do. 90 picks sat pending.

  · It was scheduled by nothing. The docstring said "runs daily at 9 AM"; its
    log last moved 2026-05-25.

  · Nothing alarmed. TestStalePendingWatchdog exempts market "outright"
    (UNGRADEABLE_MARKETS) and the three racing sports (KNOWN_MANUAL_ONLY), so
    the backlog was invisible to the rot alarm BY DESIGN — an exemption that
    outlived its reason. That file's own comment warns it: "every entry here is
    invisible to the rot alarm." Once the backlog is cleared, both exemptions
    should be dropped, since an automated path now exists.

Both are the same failure in different clothes: a grader that reports success
while grading nothing. This file pins the half that is checkable in-process —
the vocabulary. If the ledger starts writing a market name the filter does not
accept, this fails instead of the lane quietly rotting.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "grade_outrights", ROOT / "scripts" / "grade_outrights.py")
grade_outrights = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade_outrights)


def _ledger() -> list[dict]:
    path = ROOT / "data" / "pnl" / "picks.json"
    if not path.exists():
        pytest.skip("no ledger available")
    data = json.loads(path.read_text())
    return data.get("picks", []) if isinstance(data, dict) else data


def _outright_sports() -> set:
    return {f for fields in grade_outrights.SPORT_FIELDS.values() for f in fields}


def test_filter_accepts_every_market_name_the_ledger_actually_writes():
    """The accepted vocabulary must cover what the schema really emits."""
    picks = _ledger()
    sports = _outright_sports()
    seen = {p.get("market") for p in picks if p.get("sport") in sports}
    if not seen:
        pytest.skip("ledger has no outright-sport picks to check against")

    unseen = {
        m for m in seen
        if not grade_outrights._ungraded_outright_picks(
            [{"sport": next(iter(sports)), "result": None,
              "date": "9999-01-01", "market": m}],
            next(k for k, v in grade_outrights.SPORT_FIELDS.items()
                 if next(iter(sports)) in v),
            "0000-01-01")
    }
    assert not unseen, (
        f"the ledger writes market name(s) {sorted(unseen)} that the outright "
        f"grader's filter rejects, so those picks can never be graded and the "
        f"script will report 'No ungraded outright picks' while they pile up"
    )


def test_every_ungraded_outright_pick_is_visible_to_its_grader():
    """Nothing responsible-for may be invisible.

    Counts the ungraded outright rows in the ledger directly, then asks the
    grader how many it can see. The two must agree — a delegate that sees a
    subset is how 94 picks went unnoticed.
    """
    picks = _ledger()
    sports = _outright_sports()
    truth = [p for p in picks
             if p.get("sport") in sports and p.get("result") is None]
    if not truth:
        pytest.skip("no ungraded outright picks in the ledger")

    visible = []
    for key in grade_outrights.SPORT_FIELDS:
        visible += grade_outrights._ungraded_outright_picks(picks, key, "0000-01-01")

    assert len(visible) == len(truth), (
        f"{len(truth)} ungraded outright pick(s) in the ledger but the grader "
        f"can see {len(visible)}. The invisible ones will never be graded and "
        f"the script will still exit 0 reporting nothing to do."
    )


def test_espn_endpoints_are_named_per_sport_and_not_obviously_dead():
    """Each outright sport needs its own endpoint.

    ESPN calls these leagues 'nascar-premier' and 'irl'; 'nascar-cup' and
    'indycar' 400. The 400 was swallowed and printed as "no completed event" —
    identical to an idle day — so a dead endpoint looked like a quiet week.
    """
    for sport in grade_outrights.SPORT_FIELDS:
        url = grade_outrights.ESPN_ENDPOINTS.get(sport)
        assert url, f"{sport} has picks to grade but no ESPN endpoint"
    for dead in ("racing/nascar-cup/", "racing/indycar/"):
        assert not any(dead in u for u in grade_outrights.ESPN_ENDPOINTS.values()), (
            f"{dead} is a known-400 ESPN path — it was restored, and it fails "
            f"silently as 'no completed event'"
        )

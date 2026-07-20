"""
tests/test_sport_registry.py — Grader coverage drift guard.

Every sport value that appears in data/pnl/picks.json must be reachable by
some grading path in grade.py. When a pick writer changes the value it stamps
on pick["sport"] (e.g. "basketball_wnba" → "wnba" in June 2026), the nightly
grader silently matches nothing, prints "No pending picks", and exits 0 —
picks pile up as pending forever with no alert. This test makes that drift a
CI failure instead.

Run: python3 -m pytest tests/test_sport_registry.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import grade

PICKS_FILE = Path(__file__).parent.parent / "data" / "pnl" / "picks.json"

# Sport values graded only by hand (grade.py win/loss quick_result or
# --winner) — no automated grader covers them. Anything added here should
# eventually get a real grading path; shrink this set, don't grow it.
KNOWN_MANUAL_ONLY = {
    "auto_racing_indycar_series",
    "auto_racing_formula_one",
    "auto_racing_nascar_cup_series",
}


def _generic_map_fields() -> set[str]:
    """All pick['sport'] values matched by the _GENERIC_SPORT_MAP graders."""
    fields: set[str] = set()
    for _api_key, sport_field in grade._GENERIC_SPORT_MAP.values():
        if isinstance(sport_field, str):
            fields.add(sport_field)
        else:
            fields.update(sport_field)
    return fields


def _is_covered(sport: str) -> bool:
    """Mirror grade.py main() dispatch: can any automated path grade this sport?"""
    if sport in ("mlb", "baseball_mlb", ""):        # auto_grade + MLB props
        return True
    if sport in ("nba", "basketball_nba"):          # _grade_nba + props v2
        return True
    if sport in ("nhl", "icehockey_nhl"):           # _grade_nhl + props
        return True
    if sport in _generic_map_fields():              # WNBA / UFC generic grader
        return True
    if sport.startswith("soccer_"):                 # per-league generic grader
        return True
    if sport.startswith("tennis_"):                 # tennis-data.co.uk backlog
        return True
    # Outrights settle via `grade --sport <short> --winner` — read the map
    # rather than restating it, so registering a new major in grade.py is all
    # it takes to cover it here too.
    if sport in grade._OUTRIGHT_SPORT_MAP.values():
        return True
    return False


def _pick_sports() -> set[str]:
    raw = json.loads(PICKS_FILE.read_text())
    picks = raw.get("picks", raw) if isinstance(raw, dict) else raw
    return {str(p.get("sport") or "") for p in picks}


class TestSportRegistryDrift:
    def test_every_pick_sport_has_a_grader(self):
        uncovered = {
            s for s in _pick_sports()
            if not _is_covered(s) and s not in KNOWN_MANUAL_ONLY
        }
        assert not uncovered, (
            f"Sports in picks.json with NO automated grading path: {sorted(uncovered)}. "
            "Either the pick writer changed its sport value (fix the grader's "
            "sport_field mapping in grade.py) or a new sport launched without "
            "a grading path. Do not add to KNOWN_MANUAL_ONLY without a plan."
        )

    def test_wnba_grader_matches_short_name(self):
        # Regression: pick writers stamp sport="wnba"; the grader map matched
        # only "basketball_wnba" for weeks, silently grading nothing.
        assert "wnba" in _generic_map_fields()
        assert "basketball_wnba" in _generic_map_fields()

    def test_generic_map_fields_are_tuples_or_str(self):
        for short, (api_key, sport_field) in grade._GENERIC_SPORT_MAP.items():
            assert isinstance(api_key, str)
            assert isinstance(sport_field, (str, tuple)), (
                f"_GENERIC_SPORT_MAP[{short!r}] sport_field must be str or tuple"
            )


class TestStalePendingWatchdog:
    """Grading rot alarm. The nightly grader only looks at yesterday, so a pick
    that misses its window stays pending forever — 2,800+ had silently piled up
    by 2026-07-13. The nightly grade_backlog.py sweep now re-grades stragglers;
    this test fails CI if the backlog starts growing anyway (sweep broken,
    new sport not covered, score source down for a week…)."""

    # Headroom for transient states: postponed games awaiting makeup dates,
    # a source lagging a few days. Systemic rot blows past this in days.
    MAX_STALE = 25
    STALE_AFTER_DAYS = 5

    # Markets with no automated grading path. Futures settle at event end, so
    # they're legitimately pending. Shrink this set, don't grow it: every entry
    # here is invisible to the rot alarm.
    UNGRADEABLE_MARKETS = {"outright"}

    def test_no_stale_pending_buildup(self):
        import datetime as _dt

        raw = json.loads(PICKS_FILE.read_text())
        picks = raw.get("picks", raw) if isinstance(raw, dict) else raw
        # Compare in compact form — picks have carried both '2026-07-08' and
        # '20260708' over time, and '2026…' vs '2026-…' string compare lies.
        cutoff = (_dt.date.today() - _dt.timedelta(days=self.STALE_AFTER_DAYS)).strftime("%Y%m%d")
        stale = [
            p for p in picks
            if p.get("result") in (None, "pending")
            and p.get("odds") is not None
            and (str(p.get("date") or "9999")).replace("-", "") < cutoff
            and p.get("market") not in self.UNGRADEABLE_MARKETS
            and str(p.get("sport")) not in KNOWN_MANUAL_ONLY
        ]
        summary = {}
        for p in stale:
            key = f"{p.get('sport')}/{p.get('market')}"
            summary[key] = summary.get(key, 0) + 1
        assert len(stale) <= self.MAX_STALE, (
            f"{len(stale)} picks stuck pending >{self.STALE_AFTER_DAYS} days: {summary}. "
            "Grading is silently failing for these — run scripts/grade_backlog.py, "
            "check the sport's grader mapping in grade.py, and see why the "
            "nightly sweep isn't clearing them."
        )

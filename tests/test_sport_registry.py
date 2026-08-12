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

    # Per-sport override of STALE_AFTER_DAYS, keyed by pick["sport"] PREFIX.
    #
    # The default 5 days encodes an assumption — "every results source is
    # complete within 5 days" — that is simply false for tennis.
    # tennis-data.co.uk publishes its season workbook in weekly batches, so on
    # any given day the file trails live play by up to ~9 days (on 2026-08-12
    # it ended 2026-08-03, with the Canadian Open absent). A 5-day bar is
    # therefore unsatisfiable for tennis no matter how healthy grading is, and
    # an alarm that cannot be satisfied gets muted by whoever is on call.
    #
    # This is a GRACE PERIOD, not an exemption: tennis is still counted, just
    # given the lag its source actually has. Do not use this to quiet a sport
    # whose grader is broken — that is the thing the alarm is for. It was the
    # tennis backlog that hid a real month-long outage (openpyxl missing from
    # the light dependency set, see tests/test_pipeline_deps.py) behind the
    # message "match not in source yet".
    #
    # RETIRE WHEN: tennis grading moves to a source with daily settlement (an
    # ESPN/Odds API results path), at which point delete this entry and let
    # tennis sit at the 5-day default like everything else.
    STALE_AFTER_DAYS_BY_SPORT = {
        "tennis_": 14,
    }

    # Markets with no automated grading path. Futures settle at event end, so
    # they're legitimately pending. Shrink this set, don't grow it: every entry
    # here is invisible to the rot alarm.
    UNGRADEABLE_MARKETS = {"outright"}

    def _stale_after_days(self, sport: str) -> int:
        for prefix, days in self.STALE_AFTER_DAYS_BY_SPORT.items():
            if str(sport).startswith(prefix):
                return days
        return self.STALE_AFTER_DAYS

    def test_the_grace_period_applies_only_where_declared(self):
        """The grace must stay narrow, or the alarm quietly stops alarming."""
        assert self._stale_after_days("tennis_atp_canadian_open") == 14
        # Everything else keeps the strict default — these are the sports whose
        # graders DO settle daily, and where a backlog means something is broken.
        for sport in ("mlb", "wnba", "soccer_usa_mls", "mma_mixed_martial_arts"):
            assert self._stale_after_days(sport) == self.STALE_AFTER_DAYS, (
                f"{sport} picked up a grace period it should not have"
            )

    def test_the_grace_period_stays_bounded(self):
        """A grace long enough to cover a broken grader is not a grace.

        30 days is where scripts/grade_backlog.py gives up and voids a pick as
        provably ungradeable, so any allowance must sit well inside that.
        """
        for prefix, days in self.STALE_AFTER_DAYS_BY_SPORT.items():
            assert days < 30, (
                f"{prefix} grace of {days}d reaches grade_backlog's 30-day "
                f"terminal-void horizon — a pick would be voided before the "
                f"watchdog ever complained about it"
            )

    def test_no_stale_pending_buildup(self):
        import datetime as _dt

        raw = json.loads(PICKS_FILE.read_text())
        picks = raw.get("picks", raw) if isinstance(raw, dict) else raw
        # Compare in compact form — picks have carried both '2026-07-08' and
        # '20260708' over time, and '2026…' vs '2026-…' string compare lies.
        today = _dt.date.today()

        def _is_stale(p) -> bool:
            cutoff = (today - _dt.timedelta(
                days=self._stale_after_days(p.get("sport")))).strftime("%Y%m%d")
            return (str(p.get("date") or "9999")).replace("-", "") < cutoff

        stale = [
            p for p in picks
            if p.get("result") in (None, "pending")
            and p.get("odds") is not None
            and _is_stale(p)
            and p.get("market") not in self.UNGRADEABLE_MARKETS
            and str(p.get("sport")) not in KNOWN_MANUAL_ONLY
        ]
        summary = {}
        for p in stale:
            key = f"{p.get('sport')}/{p.get('market')}"
            summary[key] = summary.get(key, 0) + 1
        assert len(stale) <= self.MAX_STALE, (
            f"{len(stale)} picks stuck pending past their sport's grace "
            f"({self.STALE_AFTER_DAYS}d default, "
            f"{self.STALE_AFTER_DAYS_BY_SPORT}): {summary}. "
            "Grading is silently failing for these — run scripts/grade_backlog.py, "
            "check the sport's grader mapping in grade.py, and see why the "
            "nightly sweep isn't clearing them."
        )

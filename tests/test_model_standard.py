"""Enforcement of the build standard.

The registry's LIVE set is the card_pick gate — the single switch between
"research" and "this takes Anthony's money". Everything in this file exists to
make that switch impossible to flip by accident.

A standard written in a document gets bypassed on a fast night. These tests are
the version that can't be, and they are deliberately unkind: a missing artifact
fails the build, an undocumented exemption fails the build, and an exemption
that is no longer needed ALSO fails the build, so the escape hatch cannot rot
into permanent cover for a lane nobody fixed.
"""
import pytest

from src.config.model_standard import (
    EXEMPTIONS,
    NON_EXEMPTIBLE,
    CHECKS,
    audit,
    is_exempt,
)
from src.config.models import MODELS, is_live


def _live_lanes() -> list[tuple[str, str]]:
    return sorted({(s, m) for (s, m) in MODELS if is_live(s, m)})


class TestLiveLanesMeetTheStandard:
    """Every live lane passes every check, or carries a documented exemption."""

    def test_live_lanes_pass_or_are_exempt(self):
        problems = []
        for sport, market in _live_lanes():
            for check in audit(sport, market):
                if check.ok or is_exempt(sport, market, check.name):
                    continue
                problems.append(f"{sport}/{market} · {check.name}: {check.detail}")
        assert not problems, (
            "LIVE lane(s) violate the build standard with no exemption:\n  "
            + "\n  ".join(problems)
            + "\n\nEither fix the lane, demote it (chef.py demote <sport> <market>), "
              "or add a documented EXEMPTIONS entry in src/config/model_standard.py."
        )

    def test_there_is_at_least_one_live_lane(self):
        """A board with nothing live means the pipeline has silently stopped
        carding — which happened for three weeks in July and nobody noticed."""
        assert _live_lanes(), "no lane is live; card_pick can never be True"


class TestExemptionsCannotRot:
    """The escape hatch is deliberately uncomfortable to leave open."""

    def test_no_stale_exemptions(self):
        """If an exempted check now passes, the exemption must be deleted.

        Without this, the list becomes a graveyard: lanes get fixed, nobody
        removes the entry, and the standard silently stops covering them.
        """
        stale = []
        for (sport, market), ex in EXEMPTIONS.items():
            results = {c.name: c for c in audit(sport, market)}
            for name in ex.get("checks", []):
                c = results.get(name)
                if c is not None and c.ok:
                    stale.append(
                        f"{sport}/{market} · {name} now PASSES ({c.detail}) — "
                        f"delete this exemption"
                    )
        assert not stale, "stale exemption(s):\n  " + "\n  ".join(stale)

    def test_exemptions_are_fully_documented(self):
        required = ("checks", "since", "why", "retire_when")
        for (sport, market), ex in EXEMPTIONS.items():
            for field in required:
                assert ex.get(field), (
                    f"{sport}/{market} exemption is missing '{field}'. An exemption "
                    f"without a reason and a retirement condition is just a bypass."
                )
            assert ex["checks"], f"{sport}/{market} exempts no checks"

    def test_exemptions_name_real_checks(self):
        known = {name for name, _ in CHECKS}
        for (sport, market), ex in EXEMPTIONS.items():
            unknown = set(ex["checks"]) - known
            assert not unknown, (
                f"{sport}/{market} exempts unknown check(s) {sorted(unknown)} — "
                f"a typo here silently exempts nothing. Known: {sorted(known)}"
            )

    def test_non_exemptible_checks_are_never_exempted(self):
        """Some failures have no valid argument.

        A lane can go live without a fitted calibrator if its edges are proven
        real by other means. A lane whose claimed edge does not materialise, or
        that cannot be measured at all, or that has not cleared the promotion
        gate, cannot — allowing that would make the standard decorative.
        """
        for (sport, market), ex in EXEMPTIONS.items():
            forbidden = set(ex["checks"]) & NON_EXEMPTIBLE
            assert not forbidden, (
                f"{sport}/{market} tries to exempt {sorted(forbidden)}, which is "
                f"never permitted. Demote the lane instead."
            )

    def test_exemptions_only_cover_live_lanes(self):
        """Shadow lanes aren't gated by the standard, so exempting one is dead
        weight that hides a real gap if the lane is later promoted."""
        live = set(_live_lanes())
        for lane in EXEMPTIONS:
            assert lane in live, (
                f"{lane[0]}/{lane[1]} is exempted but not live — remove the entry; "
                f"it will mask gaps if the lane is promoted later."
            )


class TestStandardIsWiredCorrectly:
    """Guards on the harness itself — a check that silently errors is worse
    than no check, because it reads as coverage."""

    def test_every_check_runs_without_error(self):
        for sport, market in _live_lanes():
            for c in audit(sport, market):
                assert not c.detail.startswith("check errored"), (
                    f"{sport}/{market} · {c.name} raised: {c.detail}"
                )

    def test_audit_covers_the_full_check_list(self):
        lane = _live_lanes()[0]
        assert {c.name for c in audit(*lane)} == {name for name, _ in CHECKS}

    def test_unknown_lane_fails_everything_rather_than_passing(self):
        """A lane the artifacts know nothing about must not read as compliant —
        absence of evidence has to fail closed."""
        results = audit("nonexistent_sport", "nonexistent_market")
        assert all(not c.ok for c in results), (
            "an unknown lane passed a check; the standard fails open"
        )

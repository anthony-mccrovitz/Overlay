"""The money path must be honest about whether a lane can be bet today.

This tool exists because the repo is ~90k lines across 254 files and only ONE
of its 95 lanes can move money. Reading all of it is neither achievable nor
useful; knowing whether the chain to a real bet is intact is.

The properties that make it worth trusting:
  · a link that CANNOT be checked never counts as a pass
  · a link failing under a live, dated exemption does not veto the verdict —
    but is printed in full, never hidden
  · a link failing WITHOUT an exemption does veto it
"""
import pytest

from src.analytics.money_path import Link, audit, verdict


def _L(n, ok, exempt=""):
    return Link(n, f"link{n}", ok, "does", "proof", "if broken", exempt)


def test_all_ok_is_bettable():
    ok, why = verdict([_L(1, True), _L(2, True)])
    assert ok and "every link verified" in why


def test_a_plain_failure_vetoes():
    ok, why = verdict([_L(1, True), _L(2, False)])
    assert not ok and "broken" in why and "2" in why


def test_unverifiable_never_counts_as_a_pass():
    """'Could not check' is the failure mode this whole codebase keeps hitting:
    a monitor that couldn't reach the API and printed ALL GREEN."""
    ok, why = verdict([_L(1, True), _L(2, None)])
    assert not ok and "unverifiable" in why


def test_an_accepted_exemption_does_not_veto():
    """Otherwise the tool prints DO NOT BET every day until the exemption
    retires, and a verdict that never changes is a verdict nobody reads."""
    ok, why = verdict([_L(1, True), _L(2, False, exempt="calibrator quarantined")])
    assert ok and "exemption" in why and "2" in why


def test_an_exemption_does_not_rescue_an_unverifiable_link():
    """Exemptions cover accepted RISK, not missing information."""
    ok, _ = verdict([_L(1, None, exempt="whatever")])
    assert not ok


def test_a_plain_failure_still_vetoes_alongside_an_exempt_one():
    ok, why = verdict([_L(1, False, exempt="accepted"), _L(2, False)])
    assert not ok and "2" in why


def test_the_live_lane_audits_end_to_end():
    """Real data: every link reports, and each carries its three fields."""
    links = audit("mlb", "total")
    assert len(links) == 12, f"expected 12 links, got {len(links)}"
    for l in links:
        assert l.does and l.proof and l.if_broken, f"link {l.n} is missing a field"
        assert l.ok in (True, False, None)


def test_every_link_says_what_silent_failure_looks_like():
    """The if_broken text is the point of the tool — a link is only trustworthy
    if you know what its silence would mean."""
    for l in audit("mlb", "total"):
        assert len(l.if_broken) > 40, f"link {l.n}'s failure description is too thin"


def test_an_unknown_lane_does_not_read_as_bettable():
    ok, _ = verdict(audit("nosuchsport", "nosuchmarket"))
    assert not ok, "a lane with no data reported as bettable"

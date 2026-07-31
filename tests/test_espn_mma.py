"""The official-card spine: ESPN's bout list is truth, odds only join onto it.

THE BUG THIS PINS. The card reader reconstructed events from Odds API
timestamps — fights sharing a commence_time were assumed to be one card. On
2026-08-01 that misfiled four real UFC prelims under another promotion's
block and invented a bout order; the error survived until the user produced
screenshots of the actual card. An odds feed is a market menu, not a schedule.
"""
from __future__ import annotations

from src.data.espn_mma import EspnBout, parse_scoreboard


def _sb(bouts, name="UFC Fight Night: Test vs. Case"):
    return {"events": [{"name": name, "competitions": [
        {"competitors": [{"athlete": {"displayName": a}},
                         {"athlete": {"displayName": b}}],
         "status": {"type": {"name": st}}}
        for a, b, st in bouts]}]}


def test_parses_bouts_in_espn_order():
    card = parse_scoreboard(_sb([
        ("First Prelim A", "First Prelim B", "STATUS_SCHEDULED"),
        ("Co Main A", "Co Main B", "STATUS_SCHEDULED"),
        ("Main A", "Main B", "STATUS_SCHEDULED"),
    ]), "20260801")
    assert card is not None
    assert [b.order for b in card.bouts] == [0, 1, 2]
    assert card.bouts[-1].fighter_a == "Main A", \
        "ESPN lists chronologically — the main event is LAST"


def test_cancelled_bouts_carry_their_status():
    """A pulled fight must be visible as pulled, so the card and the shadow
    log can drop it instead of pricing a bout that will never happen."""
    card = parse_scoreboard(_sb([
        ("Stays A", "Stays B", "STATUS_SCHEDULED"),
        ("Pulled A", "Pulled B", "STATUS_CANCELED"),
    ]), "20260801")
    flags = {b.fighter_a: b.scheduled for b in card.bouts}
    assert flags["Stays A"] is True
    assert flags["Pulled A"] is False


def test_malformed_competitors_are_dropped_not_fatal():
    data = _sb([("Real A", "Real B", "STATUS_SCHEDULED")])
    data["events"][0]["competitions"].append({"competitors": [
        {"athlete": {"displayName": "Lonely Fighter"}}], "status": {}})
    data["events"][0]["competitions"].append({})
    card = parse_scoreboard(data, "20260801")
    assert len(card.bouts) == 1


def test_no_event_is_a_real_answer():
    assert parse_scoreboard({"events": []}, "20260801") is None
    assert parse_scoreboard({}, "20260801") is None

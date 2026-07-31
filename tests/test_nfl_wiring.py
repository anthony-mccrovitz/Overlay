"""NFL/CFB lane wiring — every link present BEFORE the first snapshot exists.

WHY A TEST AND NOT A CHECKLIST. Every previous sport was wired by hand in the
other order, and each gap produced the same silent failure weeks later:

  - tennis logged picks under four tournament keys the registry didn't know,
    so a lane with 33 rows read "building EV sample (0/30)"
  - two soccer leagues logged picks for weeks while closing capture never
    fetched their lines — 0/13 scored, a lane disqualifying itself while
    looking like patient progress

The chain has four links (key mapping → registry → shadow logging → closing
capture) and a lane is only born whole when all four exist together. This file
pins each link and one end-to-end pass, so unwiring any single piece fails the
build rather than surfacing in October as a mysteriously empty lane.
"""
from __future__ import annotations

from src.config.models import MODELS, _key, model_status


def test_odds_api_keys_map_to_registry_lanes():
    """The _canon_sport disease, blocked at birth: snapshots arrive under the
    raw Odds API key, and an unmapped key fragments the lane."""
    assert _key("americanfootball_nfl", "")[0] == "nfl"
    assert _key("americanfootball_ncaaf", "")[0] == "ncaaf"
    # And the short forms are stable identities, not accidents.
    assert _key("nfl", "")[0] == "nfl"
    assert _key("ncaaf", "")[0] == "ncaaf"


def test_registry_lanes_exist_and_are_shadow_only():
    """Incubating, never live-by-default: the gate demands ≥30 EV rows over
    ≥15 days before betting is even a conversation."""
    for lane in [("nfl", "total"), ("nfl", "spread"), ("nfl", "moneyline"),
                 ("ncaaf", "total"), ("ncaaf", "spread")]:
        assert lane in MODELS, f"{lane} missing from the registry"
        assert MODELS[lane]["status"] == "incubating"
        assert MODELS[lane]["tier"] == "shadow"
        assert model_status(*lane) != "live"


def test_shadow_logging_covers_football():
    from src.strategies.shadow_strategies import DEFAULT_SPORTS
    assert "americanfootball_nfl" in DEFAULT_SPORTS
    assert "americanfootball_ncaaf" in DEFAULT_SPORTS


def test_shadow_logging_covers_european_soccer():
    """Added 2026-07-31 ahead of the mid-August restarts, so matchday 1 accrues
    instead of waiting for someone to remember. Registry lanes and closing
    capture for all five already existed — logging was the missing link."""
    from src.strategies.shadow_strategies import DEFAULT_SPORTS
    for k in ("soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
              "soccer_germany_bundesliga", "soccer_france_ligue_one"):
        assert k in DEFAULT_SPORTS, k


def test_every_shadow_sport_has_closing_capture():
    """The pairing rule, enforced generally: a sport that logs shadow picks
    MUST have closing capture, or it accrues rows it can never score. This is
    the exact soccer failure of 2026-07-29, promoted from comment to test."""
    import importlib.util
    from pathlib import Path

    from src.strategies.shadow_strategies import DEFAULT_SPORTS

    spec = importlib.util.spec_from_file_location(
        "capture_closing", Path("scripts/capture_closing.py"))
    cap = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(cap)
    except Exception as e:  # import-time network/config failure
        import pytest
        pytest.skip(f"capture_closing not importable here: {e}")
    captured = set(cap.SPORTS.values())
    for sport in DEFAULT_SPORTS:
        assert sport in captured, (
            f"{sport} logs shadow picks but closing capture never fetches its "
            f"lines — the lane would accrue rows it can never score")


def test_an_nfl_snapshot_lands_in_the_nfl_lane():
    """End to end: a snapshot arriving under the raw Odds API key must join
    the (nfl, total) lane the scoreboard and gate read."""
    from src.analytics.ev_gate import ev_by_lane

    rows = [{"clv_ev_pct": 2.0, "sport": "americanfootball_nfl",
             "market": "total", "date": f"2026-09-{d:02d}",
             "opening_implied_prob": 0.50, "closing_implied_prob": 0.51}
            for d in range(1, 11)]
    lanes = ev_by_lane(rows)
    assert ("nfl", "total") in lanes, f"landed in {list(lanes)} instead"
    assert lanes[("nfl", "total")].n == 10
    assert ("americanfootball_nfl", "total") not in lanes, \
        "the raw key must not survive as its own fragmented lane"

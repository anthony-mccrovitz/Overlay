"""EV must be keyed on the REGISTRY lane, not the raw snapshot sport.

THE BUG (2026-07-30): ev_gate grouped by `r["sport"]` verbatim. Snapshots carry
the raw Odds API sport — `soccer_usa_mls`, `tennis_atp_washington_open`,
`mma_mixed_martial_arts` — while the registry, market_stats and the promotion
gate all key on the canonical lane (`usa_mls`, `tennis`, `ufc`). Twelve lanes
were mis-keyed, and the damage was invisible in the obvious place:

  · usa_mls/moneyline held 46 scored rows; the gate reported 0 and the
    scoreboard printed "building EV sample (0/30)"
  · ufc/moneyline held 16 and reported 0
  · tennis fragmented across FOUR tournament keys (17+9+5+2 = 33 rows), each
    under the n>=30 floor, so a lane with a real sample reported nothing

Once fixed, usa_mls/moneyline reads EV +13.00% on n=46 with ROI +7.9% and
t=+2.28 — a lane that clears the promotion gate and had been hidden.

WHY THE EXISTING GUARD MISSED IT: tests/test_sport_key_single_source.py fails
the build when a module RE-IMPLEMENTS models._key. ev_gate didn't re-implement
it — it simply never called it. Omission and duplication are different failures
and need different tests; this file covers omission.
"""
import pytest

from src.analytics.ev_gate import ev_by_lane, ev_values_by_lane
from src.config.models import _key


def _rows(sport, market, evs):
    return [{"sport": sport, "market": market, "clv_ev_pct": e} for e in evs]


def test_raw_sport_keys_are_canonicalised():
    """Every key EV emits must already be a registry lane key."""
    for (sport, _market) in ev_by_lane():
        assert _key(sport, "")[0] == sport, (
            f"ev_gate emitted raw sport {sport!r}; the registry keys it as "
            f"{_key(sport, '')[0]!r}. The gate and market_stats will never find it."
        )


def test_tennis_tournaments_pool_into_one_lane():
    """The fragmentation case. Four tournament keys, one lane, one sample.

    Split across tournaments each slice sits under the n>=30 floor and the lane
    reports nothing — which is exactly how tennis once held 246 CLV snapshots
    and reported zero.
    """
    rows = (_rows("tennis_atp_washington_open", "moneyline", [1.0] * 17)
            + _rows("tennis_wta_washington_open", "moneyline", [2.0] * 9)
            + _rows("tennis_atp_wimbledon", "moneyline", [3.0] * 5)
            + _rows("tennis_wta_wimbledon", "moneyline", [4.0] * 2))
    lanes = ev_by_lane(rows)
    assert ("tennis", "moneyline") in lanes, "tennis did not pool"
    assert lanes[("tennis", "moneyline")].n == 33
    assert len(lanes) == 1, f"tennis still fragmented into {len(lanes)} lanes"


@pytest.mark.parametrize("raw,canon", [
    ("soccer_usa_mls", "usa_mls"),
    ("mma_mixed_martial_arts", "ufc"),
    ("soccer_fifa_world_cup", "wc"),
    ("soccer_mexico_ligamx", "mexico_ligamx"),
])
def test_specific_lanes_that_were_hidden(raw, canon):
    lanes = ev_by_lane(_rows(raw, "moneyline", [1.0] * 40))
    assert (canon, "moneyline") in lanes, f"{raw} did not map to {canon}"


def test_values_helper_canonicalises_too():
    """pooled_ev builds on ev_values_by_lane — if only one of the two
    canonicalises, pooling silently disagrees with the gate."""
    vals = ev_values_by_lane(_rows("soccer_usa_mls", "moneyline", [1.0] * 5))
    assert ("usa_mls", "moneyline") in vals


def test_unmapped_sport_is_kept_not_dropped():
    """An unknown sport keeps its raw key rather than vanishing — losing rows
    silently would be worse than keying them oddly."""
    lanes = ev_by_lane(_rows("some_new_league", "moneyline", [1.0] * 5))
    assert lanes, "rows for an unmapped sport were dropped entirely"

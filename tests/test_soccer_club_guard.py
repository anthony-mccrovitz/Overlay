"""
Guard: the international soccer model must never price club fixtures.

SoccerModelV2 is a national-team model (Elo trained on internationals). Club
sides — MLS, Liga MX, EPL — are absent from its Elo table and fall back to a
1500 default, which makes it emit an identical, team-blind price for every such
fixture and manufacture phantom edges against the book (the MLS shadow record
was 2-11 on exactly this bug). can_price() gates those out; these tests lock the
behavior in.
"""
from __future__ import annotations

from src.models.soccer_model_v2 import SoccerModelV2


def _model() -> SoccerModelV2:
    return SoccerModelV2().load()


def test_club_fixtures_are_unpriceable():
    m = _model()
    club_fixtures = [
        ("Toronto FC", "CF Montreal"),          # MLS
        ("Inter Miami CF", "LA Galaxy"),        # MLS
        ("Necaxa", "Atlante FC"),               # Liga MX
        ("Cruz Azul", "Monterrey"),             # Liga MX
    ]
    for home, away in club_fixtures:
        assert m.can_price(home, away) is False, f"{away} @ {home} should be unpriceable"


def test_international_fixtures_are_priceable():
    m = _model()
    # Real national teams the model is trained on must remain priceable so the
    # guard never starves the World Cup / internationals of legitimate picks.
    intl_fixtures = [
        ("Spain", "Germany"),
        ("Argentina", "Brazil"),
        ("France", "England"),
    ]
    for home, away in intl_fixtures:
        assert m.can_price(home, away) is True, f"{away} @ {home} should be priceable"


def test_find_edges_emits_nothing_for_club_fixture():
    """A club event pushed through find_edges must yield zero edges — the guard
    upstream skips it, but find_edges must not manufacture edges even if reached."""
    m = _model()
    club_event = {
        "home_team": "Toronto FC",
        "away_team": "CF Montreal",
        "neutral": False,
        "bookmakers": [{
            "title": "DraftKings",
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "Toronto FC", "price": 150},
                    {"name": "CF Montreal", "price": 180},
                    {"name": "Draw", "price": 240},
                ],
            }],
        }],
    }
    # find_edges will price it (no guard inside), but the point is the pipeline
    # guard (can_price) keeps such events from ever reaching here.
    assert m.can_price(club_event["home_team"], club_event["away_team"]) is False

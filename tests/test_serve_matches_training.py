"""The model that prices your bet must be the model that was validated.

THE BUG (found 2026-08-01, on the ONLY live money lane). `find_totals_edges`
built its feature dicts without `has_pitcher_data` or `season_progress`, and
`predict_total`'s row builder defaults anything missing to 0. So every live
game was scored as "no starting-pitcher data, and it is March" — while the same
row carried real SP ERA/WHIP/K9, guaranteed non-empty by the TBD-pitcher guard
directly above it.

That is not a small numeric slip. In training, `has_pitcher_data=0` rows are
exactly the rows whose pitcher columns were league-average IMPUTED, so the tree
learned to discount them there. Serving real pitcher stats under that flag asks
the model a question it was never trained to answer. Measured on realistic
matchups the fix moves the projected total by up to 0.55 runs — and the card
band is 1.0-2.0 runs of edge, so it is enough to add or remove a real bet.

The general rule this pins: a feature the artifact was fitted on must be
SUPPLIED at serve, not silently defaulted. A model quietly running on defaults
is indistinguishable from a working one until the money is counted.
"""
from __future__ import annotations

import inspect

import pytest

from src.models.mlb_xgboost import FEATURE_COLS, _pyth


def _fake_slate():
    """Minimal objects shaped like the real serve inputs."""
    import pandas as pd
    from types import SimpleNamespace

    def team(name):
        return SimpleNamespace(name=name, era=4.10, rs_per_game=4.6,
                               ra_per_game=4.3, wins=58, losses=50, games=108)

    def pitcher(era, gs):
        return SimpleNamespace(era=era, whip=1.15, k_per_9=9.1, bb_per_9=2.6,
                               innings_pitched=120.0, games_started=gs)

    matchup = SimpleNamespace(
        game_id=1, game_time="2026-08-01T23:10:00Z",
        home_team=team("Chicago Cubs"), away_team=team("New York Yankees"),
        home_pitcher=pitcher(3.20, 21), away_pitcher=pitcher(3.75, 19),
    )
    odds = pd.DataFrame([{
        "GameID": "g1", "Total": 8.5, "OverOdds": -110, "UnderOdds": -110,
        "HomeTeam": "Chicago Cubs", "AwayTeam": "New York Yankees",
        "HomeTeamCanonical": "Chicago Cubs", "AwayTeamCanonical": "New York Yankees",
        "Bookmaker": "DraftKings",
    }])
    return [matchup], odds


def test_every_trained_feature_is_supplied_at_serve(monkeypatch):
    """Run the real serve path and inspect what the model is actually handed.

    BEHAVIOURAL, not a source grep. The first version of this test searched the
    function source for each feature name and was worthless: deleting a key from
    `home_stats` alone still left the name present in `away_stats`, so the
    mutation passed. predict_total reads home_ features from home_stats and
    away_ features from away_stats, so a one-sided omission is a real defect
    that only capturing both dicts can catch.

    The authority is the ARTIFACT's own feature list (37 columns), not the
    trainer's full FEATURE_COLS (91): the totals model is fitted on a subset,
    and a column the artifact does not carry is not one the serve path owes it.
    Same principle as the UFC artifact's feature_order.
    """
    from src.models import mlb_totals

    loaded = mlb_totals.load_totals_model()
    if loaded is None:
        pytest.skip("totals artifact not present")
    _model, artifact_features, _mean = loaded

    captured: dict = {}

    def spy(home_stats, away_stats, *a, **kw):
        captured["home"], captured["away"] = home_stats, away_stats
        return 8.4
    monkeypatch.setattr(mlb_totals, "predict_total", spy)

    matchups, odds = _fake_slate()
    mlb_totals.find_totals_edges(matchups, odds)
    assert captured, "the serve path never reached predict_total"

    missing = []
    for col in artifact_features:
        if col.endswith("_diff") or col in {"home_score", "away_score"}:
            continue
        side, key = "home", col
        if col.startswith("home_"):
            side, key = "home", col[len("home_"):]
        elif col.startswith("away_"):
            side, key = "away", col[len("away_"):]
        else:
            # Unprefixed features (season_progress, has_pitcher_data) are read
            # from home_stats first, falling back to away_stats.
            if key in captured["home"] or key in captured["away"]:
                continue
            missing.append(col)
            continue
        if key not in captured[side]:
            missing.append(col)

    assert not missing, (
        "these trained features are never set on the serve path and will "
        f"silently default to 0: {sorted(set(missing))}")


def test_has_pitcher_data_uses_the_training_definition():
    """Training: 1.0 iff BOTH starters have >=2 starts (mlb_xgboost.py:514).

    Anything else is a different question than the one the tree was fitted on.
    A one-sided read is the subtle version of this bug: home SP confirmed and
    away SP TBD must not report "we have both".
    """
    from src.models import mlb_totals

    src = inspect.getsource(mlb_totals.find_totals_edges)
    assert "games_started" in src, \
        "has_pitcher_data must be derived from starts, as in training"
    assert "h_gs >= 2 and a_gs >= 2" in src, \
        "has_pitcher_data must require BOTH starters, as in training"


def test_pyth_is_computed_not_pinned_at_half():
    """`pyth` was hardcoded to 0.5 on both sides, so `pyth_diff` — a feature the
    model was fitted on — was identically 0 for every game ever priced."""
    from src.models import mlb_totals

    src = inspect.getsource(mlb_totals.find_totals_edges)
    assert '"pyth": 0.5' not in src, "pyth is pinned at 0.5 again"
    assert "_pyth(" in src, "pyth must come from training's own _pyth"

    # And the shared helper must actually discriminate, or the above is hollow.
    assert _pyth(5.2, 3.9) > _pyth(3.9, 5.2)


def test_season_progress_never_silently_claims_preseason():
    """Absent -> 0.0 means March. In August that is a lie the model acts on."""
    from src.models import mlb_totals

    src = inspect.getsource(mlb_totals.find_totals_edges)
    assert "season_progress" in src
    # The month must come from the game or the calendar — never a constant.
    assert "(month - 3) / 7.0" in src, \
        "season_progress must be derived from the month, as in training"

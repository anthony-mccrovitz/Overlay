"""
Model-remediation sanity tests (2026-07-19 audit fixes).

Covers the two root causes and their satellites:
  1. Calibrator fit guardrails — degenerate (inverted / collapsed) calibrators
     must never ship; symmetric application kills structural side bias.
  2. append_picks_safe is the normalization choke point — no emitter can
     bypass the calibration gate or write non-canonical sport keys.
  3. WNBA team-blind guard, golf pregame guard, direction labels, taint rules.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics.calibration import (        # noqa: E402
    apply_calibration_symmetric,
    validate_calibrator,
)
from src.tracking.schema import (              # noqa: E402
    append_picks_safe,
    normalize_pick,
)


# ── Fake calibrators for guardrail tests ─────────────────────────────────────

class _FakeIsotonic:
    """Isotonic-like: predict(list) → list."""
    def __init__(self, fn):
        self.fn = fn

    def predict(self, xs):
        return [self.fn(float(x)) for x in xs]


def _fake_platt(slope: float, intercept: float = 0.0):
    """Platt-like object usable by _apply_platt: predict_proba([[log_odds]])."""
    import math

    class _P:
        def predict_proba(self, X):
            lo = X[0][0]
            z = slope * lo + intercept
            p = 1.0 / (1.0 + math.exp(-z))
            return [[1 - p, p]]

    return _P()


class TestCalibratorGuardrails:
    def test_healthy_platt_accepted(self):
        ok, reason = validate_calibrator("platt", _fake_platt(slope=1.0))
        assert ok, reason

    def test_inverted_platt_rejected(self):
        # Negative slope: higher raw prob → lower calibrated prob. This shipped
        # to prod on 2026-07-18 (mlb_total) and earlier pinned NRFI ~0.44.
        ok, reason = validate_calibrator("platt", _fake_platt(slope=-0.5))
        assert not ok
        assert "monotone" in reason or "inverted" in reason

    def test_plateau_isotonic_rejected(self):
        # The collapsed F5 shape: flat 0.39 through the whole realistic band.
        def plateau(x):
            if x < 0.68:
                return 0.39
            return 0.39 + (x - 0.68) * 2.0   # only the far tail moves
        ok, reason = validate_calibrator("isotonic", _FakeIsotonic(plateau))
        assert not ok
        assert "collapse" in reason

    def test_midband_collapse_rejected_despite_global_spread(self):
        # Global f(0.8)−f(0.2) big, but flat exactly where model probs live.
        def steppy(x):
            if x < 0.35:
                return 0.10
            if x <= 0.65:
                return 0.45          # flat mid-band
            return 0.90
        ok, reason = validate_calibrator("isotonic", _FakeIsotonic(steppy))
        assert not ok
        assert "mid-band" in reason

    def test_identity_accepted(self):
        ok, _ = validate_calibrator("isotonic", _FakeIsotonic(lambda x: x))
        assert ok


class TestSymmetricCalibration:
    def test_sides_sum_to_one(self, monkeypatch):
        # Asymmetric calibrator (the away-bias shape: f(0.5) = 0.42)
        import src.analytics.calibration as cal

        def biased(p, sport, market):
            return max(0.0, min(1.0, 0.85 * p))
        monkeypatch.setattr(cal, "apply_calibration", biased)

        for p in (0.3, 0.5, 0.62, 0.8):
            home = cal.apply_calibration_symmetric(p, "mlb", "moneyline")
            away = cal.apply_calibration_symmetric(1 - p, "mlb", "moneyline")
            assert home + away == pytest.approx(1.0)

    def test_coin_flip_stays_coin_flip(self, monkeypatch):
        import src.analytics.calibration as cal
        monkeypatch.setattr(cal, "apply_calibration",
                            lambda p, s, m: max(0.0, min(1.0, 0.85 * p)))
        assert cal.apply_calibration_symmetric(0.5, "mlb", "moneyline") == pytest.approx(0.5)

    def test_identity_when_no_calibrator(self):
        # No pkl for this made-up segment → symmetric wrapper is identity
        assert apply_calibration_symmetric(0.61, "zz_nosport", "zz_nomarket") == pytest.approx(0.61)


# ── Choke point: append_picks_safe normalizes everything ─────────────────────

def _raw_pick(**over):
    base = {
        "date": "2026-07-18",
        "sport": "baseball_mlb",           # non-canonical on purpose
        "market": "pitcher_strikeouts",
        "direction": "OVER",
        "team": "Test Pitcher OVER 5.5",
        "matchup": "A @ B",
        "odds": 124,
        "line": 5.5,
        "sportsbook": "TestBook",
        "model_prob": 0.885,
        "edge_pct": 46.8,
        "stake": 1.0,
        "card_pick": False,
        "result": None,
        "profit": None,
        "recorded_at": "2026-07-18T12:00:00+00:00",
        "resulted_at": None,
        "player": "Test Pitcher",          # emitter extra — must survive
    }
    base.update(over)
    return base


class TestChokePoint:
    def test_sport_canonicalized_and_gated(self, tmp_path, monkeypatch):
        import src.analytics.calibration_gate as gate
        monkeypatch.setattr(gate, "_load_table", lambda: {
            "mlb::pitcher_strikeouts": {"n": 328, "k": 0.0,
                                        "claimed_pp": 14.0, "realized_pp": -5.9},
        })
        path = tmp_path / "picks.json"
        pick = _raw_pick(pick_id="baseball_mlb_20260718_test-pitcher-over-5-5_pitcher_strikeouts_over")
        added = append_picks_safe(path, [pick])
        assert added == 1

        stored = json.loads(path.read_text())["picks"][0]
        assert stored["sport"] == "mlb"                       # canonicalized
        assert stored["pick_id"].startswith("mlb_")           # id prefix repaired
        assert stored["raw_edge_pct"] == pytest.approx(46.8)  # claim pinned
        assert stored["edge_pct"] == pytest.approx(0.0)       # k=0 → gated to zero
        assert stored["player"] == "Test Pitcher"             # extras preserved

    def test_twin_dedup_after_canonicalization(self, tmp_path):
        path = tmp_path / "picks.json"
        canonical = _raw_pick(sport="mlb",
                              pick_id="mlb_20260718_test-pitcher-over-5-5_pitcher_strikeouts_over")
        twin = _raw_pick(sport="baseball_mlb",
                         pick_id="baseball_mlb_20260718_test-pitcher-over-5-5_pitcher_strikeouts_over")
        assert append_picks_safe(path, [canonical]) == 1
        # The ungated twin now collides on the repaired id → deduped
        assert append_picks_safe(path, [twin]) == 0
        assert len(json.loads(path.read_text())["picks"]) == 1

    @staticmethod
    def _totals(edge, card):
        # Mirrors what the emitter hands the choke point: card_pick already
        # computed via is_card_pick, edge_pct carrying the run-edge.
        return _raw_pick(sport="mlb", market="total", direction="OVER",
                         team="OVER 8.5", line=8.5, model_prob=0.62,
                         edge_pct=edge, card_pick=card, player=None)

    def test_ungraded_card_refreshes_on_relog(self, tmp_path):
        # A registry change (retuned totals band) must propagate to an already-
        # logged pick whose line didn't move — its pick_id collides, but as long
        # as it's UNGRADED the refreshed gate decision wins.
        path = tmp_path / "picks.json"
        assert append_picks_safe(path, [self._totals(0.5, False)]) == 1   # shadow
        assert json.loads(path.read_text())["picks"][0]["card_pick"] is False
        # emitter re-logs the same pick_id, now in-band and carded
        assert append_picks_safe(path, [self._totals(1.5, True)]) == 0    # not re-added
        picks = json.loads(path.read_text())["picks"]
        assert len(picks) == 1
        assert picks[0]["card_pick"] is True                              # refreshed

    def test_graded_card_never_refreshed_on_relog(self, tmp_path):
        # A SETTLED pick is immutable — re-logging must never flip its card_pick.
        path = tmp_path / "picks.json"
        assert append_picks_safe(path, [self._totals(1.5, True)]) == 1    # in band → card
        data = json.loads(path.read_text())
        data["picks"][0].update(result="loss", profit=-1.0)              # settle it
        path.write_text(json.dumps(data))
        # emitter re-logs, now shadowing it — settled pick must not change
        assert append_picks_safe(path, [self._totals(3.5, False)]) == 0
        stored = json.loads(path.read_text())["picks"][0]
        assert stored["card_pick"] is True                                # unchanged
        assert stored["result"] == "loss"

    def test_double_normalize_idempotent(self):
        once = normalize_pick(_raw_pick())
        twice = normalize_pick(once)
        assert twice is not None
        # The gate must not compound: raw claim pinned, edge stable
        assert twice["raw_edge_pct"] == once["raw_edge_pct"]
        assert twice["edge_pct"] == once["edge_pct"]
        assert twice["pick_id"] == once["pick_id"]
        assert twice["sport"] == once["sport"]

    def test_corrupted_pick_never_written(self, tmp_path):
        path = tmp_path / "picks.json"
        assert append_picks_safe(path, [{"bet_type": "moneyline", "odds": -104}]) == 0

    def test_tainted_field_survives_normalization(self):
        p = normalize_pick(_raw_pick(tainted="degenerate_calibrator"))
        assert p["tainted"] == "degenerate_calibrator"

    def test_model_prob_raw_survives_normalization(self):
        p = normalize_pick(_raw_pick(model_prob_raw=0.7123))
        assert p["model_prob_raw"] == pytest.approx(0.7123)
        # absent → None, never invented
        assert normalize_pick(_raw_pick())["model_prob_raw"] is None


class TestCalibratorFeedbackLoop:
    """Calibrators must train on the PRE-calibration probability
    (model_prob_raw) — training on the stored post-calibration model_prob and
    then applying the fit to raw model outputs compounds shrinkage each refit."""

    def test_recalibrate_fits_on_raw_probs(self, tmp_path, monkeypatch):
        import src.analytics.calibration as cal

        picks = [
            {"sport": "mlb", "market": "moneyline", "result": "win" if i % 2 else "loss",
             "model_prob": 0.44,                    # calibrated (constant — no signal)
             "model_prob_raw": 0.50 + i * 0.01}     # raw (varies — the real input)
            for i in range(40)
        ]
        pf = tmp_path / "picks.json"
        pf.write_text(json.dumps({"picks": picks}))
        monkeypatch.setattr(cal, "PICKS_PATH", pf)
        monkeypatch.setattr(cal, "CALIBRATORS_DIR", tmp_path / "cals")

        seen_X: list = []
        real_fit = cal._fit_platt

        def spy_fit(X, y):
            seen_X.append(list(X))
            return real_fit(X, y)
        monkeypatch.setattr(cal, "_fit_platt", spy_fit)

        cal.recalibrate_all(min_picks=30, verbose=False)
        assert seen_X, "no fit ran"
        fitted_on = seen_X[0]
        assert 0.44 not in fitted_on          # never the calibrated constant
        assert 0.50 in fitted_on              # the raw values

    def test_recalibrate_falls_back_to_model_prob_for_legacy(self, tmp_path, monkeypatch):
        import src.analytics.calibration as cal
        picks = [
            {"sport": "mlb", "market": "moneyline", "result": "win" if i % 2 else "loss",
             "model_prob": 0.50 + i * 0.01}   # legacy rows: no raw field
            for i in range(40)
        ]
        pf = tmp_path / "picks.json"
        pf.write_text(json.dumps({"picks": picks}))
        monkeypatch.setattr(cal, "PICKS_PATH", pf)
        monkeypatch.setattr(cal, "CALIBRATORS_DIR", tmp_path / "cals")
        seen_X: list = []
        real_fit = cal._fit_platt
        monkeypatch.setattr(cal, "_fit_platt",
                            lambda X, y: (seen_X.append(list(X)), real_fit(X, y))[1])
        cal.recalibrate_all(min_picks=30, verbose=False)
        assert seen_X and 0.50 in seen_X[0]


# ── Direction labels ─────────────────────────────────────────────────────────

class TestDirectionLabels:
    def test_team_name_direction_becomes_win_not_home(self):
        p = normalize_pick({
            "date": "2026-07-18", "sport": "soccer_fifa_world_cup",
            "market": "moneyline", "direction": "England",
            "team": "England", "matchup": "England @ France", "odds": 290,
        })
        assert p["direction"] == "WIN"

    def test_missing_moneyline_direction_defaults_to_win(self):
        p = normalize_pick({
            "date": "2026-07-18", "sport": "mlb", "market": "moneyline",
            "team": "Chicago Cubs", "odds": 106,
        })
        assert p["direction"] == "WIN"

    def test_explicit_home_is_preserved(self):
        p = normalize_pick({
            "date": "2026-07-18", "sport": "mlb", "market": "moneyline",
            "direction": "HOME", "team": "Chicago Cubs", "odds": 106,
        })
        assert p["direction"] == "HOME"


# ── WNBA team-blind guard ────────────────────────────────────────────────────

class TestWnbaGuards:
    def _event(self, home="Minnesota Lynx", away="Portland Fire"):
        return {"home_team": home, "away_team": away, "bookmakers": [{
            "title": "TestBook",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": -300},
                {"name": away, "price": 250},
            ]}],
        }]}

    def test_unrated_slate_emits_no_picks(self, monkeypatch):
        import src.models.wnba_model as wm
        from src.data.wnba_stats import _default_teams
        monkeypatch.setattr(wm, "fetch_team_ratings", lambda: _default_teams())
        edges = wm.find_wnba_edges([self._event()], min_edge_pct=0.1)
        assert edges == []

    def test_rated_slate_emits(self, monkeypatch):
        import src.models.wnba_model as wm
        teams = [
            {"TEAM_NAME": "Minnesota Lynx", "OFF_RATING": 110.0,
             "DEF_RATING": 96.0, "NET_RATING": 14.0, "PACE": 98.0, "W_PCT": 0.9},
            {"TEAM_NAME": "Portland Fire", "OFF_RATING": 96.0,
             "DEF_RATING": 106.0, "NET_RATING": -10.0, "PACE": 98.0, "W_PCT": 0.2},
        ]
        monkeypatch.setattr(wm, "fetch_team_ratings", lambda: teams)
        edges = wm.find_wnba_edges([self._event()], min_edge_pct=0.1)
        assert edges                                  # real ratings → picks flow
        probs = {round(e["model_prob"], 4) for e in edges}
        assert not probs & {0.4121, 0.5879}           # never the blind constants

    def test_empty_api_result_does_not_clobber_cache(self, tmp_path, monkeypatch):
        import src.data.wnba_stats as ws
        monkeypatch.setattr(ws, "CACHE_DIR", tmp_path)
        good = [{"TEAM_NAME": f"T{i}", "OFF_RATING": 100 + i, "DEF_RATING": 100,
                 "NET_RATING": i, "PACE": 98.0, "W_PCT": 0.5} for i in range(15)]
        cache = tmp_path / f"wnba_team_advanced_{ws.SEASON}.json"
        cache.write_text(json.dumps(good))
        # Expire the cache so the fetch path runs
        import os
        os.utime(cache, (1, 1))

        fake_endpoint = types.SimpleNamespace(
            LeagueDashTeamStats=lambda **kw: types.SimpleNamespace(
                get_data_frames=lambda: [types.SimpleNamespace(
                    to_dict=lambda kind: [])]))
        monkeypatch.setitem(sys.modules, "nba_api", types.SimpleNamespace())
        monkeypatch.setitem(sys.modules, "nba_api.stats", types.SimpleNamespace())
        monkeypatch.setitem(sys.modules, "nba_api.stats.endpoints",
                            types.SimpleNamespace(leaguedashteamstats=fake_endpoint))

        teams = ws.fetch_team_ratings(refresh=True)
        assert len(teams) == 15                       # stale good cache, not []
        assert json.loads(cache.read_text()) == good  # cache not clobbered

    def test_default_table_includes_expansion_teams(self):
        from src.data.wnba_stats import _default_teams
        names = {t["TEAM_NAME"] for t in _default_teams()}
        assert {"Portland Fire", "Golden State Valkyries", "Toronto Tempo"} <= names


# ── Golf pregame guard ───────────────────────────────────────────────────────

class TestGolfGuard:
    def _fake_api(self, keys):
        return types.SimpleNamespace(
            get=lambda *a, **k: types.SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: [{"key": x, "active": True} for x in keys]))

    def test_started_tournament_skipped(self, monkeypatch):
        import run_pga
        monkeypatch.setenv("ODDS_API_KEY", "test")
        monkeypatch.setattr(run_pga, "_req",
                            self._fake_api(["golf_the_open_championship_winner"]))
        # Schedule start 2026-07-16 < today → in progress → None
        monkeypatch.setattr(run_pga, "_NEXT_MAJOR_SCHEDULE", [
            (date(2026, 7, 16), "The Open Championship", "golf_the_open_championship_winner"),
        ])
        assert run_pga.detect_active_golf_sport() is None

    def test_upcoming_tournament_modeled(self, monkeypatch):
        import run_pga
        monkeypatch.setenv("ODDS_API_KEY", "test")
        monkeypatch.setattr(run_pga, "_req", self._fake_api(
            ["golf_the_open_championship_winner", "golf_masters_tournament_winner"]))
        monkeypatch.setattr(run_pga, "_NEXT_MAJOR_SCHEDULE", [
            (date(2026, 7, 16), "The Open Championship", "golf_the_open_championship_winner"),
            (date(2099, 4, 8), "The Masters", "golf_masters_tournament_winner"),
        ])
        assert run_pga.detect_active_golf_sport() == "golf_masters_tournament_winner"

    def test_unknown_start_date_skipped(self, monkeypatch):
        import run_pga
        monkeypatch.setenv("ODDS_API_KEY", "test")
        monkeypatch.setattr(run_pga, "_req", self._fake_api(["golf_us_open_winner"]))
        monkeypatch.setattr(run_pga, "_NEXT_MAJOR_SCHEDULE", [])
        assert run_pga.detect_active_golf_sport() is None


# ── Market retirement (k=0 flood control) ────────────────────────────────────

class TestMarketRetirement:
    def test_trusted_k0_is_retired(self, monkeypatch):
        import src.analytics.calibration_gate as gate
        monkeypatch.setattr(gate, "_load_table", lambda: {
            "mlb::batter_rbis":  {"n": 350, "k": 0.0},
            "mlb::batter_hits":  {"n": 500, "k": 0.124},
            "mlb::batter_walks": {"n": 40,  "k": 0.0},   # small n → not trusted
        })
        assert gate.is_retired_market("mlb", "batter_rbis") is True
        assert gate.is_retired_market("mlb", "batter_hits") is False
        assert gate.is_retired_market("mlb", "batter_walks") is False
        assert gate.is_retired_market("mlb", "batter_home_runs") is False


# ── Taint rules ──────────────────────────────────────────────────────────────

class TestTaintRules:
    def _mk(self, **over):
        base = {"pick_id": "x", "date": "2026-07-10", "sport": "mlb",
                "market": "moneyline", "direction": "AWAY", "strategy": None,
                "model_prob": 0.6}
        base.update(over)
        return base

    def test_rules(self):
        from scripts.taint_bad_picks import build_rule_context, classify_pick
        picks = [
            self._mk(),                                             # away streak
            self._mk(date="2026-05-01"),                            # before streak
            self._mk(market="nrfi", direction="YRFI"),              # yrfi streak
            self._mk(market="f5_total", direction="UNDER", model_prob=0.6094),
            self._mk(sport="wnba", model_prob=0.4121, date="2026-07-10"),
            self._mk(sport="golf_us_open_winner", market="outright",
                     direction="WIN", date="2026-06-20"),
            self._mk(date="2026-08-01"),                            # post-fix
        ]
        # Make 0.6094 an F5 rail (needs >= 8 repeats)
        picks += [self._mk(market="f5_total", model_prob=0.6094,
                           date=f"2026-07-{d:02d}") for d in range(1, 9)]
        rails, blind_days = build_rule_context(picks)

        assert classify_pick(picks[0], rails, blind_days) == "asymmetric_calibrator"
        assert classify_pick(picks[1], rails, blind_days) is None
        assert classify_pick(picks[2], rails, blind_days) == "degenerate_calibrator"
        assert classify_pick(picks[3], rails, blind_days) == "degenerate_calibrator"
        assert classify_pick(picks[4], rails, blind_days) == "team_blind_ratings"
        assert classify_pick(picks[5], rails, blind_days) == "in_progress_pricing"
        assert classify_pick(picks[6], rails, blind_days) is None   # post-fix immune

    def test_strategy_picks_never_tainted(self):
        from scripts.taint_bad_picks import build_rule_context, classify_pick
        p = self._mk(strategy="consensus_ev")
        rails, days = build_rule_context([p])
        assert classify_pick(p, rails, days) is None

    def test_gate_table_excludes_tainted(self, tmp_path):
        from src.analytics.calibration_gate import compute_table
        picks = {"picks": [
            {"sport": "mlb", "market": "moneyline", "result": "win",
             "model_prob": 0.60, "odds": 100, "edge_pct": 10.0,
             "tainted": "asymmetric_calibrator"},
            {"sport": "mlb", "market": "moneyline", "result": "loss",
             "model_prob": 0.60, "odds": 100, "edge_pct": 10.0},
        ]}
        pf = tmp_path / "picks.json"
        pf.write_text(json.dumps(picks))
        table = compute_table(pf, tmp_path / "table.json")
        row = table.get("mlb::moneyline")
        assert row is not None and row["n"] == 1     # only the untainted pick

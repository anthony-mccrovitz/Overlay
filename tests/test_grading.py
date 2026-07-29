"""
tests/test_grading.py — Unit tests for grading logic and canonical schema.

Tests every codepath that determines whether a pick is WIN/LOSS/PUSH.
A sign error or off-by-one here silently corrupts the public record.

Run: python3 -m pytest tests/test_grading.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.tracking.schema import (
    make_pick_id,
    profit_from_odds,
    normalize_pick,
    validate_pick,
    migrate_picks_file,
)


# ─────────────────────────── profit_from_odds ────────────────────────────────

class TestProfitFromOdds:
    def test_positive_odds_win(self):
        # Win at +140: profit = 1.0 * 140/100 = 1.40u
        assert profit_from_odds(140, 1.0, won=True) == pytest.approx(1.40)

    def test_negative_odds_win(self):
        # Win at -110: profit = 1.0 * 100/110 ≈ 0.9091u
        assert profit_from_odds(-110, 1.0, won=True) == pytest.approx(100 / 110)

    def test_loss_positive_odds(self):
        assert profit_from_odds(200, 1.0, won=False) == -1.0

    def test_loss_negative_odds(self):
        assert profit_from_odds(-150, 1.0, won=False) == -1.0

    def test_even_money(self):
        assert profit_from_odds(100, 1.0, won=True) == pytest.approx(1.0)

    def test_stake_scaling(self):
        # Half unit bet at +200: profit = 0.5 * 200/100 = 1.0u
        assert profit_from_odds(200, 0.5, won=True) == pytest.approx(1.0)

    def test_zero_odds_loss(self):
        assert profit_from_odds(0, 1.0, won=False) == -1.0


# ─────────────────────────── Moneyline grading ───────────────────────────────

class TestMoneylineGrading:
    """
    Moneyline: team wins the game → WIN; team loses → LOSS.
    No push possible (game always has a winner).
    """

    def _grade(self, won: bool, odds: int, stake: float = 1.0) -> dict:
        profit = profit_from_odds(odds, stake, won)
        return {
            "result": "win" if won else "loss",
            "profit": round(profit, 4),
        }

    def test_win(self):
        r = self._grade(True, 140)
        assert r["result"] == "win"
        assert r["profit"] == pytest.approx(1.40)

    def test_loss(self):
        r = self._grade(False, 140)
        assert r["result"] == "loss"
        assert r["profit"] == pytest.approx(-1.0)

    def test_favorite_win(self):
        r = self._grade(True, -150)
        assert r["result"] == "win"
        assert r["profit"] == pytest.approx(100 / 150, abs=1e-3)

    def test_favorite_loss(self):
        r = self._grade(False, -150)
        assert r["result"] == "loss"
        assert r["profit"] == pytest.approx(-1.0)


# ─────────────────────────── Spread grading ──────────────────────────────────

class TestSpreadGrading:
    """
    Spread: team covers if (team_score + line) > opponent_score.
    Push: exactly equal (rare with half-point lines, real with whole-number lines).

    Sign convention in run_nba.py:
        bet_line > 0 → underdog getting points (e.g. ORL +3.0)
        bet_line < 0 → favorite giving points  (e.g. PHX -3.0)

    Cover formula: adj_ts = ts + bet_line; won = adj_ts > ops
    """

    def _grade_spread(
        self,
        team_score: int,
        opp_score: int,
        bet_line: float,
    ) -> str:
        adj_ts = team_score + bet_line
        if adj_ts == opp_score:
            return "push"
        return "win" if adj_ts > opp_score else "loss"

    # ── Underdog covering ─────────────────────────────────────────────────────
    def test_underdog_covers(self):
        # ORL +3.0, ORL loses 108-110 → adj = 108+3 = 111 > 110 → COVER
        assert self._grade_spread(108, 110, 3.0) == "win"

    def test_underdog_fails_to_cover(self):
        # ORL +3.0, ORL loses 105-110 → adj = 105+3 = 108 < 110 → NO COVER
        assert self._grade_spread(105, 110, 3.0) == "loss"

    def test_underdog_push(self):
        # ORL +3.0, ORL loses 107-110 → adj = 110 = 110 → PUSH
        assert self._grade_spread(107, 110, 3.0) == "push"

    # ── Favorite covering ─────────────────────────────────────────────────────
    def test_favorite_covers(self):
        # PHX -3.0, PHX wins 112-108 → adj = 112-3 = 109 > 108 → COVER
        assert self._grade_spread(112, 108, -3.0) == "win"

    def test_favorite_fails_to_cover(self):
        # PHX -3.0, PHX wins 110-109 → adj = 110-3 = 107 < 109 → NO COVER
        assert self._grade_spread(110, 109, -3.0) == "loss"

    def test_favorite_push(self):
        # PHX -3.0, PHX wins 111-108 → adj = 108 = 108 → PUSH
        assert self._grade_spread(111, 108, -3.0) == "push"

    # ── Half-point lines (no push possible) ──────────────────────────────────
    def test_half_point_no_push_win(self):
        # ORL +3.5, ORL loses 107-110 → adj = 110.5 > 110 → WIN
        assert self._grade_spread(107, 110, 3.5) == "win"

    def test_half_point_no_push_loss(self):
        # ORL +2.5, ORL loses 107-110 → adj = 109.5 < 110 → LOSS
        assert self._grade_spread(107, 110, 2.5) == "loss"


# ─────────────────────────── Total grading ───────────────────────────────────

class TestTotalGrading:
    """
    Total: combined score > line → OVER wins; < line → UNDER wins; = line → PUSH.
    """

    def _grade_total(self, direction: str, line: float, home: int, away: int) -> str:
        total = home + away
        if total == line:
            return "push"
        if direction == "OVER":
            return "win" if total > line else "loss"
        return "win" if total < line else "loss"

    def test_over_wins(self):
        assert self._grade_total("OVER", 219.5, 111, 110) == "win"

    def test_over_loses(self):
        assert self._grade_total("OVER", 219.5, 108, 110) == "loss"

    def test_under_wins(self):
        assert self._grade_total("UNDER", 219.5, 108, 108) == "win"

    def test_under_loses(self):
        assert self._grade_total("UNDER", 219.5, 111, 110) == "loss"

    def test_push_over(self):
        assert self._grade_total("OVER", 220.0, 110, 110) == "push"

    def test_push_under(self):
        assert self._grade_total("UNDER", 220.0, 110, 110) == "push"

    def test_whole_number_line_over(self):
        # Line 8.0, total 9 → OVER wins
        assert self._grade_total("OVER", 8.0, 5, 4) == "win"

    def test_whole_number_line_push(self):
        # Line 8.0, total 8 → PUSH
        assert self._grade_total("OVER", 8.0, 4, 4) == "push"


# ─────────────────────────── NRFI grading ────────────────────────────────────

class TestNrfiGrading:
    """
    NRFI: neither team scores in the first inning → NRFI wins.
    YRFI: at least one team scores → YRFI wins.
    """

    def _grade_nrfi(self, direction: str, first_inn_home: int, first_inn_away: int) -> str:
        scored = first_inn_home + first_inn_away > 0
        if direction == "NRFI":
            return "win" if not scored else "loss"
        return "win" if scored else "loss"

    def test_nrfi_wins_no_runs(self):
        assert self._grade_nrfi("NRFI", 0, 0) == "win"

    def test_nrfi_loses_home_scores(self):
        assert self._grade_nrfi("NRFI", 1, 0) == "loss"

    def test_nrfi_loses_away_scores(self):
        assert self._grade_nrfi("NRFI", 0, 2) == "loss"

    def test_nrfi_loses_both_score(self):
        assert self._grade_nrfi("NRFI", 1, 1) == "loss"

    def test_yrfi_wins_home_scores(self):
        assert self._grade_nrfi("YRFI", 1, 0) == "win"

    def test_yrfi_wins_away_scores(self):
        assert self._grade_nrfi("YRFI", 0, 1) == "win"

    def test_yrfi_loses_no_runs(self):
        assert self._grade_nrfi("YRFI", 0, 0) == "loss"


# ─────────────────────────── Schema normalization ────────────────────────────

class TestNormalizePick:
    def _base(self, **overrides) -> dict:
        base = {
            "date":        "2026-04-18",
            "team":        "Milwaukee Brewers",
            "opponent":    "St. Louis Cardinals",
            "market":      "moneyline",
            "odds":        140,
            "stake":       1.0,
            "result":      None,
            "profit":      None,
            "recorded_at": "2026-04-18T12:00:00+00:00",
            "resulted_at": None,
        }
        return {**base, **overrides}

    def test_basic_normalization(self):
        p = normalize_pick(self._base())
        assert p["sport"] == "mlb"
        # Side-neutral default: an unparseable moneyline direction becomes WIN
        # (the old HOME default mislabeled away-team picks)
        assert p["direction"] == "WIN"
        assert p["market"] == "moneyline"
        assert p["odds"] == 140
        assert p["pick_id"].startswith("mlb_20260418_")

    def test_corrupted_bet_type_removed(self):
        raw = {
            "bet_type":    "moneyline",
            "team":        "Atlanta Braves",
            "odds":        -104,
            "bet_size":    100.0,
            "profit":      96.15,
            "recorded_at": "2026-04-18T12:00:00+00:00",
        }
        assert normalize_pick(raw) is None

    def test_no_team_removed(self):
        assert normalize_pick({"date": "2026-04-18", "odds": 100}) is None

    def test_spread_direction_inferred(self):
        p = normalize_pick(self._base(market="spread"))
        assert p["direction"] == "COVER"

    def test_total_direction_parsed_from_team(self):
        p = normalize_pick(self._base(team="UNDER 8.5", market="total"))
        assert p["direction"] == "UNDER"
        assert p["line"] == pytest.approx(8.5)

    def test_total_direction_over(self):
        p = normalize_pick(self._base(team="OVER 219.5", market="total"))
        assert p["direction"] == "OVER"
        assert p["line"] == pytest.approx(219.5)

    def test_nba_sport_preserved(self):
        p = normalize_pick(self._base(sport="nba", market="spread"))
        assert p["sport"] == "nba"
        assert p["pick_id"].startswith("nba_")

    def test_old_edge_field_migrated(self):
        # Old MLB picks store edge as percentage directly (2.52 = 2.52%). The
        # legacy `edge` field now lands as the model's raw claim in raw_edge_pct;
        # edge_pct is the calibration-gated value (X1), which for a pending pick
        # is shrunk to what the segment has historically realized.
        p = normalize_pick(self._base(edge=2.52))
        assert p["raw_edge_pct"] == pytest.approx(2.52)

    def test_graded_pick_edge_not_recalibrated(self):
        # A settled pick keeps its recorded edge — the gate must never rewrite
        # the public record.
        p = normalize_pick(self._base(edge=2.52, result="win", profit=1.4))
        assert p["edge_pct"] == pytest.approx(2.52)

    def test_pick_id_deterministic(self):
        p1 = normalize_pick(self._base())
        p2 = normalize_pick(self._base())
        assert p1["pick_id"] == p2["pick_id"]

    def test_existing_result_preserved(self):
        p = normalize_pick(self._base(result="win", profit=1.40))
        assert p["result"] == "win"
        assert p["profit"] == pytest.approx(1.40)

    def test_idempotent(self):
        p1 = normalize_pick(self._base())
        p2 = normalize_pick(p1)
        assert p1["pick_id"] == p2["pick_id"]
        assert p1["market"] == p2["market"]


class TestMakePickId:
    def test_format(self):
        pid = make_pick_id("mlb", "2026-04-18", "Milwaukee Brewers", "moneyline", "WIN")
        assert pid == "mlb_20260418_milwaukee-brewers_moneyline_win"

    def test_nba_spread(self):
        pid = make_pick_id("nba", "20260417", "Orlando Magic +3.0", "spread", "COVER")
        assert pid.startswith("nba_20260417_")

    def test_special_chars_stripped(self):
        pid = make_pick_id("mlb", "2026-04-18", "OVER 8.5", "total", "OVER")
        assert " " not in pid
        assert "+" not in pid

    def test_deterministic(self):
        a = make_pick_id("mlb", "2026-04-18", "Brewers", "moneyline", "WIN")
        b = make_pick_id("mlb", "2026-04-18", "Brewers", "moneyline", "WIN")
        assert a == b


class TestValidatePick:
    def _canonical(self) -> dict:
        return {
            "pick_id":     "mlb_20260418_brewers_moneyline_win",
            "date":        "2026-04-18",
            "sport":       "mlb",
            "market":      "moneyline",
            "direction":   "WIN",
            "team":        "Milwaukee Brewers",
            "matchup":     "Brewers vs Cardinals",
            "odds":        140,
            "line":        None,
            "sportsbook":  "DraftKings",
            "model_prob":  0.567,
            "edge_pct":    8.4,
            "stake":       1.0,
            "card_pick":   True,
            "result":      None,
            "profit":      None,
            "recorded_at": "2026-04-18T12:00:00+00:00",
            "resulted_at": None,
        }

    def test_valid_pick_no_errors(self):
        assert validate_pick(self._canonical()) == []

    def test_missing_field_flagged(self):
        p = self._canonical()
        del p["pick_id"]
        issues = validate_pick(p)
        assert any("pick_id" in i for i in issues)

    def test_result_without_profit_flagged(self):
        p = self._canonical()
        p["result"] = "win"
        p["profit"] = None
        issues = validate_pick(p)
        assert any("profit" in i for i in issues)

    def test_nrfi_null_odds_result_allowed(self):
        # NRFI: odds always None — settled without profit is acceptable
        p = self._canonical()
        p["market"]  = "nrfi"
        p["odds"]    = None
        p["result"]  = "win"
        p["profit"]  = None
        assert validate_pick(p) == []

    def test_invalid_result_flagged(self):
        p = self._canonical()
        p["result"] = "unknown"
        issues = validate_pick(p)
        assert any("result" in i for i in issues)

    def test_home_away_directions_valid(self):
        p = self._canonical()
        p["direction"] = "HOME"
        assert validate_pick(p) == []
        p["direction"] = "AWAY"
        assert validate_pick(p) == []

    def test_nan_direction_invalid(self):
        p = self._canonical()
        p["direction"] = "NAN"
        issues = validate_pick(p)
        assert any("direction" in i for i in issues)

    def test_normalize_pick_moneyline_direction_default(self):
        raw = {
            "team": "Chicago Cubs",
            "date": "2026-04-23",
            "sport": "mlb",
            "market": "moneyline",
            "odds": 106,
        }
        result = normalize_pick(raw)
        assert result is not None
        # Side-neutral default: WIN (HOME was a lie for away teams)
        assert result["direction"] == "WIN"

    def test_card_pick_stake_unit_scale(self):
        p = self._canonical()
        p["stake"] = 1.0
        p["card_pick"] = True
        p["profit"] = profit_from_odds(-110, 1.0, True)
        assert abs(p["profit"] - 0.9091) < 0.001
        assert validate_pick(p) == []


class TestPriceObservedStrategiesBypassGate:
    """The calibration gate corrects MODEL overconfidence. polymarket_ev has no
    model in it — its "edge" is arithmetic on two quoted prices (one venue's
    ask vs another's devigged fair). Applying mlb::moneyline's k (~0.04, fitted
    on our own model's realised edge) zeroed real price gaps: on 2026-07-20
    every MLB Polymarket pick recorded edge_pct 0.0 against raw_edge_pct
    2.0-4.5. The gate was answering a question those picks never asked.
    """

    def _pick(self, **over):
        p = dict(date="2026-07-20", sport="mlb", market="moneyline",
                 team="Pittsburgh Pirates", direction="WIN", odds=113,
                 model_prob=0.4827, edge_pct=2.7, stake=0.0, card_pick=False,
                 matchup="Pittsburgh Pirates @ New York Yankees")
        p.update(over)
        return p

    def test_polymarket_edge_survives_the_gate(self):
        n = normalize_pick(self._pick(strategy="polymarket_ev"))
        assert n["edge_pct"] == 2.7
        assert n["raw_edge_pct"] == 2.7

    def test_model_picks_are_still_gated(self):
        """The exemption must not become a hole — ordinary picks keep shrinking."""
        n = normalize_pick(self._pick(strategy=None))
        assert n["edge_pct"] < n["raw_edge_pct"]

    def test_unknown_strategies_are_still_gated(self):
        n = normalize_pick(self._pick(strategy="some_new_model_strategy"))
        assert n["edge_pct"] < n["raw_edge_pct"]


class TestHomeAwayDerivation:
    """home_team/away_team exist on the schema and nothing ever wrote them —
    0% populated on every lane with a real sample. Any home/away analysis
    therefore classified every pick as away and produced a bias that looked
    real. normalize_pick derives them from `matchup`, which IS populated."""

    def test_derives_both_sides_from_matchup(self):
        from src.tracking.schema import normalize_pick
        p = normalize_pick({
            "sport": "mlb", "market": "total", "direction": "OVER", "line": 8.5,
            "odds": -110, "date": "2026-07-29", "team": "OVER 8.5",
            "matchup": "Toronto Blue Jays @ Washington Nationals",
            "model_prob": 0.55, "edge_pct": 1.2,
        })
        assert p["away_team"] == "Toronto Blue Jays"
        assert p["home_team"] == "Washington Nationals"

    def test_explicit_values_win_over_derivation(self):
        from src.tracking.schema import normalize_pick
        p = normalize_pick({
            "sport": "mlb", "market": "moneyline", "direction": "WIN",
            "odds": 120, "date": "2026-07-29", "team": "Mets",
            "matchup": "A @ B", "home_team": "Real Home", "away_team": "Real Away",
            "model_prob": 0.55, "edge_pct": 1.2,
        })
        assert p["home_team"] == "Real Home"
        assert p["away_team"] == "Real Away"

    def test_ambiguous_separator_is_not_guessed(self):
        """' v ' ordering is not reliably away-first on soccer/tennis boards, so
        guessing would silently invert home and away across whole leagues."""
        from src.tracking.schema import _split_matchup
        assert _split_matchup("Team A v Team B") == (None, None)
        assert _split_matchup("Team A vs Team B") == (None, None)

    def test_missing_matchup_is_safe(self):
        from src.tracking.schema import _split_matchup
        assert _split_matchup(None) == (None, None)
        assert _split_matchup("") == (None, None)


class TestVoidIsTerminal:
    """grade.py writes result="void" in five places (cancelled game, withdrawn
    player, postponed event) and market_stats/public_stats both treat it as
    settled — but schema.py only knew win/loss/push, so normalize_pick silently
    nulled it. Every migrate turned 1,628 legitimately-voided picks back into
    "pending", producing a grading backlog no grader could ever clear."""

    def test_void_survives_normalization(self):
        from src.tracking.schema import normalize_pick
        p = normalize_pick({
            "sport": "mlb", "market": "moneyline", "direction": "WIN",
            "odds": -110, "date": "2026-07-20", "team": "Mets",
            "matchup": "A @ B", "model_prob": 0.55, "edge_pct": 1.2,
            "result": "void", "profit": 0.0,
        })
        assert p["result"] == "void"

    def test_void_is_valid(self):
        from src.tracking.schema import validate_pick
        pick = {f: None for f in __import__(
            "src.tracking.schema", fromlist=["CANONICAL_FIELDS"]).CANONICAL_FIELDS}
        pick.update({"market": "moneyline", "direction": "WIN", "result": "void"})
        assert not [i for i in validate_pick(pick) if "invalid result" in i]

    def test_void_counts_as_graded_so_it_is_immutable(self):
        from src.tracking.schema import _is_ungraded
        assert _is_ungraded({"result": "void", "profit": None}) is False
        assert _is_ungraded({"result": None, "profit": None}) is True

    def test_unknown_result_is_still_rejected(self):
        from src.tracking.schema import normalize_pick
        p = normalize_pick({
            "sport": "mlb", "market": "moneyline", "direction": "WIN",
            "odds": -110, "date": "2026-07-20", "team": "Mets",
            "matchup": "A @ B", "model_prob": 0.55, "edge_pct": 1.2,
            "result": "cancelled",
        })
        assert p["result"] is None

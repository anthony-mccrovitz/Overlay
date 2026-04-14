"""
MLB ensemble model: combines Pythagorean baseline with XGBoost ML model.

The ensemble averages predictions from both models, weighted by their
validated backtest performance. This consistently outperforms either model
alone because the models capture different signals:
  - Pythagorean: first-principles run production / prevention (stable)
  - XGBoost: learned non-linear patterns from features (flexible)
"""
from __future__ import annotations

from dataclasses import dataclass

from src.data.mlb_stats import (
    Matchup, TeamStats, PitcherStats, fetch_pitcher_game_logs,
    fetch_pitcher_vs_team, fetch_lineup_quality,
)
from src.data.mlb_player_stats import fetch_team_bvp_summary
from src.data.park_factors import get_park_factor, OUTDOOR_PARKS
from src.data.weather import get_game_weather, weather_run_adjustment
from src.data.recent_form import get_recent_form, inject_form
from src.models.mlb_model import (
    GamePrediction,
    predict_game as pyth_predict,
    _build_drivers,
)
from src.models.mlb_xgboost import load_mlb_model, predict_with_xgboost

# SP covers roughly this fraction of innings in a typical start
_SP_INNINGS_FRAC = 0.61
_MIN_SP_IP = 10  # min innings pitched for SP data to be reliable

# Load once per process — 12hr cache so no extra API calls
_RECENT_FORM: dict | None = None


def _get_form() -> dict:
    global _RECENT_FORM
    if _RECENT_FORM is None:
        _RECENT_FORM = get_recent_form()
    return _RECENT_FORM


PYTH_WEIGHT = 0.45
XGBOOST_WEIGHT = 0.55

# Early-season: Pythagorean is unreliable until ~30 games played.
# Scale its weight linearly: 0% at 0 games, full weight at 30+ games.
PYTH_MIN_GAMES = 30

# Coors Field inflates run-scoring stats for Colorado Rockies home games.
# When the Rockies play away, their overall RS/RA overestimates road quality.
# Apply this multiplier to their away Pythagorean probability.
COORS_ROAD_PYTH_DISCOUNT = 0.88


@dataclass
class EnsemblePrediction:
    game_id: int
    home_team: str
    away_team: str
    ensemble_prob: float
    pyth_prob: float
    xgb_prob: float
    home_pitcher: str
    away_pitcher: str
    edge_drivers: list[str]
    model_agreement: bool


def predict_game_ensemble(matchup: Matchup) -> EnsemblePrediction:
    """
    Predict P(home wins) using weighted ensemble of Pythagorean + XGBoost.
    Falls back to Pythagorean-only if XGBoost model isn't trained yet.
    """
    pyth_pred = pyth_predict(matchup)
    pyth_prob = pyth_pred.home_win_prob

    loaded = load_mlb_model()
    if loaded is None:
        return EnsemblePrediction(
            game_id=matchup.game_id,
            home_team=matchup.home_team.name,
            away_team=matchup.away_team.name,
            ensemble_prob=pyth_prob,
            pyth_prob=pyth_prob,
            xgb_prob=pyth_prob,
            home_pitcher=matchup.home_pitcher.name if matchup.home_pitcher else "TBD",
            away_pitcher=matchup.away_pitcher.name if matchup.away_pitcher else "TBD",
            edge_drivers=pyth_pred.edge_drivers,
            model_agreement=True,
        )

    xgb_model, calibrator, lgbm_model, cb_model, meta_model, meta_names = loaded
    home = matchup.home_team
    away = matchup.away_team

    form = _get_form()

    home_stats = inject_form({
        "rs_g": home.rs_per_game if home.rs_per_game > 0 else 4.5,
        "ra_g": home.ra_per_game if home.ra_per_game > 0 else 4.5,
        "win_pct": home.wins / max(home.wins + home.losses, 1) if (home.wins + home.losses) > 0 else 0.5,
        "games": home.games or 30,
    }, home.name, form)

    away_stats = inject_form({
        "rs_g": away.rs_per_game if away.rs_per_game > 0 else 4.5,
        "ra_g": away.ra_per_game if away.ra_per_game > 0 else 4.5,
        "win_pct": away.wins / max(away.wins + away.losses, 1) if (away.wins + away.losses) > 0 else 0.5,
        "games": away.games or 30,
    }, away.name, form)

    # ── Inject pitcher stats so XGBoost uses real SP data instead of defaults ──
    # home SP
    hp = matchup.home_pitcher
    if hp and hp.innings_pitched >= _MIN_SP_IP and hp.era > 0:
        raw_bullpen_h = (home.era - hp.era * _SP_INNINGS_FRAC) / max(1 - _SP_INNINGS_FRAC, 0.01)
        home_stats.update({
            "sp_era": hp.era,
            "sp_k9": hp.k_per_9,
            "sp_bb9": hp.bb_per_9,
            "sp_whip": hp.whip,
            "sp_ip": hp.innings_pitched,
            "sp_era_vs_team": hp.era / max(home.era, 0.01),
            "sp_fip_proxy": hp.era - (hp.k_per_9 - hp.bb_per_9) * 0.5,
            "bullpen_era": max(2.0, min(8.0, raw_bullpen_h)),
            "has_pitcher_data": 1.0,
        })

    # away SP
    ap = matchup.away_pitcher
    if ap and ap.innings_pitched >= _MIN_SP_IP and ap.era > 0:
        raw_bullpen_a = (away.era - ap.era * _SP_INNINGS_FRAC) / max(1 - _SP_INNINGS_FRAC, 0.01)
        away_stats.update({
            "sp_era": ap.era,
            "sp_k9": ap.k_per_9,
            "sp_bb9": ap.bb_per_9,
            "sp_whip": ap.whip,
            "sp_ip": ap.innings_pitched,
            "sp_era_vs_team": ap.era / max(away.era, 0.01),
            "sp_fip_proxy": ap.era - (ap.k_per_9 - ap.bb_per_9) * 0.5,
            "bullpen_era": max(2.0, min(8.0, raw_bullpen_a)),
            "has_pitcher_data": 1.0,
        })

    # ELO: default to 1500 (neutral) — real ELO would need a separate tracker
    home_stats.setdefault("elo", 1500.0)
    away_stats.setdefault("elo", 1500.0)

    # Rest days: default 1 — we don't have schedule data here
    home_stats.setdefault("rest_days", 1.0)
    away_stats.setdefault("rest_days", 1.0)

    # v4: Park factor + weather (outdoor parks only)
    home_name = matchup.home_team.name
    park_factor = get_park_factor(home_name)
    is_outdoor = home_name in OUTDOOR_PARKS
    home_stats["park_factor"] = park_factor
    home_stats["park_is_outdoor"] = 1.0 if is_outdoor else 0.0

    wind_mph = 0.0
    wind_favor = 0.0
    try:
        wx = get_game_weather(home_name)
        if wx:
            wind_mph = wx.get("wind_mph", 0.0)
            wind_dir = wx.get("wind_dir_deg", 0.0)
            adj = weather_run_adjustment(wind_mph, wind_dir, is_outdoor)
            wind_favor = adj  # positive = blowing out (more runs)
    except Exception:
        pass
    home_stats["wind_mph"] = wind_mph
    home_stats["wind_favor_sp"] = wind_favor

    # v4: Pitcher last-10-starts rolling form
    season = matchup.home_team.games  # use games as proxy; actual season from date
    import datetime as _dt
    _season = _dt.date.today().year
    if hp and hp.player_id:
        try:
            logs_h = fetch_pitcher_game_logs(hp.player_id, _season)
            home_stats["sp_era_l10"] = logs_h["era_l10"]
            home_stats["sp_k9_l10"] = logs_h["k9_l10"]
            home_stats["sp_era_trend"] = logs_h["era_trend"]
        except Exception:
            home_stats.setdefault("sp_era_l10", home_stats.get("sp_era", 4.50))
            home_stats.setdefault("sp_k9_l10", home_stats.get("sp_k9", 7.5))
            home_stats.setdefault("sp_era_trend", 0.0)
    else:
        home_stats.setdefault("sp_era_l10", home_stats.get("sp_era", 4.50))
        home_stats.setdefault("sp_k9_l10", home_stats.get("sp_k9", 7.5))
        home_stats.setdefault("sp_era_trend", 0.0)

    if ap and ap.player_id:
        try:
            logs_a = fetch_pitcher_game_logs(ap.player_id, _season)
            away_stats["sp_era_l10"] = logs_a["era_l10"]
            away_stats["sp_k9_l10"] = logs_a["k9_l10"]
            away_stats["sp_era_trend"] = logs_a["era_trend"]
        except Exception:
            away_stats.setdefault("sp_era_l10", away_stats.get("sp_era", 4.50))
            away_stats.setdefault("sp_k9_l10", away_stats.get("sp_k9", 7.5))
            away_stats.setdefault("sp_era_trend", 0.0)
    else:
        away_stats.setdefault("sp_era_l10", away_stats.get("sp_era", 4.50))
        away_stats.setdefault("sp_k9_l10", away_stats.get("sp_k9", 7.5))
        away_stats.setdefault("sp_era_trend", 0.0)

    # v5: Pitcher vs this specific opponent team (historical splits)
    home_team_id = matchup.home_team.team_id
    away_team_id = matchup.away_team.team_id
    if hp and hp.player_id and away_team_id:
        try:
            vs_h = fetch_pitcher_vs_team(hp.player_id, away_team_id, _season)
            home_stats["sp_era_vs_opp"] = vs_h["era_vs_opp"]
            home_stats["sp_k9_vs_opp"] = vs_h["k9_vs_opp"]
        except Exception:
            home_stats.setdefault("sp_era_vs_opp", home_stats.get("sp_era", 4.50))
            home_stats.setdefault("sp_k9_vs_opp", home_stats.get("sp_k9", 7.5))
    else:
        home_stats.setdefault("sp_era_vs_opp", home_stats.get("sp_era", 4.50))
        home_stats.setdefault("sp_k9_vs_opp", home_stats.get("sp_k9", 7.5))

    if ap and ap.player_id and home_team_id:
        try:
            vs_a = fetch_pitcher_vs_team(ap.player_id, home_team_id, _season)
            away_stats["sp_era_vs_opp"] = vs_a["era_vs_opp"]
            away_stats["sp_k9_vs_opp"] = vs_a["k9_vs_opp"]
        except Exception:
            away_stats.setdefault("sp_era_vs_opp", away_stats.get("sp_era", 4.50))
            away_stats.setdefault("sp_k9_vs_opp", away_stats.get("sp_k9", 7.5))
    else:
        away_stats.setdefault("sp_era_vs_opp", away_stats.get("sp_era", 4.50))
        away_stats.setdefault("sp_k9_vs_opp", away_stats.get("sp_k9", 7.5))

    # v5: Day-of lineup quality (OPS of confirmed batting order)
    game_id = matchup.game_id
    if game_id and home_team_id:
        try:
            lq_home = fetch_lineup_quality(home_team_id, game_id)
            home_stats["lineup_ops"] = lq_home["lineup_ops"]
        except Exception:
            home_stats.setdefault("lineup_ops", 0.720)
    else:
        home_stats.setdefault("lineup_ops", 0.720)

    if game_id and away_team_id:
        try:
            lq_away = fetch_lineup_quality(away_team_id, game_id)
            away_stats["lineup_ops"] = lq_away["lineup_ops"]
        except Exception:
            away_stats.setdefault("lineup_ops", 0.720)
    else:
        away_stats.setdefault("lineup_ops", 0.720)

    # v6: Batter vs pitcher historical matchup data (lineup OPS vs this specific SP)
    # away batters vs home SP
    if hp and hp.player_id and away_team_id:
        try:
            bvp_away = fetch_team_bvp_summary(away_team_id, hp.player_id, _season)
            away_stats["lineup_ops_vs_sp"] = bvp_away["lineup_ops_vs_sp"]
            away_stats["hr_threat_vs_sp"] = bvp_away["hr_threat"]
            away_stats["k_rate_vs_sp"] = bvp_away["k_rate_vs_sp"]
        except Exception:
            away_stats.setdefault("lineup_ops_vs_sp", away_stats.get("lineup_ops", 0.720))
            away_stats.setdefault("hr_threat_vs_sp", 0.033)
            away_stats.setdefault("k_rate_vs_sp", 0.22)
    else:
        away_stats.setdefault("lineup_ops_vs_sp", away_stats.get("lineup_ops", 0.720))
        away_stats.setdefault("hr_threat_vs_sp", 0.033)
        away_stats.setdefault("k_rate_vs_sp", 0.22)

    # home batters vs away SP
    if ap and ap.player_id and home_team_id:
        try:
            bvp_home = fetch_team_bvp_summary(home_team_id, ap.player_id, _season)
            home_stats["lineup_ops_vs_sp"] = bvp_home["lineup_ops_vs_sp"]
            home_stats["hr_threat_vs_sp"] = bvp_home["hr_threat"]
            home_stats["k_rate_vs_sp"] = bvp_home["k_rate_vs_sp"]
        except Exception:
            home_stats.setdefault("lineup_ops_vs_sp", home_stats.get("lineup_ops", 0.720))
            home_stats.setdefault("hr_threat_vs_sp", 0.033)
            home_stats.setdefault("k_rate_vs_sp", 0.22)
    else:
        home_stats.setdefault("lineup_ops_vs_sp", home_stats.get("lineup_ops", 0.720))
        home_stats.setdefault("hr_threat_vs_sp", 0.033)
        home_stats.setdefault("k_rate_vs_sp", 0.22)

    xgb_prob = predict_with_xgboost(
        xgb_model, home_stats, away_stats, calibrator,
        lgbm_model=lgbm_model, cb_model=cb_model, meta_model=meta_model,
    )

    # Scale Pythagorean weight by games played — unreliable before 30 games
    games_played = min(home.games or 0, away.games or 0)
    pyth_scale = min(1.0, games_played / PYTH_MIN_GAMES)
    effective_pyth_weight = PYTH_WEIGHT * pyth_scale
    effective_xgb_weight = 1.0 - effective_pyth_weight

    # Coors road correction: away Rockies' Pythagorean is inflated by home games
    adjusted_pyth_prob = pyth_prob
    if matchup.away_team.name == "Colorado Rockies":
        # Pythagorean is from home team's perspective (P(home wins)).
        # A higher Rockies quality → lower home_win_prob. Discounting Rockies
        # quality means the home team wins MORE often → increase pyth_prob.
        away_pyth_raw = 1.0 - pyth_prob  # convert to P(away wins)
        away_pyth_adj = away_pyth_raw * COORS_ROAD_PYTH_DISCOUNT
        adjusted_pyth_prob = 1.0 - away_pyth_adj

    ensemble_prob = effective_pyth_weight * adjusted_pyth_prob + effective_xgb_weight * xgb_prob
    ensemble_prob = max(0.05, min(0.95, ensemble_prob))

    pyth_pick_home = pyth_prob >= 0.5
    xgb_pick_home = xgb_prob >= 0.5
    agreement = pyth_pick_home == xgb_pick_home

    drivers = pyth_pred.edge_drivers[:]
    if not agreement:
        drivers.insert(0, "Models disagree — lower confidence.")
    elif abs(pyth_prob - xgb_prob) < 0.03:
        drivers.insert(0, "Both models strongly agree on this pick.")

    # Surface pitcher injection in drivers when SP data was actually used
    _home_sp_used = bool(hp and hp.innings_pitched >= _MIN_SP_IP and hp.era > 0)
    _away_sp_used = bool(ap and ap.innings_pitched >= _MIN_SP_IP and ap.era > 0)
    if _home_sp_used and _away_sp_used:
        drivers.append(f"SP edge: {matchup.home_pitcher.name} {matchup.home_pitcher.era:.2f} ERA vs {matchup.away_pitcher.name} {matchup.away_pitcher.era:.2f} ERA.")
    elif _home_sp_used:
        drivers.append(f"SP data used for {matchup.home_pitcher.name} ({matchup.home_pitcher.era:.2f} ERA).")
    elif _away_sp_used:
        drivers.append(f"SP data used for {matchup.away_pitcher.name} ({matchup.away_pitcher.era:.2f} ERA).")

    return EnsemblePrediction(
        game_id=matchup.game_id,
        home_team=matchup.home_team.name,
        away_team=matchup.away_team.name,
        ensemble_prob=ensemble_prob,
        pyth_prob=pyth_prob,
        xgb_prob=xgb_prob,
        home_pitcher=matchup.home_pitcher.name if matchup.home_pitcher else "TBD",
        away_pitcher=matchup.away_pitcher.name if matchup.away_pitcher else "TBD",
        edge_drivers=drivers[:4],
        model_agreement=agreement,
    )


def predict_all_ensemble(matchups: list[Matchup]) -> list[EnsemblePrediction]:
    return [predict_game_ensemble(m) for m in matchups]


def ensemble_to_dict(preds: list[EnsemblePrediction]) -> dict[tuple[str, str], float]:
    return {(p.home_team, p.away_team): p.ensemble_prob for p in preds}

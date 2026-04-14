"""
Performance analytics — edge calibration, ROI breakdown, variance analysis.

Reads data/pnl/picks.json (the bet log) and output/picks/ (model output) to
produce a quant-style performance dashboard.

Usage:
  from src.analytics.performance import full_dashboard
  full_dashboard("data/pnl/picks.json")

  # Or via CLI:
  python3 track.py analytics
"""
from __future__ import annotations

import json
import math
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_picks(picks_log_path: str | Path) -> list[dict]:
    path = Path(picks_log_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("picks", [])
    except (json.JSONDecodeError, ValueError):
        return []


def _settled(picks: list[dict]) -> list[dict]:
    return [p for p in picks if p.get("result") in ("win", "loss")]


def _roi(picks: list[dict]) -> float:
    staked = sum(float(p.get("stake") or 1.0) for p in picks)
    profit = sum(float(p.get("profit") or 0.0) for p in picks)
    return (profit / staked * 100) if staked > 0 else 0.0


def _profit(picks: list[dict]) -> float:
    return sum(float(p.get("profit") or 0.0) for p in picks)


def _resolve_edge(pick: dict) -> float | None:
    """
    Return edge for a pick. Auto-logged picks store edge directly.
    Falls back to reading the generated picks.json for that date.
    """
    edge = pick.get("edge")
    if edge is not None:
        return float(edge)

    # Try to find it in output/picks/<sport>/<date>/picks.json
    date_str  = (pick.get("date") or "")[:10].replace("-", "")
    team      = (pick.get("team") or "").lower().strip()
    picks_dir = Path("output/picks")
    if not date_str or not team:
        return None

    for sport_dir in picks_dir.iterdir():
        day_dir = sport_dir / date_str
        picks_file = day_dir / "picks.json"
        if not picks_file.exists():
            continue
        try:
            generated = json.loads(picks_file.read_text())
        except (json.JSONDecodeError, ValueError):
            continue
        for g in generated:
            if str(g.get("Team", "")).lower().strip() == team:
                return float(g.get("Edge") or 0.0)
    return None


def _resolve_model_prob(pick: dict) -> float | None:
    """Return model_prob for a pick, same resolution logic as _resolve_edge."""
    mp = pick.get("model_prob")
    if mp is not None:
        return float(mp)

    date_str  = (pick.get("date") or "")[:10].replace("-", "")
    team      = (pick.get("team") or "").lower().strip()
    picks_dir = Path("output/picks")
    if not date_str or not team:
        return None

    for sport_dir in picks_dir.iterdir():
        day_dir = sport_dir / date_str
        picks_file = day_dir / "picks.json"
        if not picks_file.exists():
            continue
        try:
            generated = json.loads(picks_file.read_text())
        except (json.JSONDecodeError, ValueError):
            continue
        for g in generated:
            if str(g.get("Team", "")).lower().strip() == team:
                return float(g.get("ModelProb") or 0.5)
    return None


def _edge_tier(edge: float) -> str:
    if edge >= 0.08:
        return "HIGH"
    if edge >= 0.04:
        return "MED"
    return "LOW"


def _odds_bucket(odds: float) -> str:
    if odds > 150:
        return "BIG DOG (>+150)"
    if odds >= 100:
        return "DOG (+100 to +150)"
    if odds >= -149:
        return "SLIGHT FAV (-100 to -149)"
    return "BIG FAV (<-150)"


# ── Analysis functions ────────────────────────────────────────────────────────

def roi_by_edge_tier(picks_log_path: str | Path = "data/pnl/picks.json") -> dict:
    """
    Group settled bets by edge tier (HIGH >=8%, MED 4-8%, LOW <4%).
    Returns {tier: {count, wins, roi, profit}} for each tier.
    Bets with no resolvable edge go into "UNKNOWN".
    """
    picks   = _load_picks(picks_log_path)
    settled = _settled(picks)

    buckets: dict[str, list[dict]] = {
        "HIGH": [], "MED": [], "LOW": [], "UNKNOWN": [],
    }

    for p in settled:
        edge = _resolve_edge(p)
        if edge is None:
            buckets["UNKNOWN"].append(p)
        else:
            buckets[_edge_tier(edge)].append(p)

    result = {}
    for tier, bets in buckets.items():
        if not bets:
            continue
        wins = sum(1 for b in bets if b["result"] == "win")
        result[tier] = {
            "count":  len(bets),
            "wins":   wins,
            "losses": len(bets) - wins,
            "profit": round(_profit(bets), 4),
            "roi":    round(_roi(bets), 2),
        }
    return result


def roi_by_odds_range(picks_log_path: str | Path = "data/pnl/picks.json") -> dict:
    """
    Group settled bets by odds bucket:
      BIG DOG >+150, DOG +100 to +150,
      SLIGHT FAV -100 to -149, BIG FAV <-150

    Returns {bucket: {count, wins, roi, profit}}.
    """
    picks   = _load_picks(picks_log_path)
    settled = _settled(picks)

    buckets: dict[str, list[dict]] = {}
    for p in settled:
        odds   = float(p.get("odds") or 0)
        bucket = _odds_bucket(odds)
        buckets.setdefault(bucket, []).append(p)

    result = {}
    order  = ["BIG DOG (>+150)", "DOG (+100 to +150)", "SLIGHT FAV (-100 to -149)", "BIG FAV (<-150)"]
    for bucket in order:
        bets = buckets.get(bucket, [])
        if not bets:
            continue
        wins = sum(1 for b in bets if b["result"] == "win")
        result[bucket] = {
            "count":  len(bets),
            "wins":   wins,
            "losses": len(bets) - wins,
            "profit": round(_profit(bets), 4),
            "roi":    round(_roi(bets), 2),
        }
    return result


def calibration_check(picks_log_path: str | Path = "data/pnl/picks.json") -> list[dict]:
    """
    Calibration: group settled ML bets by model probability bin (5% width).
    Returns list of {bin_label, expected_win_rate, actual_win_rate, count}.

    A well-calibrated model has expected ≈ actual across all bins.
    Requires model_prob to be present (auto-logged picks or output/picks/).
    """
    picks   = _load_picks(picks_log_path)
    settled = _settled(picks)

    bins: dict[str, list[dict]] = {}

    for p in settled:
        mp = _resolve_model_prob(p)
        if mp is None:
            continue
        # Bin width = 0.05
        bin_lo  = math.floor(mp / 0.05) * 0.05
        bin_hi  = bin_lo + 0.05
        bin_key = f"{bin_lo:.2f}-{bin_hi:.2f}"
        bins.setdefault(bin_key, []).append((mp, p["result"] == "win"))

    rows = []
    for bin_key in sorted(bins.keys()):
        entries = bins[bin_key]
        probs   = [e[0] for e in entries]
        wins    = [e[1] for e in entries]
        rows.append({
            "bin":                bin_key,
            "count":              len(entries),
            "expected_win_rate":  round(sum(probs) / len(probs), 4),
            "actual_win_rate":    round(sum(wins) / len(wins), 4),
            "delta":              round(sum(wins) / len(wins) - sum(probs) / len(probs), 4),
        })
    return rows


def variance_report(picks_log_path: str | Path = "data/pnl/picks.json") -> dict:
    """
    Variance analysis using a simple binomial model.

    Given W-L record and average odds, computes:
      - Expected ROI (from average implied probability)
      - Actual ROI
      - Std deviation of results
      - Whether actual ROI is within 1 or 2 standard deviations of expected

    Positive actual ROI significantly above expected = skill, not luck.
    """
    picks   = _load_picks(picks_log_path)
    settled = _settled(picks)

    if not settled:
        return {
            "count":        0,
            "wins":         0,
            "losses":       0,
            "actual_roi":   0.0,
            "expected_roi": 0.0,
            "std_dev":      0.0,
            "z_score":      0.0,
            "within_1_std": True,
            "within_2_std": True,
            "verdict":      "No settled bets yet.",
        }

    n      = len(settled)
    wins   = sum(1 for p in settled if p["result"] == "win")
    staked = sum(float(p.get("stake") or 1.0) for p in settled)
    profit = sum(float(p.get("profit") or 0.0) for p in settled)

    actual_roi = (profit / staked * 100) if staked > 0 else 0.0

    # Expected win rate from average American odds (vig-inclusive)
    def american_to_implied(odds: float) -> float:
        if odds > 0:
            return 100.0 / (odds + 100.0)
        return abs(odds) / (abs(odds) + 100.0)

    implied_probs = [american_to_implied(float(p.get("odds") or -110)) for p in settled]
    avg_imp_prob  = sum(implied_probs) / len(implied_probs)

    # Expected profit per unit under market efficiency (edge = 0)
    # E[profit per bet] = p_win * payout - p_loss * stake
    # avg payout per unit win
    def payout_per_unit(odds: float) -> float:
        if odds > 0:
            return odds / 100.0
        return 100.0 / abs(odds)

    payouts      = [payout_per_unit(float(p.get("odds") or -110)) for p in settled]
    avg_payout   = sum(payouts) / len(payouts)
    exp_profit   = avg_imp_prob * avg_payout - (1 - avg_imp_prob) * 1.0
    expected_roi = exp_profit * 100  # as % of 1 unit stake

    # Binomial std dev: std(profit per bet) ≈ avg_payout * sqrt(p*(1-p))
    p   = avg_imp_prob
    std_per_bet = math.sqrt(p * (1 - p)) * avg_payout
    std_total   = std_per_bet * math.sqrt(n)
    # std dev of ROI
    std_roi = (std_total / n) * 100

    # z-score: how many std devs is actual profit from expected?
    exp_total_profit = exp_profit * n
    z_score = (profit - exp_total_profit) / (std_total + 1e-9)

    verdict = "WITHIN NORMAL VARIANCE"
    if abs(z_score) > 2.0:
        direction = "ABOVE" if z_score > 0 else "BELOW"
        verdict   = f"STATISTICALLY SIGNIFICANT — {direction} expectations at 2σ"
    elif abs(z_score) > 1.0:
        direction = "above" if z_score > 0 else "below"
        verdict   = f"Slightly {direction} expectations (1-2σ)"

    return {
        "count":        n,
        "wins":         wins,
        "losses":       n - wins,
        "actual_roi":   round(actual_roi, 2),
        "expected_roi": round(expected_roi, 2),
        "std_dev_roi":  round(std_roi, 2),
        "z_score":      round(z_score, 3),
        "within_1_std": abs(z_score) <= 1.0,
        "within_2_std": abs(z_score) <= 2.0,
        "verdict":      verdict,
    }


# ── Dashboard ─────────────────────────────────────────────────────────────────

def full_dashboard(picks_log_path: str | Path = "data/pnl/picks.json") -> None:
    """Print all performance analytics in sequence."""
    W = 60

    picks   = _load_picks(picks_log_path)
    settled = _settled(picks)
    pending = [p for p in picks if p.get("result") is None]

    print(f"\n{'═' * W}")
    print(f"  PERFORMANCE DASHBOARD")
    print(f"{'═' * W}")
    print(f"  Log: {picks_log_path}")
    print(f"  Total bets : {len(picks)}  ({len(settled)} settled, {len(pending)} pending)")

    if not settled:
        print(f"\n  No settled bets yet. Record results with:")
        print(f"    python3 track.py win  \"Team Name\"")
        print(f"    python3 track.py loss \"Team Name\"")
        print(f"{'═' * W}\n")
        return

    # ── Overall ───────────────────────────────────────────────────────────────
    wins   = sum(1 for p in settled if p["result"] == "win")
    losses = len(settled) - wins
    profit = sum(float(p.get("profit") or 0.0) for p in settled)
    roi    = _roi(settled)
    profit_sign = "+" if profit >= 0 else ""
    roi_sign    = "+" if roi >= 0 else ""

    print(f"\n  OVERALL RECORD:  {wins}W – {losses}L")
    print(f"  PROFIT:          {profit_sign}{profit:.2f}u   ROI: {roi_sign}{roi:.1f}%")

    # ── ROI by edge tier ──────────────────────────────────────────────────────
    print(f"\n  ROI BY EDGE TIER:")
    print(f"  {'Tier':<12} {'Bets':>5}  {'W-L':>6}  {'Profit':>8}  {'ROI':>7}")
    print(f"  {'─'*45}")
    tier_data = roi_by_edge_tier(picks_log_path)
    if tier_data:
        for tier in ("HIGH", "MED", "LOW", "UNKNOWN"):
            if tier not in tier_data:
                continue
            d  = tier_data[tier]
            wl = f"{d['wins']}-{d['losses']}"
            s  = "+" if d["profit"] >= 0 else ""
            rs = "+" if d["roi"] >= 0 else ""
            print(f"  {tier:<12} {d['count']:>5}  {wl:>6}  {s}{d['profit']:>7.2f}u  {rs}{d['roi']:>6.1f}%")
    else:
        print(f"  (No edge data available — bets need model_prob/edge fields)")

    # ── ROI by odds range ─────────────────────────────────────────────────────
    print(f"\n  ROI BY ODDS RANGE:")
    print(f"  {'Bucket':<28} {'Bets':>5}  {'W-L':>6}  {'Profit':>8}  {'ROI':>7}")
    print(f"  {'─'*57}")
    odds_data = roi_by_odds_range(picks_log_path)
    if odds_data:
        for bucket, d in odds_data.items():
            wl = f"{d['wins']}-{d['losses']}"
            s  = "+" if d["profit"] >= 0 else ""
            rs = "+" if d["roi"] >= 0 else ""
            print(f"  {bucket:<28} {d['count']:>5}  {wl:>6}  {s}{d['profit']:>7.2f}u  {rs}{d['roi']:>6.1f}%")
    else:
        print(f"  (No settled bets)")

    # ── Calibration ───────────────────────────────────────────────────────────
    print(f"\n  MODEL CALIBRATION (expected vs actual win rate per prob bin):")
    cal_rows = calibration_check(picks_log_path)
    if cal_rows:
        print(f"  {'Prob Bin':<14} {'N':>5}  {'Expected':>9}  {'Actual':>9}  {'Delta':>7}")
        print(f"  {'─'*48}")
        for row in cal_rows:
            delta_s = f"{row['delta']:+.1%}"
            print(
                f"  {row['bin']:<14} {row['count']:>5}  "
                f"{row['expected_win_rate']:>8.1%}  "
                f"{row['actual_win_rate']:>8.1%}  "
                f"{delta_s:>7}"
            )
    else:
        print(f"  (No model_prob data yet — auto-logged bets populate this field)")

    # ── Variance ──────────────────────────────────────────────────────────────
    print(f"\n  VARIANCE ANALYSIS:")
    var = variance_report(picks_log_path)
    roi_s  = "+" if var["actual_roi"] >= 0 else ""
    eroi_s = "+" if var["expected_roi"] >= 0 else ""
    print(f"  Actual ROI:    {roi_s}{var['actual_roi']:.1f}%")
    print(f"  Expected ROI:  {eroi_s}{var['expected_roi']:.1f}%   (market-implied, vig-inclusive)")
    print(f"  Std Dev ROI:   ±{var['std_dev_roi']:.1f}%   (per bet, 1σ)")
    print(f"  Z-Score:       {var['z_score']:+.2f}  ({'within 1σ' if var['within_1_std'] else '2σ+' if not var['within_2_std'] else '1-2σ'})")
    print(f"  Verdict:       {var['verdict']}")

    print(f"\n{'═' * W}\n")

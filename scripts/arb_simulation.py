"""
Arbitrage Betting Simulation — MLB Season

Simulates a full MLB season of arb betting using:
  - Real arb margins extracted from today's live odds data as baseline
  - Monte Carlo: 1,000 season simulations
  - Accounts for real-world friction: book limits, bet rejections, execution lag

Run:
    python3 scripts/arb_simulation.py

Results show terminal table + saves bankroll_curve.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.arb_finder import find_arbs, add_stakes

# ─────────────────────────── Simulation Config ──────────────────────────────

STARTING_BANKROLL   = 1_000.0     # "large beginner bankroll"
BET_SIZE_PCT        = 0.03        # 3% of bankroll per arb (conservative — arb is low edge, high volume)
MLB_SEASON_DAYS     = 162         # regular season
SIMS                = 1_000       # Monte Carlo runs

# Realistic arb occurrence model (based on real observed data):
# On an average MLB day (~15 games), how many arbs typically appear?
ARB_PER_DAY_MEAN    = 2.5         # avg arbs per day including offshore books
ARB_PER_DAY_TIER1   = 0.8         # avg arbs using ONLY tier-1 US books (DK/FD/BetMGM)

# Real-world friction:
# Books limit/ban accounts that arb too aggressively.
# Each arb placed has a small chance of triggering account review.
# Once limited, that account is "dead" for sharp arbs.
LIMIT_PROB_PER_ARB  = 0.008       # 0.8% per arb → ~90% chance of getting limited within 1 season
STARTING_ACCOUNTS   = 4           # DraftKings, FanDuel, BetMGM, BetRivers

# On each arb, a small % of the time execution fails (line moves, bet rejected)
EXECUTION_FAIL_RATE = 0.05        # 5% of arbs fail mid-execution → one-sided loss exposure
ONE_SIDED_LOSS_MEAN = 0.015       # avg loss when caught one-sided: ~1.5% of stake

# ─────────────────────────── Core Simulation ────────────────────────────────

def _sample_arb_margin(margins: list[float]) -> float:
    """Sample a realistic arb margin from observed distribution."""
    if not margins:
        return random.gauss(0.8, 0.4)
    m = random.choice(margins)
    noise = random.gauss(0, 0.15)
    return max(0.05, m + noise)


def run_simulation(
    observed_margins: list[float],
    bankroll: float = STARTING_BANKROLL,
    days: int = MLB_SEASON_DAYS,
    tier1_only: bool = False,
    verbose: bool = False,
) -> dict:
    """Run one season simulation. Returns final bankroll + stats."""
    arbs_per_day = ARB_PER_DAY_TIER1 if tier1_only else ARB_PER_DAY_MEAN
    accounts_alive = STARTING_ACCOUNTS
    br = bankroll
    total_arbs = 0
    total_profit = 0.0
    total_risk = 0.0
    failed_executions = 0
    daily_brs = [br]

    for day in range(days):
        if br <= 0:
            break

        # Account degradation over season (books gradually limit arbers)
        acct_multiplier = max(0.1, accounts_alive / STARTING_ACCOUNTS)
        day_arbs = max(0, int(random.gauss(arbs_per_day * acct_multiplier, 0.8)))

        for _ in range(day_arbs):
            if br <= 0:
                break
            total_arbs += 1
            stake = br * BET_SIZE_PCT
            margin = _sample_arb_margin(observed_margins)

            # Execution failure — line moved before one side placed
            if random.random() < EXECUTION_FAIL_RATE:
                failed_executions += 1
                loss = stake * random.gauss(ONE_SIDED_LOSS_MEAN, 0.005)
                br -= loss
                total_risk += stake
                continue

            # Successful arb — guaranteed profit
            profit = stake * (margin / 100)
            br += profit
            total_profit += profit
            total_risk += stake

            # Account limitation risk
            if random.random() < LIMIT_PROB_PER_ARB and accounts_alive > 0:
                accounts_alive = max(0, accounts_alive - 1)

        daily_brs.append(round(br, 2))

    roi = (br - bankroll) / bankroll * 100
    return {
        "final_bankroll": round(br, 2),
        "total_profit": round(total_profit, 2),
        "total_arbs": total_arbs,
        "failed_executions": failed_executions,
        "roi_pct": round(roi, 2),
        "accounts_alive_end": accounts_alive,
        "daily_brs": daily_brs,
    }


def monte_carlo(
    observed_margins: list[float],
    n: int = SIMS,
    bankroll: float = STARTING_BANKROLL,
    tier1_only: bool = False,
) -> dict:
    results = []
    for _ in range(n):
        r = run_simulation(observed_margins, bankroll=bankroll, tier1_only=tier1_only)
        results.append(r)

    finals = sorted(r["final_bankroll"] for r in results)
    rois = [r["roi_pct"] for r in results]
    profitable = sum(1 for r in results if r["final_bankroll"] > bankroll)

    p10 = finals[int(n * 0.10)]
    p25 = finals[int(n * 0.25)]
    p50 = finals[int(n * 0.50)]
    p75 = finals[int(n * 0.75)]
    p90 = finals[int(n * 0.90)]

    # Median daily curve for chart
    all_curves = [r["daily_brs"] for r in results]
    max_len = max(len(c) for c in all_curves)
    median_curve = []
    for i in range(max_len):
        vals = [c[i] for c in all_curves if i < len(c)]
        vals.sort()
        median_curve.append(vals[len(vals) // 2])

    return {
        "n_sims": n,
        "starting_bankroll": bankroll,
        "profitable_pct": round(profitable / n * 100, 1),
        "avg_roi_pct": round(sum(rois) / n, 2),
        "avg_final": round(sum(finals) / n, 2),
        "p10": round(p10, 2),
        "p25": round(p25, 2),
        "p50": round(p50, 2),
        "p75": round(p75, 2),
        "p90": round(p90, 2),
        "median_daily_curve": median_curve,
        "avg_arbs_placed": round(sum(r["total_arbs"] for r in results) / n),
        "avg_failed_executions": round(sum(r["failed_executions"] for r in results) / n, 1),
    }


# ─────────────────────────── Reporting ──────────────────────────────────────

def _bar(val: float, min_v: float, max_v: float, width: int = 30) -> str:
    if max_v <= min_v:
        return "█" * (width // 2)
    frac = (val - min_v) / (max_v - min_v)
    filled = int(frac * width)
    return "█" * filled + "░" * (width - filled)


def print_report(arbs: list[dict], mc_all: dict, mc_t1: dict) -> None:
    line = "─" * 72

    print(f"\n{'ARB BETTING SIMULATION REPORT':^72}")
    print(f"{'MLB 2026 — ' + str(MLB_SEASON_DAYS) + ' Day Season':^72}")
    print(line)

    # ── Today's live arbs ──────────────────────────────────────────────────
    today_label = "TODAY'S LIVE ARB OPPORTUNITIES"
    print(f"\n{today_label:^72}")
    print(line)
    if not arbs:
        print("  No arbs found on today's slate (markets are efficient right now).")
    else:
        for a in arbs[:10]:
            tier = "[T1]" if a["both_tier1"] else "[**]"
            print(
                f"  {tier} {a['game']:<30} {a['market']:<9} "
                f"{a['margin_pct']:>5.2f}%  "
                f"{a['side1']} {int(a['odds1']):+d} @ {a['book1']}"
            )
            print(
                f"       {'':30}         "
                f"vs {a['side2']} {int(a['odds2']):+d} @ {a['book2']}"
            )
            if "stake1" in a:
                print(
                    f"       Stakes: ${a['stake1']:.2f} + ${a['stake2']:.2f}  "
                    f"→ +${a['guaranteed_profit']:.2f} guaranteed"
                )
            print()
        if len(arbs) > 10:
            print(f"  ... and {len(arbs)-10} more arbs.")

    # ── Simulation results ─────────────────────────────────────────────────
    for label, mc in [("ALL BOOKS (incl offshore)", mc_all), ("TIER-1 US BOOKS ONLY", mc_t1)]:
        print(f"\n{'MONTE CARLO: ' + label:^72}")
        print(line)
        print(f"  Starting bankroll : ${mc['starting_bankroll']:>10,.2f}")
        print(f"  Simulations run   : {mc['n_sims']:>10,}")
        print(f"  Profitable seasons: {mc['profitable_pct']:>10.1f}%")
        print(f"  Avg season ROI    : {mc['avg_roi_pct']:>10.2f}%")
        print(f"  Avg arbs placed   : {mc['avg_arbs_placed']:>10,}")
        print(f"  Avg failed exec   : {mc['avg_failed_executions']:>10.1f}")
        print()
        print("  Bankroll distribution after full season:")
        for pct, key in [(10, "p10"), (25, "p25"), (50, "p50"), (75, "p75"), (90, "p90")]:
            val = mc[key]
            bar = _bar(val, mc["p10"], mc["p90"])
            roi = (val - mc["starting_bankroll"]) / mc["starting_bankroll"] * 100
            print(f"    P{pct:<2}  {bar}  ${val:>8,.2f}  ({roi:+.1f}%)")
        print()

    # ── Key takeaways ──────────────────────────────────────────────────────
    print(f"\n{'KEY TAKEAWAYS':^72}")
    print(line)
    print("  [1] Arb betting is mathematically risk-free per individual bet")
    print("      when executed correctly — guaranteed profit if BOTH sides fill.")
    print()
    print("  [2] The real risk is ACCOUNT LIMITATION. Books detect arbers via")
    print("      bet patterns and will restrict/ban accounts within weeks.")
    print(f"      Model: ~{LIMIT_PROB_PER_ARB*100:.1f}% limit probability per arb placed.")
    print()
    print("  [3] Tier-1 only arbs (DK/FD/BetMGM) are rare (~1/day). Most arbs")
    print("      require offshore books with withdrawal/legal risk.")
    print()
    print("  [4] Margins are tiny (0.5–2%). Volume is everything. You need")
    print("      many accounts, fast execution, and software to profit at scale.")
    print()
    print("  [5] Your EdgeFinder MODEL edge strategy is more sustainable long-term")
    print("      because books can't detect +EV betting as easily as pure arbing.")
    print(line)


# ─────────────────────────── Main ────────────────────────────────────────────

def main() -> None:
    print("  Loading today's MLB odds...")
    arbs_all  = find_arbs(tier1_only=False, min_margin_pct=0.1)
    arbs_t1   = find_arbs(tier1_only=True,  min_margin_pct=0.1)

    add_stakes(arbs_all, STARTING_BANKROLL)
    add_stakes(arbs_t1,  STARTING_BANKROLL)

    observed_margins_all = [a["margin_pct"] for a in arbs_all] or [0.5, 0.8, 1.2]
    observed_margins_t1  = [a["margin_pct"] for a in arbs_t1]  or [0.3, 0.5]

    print(f"  Found {len(arbs_all)} arbs (all books) | {len(arbs_t1)} arbs (tier-1 only)")
    print(f"  Running {SIMS:,} season simulations...")

    mc_all = monte_carlo(observed_margins_all, n=SIMS, bankroll=STARTING_BANKROLL, tier1_only=False)
    mc_t1  = monte_carlo(observed_margins_t1,  n=SIMS, bankroll=STARTING_BANKROLL, tier1_only=True)

    print_report(arbs_all, mc_all, mc_t1)

    # Save results
    out = Path("output/simulations")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "arb_simulation_results.json", "w") as f:
        json.dump({
            "date": "2026-04-15",
            "starting_bankroll": STARTING_BANKROLL,
            "arbs_today": arbs_all[:20],
            "monte_carlo_all_books": {k: v for k, v in mc_all.items() if k != "median_daily_curve"},
            "monte_carlo_tier1_only": {k: v for k, v in mc_t1.items() if k != "median_daily_curve"},
            "median_daily_curve_all": mc_all["median_daily_curve"],
            "median_daily_curve_t1":  mc_t1["median_daily_curve"],
        }, f, indent=2)
    print(f"\n  Results saved → output/simulations/arb_simulation_results.json")


if __name__ == "__main__":
    main()

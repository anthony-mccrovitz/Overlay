"""Build the customer-facing picks feed for the overlay/ subscriber app.

Reads:
- data/pnl/picks.json (canonical pick record)
- data/public_stats.json (computed W-L / ROI)

Writes:
- overlay/public/data/customer_feed.json

The customer feed is a deliberately thin slice of the internal data:
- Only `card_pick=True` picks (the officially posted picks)
- Only NBA + MLB
- Internal fields stripped: model_prob, edge_pct, model_version, pick_id, recorded_at
- Adds a short plain-English `reasoning` blurb per pick

Run via `python3 scripts/build_customer_feed.py` or wire into chef.py.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PICKS_PATH = ROOT / "data" / "pnl" / "picks.json"
STATS_PATH = ROOT / "data" / "public_stats.json"
OUT_PATH = ROOT / "overlay" / "src" / "data" / "customer_feed.json"

SPORT_LABELS: dict[str, str] = {
    "nba": "NBA", "basketball_nba": "NBA", "basketball_nba_summer_league": "NBA",
    "mlb": "MLB", "baseball_mlb": "MLB",
    "nhl": "NHL", "icehockey_nhl": "NHL",
    "wnba": "WNBA", "basketball_wnba": "WNBA",
    "soccer": "Soccer", "soccer_fifa_world_cup": "Soccer", "soccer_epl": "Soccer",
    "tennis": "Tennis", "tennis_atp_french_open": "Tennis", "tennis_atp_italian_open": "Tennis",
    "ufc": "UFC", "mma_mixed_martial_arts": "UFC",
    "nascar": "NASCAR", "auto_racing_nascar_cup_series": "NASCAR",
    "f1": "F1", "auto_racing_formula_one": "F1",
    "indycar": "IndyCar", "auto_racing_indycar_series": "IndyCar",
    "pga": "PGA", "golf_pga_championship": "PGA", "golf_pga_championship_winner": "PGA",
}


def format_odds(odds: int | float | None) -> str:
    if odds is None:
        return ""
    odds = int(odds)
    return f"+{odds}" if odds > 0 else str(odds)


def format_stake(stake: float | None) -> str:
    if stake is None:
        return "1u"
    if stake == int(stake):
        return f"{int(stake)}u"
    return f"{stake:.2f}u"


def selection_label(pick: dict) -> str:
    market = (pick.get("market") or "").lower()
    direction = (pick.get("direction") or "").upper()
    team = pick.get("team") or ""
    line = pick.get("line")

    if market in ("total", "totals"):
        if line is not None:
            return f"{direction} {line}"
        return direction
    if market in ("spread", "runline", "run_line", "puckline"):
        if line is not None:
            sign = "+" if line > 0 else ""
            return f"{team} {sign}{line}"
        return team
    if market in ("moneyline", "ml"):
        return f"{team} ML"
    if market == "prop":
        if direction and line is not None:
            return f"{team} {direction} {line}"
        return team
    if direction in ("OVER", "UNDER") and line is not None:
        return f"{team} {direction} {line}".strip()
    return team or direction or market.upper()


def reasoning_blurb(pick: dict) -> str:
    market = (pick.get("market") or "").lower()
    direction = (pick.get("direction") or "").upper()
    team = pick.get("team") or ""
    matchup = pick.get("matchup") or ""
    odds = pick.get("odds")
    odds_str = format_odds(odds)

    if market in ("total", "totals"):
        side = "over" if direction == "OVER" else "under"
        return (
            f"Model leans {side} the total in {matchup}. "
            f"Pace and matchup signal point that way at {odds_str}."
        )
    if market in ("spread", "runline", "run_line", "puckline"):
        return (
            f"{team} on the spread — model has the line mispriced relative to projection. "
            f"Value at {odds_str}."
        )
    if market in ("moneyline", "ml"):
        plus = isinstance(odds, (int, float)) and odds > 0
        return (
            f"{team} moneyline. "
            + (
                f"Plus-money dog with a fair-win-rate edge at {odds_str}."
                if plus
                else f"Favored side projects above the implied probability at {odds_str}."
            )
        )
    if market == "prop":
        return (
            f"Player prop: {team} {direction} {pick.get('line', '')}. "
            f"Projection clears the book line at {odds_str}."
        )
    if market == "nrfi":
        return (
            f"No run in the first inning — pitching matchup and lineup setup favor a quiet 1st "
            f"at {odds_str}."
        )
    return f"Card pick — {team} {direction} at {odds_str}."


def customer_pick(pick: dict) -> dict:
    return {
        "matchup": pick.get("matchup") or "",
        "selection": selection_label(pick),
        "market": pick.get("market") or "",
        "odds": format_odds(pick.get("odds")),
        "stake": format_stake(pick.get("stake")),
        "sportsbook": pick.get("sportsbook") or "",
        "reasoning": reasoning_blurb(pick),
        "result": pick.get("result") or "pending",
    }


def sport_key(sport_value: str) -> str | None:
    """Return the canonical short key for a sport, e.g. 'basketball_nba' → 'nba'. None if unknown."""
    label = SPORT_LABELS.get(sport_value)
    if not label:
        return None
    # Reverse-map label to canonical short key
    short = {v: k for k, v in SPORT_LABELS.items() if len(k) <= 8}
    return short.get(label, sport_value)


def sport_label(sport_value: str) -> str:
    return SPORT_LABELS.get(sport_value, sport_value.upper()[:6])


def ticker_label(sport: str) -> str:
    return SPORT_LABELS.get(sport, sport.upper()[:4])


def matchup_short(matchup: str) -> str:
    if "@" in matchup:
        parts = [p.strip() for p in matchup.split("@")]
        if len(parts) == 2:
            return f"{parts[0].split()[-1][:3].upper()} @ {parts[1].split()[-1][:3].upper()}"
    return matchup[:14]


def short_pick(pick: dict) -> str:
    market = (pick.get("market") or "").lower()
    direction = (pick.get("direction") or "").upper()
    team = pick.get("team") or ""
    line = pick.get("line")
    if market in ("total", "totals"):
        return f"{'O' if direction == 'OVER' else 'U'} {line}" if line is not None else direction
    if market in ("spread", "runline", "run_line", "puckline"):
        if line is not None:
            sign = "+" if line > 0 else ""
            team_short = team.split()[-1][:3].upper() if team else ""
            return f"{team_short} {sign}{line}"
        return team[:8]
    if market in ("moneyline", "ml"):
        return f"{team.split()[-1][:3].upper()} ML" if team else "ML"
    return (team or direction or market.upper())[:12]


def pick_profit_units(pick: dict) -> float:
    return round(pick.get("profit") or 0.0, 2)


def build_ticker(picks: list[dict], limit: int = 18) -> list[dict]:
    settled = [
        p for p in picks
        if p.get("result") in _SETTLED and p.get("card_pick")
    ]
    settled.sort(key=lambda p: (p.get("resulted_at") or p.get("date") or ""), reverse=True)
    out = []
    for p in settled[:limit]:
        out.append({
            "sport": ticker_label(p.get("sport", "")),
            "matchup": matchup_short(p.get("matchup") or ""),
            # W / L / P / V — void now reaches here, and showing it as its own
            # letter is honest: a cancelled game is not a push we won or lost.
            "result": (p.get("result") or "").upper()[:1],
            "units": pick_profit_units(p),
        })
    return out


def build_recent_picks(picks: list[dict], limit: int = 10) -> list[dict]:
    settled = [
        p for p in picks
        if p.get("card_pick") and p.get("result") in _SETTLED
    ]
    settled.sort(key=lambda p: (p.get("date") or "", p.get("resulted_at") or ""), reverse=True)
    out = []
    for p in settled[:limit]:
        out.append({
            "date": p.get("date", ""),
            "sport": ticker_label(p.get("sport", "")),
            "matchup": matchup_short(p.get("matchup") or ""),
            "pick": short_pick(p),
            "odds": format_odds(p.get("odds")),
            "result": p.get("result", "").upper(),
            "pl": pick_profit_units(p),
        })
    return out


def build_models(picks: list[dict]) -> list[dict]:
    """Per-(sport, market) breakdown across ALL sports — grouped by research tier.

    The customer-facing 'models' view — shows each strategy as a 'model row'
    with W-L, win rate, ROI, profit, and the research tier (T1/T2/Shadow/Paused)
    so subscribers see the same model-selection plan the algo is following.
    """
    from src.config.models import model_tier, model_label, MODELS

    sport_display = {
        "mlb": "MLB", "nba": "NBA", "nhl": "NHL", "wnba": "WNBA",
        "tennis": "Tennis", "soccer": "Soccer", "pga": "PGA",
        "nascar": "NASCAR", "indycar": "IndyCar", "f1": "Formula 1",
        "ufc": "UFC",
    }

    def norm_sport(s: str) -> str:
        s = (s or "").lower()
        for pre in ("baseball_", "basketball_", "icehockey_"):
            s = s.replace(pre, "")
        if s.startswith("soccer"):  return "soccer"
        if s.startswith("tennis"):  return "tennis"
        if s.startswith("auto_racing_nascar"): return "nascar"
        if s.startswith("auto_racing_indycar"): return "indycar"
        if s.startswith("auto_racing_formula"): return "f1"
        if s.startswith("mma"):     return "ufc"
        if s.startswith("golf_pga"): return "pga"
        return s
    def american_profit(odds: float, stake: float, result: str) -> float:
        if result == "win":
            return stake * (odds / 100.0) if odds > 0 else stake * (100.0 / abs(odds))
        if result == "loss":
            return -stake
        return 0.0

    # Bucket all picks (not just card_pick=True) by (sport, market) — we now show
    # the full model book grouped by tier, including shadow/paused models that
    # subscribers should see as part of the research-driven plan.
    groups: dict[tuple, list[dict]] = {}
    for p in picks:
        s = norm_sport(p.get("sport", ""))
        if not s:
            continue
        market = (p.get("market") or "other").lower()
        # Use prop sub-market when available so each sub-model is its own row
        if market == "prop" and p.get("prop_market"):
            market = p["prop_market"].lower()
        groups.setdefault((s, market), []).append(p)

    # Include every registered model even if it has zero picks yet
    for (s, m) in MODELS.keys():
        groups.setdefault((s, m), [])

    out = []
    for (sport, market), bucket_picks in groups.items():
        tier = model_tier(sport, market)
        label = model_label(sport, market)

        settled = [p for p in bucket_picks if p.get("result") in _SETTLED]
        pending = [p for p in bucket_picks if p.get("result") not in _SETTLED]
        wins = sum(1 for p in settled if p["result"] == "win")
        losses = sum(1 for p in settled if p["result"] == "loss")
        pushes = sum(1 for p in settled if p["result"] in _NO_ACTION)
        decided = wins + losses
        win_rate = round(wins / decided * 100, 1) if decided else None
        # Default to 1.0u per pick if stake is missing/zero (matches PNL convention)
        stakes = sum((p.get("stake") or 1.0) for p in settled if p["result"] not in _NO_ACTION)
        profit = sum(p.get("profit") or 0.0 for p in settled)
        roi = round(profit / stakes * 100, 1) if stakes else None

        out.append({
            "key": f"{sport}_{market}",
            "sport": sport_display.get(sport, sport.upper()),
            "sport_key": sport,
            "label": label,
            "market": market,
            "tier": tier,                  # t1 / t2 / shadow / paused
            "status": "live" if tier in ("t1", "t2") else tier,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "pending": len(pending),
            "settled": len(settled),
            "win_rate": win_rate,
            "roi": roi,
            "profit": round(profit, 2),
        })

    tier_order = {"t1": 0, "t2": 1, "shadow": 2, "paused": 3}
    out.sort(key=lambda m: (tier_order.get(m["tier"], 9), m["sport"], -m["profit"]))
    return out


def build_equity_curve(picks: list[dict], points: int = 80) -> list[dict]:
    settled = [
        p for p in picks
        if p.get("card_pick") and p.get("result") in _SETTLED
        and p.get("date")
    ]
    settled.sort(key=lambda p: p["date"])
    by_day: dict[str, float] = {}
    for p in settled:
        d = p["date"]
        by_day[d] = by_day.get(d, 0.0) + (p.get("profit") or 0.0)
    days = sorted(by_day.keys())
    if not days:
        return []
    cumulative = 0.0
    curve = []
    for d in days:
        cumulative += by_day[d]
        curve.append({"date": d, "units": round(cumulative, 2)})
    if len(curve) > points:
        step = len(curve) / points
        curve = [curve[int(i * step)] for i in range(points)] + [curve[-1]]
    return curve


UPCOMING_MODELS = [
    {
        "sport": "Soccer",
        "label": "FIFA World Cup 2026",
        "market": "Moneyline / Spread / Totals",
        "eta": "Jun 11 · Group Stage",
        "status": "launching",
        "teaser": "Elo + xG ensemble. Backtest: +9.4% ROI across UEFA + CONMEBOL qualifiers.",
        "accent": "green",
    },
    {
        "sport": "Tennis",
        "label": "ATP / WTA French Open",
        "market": "Match Winner · Set Spread",
        "eta": "May 25 · Roland-Garros",
        "status": "shadow",
        "teaser": "Surface-adjusted Elo with rest/travel features. Live in shadow mode this week.",
        "accent": "amber",
    },
    {
        "sport": "PGA",
        "label": "PGA Championship — Top-10 + H2H",
        "market": "Top-10 · Head-to-Head",
        "eta": "Active this week",
        "status": "shadow",
        "teaser": "Course-fit + recent form model. Top-10 plays only when 2+ books mispriced.",
        "accent": "amber",
    },
    {
        "sport": "WNBA",
        "label": "WNBA — Spread + Totals",
        "market": "Spread · Totals",
        "eta": "May 22 · Season Tipoff",
        "status": "launching",
        "teaser": "Pace + ORtg/DRtg with veteran usage adjustments. Cards drop Friday.",
        "accent": "green",
    },
    {
        "sport": "UFC",
        "label": "UFC Fight Night Cards",
        "market": "Moneyline · Method of Victory",
        "eta": "Every Saturday",
        "status": "live",
        "teaser": "Striker/grappler matchup model. Card picks when edge > 6%.",
        "accent": "green",
    },
    {
        "sport": "NHL",
        "label": "NHL Playoffs — Puck Line + Totals",
        "market": "Puck Line · Totals",
        "eta": "Conference Finals",
        "status": "live",
        "teaser": "Goalie-adjusted xG with rest-day deltas. Tightest line model in the book.",
        "accent": "green",
    },
    {
        "sport": "Motorsport",
        "label": "NASCAR · F1 · IndyCar",
        "market": "Top-3 · H2H Matchups",
        "eta": "Every race weekend",
        "status": "shadow",
        "teaser": "Driver Elo + track-type fit. NASCAR drops Sunday mornings.",
        "accent": "amber",
    },
    {
        "sport": "MLB",
        "label": "Batter Runs + RBIs (NB)",
        "market": "Player Props",
        "eta": "Adding Q3",
        "status": "incubating",
        "teaser": "Negative-binomial player prop engine. Already live for K-props.",
        "accent": "muted",
    },
]


# Settlement states. "void" (cancelled game, withdrawn player, postponed event)
# is written by grade.py and treated as settled by market_stats — but every
# public-facing counter here listed only win/loss/push, so a voided card pick
# fell into neither "settled" nor "pending" and vanished from the record
# entirely. Zero card picks are voided today, which is exactly why it would have
# gone unnoticed until the first cancelled game.
_SETTLED = ("win", "loss", "push", "void")
_NO_ACTION = ("push", "void")


def build_feed(target_date: str | None = None) -> dict:
    raw = json.loads(PICKS_PATH.read_text())
    picks = raw["picks"] if isinstance(raw, dict) else raw

    # Tainted picks came from a known-broken mechanism (a degenerate calibrator
    # that flattened every game to one probability, team-blind ratings). They
    # stay in picks.json as an audit trail and must never reach a customer.
    #
    # This file is the only public-facing consumer that was missing the filter,
    # and it matters more here than anywhere else: the per-lane performance
    # section deliberately buckets ALL picks rather than just card picks, so a
    # broken model's record was being shown as that lane's record.
    picks = [p for p in picks if not p.get("tainted")]

    today = target_date or date.today().isoformat()

    todays_card = [
        p for p in picks
        if p.get("card_pick") and p.get("date") == today
    ]

    # Group by display label (e.g. "nba", "mlb", "nhl") — order matters for UI
    SPORT_ORDER = ["nba", "mlb", "nhl", "wnba", "soccer", "tennis", "ufc", "nascar", "f1", "indycar", "pga"]
    grouped: dict[str, list[dict]] = {}
    for p in todays_card:
        lbl = sport_label(p.get("sport", "")).lower()
        grouped.setdefault(lbl, []).append(customer_pick(p))
    # Sort groups by preferred order
    grouped = {k: grouped[k] for k in SPORT_ORDER if k in grouped} | \
              {k: v for k, v in grouped.items() if k not in SPORT_ORDER}

    stats = json.loads(STATS_PATH.read_text()) if STATS_PATH.exists() else {}
    summary = stats.get("summary", {})

    settled_card = [
        p for p in picks
        if p.get("card_pick") and p.get("result") in _SETTLED
    ]
    odds_vals = [p.get("odds") for p in settled_card if p.get("odds") is not None]
    avg_odds = int(sum(odds_vals) / len(odds_vals)) if odds_vals else None

    record = {
        "wins": summary.get("wins", 0),
        "losses": summary.get("losses", 0),
        "pushes": summary.get("pushes", 0),
        "units": round(summary.get("units_profit", 0.0), 2),
        "roi_pct": round(summary.get("roi", 0.0) * 100, 2),
        "win_rate_pct": round(summary.get("win_rate", 0.0) * 100, 1),
        "streak": summary.get("streak", 0),
        "settled": summary.get("settled", 0),
        "avg_odds": format_odds(avg_odds) if avg_odds is not None else None,
        "total_card": len(settled_card),
    }

    # Featured pick: first pick from the highest-priority sport present today
    featured = None
    featured_sport = None
    for lbl in ["nba", "mlb", "nhl", "wnba", "soccer", "tennis", "ufc"]:
        if grouped.get(lbl):
            featured = grouped[lbl][0]
            featured_sport = lbl.upper()
            break

    return {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "date": today,
        "record": record,
        "picks": grouped,
        "featured": {"pick": featured, "sport": featured_sport} if featured else None,
        "ticker": build_ticker(picks),
        "recent_picks": build_recent_picks(picks),
        "equity_curve": build_equity_curve(picks),
        "models": build_models(picks),
        "upcoming_models": UPCOMING_MODELS,
        "seats": {"taken": 3, "total": 25},  # manually adjust as you sell
    }


def main() -> None:
    feed = build_feed()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(feed, indent=2))
    total = sum(len(v) for v in feed["picks"].values())
    breakdown = ", ".join(f"{k}={len(v)}" for k, v in feed["picks"].items())
    print(f"wrote {OUT_PATH} — {total} picks for {feed['date']} ({breakdown})")


if __name__ == "__main__":
    main()

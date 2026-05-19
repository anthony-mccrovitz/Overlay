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
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PICKS_PATH = ROOT / "data" / "pnl" / "picks.json"
STATS_PATH = ROOT / "data" / "public_stats.json"
OUT_PATH = ROOT / "overlay" / "public" / "data" / "customer_feed.json"

NBA_SPORTS = {"nba", "basketball_nba"}
MLB_SPORTS = {"mlb", "baseball_mlb"}


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


def bucket(sport_value: str) -> str | None:
    if sport_value in NBA_SPORTS:
        return "nba"
    if sport_value in MLB_SPORTS:
        return "mlb"
    return None


def ticker_label(sport: str) -> str:
    if sport in NBA_SPORTS:
        return "NBA"
    if sport in MLB_SPORTS:
        return "MLB"
    return sport.upper()[:4]


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
        if p.get("result") in ("win", "loss", "push") and bucket(p.get("sport", ""))
    ]
    settled.sort(key=lambda p: (p.get("resulted_at") or p.get("date") or ""), reverse=True)
    out = []
    for p in settled[:limit]:
        out.append({
            "sport": ticker_label(p.get("sport", "")),
            "matchup": matchup_short(p.get("matchup") or ""),
            "result": p.get("result", "").upper()[0],  # W / L / P
            "units": pick_profit_units(p),
        })
    return out


def build_recent_picks(picks: list[dict], limit: int = 10) -> list[dict]:
    settled = [
        p for p in picks
        if p.get("card_pick") and p.get("result") in ("win", "loss", "push")
        and bucket(p.get("sport", ""))
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


def build_equity_curve(picks: list[dict], points: int = 80) -> list[dict]:
    settled = [
        p for p in picks
        if p.get("card_pick") and p.get("result") in ("win", "loss", "push")
        and p.get("date") and bucket(p.get("sport", ""))
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


def build_feed(target_date: str | None = None) -> dict:
    raw = json.loads(PICKS_PATH.read_text())
    picks = raw["picks"] if isinstance(raw, dict) else raw

    today = target_date or date.today().isoformat()

    todays_card = [
        p
        for p in picks
        if p.get("card_pick") and p.get("date") == today and bucket(p.get("sport", ""))
    ]

    grouped: dict[str, list[dict]] = {"nba": [], "mlb": []}
    for p in todays_card:
        b = bucket(p["sport"])
        if b:
            grouped[b].append(customer_pick(p))

    stats = json.loads(STATS_PATH.read_text()) if STATS_PATH.exists() else {}
    summary = stats.get("summary", {})

    settled_card = [
        p for p in picks
        if p.get("card_pick") and p.get("result") in ("win", "loss", "push")
        and bucket(p.get("sport", ""))
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

    # Featured pick: highest-stake or first NBA pick today, fallback first MLB
    featured = None
    if grouped["nba"]:
        featured = grouped["nba"][0]
        featured_sport = "NBA"
    elif grouped["mlb"]:
        featured = grouped["mlb"][0]
        featured_sport = "MLB"
    else:
        featured_sport = None

    return {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "date": today,
        "record": record,
        "picks": grouped,
        "featured": {"pick": featured, "sport": featured_sport} if featured else None,
        "ticker": build_ticker(picks),
        "recent_picks": build_recent_picks(picks),
        "equity_curve": build_equity_curve(picks),
        "seats": {"taken": 3, "total": 25},  # manually adjust as you sell
    }


def main() -> None:
    feed = build_feed()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(feed, indent=2))
    total = len(feed["picks"]["nba"]) + len(feed["picks"]["mlb"])
    print(f"wrote {OUT_PATH} — {total} picks for {feed['date']} "
          f"(nba={len(feed['picks']['nba'])}, mlb={len(feed['picks']['mlb'])})")


if __name__ == "__main__":
    main()

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
    record = {
        "wins": summary.get("wins", 0),
        "losses": summary.get("losses", 0),
        "pushes": summary.get("pushes", 0),
        "units": round(summary.get("units_profit", 0.0), 2),
        "roi_pct": round(summary.get("roi", 0.0) * 100, 2),
        "streak": summary.get("streak", 0),
        "settled": summary.get("settled", 0),
    }

    return {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "date": today,
        "record": record,
        "picks": grouped,
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

"""Build slate_data.json for the overlay/ subscriber app.

Reads from output/picks/{sport}/{date}/ (latest date for each sport)
and writes a flat list of SlateRow objects to:
  overlay/src/data/slate_data.json

This is the Vercel-compatible pattern — the JSON is bundled into the
Next.js deployment so the /api/slate route can read it on Vercel even
though output/picks/ doesn't exist there.

Run via:
  python3 scripts/build_slate_data.py
Or auto-invoked by:
  python3 chef.py deploy
  python3 chef.py morning
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = ROOT / "output" / "picks"
OUT_PATH = ROOT / "overlay" / "src" / "data" / "slate_data.json"

SPORT_DIRS: dict[str, str] = {
    "mlb": "baseball_mlb",
    "nba": "basketball_nba",
    "nhl": "icehockey_nhl",
}


# ── Helpers ────────────────────────────────────────────────────────────────

def get_latest_date_dir(sport_dir: str) -> str | None:
    d = OUTPUT_ROOT / sport_dir
    if not d.exists():
        return None
    candidates = sorted(
        [x.name for x in d.iterdir() if x.is_dir() and x.name.isdigit() and len(x.name) == 8],
        reverse=True,
    )
    return candidates[0] if candidates else None


def read_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        text = path.read_text("utf-8")
        # Sanitize NaN / Infinity that Python writes but JSON doesn't allow
        text = text.replace(": NaN", ": null").replace(": Infinity", ": null")
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return parsed.get("picks", [])
        return []
    except Exception:
        return []


def fmt_odds(o: int | float | None) -> str:
    if o is None:
        return "—"
    return f"+{int(o)}" if o > 0 else str(int(o))


def implied_prob(odds: int | float | None) -> float | None:
    if odds is None:
        return None
    if odds < 0:
        return (-odds) / (-odds + 100)
    return 100 / (odds + 100)


# ── Sport builders ─────────────────────────────────────────────────────────

def build_mlb_rows(date_dir: str, sport_dir: str) -> list[dict]:
    base = OUTPUT_ROOT / sport_dir / date_dir
    rows: list[dict] = []

    # ── Moneyline / spread / game totals ──
    for p in read_json(base / "picks.json"):
        market = str(p.get("Market") or p.get("market") or "").lower()
        if market not in {"moneyline", "spread", "total"}:
            continue

        matchup_raw = str(p.get("Matchup") or "")
        parts = matchup_raw.split(" @ ")
        away = parts[0].strip() if len(parts) == 2 else str(p.get("Opponent") or "")
        home = parts[1].strip() if len(parts) == 2 else str(p.get("HomeTeam") or "")
        team = str(p.get("Team") or "")
        opponent = str(p.get("Opponent") or "")
        matchup = (
            f"{away} @ {home}" if away and home
            else f"{team} vs {opponent}" if (away or opponent) else team
        )

        model_prob = p.get("ModelProb")
        implied_p = p.get("ImpliedProb")
        raw_edge = float(p.get("Edge") or 0)
        edge_pct = raw_edge if raw_edge > 1 else raw_edge * 100
        odds = p.get("BestOdds")

        direction = (
            ("HOME" if team == home else "AWAY") if market == "moneyline"
            else str(p.get("Direction") or "")
        )

        rows.append({
            "id": f"mlb-{market}-{matchup}-{direction}",
            "sport": "mlb",
            "market": market,
            "matchup": matchup,
            "away_team": away or opponent,
            "home_team": home,
            "direction": direction or team,
            "line": p.get("MarketLine") or p.get("BetLine"),
            "model_prob": model_prob,
            "implied_prob": implied_p,
            "edge_pct": round(edge_pct * 10) / 10,
            "odds": odds,
            "odds_fmt": fmt_odds(odds),
            "book": str(p.get("Sportsbook") or ""),
            "commence_time": p.get("CommenceTime"),
            "away_sp": None,
            "home_sp": None,
            "why": p.get("Why"),
            "is_card_pick": bool(p.get("CardPick") or p.get("card_pick")),
        })

    # ── NRFI ──
    for n in read_json(base / "nrfi.json"):
        away = str(n.get("away_team") or "")
        home = str(n.get("home_team") or "")
        matchup = f"{away} @ {home}"
        model_prob = n.get("projected_nrfi")
        implied_p = n.get("implied_nrfi")
        edge_pct = float(n.get("edge_pct") or 0)
        odds = n.get("odds")

        rows.append({
            "id": f"mlb-nrfi-{matchup}",
            "sport": "mlb",
            "market": "nrfi",
            "matchup": matchup,
            "away_team": away,
            "home_team": home,
            "direction": "NRFI",
            "line": None,
            "model_prob": model_prob,
            "implied_prob": implied_p,
            "edge_pct": round(edge_pct * 10) / 10,
            "odds": odds,
            "odds_fmt": fmt_odds(odds),
            "book": str(n.get("book") or ""),
            "commence_time": None,
            "away_sp": n.get("away_sp"),
            "home_sp": n.get("home_sp"),
            "why": None,
            "is_card_pick": True,
        })

    # ── F5 Totals ──
    for f in read_json(base / "f5_totals.json"):
        matchup = str(f.get("matchup") or "")
        parts = matchup.split(" @ ")
        away = parts[0].strip() if len(parts) == 2 else str(f.get("away_team") or "")
        home = parts[1].strip() if len(parts) == 2 else str(f.get("home_team") or "")
        model_prob = f.get("model_prob")
        implied_p = f.get("implied_prob")
        edge_pct = float(f.get("edge_pct") or 0)
        odds = f.get("odds")
        direction = str(f.get("direction") or "")

        rows.append({
            "id": f"mlb-f5-{matchup}-{direction}",
            "sport": "mlb",
            "market": "f5_total",
            "matchup": matchup,
            "away_team": away,
            "home_team": home,
            "direction": direction,
            "line": f.get("line"),
            "model_prob": model_prob,
            "implied_prob": implied_p,
            "edge_pct": round(edge_pct * 10) / 10,
            "odds": odds,
            "odds_fmt": fmt_odds(odds),
            "book": str(f.get("book") or ""),
            "commence_time": None,
            "away_sp": None,
            "home_sp": None,
            "why": None,
            "is_card_pick": True,
        })

    return rows


def build_nba_rows(date_dir: str, sport_dir: str) -> list[dict]:
    base = OUTPUT_ROOT / sport_dir / date_dir
    rows: list[dict] = []

    for p in read_json(base / "picks.json"):
        market = str(p.get("market") or p.get("Market") or "").lower()
        matchup = str(p.get("matchup") or "")
        parts = matchup.split(" @ ")
        away = parts[0].strip() if len(parts) == 2 else ""
        home = parts[1].strip() if len(parts) == 2 else ""
        model_prob = p.get("model_prob")
        odds = p.get("best_odds") or p.get("odds")
        implied_p = implied_prob(odds)
        edge_pct = float(p.get("edge_pct") or 0)
        direction = str(p.get("direction") or "")
        line = p.get("bet_line")
        commence_time = p.get("commence_time")

        rows.append({
            "id": f"nba-{market}-{matchup}-{direction}",
            "sport": "nba",
            "market": market,
            "matchup": matchup,
            "away_team": away,
            "home_team": home,
            "direction": direction or str(p.get("team") or ""),
            "line": line,
            "model_prob": model_prob,
            "implied_prob": implied_p,
            "edge_pct": round(edge_pct * 10) / 10,
            "odds": odds,
            "odds_fmt": fmt_odds(odds),
            "book": str(p.get("sportsbook") or ""),
            "commence_time": commence_time,
            "away_sp": None,
            "home_sp": None,
            "why": p.get("notes"),
            "is_card_pick": bool(p.get("card_pick")),
        })

    return rows


# ── Main ───────────────────────────────────────────────────────────────────

def build() -> dict:
    all_rows: list[dict] = []
    dates: dict[str, str] = {}

    for sport, sport_dir in SPORT_DIRS.items():
        date_dir = get_latest_date_dir(sport_dir)
        if not date_dir:
            continue
        dates[sport] = date_dir

        if sport == "mlb":
            rows = build_mlb_rows(date_dir, sport_dir)
        elif sport == "nba":
            rows = build_nba_rows(date_dir, sport_dir)
        else:
            rows = []

        all_rows.extend(rows)

    # Sort: card picks first, then by edge descending
    all_rows.sort(key=lambda r: (0 if r["is_card_pick"] else 1, -r["edge_pct"]))

    positive = sum(1 for r in all_rows if r["edge_pct"] > 0)
    card_picks = sum(1 for r in all_rows if r["is_card_pick"])
    avg_edge = sum(r["edge_pct"] for r in all_rows) / len(all_rows) if all_rows else 0
    top_edge = all_rows[0]["edge_pct"] if all_rows else 0

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "dates": dates,
        "total": len(all_rows),
        "positive_ev": positive,
        "avg_edge": round(avg_edge * 10) / 10,
        "top_edge": top_edge,
        "card_picks": card_picks,
        "rows": all_rows,
    }


def main() -> int:
    print("  ▸ Building slate_data.json...")
    try:
        data = build()
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(data, indent=2, default=str), "utf-8")
        print(f"  ✓ slate_data.json  →  {data['total']} rows  "
              f"({data['card_picks']} card picks, top edge {data['top_edge']}%)")
        return 0
    except Exception as e:
        print(f"  ✗ slate_data build failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

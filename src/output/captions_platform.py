"""
Platform caption generator — Instagram, X/Twitter, Reddit only.

Output: output/picks/{sport}/{YYYYMMDD}/captions/{platform}.txt
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

OUTPUT_DIR = Path("output/picks")

MLB_IG_TAGS = (
    "#MLB #MLBpicks #sportsbetting #baseballbetting #sharpbetting "
    "#valuebet #totals #DraftKings #FanDuel #BetMGM #edgebetting "
    "#bettingmodel #freepicks #dailypicks #sportsbettingtips"
)
NBA_IG_TAGS = (
    "#NBA #NBAPlayoffs #sportsbetting #NBApicks #sharpbetting "
    "#valuebet #edgebetting #DraftKings #FanDuel #BetMGM "
    "#bettingmodel #freepicks #dailypicks #NBAPlayoffs2026"
)

DISCLAIMER = "Not financial advice. Bet responsibly. 21+"

# Books we actually have accounts with — never feature a book we can't bet at
_APPROVED_BOOKS = {
    "fanduel", "draftkings", "betmgm", "betrivers", "hard rock bet",
    "hardrockbet", "fliff", "caesars", "bet365", "thescore bet",
    "thescorebet", "fanatics", "novig", "espn bet", "espnbet",
}


def _is_approved_book(book: str) -> bool:
    return book.lower().strip() in _APPROVED_BOOKS


def _fmt_odds(odds) -> str:
    try:
        return f"{int(float(odds)):+d}"
    except Exception:
        return str(odds)


def _fmt_edge(edge) -> str:
    try:
        e = float(edge)
        return f"+{e:.1f}%" if e >= 0 else f"{e:.1f}%"
    except Exception:
        return str(edge)


def _load_totals_record() -> str:
    """Return overall card-pick record from picks.json."""
    try:
        import json as _json
        picks_path = Path("data/pnl/picks.json")
        if not picks_path.exists():
            return ""
        raw = _json.loads(picks_path.read_text())
        picks = raw if isinstance(raw, list) else raw.get("picks", [])
        settled = [p for p in picks
                   if isinstance(p, dict)
                   and p.get("card_pick")
                   and p.get("result") in ("win", "loss", "push")]
        w = sum(1 for p in settled if p["result"] == "win")
        l = sum(1 for p in settled if p["result"] == "loss")
        n = w + l
        if n < 5:
            return ""
        wr = round(w / n * 100, 1)
        profit = sum(p.get("profit") or 0 for p in settled)
        sign = "+" if profit >= 0 else ""
        return f"{w}-{l} ({wr}% WR, {sign}{profit:.1f}u)"
    except Exception:
        return ""


def _top_picks(picks: list[dict], markets: list[str] | None = None) -> list[dict]:
    """Return positive-edge picks from approved books, sorted by edge."""
    out = [
        p for p in picks
        if float(p.get("edge_pct", p.get("Edge", 0) or 0)) > 0
        and _is_approved_book(str(p.get("sportsbook") or p.get("Sportsbook") or ""))
    ]
    if markets:
        out = [p for p in out if str(p.get("market", p.get("Market", ""))).lower() in markets]
    return sorted(out, key=lambda x: float(x.get("edge_pct", x.get("Edge", 0) or 0)), reverse=True)


def _pick_line(p: dict) -> str:
    team = p.get("team") or p.get("Team", "")
    odds = _fmt_odds(p.get("odds") or p.get("best_odds") or p.get("BestOdds"))
    book = (p.get("sportsbook") or p.get("Sportsbook", "")).strip()
    edge = _fmt_edge(p.get("edge_pct") or p.get("Edge", 0))
    matchup = p.get("matchup", "")
    short_matchup = ""
    if matchup and " @ " in matchup:
        away, home = matchup.split(" @ ", 1)
        a = away.split()[-1]
        h = home.split()[-1]
        short_matchup = f" ({a} @ {h})"
    return f"{team}{short_matchup}  {odds} @ {book}  |  {edge}"


# ── INSTAGRAM ─────────────────────────────────────────────────────────────────

def instagram_caption(picks: list[dict], sport: str, card_date: date) -> str:
    is_nba  = "nba" in sport.lower()
    sl      = "NBA" if is_nba else "MLB"
    dl      = card_date.strftime("%b %d")
    tags    = NBA_IG_TAGS if is_nba else MLB_IG_TAGS
    record  = _load_totals_record()

    # Prefer live markets: totals and spread (run line) over moneyline
    best_picks = _top_picks(picks, ["total", "f5_total", "spread"])
    if not best_picks:
        best_picks = _top_picks(picks)

    lines = [f"{sl} — {dl} PICKS"]

    best = best_picks[0] if best_picks else None
    if best:
        team    = best.get("team") or best.get("Team", "")
        odds    = _fmt_odds(best.get("odds") or best.get("best_odds") or best.get("BestOdds"))
        book    = (best.get("sportsbook") or best.get("Sportsbook", "")).strip()
        edge    = _fmt_edge(best.get("edge_pct") or best.get("Edge", 0))
        matchup = best.get("matchup", "")
        lines += [
            "",
            "BEST BET",
            f"{team}  {odds} @ {book}",
            f"Model edge: {edge}",
        ]
        if matchup:
            lines.append(matchup)

    if len(best_picks) > 1:
        lines += ["", "Also:"]
        for p in best_picks[1:3]:
            lines.append(f"- {_pick_line(p)}")

    if record:
        lines += ["", f"Season {record}"]

    lines += [
        "Picks timestamped before first pitch. Record in bio.",
        "",
        DISCLAIMER,
        "",
        tags,
    ]
    return "\n".join(lines)


# ── X / TWITTER ───────────────────────────────────────────────────────────────

def twitter_post(picks: list[dict], sport: str, card_date: date) -> str:
    """Single post ≤280 chars, plus a reply thread for supporting picks."""
    is_nba = "nba" in sport.lower()
    sl     = "NBA" if is_nba else "MLB"
    dl     = card_date.strftime("%b %d")
    record = _load_totals_record()
    tags   = "#NBAPlayoffs #sportsbetting" if is_nba else "#MLB #sportsbetting"

    best_picks = _top_picks(picks, ["total", "f5_total", "spread"])
    if not best_picks:
        best_picks = _top_picks(picks)

    tweets = []

    best = best_picks[0] if best_picks else None
    if best:
        team    = best.get("team") or best.get("Team", "")
        odds    = _fmt_odds(best.get("odds") or best.get("best_odds") or best.get("BestOdds"))
        book    = (best.get("sportsbook") or best.get("Sportsbook", "")).replace(" ", "")
        edge    = _fmt_edge(best.get("edge_pct") or best.get("Edge", 0))
        matchup = best.get("matchup", "")
        short_m = ""
        if matchup and " @ " in matchup:
            away, home = matchup.split(" @ ", 1)
            short_m = f" ({away.split()[-1]} @ {home.split()[-1]})"

        t1_parts = [
            f"{sl} — {dl} | BEST BET",
            f"{team}{short_m}  {odds} @{book}",
            f"Model edge: {edge}",
        ]
        if record:
            t1_parts.append(f"Season {record}")
        t1_parts.append(f"{DISCLAIMER}  {tags}")
        tweets.append("\n".join(t1_parts))

    if len(best_picks) > 1:
        lines = ["Full card:"]
        for p in best_picks[1:4]:
            team = p.get("team") or p.get("Team", "")
            odds = _fmt_odds(p.get("odds") or p.get("best_odds") or p.get("BestOdds"))
            book = (p.get("sportsbook") or p.get("Sportsbook", "")).replace(" ", "")
            edge = _fmt_edge(p.get("edge_pct") or p.get("Edge", 0))
            lines.append(f"- {team}  {odds} @{book}  ({edge})")
        tweets.append("\n".join(lines))

    return "\n\n---\n\n".join(tweets)


# ── REDDIT ────────────────────────────────────────────────────────────────────

def reddit_post(picks: list[dict], sport: str, card_date: date) -> str:
    is_nba  = "nba" in sport.lower()
    sl      = "NBA PLAYOFFS" if is_nba else "MLB"
    dl      = card_date.strftime("%B %d, %Y").upper()
    record  = _load_totals_record()
    all_p   = _top_picks(picks)
    totals  = _top_picks(picks, ["total", "f5_total"])

    model_note = (
        "Running XGBoost on NBA efficiency ratings (ORtg/DRtg/Pace). "
        "Walk-forward validated on 2015-2026 games. All picks logged with timestamp before tip-off."
        if is_nba else
        "Running XGBoost + Pythagorean ensemble on MLB team stats. "
        "All picks logged with timestamp before first pitch."
    )

    lines = [
        f"**Overlay AI Model — {sl} {dl}**",
        "",
        model_note,
        "",
        "---",
        "",
    ]

    if record:
        lines += [f"**Season {record}**", ""]

    if totals:
        lines += ["**🔒 Totals (model's strongest market)**", ""]
        lines += ["| Game | Bet | Odds | Edge | Book |",
                  "|------|-----|------|------|------|"]
        for p in totals:
            matchup = p.get("matchup", "")
            team    = p.get("team") or p.get("Team", "")
            odds    = _fmt_odds(p.get("odds") or p.get("best_odds") or p.get("BestOdds"))
            book    = p.get("sportsbook") or p.get("Sportsbook", "")
            edge    = _fmt_edge(p.get("edge_pct") or p.get("Edge", 0))
            lines.append(f"| {matchup} | {team} | {odds} | {edge} | {book} |")
        lines.append("")

    other = [p for p in all_p if str(p.get("market", p.get("Market",""))).lower() not in ("total","f5_total")]
    if other:
        lines += ["**Other Edges**", ""]
        lines += ["| Bet | Odds | Edge | Book |",
                  "|-----|------|------|------|"]
        for p in other[:4]:
            team = p.get("team") or p.get("Team", "")
            odds = _fmt_odds(p.get("odds") or p.get("best_odds") or p.get("BestOdds"))
            book = p.get("sportsbook") or p.get("Sportsbook", "")
            edge = _fmt_edge(p.get("edge_pct") or p.get("Edge", 0))
            lines.append(f"| {team} | {odds} | {edge} | {book} |")
        lines.append("")

    lines += [
        "---",
        "",
        "*Results posted daily. All picks logged before game time. No paid shills.*",
        "",
        f"*{DISCLAIMER}*",
    ]
    return "\n".join(lines)


# ── Writer ────────────────────────────────────────────────────────────────────

def write_platform_captions(
    picks: list[dict],
    sport: str,
    card_date: date | None = None,
) -> dict[str, Path]:
    """Generate Instagram, Twitter, Reddit captions. Returns {platform: path}."""
    d = card_date or date.today()
    cap_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d") / "captions"
    cap_dir.mkdir(parents=True, exist_ok=True)

    ig = instagram_caption(picks, sport, d)
    tw = twitter_post(picks, sport, d)
    rd = reddit_post(picks, sport, d)

    paths = {}
    for platform, content in [("instagram", ig), ("twitter", tw), ("reddit", rd)]:
        path = cap_dir / f"{platform}.txt"
        path.write_text(content, encoding="utf-8")
        paths[platform] = path

    return paths


# Keep old name as alias so existing callers don't break
def write_all_platform_captions(
    picks: list[dict],
    props: list[dict],
    nrfi: list[dict],
    sport: str,
    card_date: date | None = None,
) -> dict[str, Path]:
    return write_platform_captions(picks, sport, card_date)

"""
social.py — personal-bet content generator for the daily ritual.

Surfaces:
  - pick_of_day_mlb(picks_path) -> ranked list of today's MLB edges
  - format_pre_game(pick, stake, raf_link) -> {tweet, video_script}
  - format_post_game(pick, running, raf_link) -> {tweet, video_script}
  - wc_match_of_day(fixtures_path) -> the marquee World Cup fixture today
  - format_wc_post(match, product_link) -> {tweet, video_script}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Anthony's RAF links, mirrored from parlay_card._BOOK_BRAND.
PARTNER_BOOKS = {
    "fanduel":    "https://fndl.co/92pew6d",
    "draftkings": "https://sportsbook.draftkings.com/r/sb/amccrovitz/US-IN-SB/US-IN",
    "betmgm":     "https://playmgmsports.onelink.me/TkMx?af_xp=custom&pid=RAF&c=BMGM_RAF&af_web_dp=https%3A%2F%2Fwww.betmgm.com%2Fen%2Fmobileportal%2Finvitefriendssignup%3FinvID%3D22495798",
}
FANDUEL_RAF = PARTNER_BOOKS["fanduel"]
# Placeholder for the $9 World Cup product. Edit when the live URL exists.
WC_PRODUCT_LINK = "https://overlay-gray.vercel.app/world-cup"
WC_PRODUCT_PRICE = "$9"


def raf_link_for(book: str) -> str:
    """Return the affiliate link matching a sportsbook name (case-insensitive)."""
    if not book:
        return FANDUEL_RAF
    return PARTNER_BOOKS.get(book.lower().replace(" ", ""), FANDUEL_RAF)


def is_partner_book(book: str) -> bool:
    return bool(book) and book.lower().replace(" ", "") in PARTNER_BOOKS


# ─── MLB pick selection ──────────────────────────────────────────────────────

def _pick_get(p: dict, *keys, default=None):
    """Look up a value by any of the given keys (handles both source schemas)."""
    for k in keys:
        if p.get(k) is not None:
            return p.get(k)
    return default


def _pretty_market(p: dict) -> str:
    m = (_pick_get(p, "Market", "market") or "").lower()
    if m == "moneyline":
        return "ML"
    if m == "spread":
        line = _pick_get(p, "Spread", "line")
        if line is None:
            bl = p.get("BetLine")
            if bl is not None:
                try:
                    line = float(str(bl).replace("+", ""))
                except ValueError:
                    line = None
        if line is not None:
            return f"RL {line:+g}"
        return "RL"
    if m == "total":
        # Team field carries "OVER 8.5" or "UNDER 9.5" style strings already.
        return _pick_get(p, "Team", "team", default="TOTAL")
    return m.upper() or "?"


def _is_positive_why(why: str) -> bool:
    """Only surface model commentary when it reads as confidence, not hedging."""
    if not why:
        return False
    lower = why.lower()
    bad = ("disagree", "lower confidence", "low confidence", "uncertain", "split")
    return not any(b in lower for b in bad)


def _label_pick(p: dict) -> str:
    team = _pick_get(p, "Team", "team", default="?")
    market = (_pick_get(p, "Market", "market") or "").lower()
    if market == "total":
        opp = _pick_get(p, "Opponent", "matchup", default="")
        return f"{team}  ({opp})"
    market_str = _pretty_market(p)
    return f"{team} {market_str}".strip()


def pick_of_day_mlb(picks_path: Path, top: int = 5,
                    partner_only: bool = True,
                    book: Optional[str] = None) -> list[dict]:
    """Return today's top MLB picks sorted by edge.

    partner_only=True restricts to picks where the best price is at one of
    Anthony's RAF-linked partner books (FanDuel / DraftKings / BetMGM), so the
    receipt and the affiliate link in the tweet point to the same place.
    book=<name> narrows further to a single book.
    """
    if not picks_path.exists():
        return []
    try:
        picks = json.loads(picks_path.read_text())
    except json.JSONDecodeError:
        return []
    picks = [p for p in picks if p.get("BestOdds") is not None]
    if book:
        target = book.lower().replace(" ", "")
        picks = [p for p in picks
                 if (p.get("Sportsbook") or "").lower().replace(" ", "") == target]
    elif partner_only:
        picks = [p for p in picks if is_partner_book(p.get("Sportsbook") or "")]

    def pp_edge(p: dict) -> float:
        return (p.get("ModelProb") or 0) - (p.get("ImpliedProb") or 0)

    # Only keep genuine +EV plays; sort by the gap we're going to show in the tweet.
    picks = [p for p in picks if pp_edge(p) > 0]
    picks.sort(key=pp_edge, reverse=True)
    return picks[:top]


# ─── Personal bankroll math ──────────────────────────────────────────────────

def running_record(picks: list[dict], days: int = 30) -> dict:
    """Compute running W/L and $ P&L across recent settled personal bets."""
    from datetime import datetime, timedelta
    cutoff = datetime.now().date() - timedelta(days=days)
    settled = [
        p for p in picks
        if p.get("result") in ("win", "loss", "push")
        and _parse_date(p.get("date")) >= cutoff
    ]
    w = sum(1 for p in settled if p["result"] == "win")
    l = sum(1 for p in settled if p["result"] == "loss")
    push = sum(1 for p in settled if p["result"] == "push")
    pl = sum(float(p.get("profit_dollars") or 0) for p in settled)
    return {"wins": w, "losses": l, "pushes": push, "pnl": pl, "days_active": days}


def _parse_date(s: Optional[str]):
    from datetime import datetime, date
    if not s:
        return date(1970, 1, 1)
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return date(1970, 1, 1)


# ─── Pre-game content ────────────────────────────────────────────────────────

def format_pre_game(pick: dict, stake: float, raf_link: str = FANDUEL_RAF,
                    book: str = "FanDuel") -> dict:
    """Build the pre-game tweet + a video script the user can read aloud."""
    label = _label_pick(pick)
    odds = int(pick.get("BestOdds") or 0)
    model_prob = float(pick.get("ModelProb") or 0) * 100
    implied = float(pick.get("ImpliedProb") or 0) * 100
    edge_pp = model_prob - implied if implied else 0
    matchup = f"{pick.get('Team','')} vs {pick.get('Opponent','')}"
    why = (pick.get("Why") or "").strip()

    tweet = (
        f"Today's bet 🎯  {label}  ({odds:+d}) at {book}\n"
        f"My model has it {model_prob:.0f}% to hit, market is pricing {implied:.0f}% — "
        f"that's a {edge_pp:.1f}-pt edge.\n"
        f"${stake:.0f} in. Receipt at the end of the night.\n"
        f"👉 {raf_link}"
    )

    script = (
        f"What's up. Today my model loves {label} at {odds:+d}.\n\n"
        f"Here's the read: it thinks they hit {model_prob:.0f} percent of the time, "
        f"but the sportsbook is only pricing it at {implied:.0f}. "
        f"That's a {edge_pp:.0f}-point edge — those don't come around often.\n\n"
    )
    if _is_positive_why(why):
        script += f"Model note: {why}\n\n"
    script += (
        f"I'm putting ${stake:.0f} of my own money on this at {book}. "
        f"Win or lose, I'll show the receipt tonight.\n\n"
        f"Link to follow along is in my bio."
    )
    return {"tweet": tweet, "script": script, "matchup": matchup}


# ─── Post-game content ───────────────────────────────────────────────────────

def format_post_game(pick: dict, running: dict, raf_link: str = FANDUEL_RAF) -> dict:
    """Build the post-game tweet + reaction video script."""
    label = _label_pick(pick)
    result = (pick.get("result") or "").lower()
    profit = float(pick.get("profit_dollars") or 0)
    stake = float(pick.get("stake_dollars") or pick.get("stake") or 0)
    pnl_running = running.get("pnl", 0)
    record = f"{running.get('wins',0)}-{running.get('losses',0)}"
    push = running.get("pushes", 0)
    if push:
        record += f"-{push}"

    if result == "win":
        emoji, sign, status = "✅", "+", "cashed"
    elif result == "loss":
        emoji, sign, status = "❌", "-", "lost"
    else:
        emoji, sign, status = "↔️", "", "pushed"
    pnl_sign = "+" if pnl_running >= 0 else "-"

    tweet = (
        f"{label}  {status}  {emoji}  {sign}${abs(profit):.0f}\n"
        f"Running: {record}  ·  {pnl_sign}${abs(pnl_running):.0f} over {running.get('days_active',30)} days\n"
        f"No chasing. Tomorrow at 11am.\n"
        f"👉 {raf_link}"
    )

    if result == "win":
        script = (
            f"{label} cashed. Up ${profit:.0f} on the day.\n\n"
            f"Running record is {record}, {pnl_sign}${abs(pnl_running):.0f} since I started posting these.\n\n"
            f"Tomorrow's bet drops at 11am. Bio link if you want to tail."
        )
    elif result == "loss":
        script = (
            f"{label} lost. Down ${abs(profit):.0f}.\n\n"
            f"That's the game — I'm posting the losses too because if I only show the wins, "
            f"none of this means anything.\n\n"
            f"Running: {record}, {pnl_sign}${abs(pnl_running):.0f}. No chase. Back tomorrow."
        )
    else:
        script = (
            f"{label} pushed. Stake back, no damage.\n\n"
            f"Still sitting at {record}, {pnl_sign}${abs(pnl_running):.0f}. Back tomorrow."
        )
    return {"tweet": tweet, "script": script}


# ─── World Cup content ───────────────────────────────────────────────────────

def _today_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def wc_match_of_day(fixtures_path: Path, date_str: Optional[str] = None) -> Optional[dict]:
    """Return the most interesting WC fixture today by model conviction or upset risk."""
    if not fixtures_path.exists():
        return None
    try:
        fixtures = json.loads(fixtures_path.read_text())
    except json.JSONDecodeError:
        return None
    date_str = date_str or _today_str()
    today = [f for f in fixtures if f.get("date") == date_str]
    if not today:
        # Fall back to next available match day.
        future = sorted(
            (f for f in fixtures if (f.get("date") or "") >= date_str),
            key=lambda f: f.get("date") or "9999",
        )
        if not future:
            return None
        next_day = future[0]["date"]
        today = [f for f in fixtures if f.get("date") == next_day]

    def score(f: dict) -> float:
        m = f.get("model", {})
        # Highest absolute conviction (the matchup most asymmetric vs a coin flip).
        return max(m.get("home_win", 0), m.get("away_win", 0), m.get("draw", 0))

    today.sort(key=score, reverse=True)
    return today[0]


def format_wc_post(match: dict, product_link: str = WC_PRODUCT_LINK,
                   price: str = WC_PRODUCT_PRICE) -> dict:
    """Build a World Cup tweet + video script with a $9 product CTA."""
    home, away = match["home"], match["away"]
    m = match.get("model", {})
    hw, aw, dw = m.get("home_win", 0) * 100, m.get("away_win", 0) * 100, m.get("draw", 0) * 100
    o25 = m.get("over_2_5", 0) * 100
    btts = m.get("btts", 0) * 100
    top_score = (match.get("top_scores") or [{}])[0]
    score_str = top_score.get("score", "—")
    score_prob = (top_score.get("prob") or 0) * 100
    group = match.get("group") or ""
    round_ = match.get("round") or ""
    fav = home if hw >= aw else away
    fav_prob = max(hw, aw)
    city = (match.get("context") or {}).get("city", "")

    tweet = (
        f"🌍 World Cup today: {home} vs {away}  ({round_} · Group {group})\n"
        f"My model: {home} {hw:.0f}% / Draw {dw:.0f}% / {away} {aw:.0f}%\n"
        f"Most likely score: {score_str} ({score_prob:.0f}%)  ·  O2.5 {o25:.0f}%  ·  BTTS {btts:.0f}%\n"
        f"Full 20k-sim model for every match → {price}  👇\n"
        f"{product_link}"
    )

    script = (
        f"World Cup match of the day: {home} versus {away}"
        f"{' in ' + city if city else ''}.\n\n"
        f"My model ran 20,000 simulations on this one. It has {fav} winning "
        f"{fav_prob:.0f} percent of the time, with the most likely scoreline at {score_str}.\n\n"
        f"Over 2.5 goals hits {o25:.0f} percent, both teams to score {btts:.0f} percent.\n\n"
        f"I'm running these sims on every World Cup match all summer. Full board, "
        f"every fixture, every prop — {price} flat. Link's in bio."
    )

    return {"tweet": tweet, "script": script, "matchup": f"{home} vs {away}"}

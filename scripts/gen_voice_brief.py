#!/usr/bin/env python3
"""
gen_voice_brief.py — Daily content scaffold for Anthony.

Reads today's picks + season record + June Challenge state,
writes a short brief to output/briefs/voice_YYYYMMDD.md.

NOT AI captions. A starting point you edit in your own voice.

Usage:
    python3 scripts/gen_voice_brief.py             # today
    python3 scripts/gen_voice_brief.py 20260602    # specific date
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT        = Path(__file__).parent.parent
_STATS_FILE  = _ROOT / "data/public_stats.json"
_PICKS_ROOT  = _ROOT / "output/picks"
_BRIEFS_DIR  = _ROOT / "output/briefs"
_CHALLENGE   = _ROOT / "data/june_challenge/state.json"

_SKIP_MARKETS = {"f5_total", "nrfi"}

_SPORT_LABELS = {
    "baseball_mlb":           "MLB",
    "mlb":                    "MLB",
    "basketball_nba":         "NBA",
    "nba":                    "NBA",
    "basketball_wnba":        "WNBA",
    "wnba":                   "WNBA",
    "icehockey_nhl":          "NHL",
    "nhl":                    "NHL",
    "tennis_atp_french_open": "French Open (ATP)",
    "tennis_wta_french_open": "French Open (WTA)",
    "soccer_fifa_world_cup":  "World Cup",
    "soccer_epl":             "EPL",
    "soccer_spain_la_liga":   "La Liga",
    "soccer_italy_serie_a":   "Serie A",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_usa_mls":         "MLS",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _pct(v: float) -> str:
    return f"{v * 100:.1f}%" if v < 2 else f"{v:.1f}%"


def _odds_str(odds: int | float) -> str:
    odds = int(odds)
    return f"+{odds}" if odds >= 0 else str(odds)


def _fmt_odds(odds: int | float) -> str:
    return _odds_str(odds)


def _load_stats() -> dict:
    if _STATS_FILE.exists():
        return json.loads(_STATS_FILE.read_text())
    return {}


def _load_challenge() -> dict:
    if _CHALLENGE.exists():
        return json.loads(_CHALLENGE.read_text())
    return {}


def _load_picks(ts: str) -> list[dict]:
    """Return picks for ts from output folders + pnl ledger (merged, pnl is authoritative for card_pick)."""
    date_str = f"{ts[:4]}-{ts[4:6]}-{ts[6:]}"

    # 1) Load from output folders (has model notes, game times, etc.)
    output_picks: dict[str, dict] = {}
    for sport_dir in sorted(_PICKS_ROOT.iterdir()):
        if not sport_dir.is_dir():
            continue
        pf = sport_dir / ts / "picks.json"
        if not pf.exists():
            continue
        try:
            raw = json.loads(pf.read_text())
            picks = raw if isinstance(raw, list) else raw.get("picks", [])
            for p in picks:
                p["_sport_dir"] = sport_dir.name
                key = (sport_dir.name,
                       str(p.get("team") or p.get("Team") or ""),
                       str(p.get("market") or p.get("Market") or ""))
                output_picks[str(key)] = p
        except Exception:
            pass

    # 2) Load card_pick flags from pnl ledger (authoritative)
    pnl_file = _ROOT / "data/pnl/picks.json"
    pnl_card: list[dict] = []
    if pnl_file.exists():
        try:
            raw = json.loads(pnl_file.read_text())
            all_pnl = raw if isinstance(raw, list) else raw.get("picks", [])
            for p in all_pnl:
                if p.get("date") == date_str and p.get("card_pick") is True:
                    p.setdefault("_sport_dir", p.get("sport", ""))
                    pnl_card.append(p)
        except Exception:
            pass

    # Merge: prefer pnl entries (they have card_pick=True) and enrich with notes from output
    if pnl_card:
        return pnl_card

    # Fallback: return all output picks
    return list(output_picks.values())


def _top_pick(picks: list[dict]) -> dict | None:
    """
    Highest-edge CONFIRMED card pick (card_pick must be explicitly True).
    Prefers edge >= 5 but falls back to best available card pick if none qualify.
    card_pick=True already means it was curated — hard edge floor adds no safety here.
    """
    all_card: list[tuple[float, dict]] = []
    for p in picks:
        mkt = (p.get("market") or p.get("Market") or "").lower()
        if mkt in _SKIP_MARKETS:
            continue
        card = p.get("card_pick") or p.get("CardPick")
        if card is not True:
            continue
        edge = float(p.get("edge_pct") or p.get("Edge") or p.get("edge") or 0)
        all_card.append((edge, p))
    if not all_card:
        return None
    all_card.sort(key=lambda x: x[0], reverse=True)
    return all_card[0][1]


def _all_card_picks(picks: list[dict]) -> list[dict]:
    """All confirmed card picks sorted by edge descending."""
    result = []
    for p in picks:
        mkt = (p.get("market") or p.get("Market") or "").lower()
        if mkt in _SKIP_MARKETS:
            continue
        card = p.get("card_pick") or p.get("CardPick")
        if card is not True:
            continue
        edge = float(p.get("edge_pct") or p.get("Edge") or p.get("edge") or 0)
        result.append((edge, p))
    result.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in result]


def _pick_notes(p: dict) -> list[str]:
    """Extract model notes bullets from pick dict."""
    raw = p.get("notes") or []
    if isinstance(raw, str):
        raw = [raw]
    return [n for n in raw if n]


def _implied_from_odds(odds: float) -> float:
    """American odds → implied probability (0-1)."""
    if not odds or odds == 0:
        return 0.0
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def _sport_label(p: dict) -> str:
    sd = p.get("_sport_dir", "")
    return _SPORT_LABELS.get(sd, sd.replace("_", " ").title())


def _game_time_str(p: dict) -> str:
    ct = p.get("commence_time") or p.get("commence") or p.get("CommenceTime") or ""
    if not ct:
        return ""
    try:
        dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        # Convert UTC → ET (rough: -4 in summer)
        from datetime import timezone, timedelta
        et = dt.astimezone(timezone(timedelta(hours=-4)))
        return et.strftime("%I:%M %p ET").lstrip("0")
    except Exception:
        return ""


def _matchup_str(p: dict) -> str:
    m = p.get("matchup") or p.get("Matchup") or ""
    # NHL picks have full matchup in notes[0] sometimes
    if not m:
        notes = _pick_notes(p)
        if notes and "@" in notes[0]:
            m = notes[0].split(":")[0].strip()
    return m


# ── sections ──────────────────────────────────────────────────────────────────

def _challenge_top_pick(challenge: dict, ts: str) -> dict | None:
    """Build a pseudo-pick dict from today's June Challenge bet for use in tweet/ig scaffolds."""
    if not challenge:
        return None
    today_str = datetime.strptime(ts, "%Y%m%d").strftime("%Y-%m-%d")
    bet = next((b for b in challenge.get("bets", []) if b.get("date") == today_str), None)
    if not bet:
        return None
    # Normalise to picks format
    return {
        "team":        bet.get("player") or bet.get("team") or "",
        "matchup":     bet.get("opponent") or "",
        "market":      bet.get("market") or "total",
        "odds":        bet.get("odds", 0),
        "edge_pct":    bet.get("edge", 0),
        "model_prob":  bet.get("model_prob", 0),
        "market_prob": bet.get("market_prob", 0),
        "sportsbook":  bet.get("book") or "",
        "notes":       bet.get("notes") or [],
        "_sport_dir":  bet.get("sport") or "",
        "_tournament": bet.get("tournament") or "",
    }


def _section_card_picks(all_picks: list[dict]) -> str:
    """List all today's card picks with market, direction, odds, edge."""
    if not all_picks:
        return "No card picks yet — run: python3 chef.py morning"
    lines = []
    for p in all_picks:
        team   = p.get("team") or p.get("Team") or p.get("player") or ""
        mkt    = (p.get("market") or p.get("Market") or "").upper()
        matchup = _matchup_str(p)
        odds   = int(float(p.get("odds") or p.get("BestOdds") or 0))
        edge   = float(p.get("edge_pct") or p.get("Edge") or p.get("edge") or 0)
        sport  = _sport_label(p)
        book   = p.get("sportsbook") or p.get("Sportsbook") or ""
        book_s = f" @ {book}" if book else ""
        match_s = f"  {matchup}" if matchup else ""
        lines.append(f"  [{sport} {mkt}]  {team} {_fmt_odds(odds)}{book_s}  +{edge:.1f}% edge{match_s}")
    return "\n".join(lines)


def _section_numbers(stats: dict, challenge: dict) -> str:
    summ = stats.get("summary", {})
    by_mkt = stats.get("by_market", {})
    totals = by_mkt.get("total", {})

    s_w   = summ.get("wins", 0)
    s_l   = summ.get("losses", 0)
    s_wr  = summ.get("win_rate", 0)
    s_u   = summ.get("units_profit", 0)
    s_roi = summ.get("roi", 0)

    t_w   = totals.get("wins", 0)
    t_l   = totals.get("losses", 0)
    t_wr  = totals.get("win_rate", 0)
    t_u   = totals.get("units_profit", t_w - t_l)
    t_roi = totals.get("roi", 0)

    lines = [
        "YOUR NUMBERS",
        f"  Totals    {t_w}-{t_l} ({_pct(t_wr)})  {t_u:+.1f}u  {_pct(t_roi)} ROI",
        f"  Season    {s_w}-{s_l} ({_pct(s_wr)})  {s_u:+.1f}u",
    ]

    if challenge:
        bk    = challenge.get("bankroll", 200)
        start = 200.0
        gain  = bk - start
        rec   = challenge.get("record", {})
        cw    = rec.get("w", 0)
        cl    = rec.get("l", 0)
        bets  = challenge.get("bets", [])
        day   = len([b for b in bets if b.get("result") is not None]) + 1
        lines.append(
            f"  Challenge  Day {day} · {cw}-{cl} · ${bk:.2f} ({gain:+.2f})"
        )

    return "\n".join(lines)


def _section_tweet(top: dict, stats: dict) -> str:
    by_mkt = stats.get("by_market", {})
    totals = by_mkt.get("total", {})
    t_w  = totals.get("wins", 0)
    t_l  = totals.get("losses", 0)
    t_wr = totals.get("win_rate", 0)

    team    = top.get("team") or top.get("Team") or top.get("player") or "Pick"
    matchup = _matchup_str(top)
    odds    = int(float(top.get("odds") or top.get("BestOdds") or 0))
    edge    = float(top.get("edge_pct") or top.get("Edge") or top.get("edge") or 0)
    mprob   = float(top.get("model_prob") or top.get("ModelProb") or 0)
    mktprob = float(top.get("market_prob") or top.get("implied_prob") or 0)
    book    = top.get("sportsbook") or top.get("Sportsbook") or ""
    sport   = _sport_label(top)
    gtime   = _game_time_str(top)
    notes   = _pick_notes(top)

    # Model prob: normalize to percentage
    if mprob > 0 and mprob < 1:
        mprob *= 100
    # Market prob fallback: derive from odds when not stored
    if mktprob == 0 and odds != 0:
        mktprob = _implied_from_odds(float(odds)) * 100
    elif mktprob > 0 and mktprob < 1:
        mktprob *= 100

    # Reasoning line — pull first useful note or fallback
    reasoning = ""
    for n in notes[:2]:
        if any(kw in n.lower() for kw in ["gaa", "sv%", "era", "fip", "elo", "win prob", "proj"]):
            reasoning = n
            break
    if not reasoning and notes:
        reasoning = notes[0]

    time_str = f" · {gtime}" if gtime else ""
    matchup_str = f" — {matchup}" if matchup else ""
    book_str = f" @ {book}" if book else ""

    lines = [
        f"[EDIT BEFORE POSTING — use your own words]",
        "",
        f"{sport}: {team} {_fmt_odds(odds)}{matchup_str}{time_str}",
        "",
    ]
    if reasoning:
        lines.append(f"{reasoning}")
        lines.append("")
    lines += [
        f"Model: {mprob:.0f}% · Market: {mktprob:.0f}% · Edge: {edge:+.1f}%{book_str}",
        "",
        f"Totals model: {t_w}-{t_l} ({_pct(t_wr)}). Every pick logged before game time.",
        "→ overlay-gray.vercel.app",
    ]
    return "\n".join(lines)


def _section_instagram(top: dict) -> str:
    team    = top.get("team") or top.get("Team") or top.get("player") or "Pick"
    matchup = _matchup_str(top)
    odds    = int(float(top.get("odds") or top.get("BestOdds") or 0))
    edge    = float(top.get("edge_pct") or top.get("Edge") or top.get("edge") or 0)
    mprob   = float(top.get("model_prob") or top.get("ModelProb") or 0)
    mktprob = float(top.get("market_prob") or top.get("implied_prob") or 0)
    sport   = _sport_label(top)
    notes   = _pick_notes(top)

    if mprob > 0 and mprob < 1:
        mprob *= 100
    if mktprob == 0 and odds != 0:
        mktprob = _implied_from_odds(float(odds)) * 100
    elif mktprob > 0 and mktprob < 1:
        mktprob *= 100

    # One-line reasoning from notes
    reason = ""
    for n in notes[:2]:
        if any(kw in n.lower() for kw in ["gaa", "sv%", "era", "elo", "win prob"]):
            reason = n
            break
    if not reason and notes:
        reason = notes[0]

    matchup_str = f" · {matchup}" if matchup else ""
    lines = [
        "[EDIT — 2-3 lines, your voice, no hashtags]",
        "",
        f"{team} {_fmt_odds(odds)}{matchup_str}",
    ]
    if reason:
        lines.append("")
        lines.append(reason)
    lines += [
        "",
        f"Model: {mprob:.0f}% | Market: {mktprob:.0f}% | Edge: {edge:+.1f}%",
        "",
        "Record in bio.",
    ]
    return "\n".join(lines)


def _section_outreach(top: dict, stats: dict) -> str:
    by_mkt = stats.get("by_market", {})
    totals = by_mkt.get("total", {})
    t_w  = totals.get("wins", 0)
    t_l  = totals.get("losses", 0)
    t_wr = totals.get("win_rate", 0)

    team    = top.get("team") or top.get("Team") or top.get("player") or "the pick"
    matchup = _matchup_str(top)
    sport   = _sport_label(top)
    notes   = _pick_notes(top)

    # Pick the most quotable fact from notes
    fact = ""
    for n in notes:
        if any(kw in n.lower() for kw in ["gaa", "sv%", "era", "fip", "elo", "win prob", "proj"]):
            # Shorten it
            fact = n.split("|")[0].strip() if "|" in n else n
            break
    if not fact and notes:
        fact = notes[0].split("|")[0].strip()

    matchup_search = matchup.replace(" @ ", " vs ") if matchup else sport
    # For totals/direction picks (OVER/UNDER), use teams from matchup not direction
    is_direction_pick = team.upper().startswith(("OVER ", "UNDER ")) if team else False
    if is_direction_pick and matchup and " @ " in matchup:
        away_team, home_team = matchup.split(" @ ", 1)
        team_search = away_team.strip().split()[-1]   # last word of away team (e.g. "Cubs")
    elif team and not is_direction_pick:
        team_search = team.split()[0]
    else:
        team_search = sport

    lines = [
        "— Do this, not just posting —",
        "",
        "SEARCH TWITTER (find existing conversations):",
        f'  "{matchup_search} tonight"',
        f'  "{team_search} game"',
        f'  "{sport} picks tonight"',
        "",
        "REPLY WITH (a fact, not your pick, no link):",
    ]
    if fact:
        lines.append(f'  "{fact}"')
    else:
        lines.append(f'  Share one stat about {team} from a quick search.')
    lines += [
        "",
        "DM ANYONE WHO LIKES / REPLIES:",
        f'  "Hey — I run an ML model on sports totals, logged before game time.',
        f'   Totals model: {t_w}-{t_l} ({_pct(t_wr)}) this season.',
        '   Want today\'s slate for free? Happy to send it."',
        "",
        "TARGET: 3 DM conversations → 1 paying sub by Day 14.",
    ]
    return "\n".join(lines)


def _section_challenge(challenge: dict, ts: str) -> str:
    if not challenge:
        return "June Challenge state not found."

    bets = challenge.get("bets", [])
    today_str = datetime.strptime(ts, "%Y%m%d").strftime("%Y-%m-%d")
    today_bet = next((b for b in bets if b.get("date") == today_str), None)
    bk   = challenge.get("bankroll", 200)
    rec  = challenge.get("record", {})
    cw   = rec.get("w", 0)
    cl   = rec.get("l", 0)

    if not today_bet:
        return (
            "No bet registered for today yet.\n"
            "Run:  python3 chef.py morning\n"
            "      python3 chef.py challenge add"
        )

    day    = today_bet.get("day", "?")
    player = today_bet.get("player") or today_bet.get("team") or "Pick"
    tour   = today_bet.get("tournament") or today_bet.get("sport") or ""
    odds   = int(float(today_bet.get("odds", 0)))
    book   = today_bet.get("book") or "your book"
    unit   = float(today_bet.get("unit", 20))

    # Card path
    sport_dir = today_bet.get("sport", "")
    card_dir  = _PICKS_ROOT / sport_dir / ts
    card_file = card_dir / f"june_challenge_day{day}_card.png"
    card_str  = str(card_file.relative_to(_ROOT)) if card_file.exists() else f"(not yet generated — run chef.py morning)"

    # Game time
    top_picks = _load_picks(ts)
    gtime = ""
    for p in top_picks:
        t = p.get("team") or p.get("Team") or p.get("player") or ""
        if player.lower() in t.lower() or t.lower() in player.lower():
            gtime = _game_time_str(p)
            break

    bet_line = f"${unit:.0f} {player} {_fmt_odds(odds)} @ {book}"
    if gtime:
        bet_line += f"  (before {gtime})"

    lines = [
        f"DAY {day} · {cw}-{cl} record · ${bk:.2f} bankroll",
        "",
        f"CARD:  {card_str}",
        f'POST:  "Day {day} — {player} {_fmt_odds(odds)}{(" · " + tour) if tour else ""}.',
        f'        ${bk:.2f} on the line. {cw}-{cl} so far."',
        "",
        f"BET:   {bet_line}",
    ]
    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def build_voice_brief(brief_date: date | None = None) -> Path:
    d  = brief_date or date.today()
    ts = d.strftime("%Y%m%d")

    stats     = _load_stats()
    challenge = _load_challenge()
    picks     = _load_picks(ts)
    all_card  = _all_card_picks(picks)

    # For tweet/instagram scaffolds: prefer the June Challenge bet of the day
    # (it's already been curated) — fall back to highest-edge card pick
    tweet_pick = _challenge_top_pick(challenge, ts) or _top_pick(picks)

    sep    = "━" * 44
    date_s = d.strftime("%B %d, %Y").upper()

    lines: list[str] = [
        sep,
        f"{date_s} — DAILY VOICE BRIEF",
        sep,
        "",
        _section_numbers(stats, challenge),
        "",
        f"{'─'*44}",
        f"TODAY'S CARD PICKS ({len(all_card)} picks)",
        f"{'─'*44}",
        _section_card_picks(all_card),
        "",
        f"{'─'*44}",
        "9AM TWEET  — edit before posting",
        f"{'─'*44}",
    ]

    if tweet_pick:
        lines.append(_section_tweet(tweet_pick, stats))
    else:
        lines.append("No picks yet — run: python3 chef.py morning")

    lines += [
        "",
        f"{'─'*44}",
        "INSTAGRAM CAPTION",
        f"{'─'*44}",
    ]
    if tweet_pick:
        lines.append(_section_instagram(tweet_pick))
    else:
        lines.append("(no picks yet)")

    lines += [
        "",
        f"{'─'*44}",
        "OUTREACH — do this, not just posting",
        f"{'─'*44}",
    ]
    if tweet_pick:
        lines.append(_section_outreach(tweet_pick, stats))
    else:
        lines.append("(run morning pipeline first)")

    lines += [
        "",
        f"{'─'*44}",
        "JUNE CHALLENGE — BET OF THE DAY",
        f"{'─'*44}",
        _section_challenge(challenge, ts),
        "",
        sep,
    ]

    out  = "\n".join(lines)
    _BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _BRIEFS_DIR / f"voice_{ts}.md"
    out_path.write_text(out)
    return out_path


if __name__ == "__main__":
    arg_ts = sys.argv[1] if len(sys.argv) > 1 else None
    if arg_ts:
        try:
            d = datetime.strptime(arg_ts, "%Y%m%d").date()
        except ValueError:
            print(f"Invalid date: {arg_ts}. Use YYYYMMDD.")
            sys.exit(1)
    else:
        d = date.today()

    path = build_voice_brief(d)
    print(f"Voice brief → {path}")
    print()
    print(path.read_text())

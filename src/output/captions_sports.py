"""
Caption generators for Tennis, Soccer, and PGA — Overlay.

Each sport returns 4 platform formats:
    instagram, x_twitter, reddit, tiktok_script

Output written by write_sport_captions() to out_dir/captions/{platform}.txt

Usage:
    from src.output.captions_sports import tennis_captions, soccer_captions, pga_captions, write_sport_captions
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

DISCLAIMER = "Not financial advice. Bet responsibly. 21+"

_APPROVED_BOOKS = {
    "fanduel", "draftkings", "betmgm", "betrivers",
    "caesars", "bet365", "espn bet", "espnbet", "fanatics",
}

# ── Rotating hashtag sets (day-of-week based) to avoid shadowban ─────────────

_TENNIS_TAG_SETS = [
    "#tennis #rolandgarros #sportsbetting #tennisbetting #ATP #freepicks",
    "#tennis #sportsbetting #tennisbetting #WTA #valuebet #edgebetting",
    "#tennis #rolandgarros #ATP #sportsbetting #bettingmodel #freepicks",
    "#tennis #tennisbetting #sportsbetting #sharpbetting #WTA #valuebet",
    "#tennis #ATP #WTA #sportsbetting #edgebetting #dailypicks",
    "#tennis #rolandgarros #sportsbetting #tennisbetting #freepicks #bettingmodel",
    "#tennis #sportsbetting #sharpbetting #tennisbetting #ATP #valuebet",
]

_SOCCER_TAG_SETS = [
    "#soccer #EPL #sportsbetting #soccerbetting #footballbetting #freepicks",
    "#soccer #LaLiga #sportsbetting #footballbetting #valuebet #edgebetting",
    "#soccer #SerieA #sportsbetting #soccerbetting #sharpbetting #freepicks",
    "#soccer #Bundesliga #sportsbetting #footballbetting #bettingmodel #freepicks",
    "#soccer #Ligue1 #sportsbetting #soccerbetting #valuebet #dailypicks",
    "#soccer #EPL #LaLiga #sportsbetting #footballbetting #edgebetting",
    "#soccer #sportsbetting #soccerbetting #footballbetting #freepicks #sharpbetting",
]

_PGA_TAG_SETS = [
    "#golf #PGA #sportsbetting #golfbetting #PGAChampionship #freepicks",
    "#golf #PGATour #sportsbetting #golfbetting #valuebet #edgebetting",
    "#golf #PGA #sportsbetting #golfbetting #sharpbetting #freepicks",
    "#golf #Masters #sportsbetting #golfbetting #bettingmodel #freepicks",
    "#golf #USOpen #sportsbetting #golfbetting #valuebet #dailypicks",
    "#golf #TheOpen #sportsbetting #golfbetting #edgebetting #freepicks",
    "#golf #PGATour #sportsbetting #golfbetting #sharpbetting #freepicks",
]


def _day_tags(tag_sets: list[str], d: date) -> str:
    return tag_sets[d.weekday() % len(tag_sets)]


# ── Shared helpers ────────────────────────────────────────────────────────────

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


def _filter_picks(picks: list[dict]) -> list[dict]:
    """Return positive-edge picks from approved books, sorted by edge desc."""
    out = [
        p for p in picks
        if float(p.get("edge_pct", 0) or 0) > 0
        and _is_approved_book(str(p.get("sportsbook", "") or ""))
    ]
    return sorted(out, key=lambda x: float(x.get("edge_pct", 0) or 0), reverse=True)


def _load_sport_record(sport_prefix: str) -> str:
    """Return 'W-L (WR%)' string from public_stats.json for a given sport prefix."""
    try:
        stats_path = Path("data/public_stats.json")
        if not stats_path.exists():
            return ""
        stats = json.loads(stats_path.read_text())
        by_sport = stats.get("by_sport", {})
        for key, val in by_sport.items():
            if sport_prefix in key.lower():
                w = val.get("wins", 0)
                l = val.get("losses", 0)
                n = w + l
                if n < 3:
                    return ""
                wr = round(w / n * 100, 1)
                return f"{w}-{l} ({wr}% WR)"
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# TENNIS
# ═══════════════════════════════════════════════════════════════════════════════

def tennis_captions(
    picks: list[dict],
    tournament: str,
    surface: str,
    card_date: date,
) -> dict[str, str]:
    """
    Generate captions for tennis picks.
    Returns {'instagram': str, 'x_twitter': str, 'reddit': str, 'tiktok_script': str}
    """
    top = _filter_picks(picks)
    record = _load_sport_record("tennis")
    tags = _day_tags(_TENNIS_TAG_SETS, card_date)
    dl = card_date.strftime("%b %d")
    dl_long = card_date.strftime("%B %d, %Y")
    surface_cap = surface.capitalize()
    n_edges = len(top)

    return {
        "instagram":     _tennis_ig(top, tournament, surface_cap, dl, record, tags),
        "x_twitter":     _tennis_x(top, tournament, surface_cap, dl, record, n_edges),
        "reddit":        _tennis_reddit(top, tournament, surface_cap, dl_long, record),
        "tiktok_script": _tennis_tiktok(top, tournament, surface_cap, dl),
    }


def _tennis_ig(
    top: list[dict], tournament: str, surface: str, dl: str, record: str, tags: str
) -> str:
    lines = [f"🎾 {tournament.upper()} — {dl} PICKS"]
    lines += ["", f"Elo model scanning today's {surface.lower()} court matches."]

    if top:
        best = top[0]
        player = best.get("team", "")
        odds   = _fmt_odds(best.get("odds"))
        edge   = _fmt_edge(best.get("edge_pct"))
        book   = (best.get("sportsbook") or "").title()
        matchup = best.get("matchup", "")
        lines += ["", "BEST BET", f"{player}  {odds} @ {book}", f"Model edge: {edge}"]
        if matchup:
            lines.append(matchup)

    if len(top) > 1:
        lines += ["", "Also liking:"]
        for p in top[1:3]:
            player = p.get("team", "")
            odds   = _fmt_odds(p.get("odds"))
            book   = (p.get("sportsbook") or "").title()
            edge   = _fmt_edge(p.get("edge_pct"))
            lines.append(f"- {player}  {odds} @ {book}  |  {edge}")

    if record:
        lines += ["", f"Tennis record: {record}"]

    lines += [
        "Picks logged before match time. Record in bio.",
        "",
        DISCLAIMER,
        "",
        tags,
    ]
    return "\n".join(lines)


def _tennis_x(
    top: list[dict], tournament: str, surface: str, dl: str, record: str, n_edges: int
) -> str:
    tweets = []

    if top:
        best   = top[0]
        player = best.get("team", "")
        odds   = _fmt_odds(best.get("odds"))
        book   = (best.get("sportsbook") or "").replace(" ", "")
        edge   = _fmt_edge(best.get("edge_pct"))
        t1 = (
            f"🎾 {tournament} picks — {dl}\n"
            f"Elo model found edge on {n_edges} match(es).\n"
            f"{player}  {odds} @{book}  edge: {edge}"
        )
        if record:
            t1 += f"\nRecord: {record}"
        t1 += f"\nGraded publicly.  {DISCLAIMER}  #tennis #sportsbetting"
        tweets.append(t1)

    if len(top) > 1:
        lines = ["Full card:"]
        for p in top[1:4]:
            player = p.get("team", "")
            odds   = _fmt_odds(p.get("odds"))
            book   = (p.get("sportsbook") or "").replace(" ", "")
            edge   = _fmt_edge(p.get("edge_pct"))
            lines.append(f"- {player}  {odds} @{book}  ({edge})")
        tweets.append("\n".join(lines))

    if not tweets:
        return f"🎾 {tournament} — {dl}\nNo edges meet threshold today. Watching {surface.lower()} court action.\n{DISCLAIMER}"

    return "\n\n---\n\n".join(tweets)


def _tennis_reddit(
    top: list[dict], tournament: str, surface: str, dl_long: str, record: str
) -> str:
    lines = [
        f"**Overlay Elo Model — {tournament} {dl_long}**",
        "",
        f"Surface: {surface}",
        "",
        (
            "Model methodology: Surface-specific Elo ratings built from ATP/WTA match history "
            "(Kovalchik 2016 / Angelini 2022 peer-reviewed framework). "
            "Ratings updated after every match. Edges calculated vs no-vig implied probability "
            "across FanDuel, DraftKings, BetMGM, Caesars, and Bet365."
        ),
        "",
        "---",
        "",
    ]

    if record:
        lines += [f"**Tennis record: {record}**", ""]

    if top:
        lines += [
            "**Edges today**",
            "",
            "| Match | Pick | Odds | Model Prob | Implied Prob | Edge | Book |",
            "|-------|------|------|------------|--------------|------|------|",
        ]
        for p in top:
            matchup    = p.get("matchup", "")
            player     = p.get("team", "")
            odds       = _fmt_odds(p.get("odds"))
            model_prob = p.get("model_prob")
            book       = p.get("sportsbook", "")
            edge       = _fmt_edge(p.get("edge_pct"))
            implied    = ""
            if model_prob:
                try:
                    o = float(p.get("odds", -110))
                    implied = f"{(100 / (100 + o) if o > 0 else abs(o) / (abs(o) + 100)) * 100:.1f}%"
                except Exception:
                    implied = ""
            mp_str = f"{float(model_prob)*100:.1f}%" if model_prob else ""
            lines.append(f"| {matchup} | {player} | {odds} | {mp_str} | {implied} | {edge} | {book} |")
        lines.append("")
    else:
        lines += ["No edges meet minimum threshold today.", ""]

    lines += [
        "---",
        "",
        "*All picks logged with timestamp before match start. Results posted daily.*",
        "",
        f"*{DISCLAIMER}*",
    ]
    return "\n".join(lines)


def _tennis_tiktok(
    top: list[dict], tournament: str, surface: str, dl: str
) -> str:
    best = top[0] if top else None
    player = best.get("team", "unknown player") if best else "no clear edge today"
    odds   = _fmt_odds(best.get("odds")) if best else ""
    edge   = _fmt_edge(best.get("edge_pct")) if best else ""
    book   = (best.get("sportsbook") or "").title() if best else ""

    script = f"""[TALKING HEAD — Tennis Picks {dl}]
[DURATION: 30-45 seconds]

[HOLD UP PHONE / STAND IN FRONT OF CAMERA]

HOOK (0-5s):
"My Elo model just found a {surface} court edge at {tournament}. Here's the pick."

[PAUSE]

ELO EXPLAINER (5-15s):
"So what's an Elo model? Think chess ratings — every tennis player gets a number
based on who they beat and how. Beat a top-10 guy, your number shoots up.
Lose to a qualifier, it tanks. My model tracks these ratings by surface,
because a clay-court Elo and a grass-court Elo are completely different numbers."

[PAUSE]

THE PICK (15-25s):
"Today's top play: {player} {odds} at {book}.
My model gives them a {edge} edge over the book's number.
That's meaningful on clay — it's a grind-it-out surface where Elo is most predictive."

[SHOW SCREEN — caption or pick card]

CTA (25-35s):
"Full card's in the caption. Every pick gets logged before match time —
you can verify the timestamp. Follow for the nightly recap."

[PAUSE]

OUTRO:
"Not financial advice. Bet responsibly. 21+."

[END]"""
    return script


# ═══════════════════════════════════════════════════════════════════════════════
# SOCCER
# ═══════════════════════════════════════════════════════════════════════════════

def soccer_captions(
    picks: list[dict],
    leagues_active: list[str],
    card_date: date,
) -> dict[str, str]:
    """
    Generate captions for soccer picks across one or more leagues.
    Returns {'instagram': str, 'x_twitter': str, 'reddit': str, 'tiktok_script': str}
    """
    top = _filter_picks(picks)
    record = _load_sport_record("soccer")
    tags = _day_tags(_SOCCER_TAG_SETS, card_date)
    dl = card_date.strftime("%b %d")
    dl_long = card_date.strftime("%B %d, %Y")
    leagues_str = " / ".join(leagues_active) if leagues_active else "Soccer"

    return {
        "instagram":     _soccer_ig(top, leagues_str, dl, record, tags),
        "x_twitter":     _soccer_x(top, leagues_str, dl, record),
        "reddit":        _soccer_reddit(top, leagues_active, dl_long, record),
        "tiktok_script": _soccer_tiktok(top, leagues_str, dl),
    }


def _soccer_ig(
    top: list[dict], leagues_str: str, dl: str, record: str, tags: str
) -> str:
    lines = [f"⚽ {leagues_str.upper()} — {dl} PICKS"]
    lines += ["", "Dixon-Coles model found today's best edges."]

    if top:
        best = top[0]
        team    = best.get("team", "")
        odds    = _fmt_odds(best.get("odds"))
        edge    = _fmt_edge(best.get("edge_pct"))
        book    = (best.get("sportsbook") or "").title()
        matchup = best.get("matchup", "")
        league  = (best.get("sport", "")).replace("soccer_", "").replace("_", " ").title()
        lines += ["", "BEST BET", f"{team}  {odds} @ {book}", f"Model edge: {edge}"]
        if matchup:
            lines.append(matchup)
        if league:
            lines.append(f"[{league}]")

    if len(top) > 1:
        lines += ["", "Also:"]
        for p in top[1:3]:
            team  = p.get("team", "")
            odds  = _fmt_odds(p.get("odds"))
            book  = (p.get("sportsbook") or "").title()
            edge  = _fmt_edge(p.get("edge_pct"))
            lines.append(f"- {team}  {odds} @ {book}  |  {edge}")

    if record:
        lines += ["", f"Soccer record: {record}"]

    lines += [
        "Picks logged before kickoff. Record in bio.",
        "",
        DISCLAIMER,
        "",
        tags,
    ]
    return "\n".join(lines)


def _soccer_x(
    top: list[dict], leagues_str: str, dl: str, record: str
) -> str:
    tweets = []

    if top:
        best  = top[0]
        team  = best.get("team", "")
        odds  = _fmt_odds(best.get("odds"))
        book  = (best.get("sportsbook") or "").replace(" ", "")
        edge  = _fmt_edge(best.get("edge_pct"))
        t1 = (
            f"⚽ {leagues_str} picks — {dl}\n"
            f"Dixon-Coles model.  {team}  {odds} @{book}  edge: {edge}"
        )
        if record:
            t1 += f"\nRecord: {record}"
        t1 += f"\nTrack record in bio.  {DISCLAIMER}  #soccer #sportsbetting"
        tweets.append(t1)

    if len(top) > 1:
        lines = ["Full card:"]
        for p in top[1:4]:
            team  = p.get("team", "")
            odds  = _fmt_odds(p.get("odds"))
            book  = (p.get("sportsbook") or "").replace(" ", "")
            edge  = _fmt_edge(p.get("edge_pct"))
            lines.append(f"- {team}  {odds} @{book}  ({edge})")
        tweets.append("\n".join(lines))

    if not tweets:
        return f"⚽ {leagues_str} — {dl}\nNo edges meet threshold today. Monitoring lines.\n{DISCLAIMER}"

    return "\n\n---\n\n".join(tweets)


def _soccer_reddit(
    top: list[dict], leagues_active: list[str], dl_long: str, record: str
) -> str:
    leagues_str = " / ".join(leagues_active) if leagues_active else "Soccer"
    lines = [
        f"**Overlay Dixon-Coles Model — {leagues_str} {dl_long}**",
        "",
        (
            "Model: Rolling Elo + 2-parameter Poisson (Dixon-Coles v2). "
            "Fit on 5 seasons of match data per league. "
            "Attack/defense ratings updated on a rolling 52-week window with recency weighting. "
            "Edges calculated as model probability minus no-vig implied probability."
        ),
        "",
        "---",
        "",
    ]

    if record:
        lines += [f"**Soccer record: {record}**", ""]

    if top:
        # Group by league (sport key)
        by_league: dict[str, list[dict]] = {}
        for p in top:
            sk = p.get("sport", "unknown")
            by_league.setdefault(sk, []).append(p)

        for sport_key, league_picks in by_league.items():
            league_name = sport_key.replace("soccer_", "").replace("_", " ").title()
            lines += [f"**{league_name}**", ""]
            lines += [
                "| Match | Bet | Odds | Model Prob | Edge | Book |",
                "|-------|-----|------|------------|------|------|",
            ]
            for p in league_picks:
                matchup    = p.get("matchup", "")
                team       = p.get("team", "")
                odds       = _fmt_odds(p.get("odds"))
                model_prob = p.get("model_prob")
                book       = p.get("sportsbook", "")
                edge       = _fmt_edge(p.get("edge_pct"))
                mp_str     = f"{float(model_prob)*100:.1f}%" if model_prob else ""
                lines.append(f"| {matchup} | {team} | {odds} | {mp_str} | {edge} | {book} |")
            lines.append("")
    else:
        lines += ["No edges meet minimum threshold today.", ""]

    lines += [
        "---",
        "",
        "*All picks logged before kickoff. Results posted same-day.*",
        "",
        f"*{DISCLAIMER}*",
    ]
    return "\n".join(lines)


def _soccer_tiktok(top: list[dict], leagues_str: str, dl: str) -> str:
    best   = top[0] if top else None
    team   = best.get("team", "no clear edge today") if best else "no clear edge today"
    odds   = _fmt_odds(best.get("odds")) if best else ""
    edge   = _fmt_edge(best.get("edge_pct")) if best else ""
    book   = (best.get("sportsbook") or "").title() if best else ""
    match  = best.get("matchup", "") if best else ""

    script = f"""[TALKING HEAD — Soccer Picks {dl}]
[DURATION: 30-45 seconds]

[HOLD UP PHONE / STAND IN FRONT OF CAMERA]

HOOK (0-5s):
"My Dixon-Coles soccer model just fired on a {leagues_str} match. Here's why."

[PAUSE]

MODEL EXPLAINER (5-18s):
"Dixon-Coles is a 2-param Poisson model — fancy way of saying it predicts
how many goals each team scores based on attack strength versus the other team's
defense. It was literally published in a stats journal in the 90s and it's still
one of the best soccer prediction models out there. I run it on 5 seasons of
match data, updated every week."

[PAUSE]

THE PICK (18-28s):
"Today's top play: {team} at {book}, {odds}.
{match}
Model gives {edge} edge over the book's number."

[SHOW SCREEN — caption or pick card]

CTA (28-38s):
"Full breakdown in the caption. Every pick timestamped before kickoff.
Graded publicly. Follow for results tonight."

[PAUSE]

OUTRO:
"Not financial advice. Bet responsibly. 21+."

[END]"""
    return script


# ═══════════════════════════════════════════════════════════════════════════════
# PGA
# ═══════════════════════════════════════════════════════════════════════════════

def pga_captions(
    picks: list[dict],
    tournament_name: str,
    card_date: date,
) -> dict[str, str]:
    """
    Generate captions for PGA Tour major picks.
    Returns {'instagram': str, 'x_twitter': str, 'reddit': str, 'tiktok_script': str}
    """
    top = _filter_picks(picks)
    record = _load_sport_record("golf")
    tags = _day_tags(_PGA_TAG_SETS, card_date)
    dl = card_date.strftime("%b %d")
    dl_long = card_date.strftime("%B %d, %Y")

    return {
        "instagram":     _pga_ig(top, tournament_name, dl, record, tags),
        "x_twitter":     _pga_x(top, tournament_name, dl, record),
        "reddit":        _pga_reddit(top, tournament_name, dl_long, record),
        "tiktok_script": _pga_tiktok(top, tournament_name, dl),
    }


def _pga_ig(
    top: list[dict], tournament: str, dl: str, record: str, tags: str
) -> str:
    lines = [f"⛳ {tournament.upper()} — {dl} OUTRIGHT VALUE"]
    lines += ["", "Strokes Gained model + Monte Carlo simulation found value."]

    if top:
        best   = top[0]
        player = best.get("team", "")
        odds   = _fmt_odds(best.get("odds"))
        edge   = _fmt_edge(best.get("edge_pct"))
        book   = (best.get("sportsbook") or "").title()
        lines += [
            "",
            "TOP VALUE PICK",
            f"{player}  {odds} @ {book}",
            f"Model edge: {edge}",
            "",
            "SG model weights: SG:Approach, SG:Off-the-Tee, SG:Around-the-Green",
        ]

    if len(top) > 1:
        lines += ["", "Also watching:"]
        for p in top[1:3]:
            player = p.get("team", "")
            odds   = _fmt_odds(p.get("odds"))
            book   = (p.get("sportsbook") or "").title()
            edge   = _fmt_edge(p.get("edge_pct"))
            lines.append(f"- {player}  {odds} @ {book}  |  {edge}")

    if record:
        lines += ["", f"Golf record: {record}"]

    lines += [
        "Picks logged before first round tee times. Record in bio.",
        "",
        DISCLAIMER,
        "",
        tags,
    ]
    return "\n".join(lines)


def _pga_x(
    top: list[dict], tournament: str, dl: str, record: str
) -> str:
    tweets = []
    n_edges = len(top)

    if top:
        best   = top[0]
        player = best.get("team", "")
        odds   = _fmt_odds(best.get("odds"))
        book   = (best.get("sportsbook") or "").replace(" ", "")
        edge   = _fmt_edge(best.get("edge_pct"))
        t1 = (
            f"⛳ {tournament} outright value — {dl}\n"
            f"SG model found {n_edges} edge(s).\n"
            f"{player} at {odds} ({edge}). @{book}"
        )
        if record:
            t1 += f"\nGolf record: {record}"
        t1 += f"\n{DISCLAIMER}  #golf #PGA #sportsbetting"
        tweets.append(t1)

    if len(top) > 1:
        lines = ["Full card:"]
        for p in top[1:4]:
            player = p.get("team", "")
            odds   = _fmt_odds(p.get("odds"))
            book   = (p.get("sportsbook") or "").replace(" ", "")
            edge   = _fmt_edge(p.get("edge_pct"))
            lines.append(f"- {player}  {odds} @{book}  ({edge})")
        tweets.append("\n".join(lines))

    if not tweets:
        return f"⛳ {tournament} — {dl}\nNo edges meet threshold. Watching the field.\n{DISCLAIMER}"

    return "\n\n---\n\n".join(tweets)


def _pga_reddit(
    top: list[dict], tournament: str, dl_long: str, record: str
) -> str:
    lines = [
        f"**Overlay SG Model — {tournament} {dl_long}**",
        "",
        (
            "Model: Strokes Gained (SG) composite + Monte Carlo tournament simulation. "
            "SG data sourced from PGA Tour ShotLink (last 24 months, recency-weighted). "
            "Course fit score calculated from historical SG:APP and SG:OTT at this venue. "
            "100k simulations per run. Edges vs book outright odds (no-vig conversion)."
        ),
        "",
        "---",
        "",
    ]

    if record:
        lines += [f"**Golf record: {record}**", ""]

    if top:
        lines += [
            "**Outright value picks**",
            "",
            "| Player | Odds | Model Prob | Book Implied | Edge | SG Rank | Book |",
            "|--------|------|------------|--------------|------|---------|------|",
        ]
        for p in top[:8]:
            player     = p.get("team", "")
            odds       = _fmt_odds(p.get("odds"))
            model_prob = p.get("model_prob")
            book       = p.get("sportsbook", "")
            edge       = _fmt_edge(p.get("edge_pct"))
            mp_str     = f"{float(model_prob)*100:.1f}%" if model_prob else ""
            implied    = ""
            if p.get("odds"):
                try:
                    o = float(p["odds"])
                    implied = f"{(100 / (100 + o) if o > 0 else abs(o) / (abs(o) + 100)) * 100:.1f}%"
                except Exception:
                    pass
            sg_rank = p.get("sg_rank", p.get("course_fit", ""))
            lines.append(f"| {player} | {odds} | {mp_str} | {implied} | {edge} | {sg_rank} | {book} |")
        lines.append("")
    else:
        lines += ["No edges meet minimum threshold. No picks today.", ""]

    lines += [
        "---",
        "",
        "*All picks logged before first tee time. Outrights graded after 72-hole final result.*",
        "",
        f"*{DISCLAIMER}*",
    ]
    return "\n".join(lines)


def _pga_tiktok(top: list[dict], tournament: str, dl: str) -> str:
    best   = top[0] if top else None
    player = best.get("team", "no clear value play today") if best else "no clear value play today"
    odds   = _fmt_odds(best.get("odds")) if best else ""
    edge   = _fmt_edge(best.get("edge_pct")) if best else ""
    book   = (best.get("sportsbook") or "").title() if best else ""

    script = f"""[TALKING HEAD — PGA Picks {dl}]
[DURATION: 35-50 seconds]

[HOLD UP PHONE / STAND IN FRONT OF CAMERA]

HOOK (0-5s):
"My strokes gained model found outright value at {tournament}. Here's the play."

[PAUSE]

SG EXPLAINER (5-20s):
"Strokes gained — this is how the PGA Tour actually measures player skill.
Instead of counting birdies, it measures how many strokes better or worse
you are than the tour average from the same shot location.
SG:Approach is the most predictive for major winners.
My model ranks every player in the field by their SG numbers
over the last two years, weights recent form heavier,
then runs 100,000 simulations of the tournament."

[PAUSE]

THE PICK (20-35s):
"Top value this week: {player} at {book}, {odds}.
{edge} edge over the book's implied probability.
This player's SG profile fits this course."

[SHOW SCREEN — pick card or stats screenshot]

CTA (35-45s):
"Full breakdown in the caption with the SG numbers.
I log every pick before the first tee time — you can verify the timestamp.
Follow for round-by-round updates."

[PAUSE]

OUTRO:
"Not financial advice. Bet responsibly. 21+."

[END]"""
    return script


# ═══════════════════════════════════════════════════════════════════════════════
# Writer
# ═══════════════════════════════════════════════════════════════════════════════

def wc_futures_captions(
    rows: list[dict],
    blend_weight: float,
    card_date: date,
    n_sims: int = 20000,
) -> dict[str, str]:
    """
    Content captions for the World Cup 2026 title-odds table (model vs market).
    `rows`: futures_2026.json "teams" — each {team, model, market, blend,
    reach_final, edge_pp}. Leads with the credible BLEND, features the biggest
    model-vs-Vegas disagreements as the hook. Returns the 4-platform dict.
    """
    def pct(x):
        return f"{x*100:.0f}%" if x is not None else "—"

    ranked = [r for r in rows if r.get("blend")]
    top = ranked[:8]
    # Disagreements among teams the market takes seriously (≥3%).
    serious = [r for r in rows if r.get("edge_pp") is not None and (r.get("market") or 0) >= 0.03]
    high = sorted(serious, key=lambda r: r["edge_pp"], reverse=True)[:2]   # model loves
    low = sorted(serious, key=lambda r: r["edge_pp"])[:2]                  # model fades
    dl_long = card_date.strftime("%B %d, %Y")

    # ── X / Twitter ──────────────────────────────────────────────────────────
    x = [f"🏆 WHO WINS WORLD CUP 2026? — {n_sims:,} model simulations\n"]
    for i, r in enumerate(top[:5], 1):
        x.append(f"{i}. {r['team']} — {pct(r['blend'])}")
    if high:
        h = high[0]
        x.append(f"\n📈 We're HIGHER than Vegas on {h['team']} ({pct(h['model'])} vs {pct(h['market'])})")
    if low:
        l = low[0]
        x.append(f"📉 LOWER on {l['team']} ({pct(l['model'])} vs {pct(l['market'])})")
    x.append(f"\nFull board + daily picks in bio. {DISCLAIMER}\n#WorldCup2026 #sportsbetting")
    x_twitter = "\n".join(x)

    # ── Instagram ────────────────────────────────────────────────────────────
    ig = [f"🏆 WORLD CUP 2026 — TITLE ODDS", f"Model vs Vegas · {n_sims:,} simulations", ""]
    ig.append("OUR NUMBER (model + market blend):")
    for i, r in enumerate(top, 1):
        ig.append(f"{i}. {r['team']:<16} {pct(r['blend'])}")
    if high or low:
        ig += ["", "WHERE WE DISAGREE WITH VEGAS 👀"]
        for r in high:
            ig.append(f"📈 {r['team']}: us {pct(r['model'])} / book {pct(r['market'])}")
        for r in low:
            ig.append(f"📉 {r['team']}: us {pct(r['model'])} / book {pct(r['market'])}")
    ig += ["", "Rolling Elo + Dixon-Coles, calibrated on 800+ tournament matches.",
           "Daily match picks + full board — link in bio.", "", DISCLAIMER,
           "#WorldCup2026 #WorldCup #soccer #sportsbetting #bettingtwitter"]
    instagram = "\n".join(ig)

    # ── Reddit (show your work) ──────────────────────────────────────────────
    rd = [f"**World Cup 2026 — title odds from {n_sims:,} Monte Carlo simulations (model vs market)**", ""]
    rd.append(f"Built a rolling-Elo + Dixon-Coles model (calibrated on 800+ tournament matches), "
              f"simulated the full 48-team bracket {n_sims:,} times, and blended the output with the "
              f"de-vigged market ({int(blend_weight*100)}% model / {int((1-blend_weight)*100)}% market). "
              f"As of {dl_long}:")
    rd += ["", "| # | Team | Our blend | Model | Market | Reach final |",
           "|---|------|-----------|-------|--------|-------------|"]
    for i, r in enumerate(top, 1):
        rd.append(f"| {i} | {r['team']} | {pct(r['blend'])} | {pct(r['model'])} | "
                  f"{pct(r['market'])} | {pct(r.get('reach_final'))} |")
    rd += ["", "**Where the model disagrees with the market (the interesting part):**"]
    for r in high:
        rd.append(f"- 📈 **{r['team']}** — model {pct(r['model'])} vs market {pct(r['market'])} (+{r['edge_pp']:.0f}pp)")
    for r in low:
        rd.append(f"- 📉 **{r['team']}** — model {pct(r['model'])} vs market {pct(r['market'])} ({r['edge_pp']:.0f}pp)")
    rd += ["", "Honest caveat: these are *probabilities*, not locks — the value is calibration, not "
           "claiming an edge over the closing line. CLV tracked publicly all tournament.", "", DISCLAIMER]
    reddit = "\n".join(rd)

    # ── TikTok / Shorts script ───────────────────────────────────────────────
    leader = top[0] if top else {"team": "?", "blend": 0}
    surprise = high[0] if high else leader
    tk = [
        "[HOOK] I simulated the World Cup 20,000 times. Here's who wins.",
        f"[BEAT] Favorite: {leader['team']} at {pct(leader['blend'])}.",
        f"[TURN] But here's where my model fights Vegas — it's way higher on "
        f"{surprise['team']} than the books are.",
        "[PROOF] Rolling Elo, Dixon-Coles, calibrated on 800 tournament games.",
        "[CTA] Full board + daily picks — follow, link in bio.",
    ]
    tiktok_script = "\n".join(tk)

    return {"instagram": instagram, "x_twitter": x_twitter,
            "reddit": reddit, "tiktok_script": tiktok_script}


def write_sport_captions(captions: dict[str, str], out_dir: Path) -> None:
    """Write captions dict to out_dir/captions/{platform}.txt"""
    cap_dir = out_dir / "captions"
    cap_dir.mkdir(parents=True, exist_ok=True)
    for platform, content in captions.items():
        (cap_dir / f"{platform}.txt").write_text(content, encoding="utf-8")

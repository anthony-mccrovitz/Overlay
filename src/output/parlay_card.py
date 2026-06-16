"""
Parlay card generator — builds 2–5 leg parlays from top edge picks.

Rules:
  1. All legs MUST come from the same sportsbook (parlays cannot span books).
  2. Highest edge_pct first, one leg per matchup (no SGP unless flagged).
  3. Renders an HTML card with team logos, book branding, and per-leg edge.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from src.output.card_html import (
    _NBA_HEX, _MLB_HEX, _NBA_ESPN_ABBR, _ESPN_ABBR,
    _nba_logo_url, _logo_url, _nba_team_abbr, _clean_book,
)

OUTPUT_DIR = Path("output/picks")


# ── Odds math ─────────────────────────────────────────────────────────────────

def american_to_decimal(odds: float) -> float:
    if odds >= 0:
        return odds / 100 + 1
    return 100 / abs(odds) + 1


def decimal_to_american(dec: float) -> int:
    if dec >= 2.0:
        return int(round((dec - 1) * 100))
    return int(round(-100 / (dec - 1)))


def parlay_odds(legs: list[dict]) -> int:
    decimal = 1.0
    for leg in legs:
        o = leg.get("odds") or leg.get("best_odds") or leg.get("BestOdds")
        if o is None:
            continue
        decimal *= american_to_decimal(float(o))
    return decimal_to_american(decimal)


def parlay_payout(legs: list[dict], stake: float = 100.0) -> float:
    decimal = 1.0
    for leg in legs:
        o = leg.get("odds") or leg.get("best_odds") or leg.get("BestOdds")
        if o is None:
            continue
        decimal *= american_to_decimal(float(o))
    return round((decimal - 1) * stake, 2)


# ── Leg selection ─────────────────────────────────────────────────────────────

def _normalize_book(name: str) -> str:
    """Normalize for grouping: 'DraftKings', 'draftkings', 'DRAFTKINGS' → 'draftkings'."""
    return (name or "").strip().lower()


def _best_book_legs(
    picks: list[dict],
    max_legs: int,
    min_edge_pct: float,
    allow_sgp: bool,
) -> list[dict]:
    """
    Pick the sportsbook with the most viable legs (≥ min_edge), then take its top legs
    by edge_pct, deduped by matchup (unless allow_sgp).
    """
    def _edge(p: dict) -> float:
        raw = float(p.get("edge_pct") or p.get("Edge", 0) or 0)
        return raw * 100 if raw < 1.0 and raw > 0 else raw

    # Parlay cards are DraftKings / FanDuel only — these books offer sign-up
    # bonuses that make the parlay content actionable for new bettors.
    _BONUS_BOOKS = {"draftkings", "fanduel"}

    qualified = [
        p for p in picks
        if _edge(p) >= min_edge_pct
        and _normalize_book(p.get("sportsbook") or p.get("Sportsbook") or p.get("book") or "") in _BONUS_BOOKS
    ]
    if not qualified:
        return []

    # Group by normalized book
    by_book: dict[str, list[dict]] = defaultdict(list)
    for p in qualified:
        book_raw = p.get("sportsbook") or p.get("Sportsbook") or p.get("book") or ""
        by_book[_normalize_book(book_raw)].append(p)

    _DIRECTIONAL = {"moneyline", "h2h", "spread", "spreads", "run_line"}

    def _base_team(p: dict) -> str:
        t = p.get("team") or p.get("Team") or ""
        return t.split(" +")[0].split(" -")[0].strip()

    # Score each book: pick the one with most deduped legs at ≥ min_edge
    def _legs_for_book(book_picks: list[dict]) -> list[dict]:
        sorted_picks = sorted(book_picks, key=_edge, reverse=True)
        seen_matchups: set[str] = set()
        seen_dir_teams: set[str] = set()  # one directional bet per team in SGP
        out = []
        for p in sorted_picks:
            matchup = (
                p.get("matchup") or p.get("Matchup")
                or f"{p.get('away_team','')}@{p.get('home_team','')}"
                or p.get("team", "")
            )
            market = (p.get("market") or p.get("Market") or "").lower()
            team   = _base_team(p)

            if not allow_sgp:
                if matchup in seen_matchups:
                    continue
                seen_matchups.add(matchup)
            else:
                # Multiple legs per game OK, but no spread+ML for the same team
                if market in _DIRECTIONAL and team in seen_dir_teams:
                    continue
                if market in _DIRECTIONAL:
                    seen_dir_teams.add(team)

            out.append(p)
            if len(out) >= max_legs:
                break
        return out

    def _score(legs_in: list[dict]) -> tuple[int, float]:
        total_edge = sum(_edge(p) for p in legs_in)
        return (len(legs_in), total_edge)

    best_legs: list[dict] = []
    for legs in by_book.values():
        candidate = _legs_for_book(legs)
        if _score(candidate) > _score(best_legs):
            best_legs = candidate

    return best_legs if len(best_legs) >= 2 else []


def build_parlay(
    picks: list[dict],
    max_legs: int = 4,
    min_edge_pct: float = 1.0,
    allow_sgp: bool = False,
) -> list[dict]:
    """
    Select parlay legs — all from the SAME sportsbook (DK/FanDuel only for sign-up bonus angle).
    Low edge floor (1%) because parlay content is about action + sign-up bonus use, not pure edge.
    """
    return _best_book_legs(picks, max_legs, min_edge_pct, allow_sgp)


# ── Card rendering ────────────────────────────────────────────────────────────

_BOOK_ACCENT = {
    "draftkings":   "#53D337",
    "fanduel":      "#1493FF",
    "betmgm":       "#B8862F",
    "caesars":      "#C8A85B",
    "hard rock bet":"#D32F2F",
    "hardrock":     "#D32F2F",
    "betrivers":    "#0097E6",
    "pointsbet":    "#FF0033",
    "espn bet":     "#D62828",
    "espnbet":      "#D62828",
    "fliff":        "#A435F0",
    "thescore bet": "#FF6B00",
    "thescorebet":  "#FF6B00",
}

# (display name, bg color, text color, referral bonus copy, referral link)
_BOOK_BRAND = {
    "fanduel":      ("FanDuel",       "#003087", "#FFFFFF",
                     "Sign up & bet $5+ → get $50 in Bonus Bets",
                     "https://fndl.co/92pew6d"),
    "draftkings":   ("DraftKings",    "#1B5E20", "#FFFFFF",
                     "Sign up & bet $5+ → get $50 in Bonus Bets",
                     "https://sportsbook.draftkings.com/r/sb/amccrovitz/US-IN-SB/US-IN"),
    "betmgm":       ("BetMGM",        "#1C1C1C", "#D4AF37",
                     "First Bet up to $1,500 back in Bonus Bets",
                     "https://playmgmsports.onelink.me/TkMx?af_xp=custom&pid=RAF&c=BMGM_RAF&af_ios_url=https%3A%2F%2Fwww.betmgm.com%2Fen%2Fmobileportal%2Finvitefriendssignup%3FinvID%3D22495798&af_android_url=https%3A%2F%2Fwww.betmgm.com%2Fen%2Fmobileportal%2Finvitefriendssignup%3FinvID%3D22495798&af_web_dp=https%3A%2F%2Fwww.betmgm.com%2Fen%2Fmobileportal%2Finvitefriendssignup%3FinvID%3D22495798&af_dp=playmgmsportswrp%3A%2F%2Fnavigation%3Fscheme%3Dhttps%26url%3Dwww.betmgm.com%2Fen%2Fmobileportal%2Finvitefriendssignup%3FinvID%3D22495798"),
    "caesars":      ("Caesars",       "#006241", "#C8A85B",
                     "First Bet back up to $1,000", ""),
    "hard rock bet":("Hard Rock Bet", "#C8102E", "#FFFFFF",
                     "Bet $5, Get $100 in Bonus Bets", ""),
    "hardrock":     ("Hard Rock Bet", "#C8102E", "#FFFFFF",
                     "Bet $5, Get $100 in Bonus Bets", ""),
    "betrivers":    ("BetRivers",     "#003087", "#FFFFFF",
                     "2nd Chance Bet up to $500", ""),
    "pointsbet":    ("PointsBet",     "#FF0033", "#FFFFFF",
                     "Up to $500 in Bonus Bets", ""),
    "espn bet":     ("ESPN BET",      "#D62828", "#FFFFFF",
                     "Bet $10, Get $150 in Bonus Bets", ""),
    "espnbet":      ("ESPN BET",      "#D62828", "#FFFFFF",
                     "Bet $10, Get $150 in Bonus Bets", ""),
    "fliff":        ("Fliff",         "#A435F0", "#FFFFFF",
                     "Get 100 Fliff Cash on signup", ""),
    "thescore bet": ("theScore Bet",  "#FF6B00", "#FFFFFF",
                     "Bet $1, Get $200 in Bonus Bets", ""),
    "thescorebet":  ("theScore Bet",  "#FF6B00", "#FFFFFF",
                     "Bet $1, Get $200 in Bonus Bets", ""),
    "bet365":       ("bet365",        "#027B5B", "#FFFFFF",
                     "Bet $5, Get $150 in Bonus Bets", ""),
}


def _book_wordmark_html(book: str, accent: str) -> str:
    """Brand-colored wordmark for the sportsbook — no external assets needed."""
    key = _normalize_book(book)
    if key in _BOOK_BRAND:
        name, bg, fg, _, _ = _BOOK_BRAND[key]
    else:
        name, bg, fg = _clean_book(book), "#1a1a2e", accent
    return (
        f'<div style="display:inline-flex;align-items:center;padding:10px 24px;'
        f'background:{bg};border-radius:12px;border:2px solid {accent}55;">'
        f'<span style="font-size:26px;font-weight:900;color:{fg};letter-spacing:-0.5px;'
        f'font-family:-apple-system,Helvetica Neue,Arial,sans-serif;">{name}</span>'
        f'</div>'
    )


def _book_sign_up_bonus(book: str) -> str:
    key = _normalize_book(book)
    brand = _BOOK_BRAND.get(key)
    return brand[3] if brand else ""


def _book_referral_link(book: str) -> str:
    key = _normalize_book(book)
    brand = _BOOK_BRAND.get(key)
    return brand[4] if brand else ""


def _book_accent(book: str) -> str:
    return _BOOK_ACCENT.get(_normalize_book(book), "#FFBE00")


def _parse_matchup(matchup: str) -> tuple[str, str]:
    if "@" in matchup:
        a, h = matchup.split("@", 1)
        return a.strip(), h.strip()
    if " vs " in matchup.lower():
        parts = matchup.replace(" VS ", " vs ").split(" vs ")
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    return "", matchup.strip()


def _is_nba_sport(sport: str) -> bool:
    return sport in ("basketball_nba", "nba")


def _logo_for(team: str, is_nba: bool) -> str:
    return _nba_logo_url(team) if is_nba else _logo_url(team)


def _hex_for(team: str, is_nba: bool) -> str:
    if is_nba:
        return _NBA_HEX.get(team, "#4080FF")
    return _MLB_HEX.get(team, "#4080FF")


def _abbr_for(team: str, is_nba: bool) -> str:
    if is_nba:
        return _nba_team_abbr(team)
    return _ESPN_ABBR.get(team, team[:3].upper()).upper() if _ESPN_ABBR.get(team) else team[:3].upper()


def _bet_label(p: dict, is_nba: bool) -> tuple[str, str, str]:
    """Return (bet_display, market_badge, side_hex)."""
    team    = p.get("team") or p.get("Team") or ""
    market  = (p.get("market") or p.get("Market") or "").lower()
    line    = p.get("line") or p.get("bet_line")
    direction = (p.get("direction") or "").upper()

    if market in ("moneyline", "h2h"):
        abbr = _abbr_for(team, is_nba)
        return f"{abbr} ML", "MONEYLINE", _hex_for(team, is_nba)
    if market in ("spread", "spreads"):
        # Strip trailing numeric spread value (e.g. "Yankees -1.5" → "Yankees")
        # but only if the last token is actually a number, not a team name word
        parts = team.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].lstrip("+-").replace(".", "", 1).isdigit():
            bet_team = parts[0]
        else:
            bet_team = team
        abbr = _abbr_for(bet_team, is_nba)
        # Try canonical line field, then old-format Spread field
        line_val = line if line is not None else p.get("Spread")
        line_str = ""
        if line_val is not None:
            try:
                fv = float(line_val)
                if fv == fv:  # not NaN
                    line_str = f" {fv:+.1f}"
            except (TypeError, ValueError):
                pass
        return f"{abbr}{line_str}", "SPREAD", _hex_for(bet_team, is_nba)
    if market in ("run_line",):
        # team field already contains "+1.5 RL" or similar
        bet_team = team.split(" +")[0].split(" -")[0].strip()
        abbr = _abbr_for(bet_team, is_nba)
        line_str = ""
        if line is not None:
            try:
                line_str = f" {float(line):+.1f}"
            except (TypeError, ValueError):
                line_str = f" {line}"
        return f"{abbr}{line_str} RL", "RUN LINE", _hex_for(bet_team, is_nba)
    if market in ("total", "totals"):
        side_hex = "#39FF78" if direction == "OVER" or "OVER" in team.upper() else "#FF6B6B"
        # team field may already have "OVER 7.0" baked in
        return team if team else f"{direction} {line}", "TOTAL", side_hex
    return team or market.upper(), market.upper() or "BET", "#FFBE00"


def _logo_img_html(team: str, is_nba: bool, size: int = 56) -> str:
    url  = _logo_for(team, is_nba)
    hexc = _hex_for(team, is_nba)
    abbr = _abbr_for(team, is_nba)
    if url:
        return (
            f'<img class="leg-logo" src="{url}" alt="{abbr}" '
            f'style="width:{size}px;height:{size}px">'
        )
    return (
        f'<div class="leg-logo leg-logo-fb" '
        f'style="width:{size}px;height:{size}px;background:{hexc}">{abbr}</div>'
    )


def _build_parlay_html(
    legs: list[dict],
    sport: str,
    card_date: date,
    combined_odds: int,
    payout_100: float,
    book_label: str,
    is_sgp: bool = False,
) -> str:
    is_nba      = _is_nba_sport(sport)
    sport_label = "NBA PLAYOFFS" if is_nba else "MLB"
    date_str    = card_date.strftime("%b %d, %Y").upper()
    n_legs      = len(legs)
    book_clean  = _clean_book(book_label)
    accent      = _book_accent(book_label)
    parlay_type = "SAME-GAME PARLAY" if is_sgp else "SAME-BOOK PARLAY"
    glow        = accent

    # ── Scale leg sizes to fill the card based on leg count ───────────────────
    # Tuned so 2-leg cards feel as full as 5-leg cards
    scale_table = {
        2: dict(min_h=180, pad_v=30, bet_size=34, odds_size=58, logo_size=72, gap=18),
        3: dict(min_h=140, pad_v=24, bet_size=28, odds_size=46, logo_size=60, gap=14),
        4: dict(min_h=110, pad_v=18, bet_size=24, odds_size=40, logo_size=52, gap=12),
        5: dict(min_h=92,  pad_v=14, bet_size=22, odds_size=36, logo_size=46, gap=10),
    }
    sc = scale_table.get(n_legs, scale_table[4])

    leg_rows = ""
    for i, p in enumerate(legs, 1):
        market   = (p.get("market") or "").lower()
        matchup  = p.get("matchup") or p.get("Matchup") or ""
        away, home = _parse_matchup(matchup)
        raw_edge = float(p.get("edge_pct") or p.get("Edge", 0) or 0)
        edge_pct = raw_edge * 100 if raw_edge < 1.0 and raw_edge > 0 else raw_edge
        odds     = p.get("odds") or p.get("best_odds") or p.get("BestOdds") or 0
        try:
            odds_int = int(float(odds))
            odds_str = f"{odds_int:+d}"
        except (TypeError, ValueError):
            odds_str = ""

        bet_disp, mkt_badge, side_hex = _bet_label(p, is_nba)
        ec = "#39FF78" if edge_pct >= 10 else ("#FFA514" if edge_pct >= 5 else "#6480FF")

        # Clean NaN strings from pandas serialisation
        away = "" if away.lower() in ("nan", "none") else away
        home = "" if home.lower() in ("nan", "none") else home
        # Fallback: if matchup was null, use Team/Opponent fields
        if not away and not home:
            bet_team = p.get("team") or p.get("Team") or ""
            opponent = p.get("opponent") or p.get("Opponent") or ""
            away, home = opponent, bet_team
        elif not away:
            bet_team = p.get("team") or p.get("Team") or ""
            opponent = p.get("opponent") or p.get("Opponent") or ""
            away = opponent if opponent else bet_team

        away_logo = _logo_img_html(away, is_nba, sc["logo_size"]) if away else ""
        home_logo = _logo_img_html(home, is_nba, sc["logo_size"]) if home else ""

        leg_rows += f"""
        <div class="leg" style="--sc:{side_hex};--ec:{ec}">
          <div class="leg-accent"></div>
          <div class="leg-num">{i}</div>
          <div class="leg-teams">
            {away_logo}
            <span class="vs-tiny">vs</span>
            {home_logo}
          </div>
          <div class="leg-info">
            <div class="leg-bet">{bet_disp}</div>
            <div class="leg-meta">
              <span class="mkt-badge">{mkt_badge}</span>
              <span class="edge-pill">+{edge_pct:.1f}%</span>
            </div>
          </div>
          <div class="leg-odds-col">
            <span class="leg-odds">{odds_str}</span>
          </div>
        </div>"""

    combined_str = f"{combined_odds:+d}" if combined_odds else "N/A"
    payout_str   = f"${payout_100:,.0f}"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}

  body {{ width:1080px; background:#070810; font-family:-apple-system,'Helvetica Neue',Arial,sans-serif; overflow:hidden; }}

  .card-wrap {{
    width:1080px; min-height:1080px;
    background:
      radial-gradient(ellipse 80% 40% at 50% 0%, {glow}18 0%, transparent 65%),
      radial-gradient(ellipse 60% 60% at 80% 100%, rgba(57,255,120,0.05) 0%, transparent 60%),
      linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
    padding-bottom:30px;
  }}

  .header {{
    padding:28px 44px 22px;
    border-bottom:1px solid {accent}40;
    background:linear-gradient(180deg, {accent}10 0%, transparent 100%);
    display:flex; align-items:flex-end; justify-content:space-between;
  }}
  .brand {{ display:flex; align-items:baseline; line-height:1; }}
  .brand-chef {{ font-size:72px; font-weight:900; color:#F8F8FC; letter-spacing:-2px; }}
  .brand-bets {{ font-size:56px; font-weight:900; color:#FFBE00; letter-spacing:-1px; margin-left:4px; }}
  .brand-ai {{
    font-size:34px; font-weight:800; margin-left:10px; margin-bottom:6px;
    background:linear-gradient(135deg,#00D4E0,#7B61FF);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
    filter:drop-shadow(0 0 12px rgba(0,210,220,0.5));
  }}
  .brand-sub {{ font-size:16px; color:#555870; margin-top:8px; letter-spacing:0.02em; }}

  .header-right {{ text-align:right; }}
  .header-date {{ font-size:18px; font-weight:700; color:#F8F8FC; letter-spacing:0.05em; }}
  .sport-pill {{
    display:inline-block; margin-top:8px; padding:5px 14px;
    background:{accent}22; border:1px solid {accent}55;
    border-radius:999px; font-size:13px; font-weight:800;
    color:{accent}; letter-spacing:0.10em;
  }}

  /* Book banner */
  .book-banner {{
    margin:18px 44px 0;
    display:flex; align-items:center; justify-content:space-between;
    padding:14px 22px;
    background:linear-gradient(135deg, {accent}15, {accent}05);
    border:1px solid {accent}44;
    border-radius:14px;
  }}
  .book-banner-left {{ display:flex; align-items:center; gap:16px; }}
  .book-banner-lbl {{ font-size:10px; font-weight:700; color:rgba(255,255,255,0.45); letter-spacing:0.18em; text-transform:uppercase; margin-bottom:6px; }}
  .book-banner-right {{
    font-size:11px; font-weight:800; color:{accent};
    background:{accent}18; border:1px solid {accent}55;
    padding:6px 14px; border-radius:999px; letter-spacing:0.12em;
  }}

  /* Legs */
  .legs-list {{ padding:16px 44px 0; display:flex; flex-direction:column; gap:{sc['gap']}px; }}

  .leg {{
    position:relative;
    display:flex; align-items:center; gap:0;
    background:rgba(255,255,255,0.035);
    border:1px solid rgba(255,255,255,0.08);
    border-radius:18px; overflow:hidden;
    padding:{sc['pad_v']}px 22px {sc['pad_v']}px 0; min-height:{sc['min_h']}px;
  }}
  .leg-accent {{
    width:5px; align-self:stretch;
    background:var(--sc); border-radius:3px;
    margin-right:18px; flex-shrink:0;
    box-shadow:0 0 14px var(--sc), 0 0 4px var(--sc);
  }}
  .leg-num {{
    width:36px; height:36px; border-radius:50%;
    background:linear-gradient(135deg, {accent}EE, {accent}88);
    color:#000; font-size:16px; font-weight:900;
    display:flex; align-items:center; justify-content:center;
    margin-right:18px; flex-shrink:0;
  }}
  .leg-teams {{
    display:flex; align-items:center; gap:8px;
    margin-right:24px; flex-shrink:0;
    width:160px;
  }}
  .leg-logo {{
    object-fit:contain;
    filter:drop-shadow(0 0 10px rgba(0,0,0,0.4));
  }}
  .leg-logo-fb {{
    border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    color:#fff; font-size:14px; font-weight:900;
  }}
  .vs-tiny {{ font-size:11px; font-weight:700; color:rgba(255,255,255,0.4); letter-spacing:0.05em; }}

  .leg-info {{ flex:1; min-width:0; display:flex; flex-direction:column; gap:8px; }}
  .leg-bet {{
    font-size:{sc['bet_size']}px; font-weight:900;
    color:var(--sc); letter-spacing:-0.3px;
    line-height:1.1;
    filter:drop-shadow(0 0 12px color-mix(in srgb, var(--sc) 50%, transparent));
  }}
  .leg-meta {{ display:flex; align-items:center; gap:8px; }}
  .mkt-badge {{
    font-size:10px; font-weight:800; letter-spacing:0.10em;
    color:rgba(255,255,255,0.55);
    background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.10);
    padding:3px 9px; border-radius:5px;
  }}
  .edge-pill {{
    font-size:12px; font-weight:800; letter-spacing:0.04em;
    color:var(--ec); background:color-mix(in srgb, var(--ec) 10%, transparent);
    border:1px solid color-mix(in srgb, var(--ec) 35%, transparent);
    padding:3px 10px; border-radius:999px;
  }}

  .leg-odds-col {{ flex-shrink:0; text-align:right; min-width:120px; }}
  .leg-odds {{
    font-size:{sc['odds_size']}px; font-weight:900;
    color:var(--ec); letter-spacing:-0.5px; line-height:1;
    filter:drop-shadow(0 0 16px var(--ec));
  }}

  /* Summary */
  .summary {{
    margin:20px 44px 0;
    display:flex; gap:0;
    background:linear-gradient(135deg, {accent}1F, {accent}08);
    border:1px solid {accent}45;
    border-radius:18px; overflow:hidden;
  }}
  .summary-block {{ flex:1; padding:22px 26px; }}
  .summary-block:not(:last-child) {{ border-right:1px solid {accent}25; }}
  .summary-label {{
    font-size:10px; font-weight:800; color:rgba(255,255,255,0.5);
    letter-spacing:0.18em; text-transform:uppercase; margin-bottom:8px;
  }}
  .summary-value {{ font-size:38px; font-weight:900; color:#F8F8FC; letter-spacing:-1px; line-height:1; }}
  .summary-value.green {{ color:#39FF78; filter:drop-shadow(0 0 14px #39FF7888); }}
  .summary-value.gold  {{ color:{accent}; filter:drop-shadow(0 0 14px {accent}66); }}

  /* Footer */
  .footer {{
    margin:18px 44px 0; padding-top:14px;
    border-top:1px solid {accent}25;
    display:flex; align-items:center; justify-content:space-between;
  }}
  .footer-left {{ font-size:13px; color:#555870; font-weight:600; letter-spacing:0.04em; }}
  .footer-handle {{ font-size:20px; font-weight:800; color:#FFBE00; letter-spacing:0.02em; }}
  .footer-right {{ font-size:12px; color:#555870; font-weight:500; }}
</style>
</head>
<body>
<div class="card-wrap">
  <div class="header">
    <div>
      <div class="brand">
        <span class="brand-chef">Overlay</span>
      </div>
      <div class="brand-sub">ML Picks Model &nbsp;·&nbsp; @getoverlay</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="sport-pill">{n_legs}-LEG PARLAY · {sport_label}</div>
    </div>
  </div>

  <div class="book-banner">
    <div class="book-banner-left">
      <div>
        <div class="book-banner-lbl">Place this parlay on</div>
        {_book_wordmark_html(book_label, accent)}
      </div>
    </div>
    <div class="book-banner-right">{parlay_type}</div>
  </div>

  <div class="legs-list">{leg_rows}</div>

  <div class="summary">
    <div class="summary-block">
      <div class="summary-label">Combined Odds</div>
      <div class="summary-value gold">{combined_str}</div>
    </div>
    <div class="summary-block">
      <div class="summary-label">$100 Wins</div>
      <div class="summary-value green">{payout_str}</div>
    </div>
    <div class="summary-block">
      <div class="summary-label">Legs</div>
      <div class="summary-value">{n_legs}</div>
    </div>
  </div>

  <div class="footer">
    <div class="footer-left">{sport_label} · {date_str} · {book_clean}</div>
    <div class="footer-handle">@getoverlay</div>
    <div class="footer-right">Verified Picks</div>
  </div>
</div>
</body>
</html>"""


def render_parlay_card(
    picks: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
    max_legs: int = 4,
    filename: str = "parlay_card",
) -> Optional[Path]:
    """
    Build and render a SAME-BOOK parlay card from a list of picks.
    Returns path to PNG or None if rendering fails or fewer than 2 legs found.
    """
    d    = card_date or date.today()
    # Try cross-game parlay first; fall back to SGP if not enough legs
    legs = build_parlay(picks, max_legs=max_legs, allow_sgp=False)
    is_sgp = False
    if not legs:
        legs = build_parlay(picks, max_legs=max_legs, allow_sgp=True)
        is_sgp = bool(legs)
    if not legs:
        return None

    # All legs share one book — pick from any leg
    book_label = (
        legs[0].get("sportsbook")
        or legs[0].get("Sportsbook")
        or legs[0].get("book")
        or ""
    )

    odds   = parlay_odds(legs)
    payout = parlay_payout(legs, stake=100)
    html   = _build_parlay_html(legs, sport, d, odds, payout, book_label, is_sgp=is_sgp)

    # Normalize sport dir to match rest of pipeline (mlb → baseball_mlb, etc.)
    _SPORT_DIR = {
        "mlb":  "baseball_mlb",
        "nba":  "basketball_nba",
        "nhl":  "icehockey_nhl",
        "wnba": "basketball_wnba",
    }
    sport_dir = _SPORT_DIR.get(sport.lower(), sport.lower())
    save_dir  = OUTPUT_DIR / sport_dir / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    html_path = save_dir / f"{filename}.html"
    png_path  = save_dir / f"{filename}.png"
    html_path.write_text(html, encoding="utf-8")

    write_parlay_captions(legs, sport, d, is_sgp=is_sgp)

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page    = browser.new_page(viewport={"width": 1080, "height": 1080})
            page.goto(f"file://{html_path.resolve()}", wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            page.screenshot(path=str(png_path), full_page=False)
            browser.close()
        return png_path
    except Exception as e:
        print(f"  [parlay card] render failed: {e}")
        return html_path


# ── Platform captions ─────────────────────────────────────────────────────────

_DISCLAIMER = "Not financial advice. Bet responsibly. 21+"

def write_parlay_captions(
    legs: list[dict],
    sport: str,
    card_date: date | None = None,
    is_sgp: bool = False,
) -> dict[str, Path]:
    """Generate Instagram, Twitter, Reddit captions for a parlay card."""
    d          = card_date or date.today()
    is_nba     = _is_nba_sport(sport)
    sport_lbl  = "NBA PLAYOFFS" if is_nba else "MLB"
    emoji      = "🏀" if is_nba else "⚾"
    date_str   = d.strftime("%b %d")
    parlay_lbl = "SAME-GAME PARLAY" if is_sgp else "PARLAY"

    book_label = (
        legs[0].get("sportsbook") or legs[0].get("Sportsbook") or legs[0].get("book") or ""
    ) if legs else ""
    book_key   = _normalize_book(book_label)
    book_brand = _BOOK_BRAND.get(book_key)
    book_clean = book_brand[0] if book_brand else _clean_book(book_label)
    bonus      = book_brand[3] if book_brand else ""
    ref_link   = book_brand[4] if book_brand else ""

    combined   = parlay_odds(legs)
    payout     = parlay_payout(legs, stake=100)
    combined_s = f"{combined:+d}" if combined else "?"

    def _leg_line(p: dict) -> str:
        team   = p.get("team") or p.get("Team") or ""
        market = (p.get("market") or p.get("Market") or "").lower()
        odds   = p.get("odds") or p.get("best_odds") or p.get("BestOdds") or 0
        try:
            odds_s = f"{int(float(odds)):+d}"
        except Exception:
            odds_s = ""
        if market in ("moneyline", "h2h"):
            return f"{team} ML {odds_s}"
        if market in ("spread", "spreads", "run_line"):
            line_v = p.get("line") or p.get("bet_line") or p.get("Spread")
            try:
                ls = f" {float(line_v):+.1f}" if line_v is not None and float(line_v) == float(line_v) else ""
            except Exception:
                ls = ""
            return f"{team}{ls} {odds_s}"
        if market in ("total", "totals"):
            return f"{team} {odds_s}"
        return f"{team} {odds_s}"

    # Instagram
    ig_lines = [
        f"{emoji} {date_str} {parlay_lbl} — {sport_lbl}",
        "",
        f"🎰 {len(legs)}-Leg {parlay_lbl} on {book_clean}",
        f"Combined odds: {combined_s}  |  $100 wins ${payout:,.0f}",
        "",
    ]
    for i, p in enumerate(legs, 1):
        ig_lines.append(f"  {i}. {_leg_line(p)}")
    ig_lines.append("")
    if bonus:
        cta = f"🎁 New to {book_clean}? {bonus}"
        if ref_link:
            cta += f"\n👉 Sign up link in bio 🔗"
        ig_lines += [cta, ""]
    ig_tags = (
        "#NBAPlayoffs #sportsbetting #NBApicks #parlay #samegameparlay "
        "#sharpbetting #DraftKings #FanDuel #BetMGM #bettingmodel"
        if is_nba else
        "#MLB #sportsbetting #MLBpicks #parlay #sharpbetting "
        "#valuebet #DraftKings #FanDuel #BetMGM #bettingmodel"
    )
    ig_lines += [_DISCLAIMER, "", ig_tags]
    instagram = "\n".join(ig_lines)

    # Twitter (≤280 main post + reply thread)
    tw_parts = [f"{emoji} {date_str} | {len(legs)}-LEG {parlay_lbl} · {sport_lbl}"]
    for p in legs:
        tw_parts.append(f"🔒 {_leg_line(p)}")
    tw_parts.append(f"Combined: {combined_s}  ($100 → ${payout:,.0f})")
    tw_parts.append(f"{_DISCLAIMER}  #{sport_lbl.replace(' ', '')} #parlay")
    main_tweet = "\n".join(tw_parts)

    if bonus and ref_link:
        reply = f"👇 New to {book_clean}? {bonus}\nSign up with my link: {ref_link}"
    elif bonus:
        reply = f"👇 New to {book_clean}? {bonus}\nSign up and place this parlay today!"
    else:
        reply = f"👇 Place this parlay on {book_clean}!"
    twitter = main_tweet + "\n\n---\n\n" + reply

    # Reddit
    rd_lines = [
        f"**Overlay AI — {sport_lbl} {parlay_lbl} · {d.strftime('%B %d, %Y').upper()}**",
        "",
        f"AI model identified {len(legs)} correlated edges — built into a {len(legs)}-leg {parlay_lbl.lower()} on **{book_clean}**.",
        "",
        f"**Combined odds: {combined_s}** | $100 wins **${payout:,.0f}**",
        "",
        "| # | Bet | Odds |",
        "|---|-----|------|",
    ]
    for i, p in enumerate(legs, 1):
        odds = p.get("odds") or p.get("best_odds") or p.get("BestOdds") or 0
        try:
            odds_s = f"{int(float(odds)):+d}"
        except Exception:
            odds_s = ""
        rd_lines.append(f"| {i} | {_leg_line(p)} | {odds_s} |")
    rd_lines.append("")
    if bonus:
        ref_line = f" — [Sign up here]({ref_link})" if ref_link else ""
        rd_lines += [f"**Sign up via my referral ({book_clean}):** {bonus}{ref_line}", ""]
    rd_lines += [
        "---",
        "",
        "*All picks timestamped before tip-off/first pitch. Results posted daily.*",
        "",
        f"*{_DISCLAIMER}*",
    ]
    reddit = "\n".join(rd_lines)

    _SD = {"mlb": "baseball_mlb", "nba": "basketball_nba", "nhl": "icehockey_nhl", "wnba": "basketball_wnba"}
    save_dir = OUTPUT_DIR / _SD.get(sport.lower(), sport.lower()) / d.strftime("%Y%m%d") / "captions"
    save_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for platform, content in [("parlay_instagram", instagram), ("parlay_twitter", twitter), ("parlay_reddit", reddit)]:
        p = save_dir / f"{platform}.txt"
        p.write_text(content, encoding="utf-8")
        paths[platform] = p
    return paths

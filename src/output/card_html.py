"""
HTML/CSS pick card renderer — ChefTonyBets AI.

Renders via Playwright (headless Chrome) for photorealistic quality:
  - Glassmorphism cards with backdrop-blur
  - CSS gradient text + box-shadow glows
  - Inter font from Google Fonts
  - Team logos from ESPN CDN
  - Proper anti-aliasing on everything

Falls back to PIL card if Playwright isn't available.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

OUTPUT_DIR = Path("output/picks")

# ── Team data ─────────────────────────────────────────────────────────────────

_ESPN_ABBR: dict[str, str] = {
    "Arizona Diamondbacks":  "ari",  "Atlanta Braves":        "atl",
    "Baltimore Orioles":     "bal",  "Boston Red Sox":        "bos",
    "Chicago Cubs":          "chc",  "Chicago White Sox":     "chw",
    "Cincinnati Reds":       "cin",  "Cleveland Guardians":   "cle",
    "Colorado Rockies":      "col",  "Detroit Tigers":        "det",
    "Houston Astros":        "hou",  "Kansas City Royals":    "kc",
    "Los Angeles Angels":    "laa",  "Los Angeles Dodgers":   "lad",
    "Miami Marlins":         "mia",  "Milwaukee Brewers":     "mil",
    "Minnesota Twins":       "min",  "New York Mets":         "nym",
    "New York Yankees":      "nyy",  "Athletics":             "oak",
    "Oakland Athletics":     "oak",  "Philadelphia Phillies": "phi",
    "Pittsburgh Pirates":    "pit",  "San Diego Padres":      "sd",
    "San Francisco Giants":  "sf",   "Seattle Mariners":      "sea",
    "St. Louis Cardinals":   "stl",  "Tampa Bay Rays":        "tb",
    "Texas Rangers":         "tex",  "Toronto Blue Jays":     "tor",
    "Washington Nationals":  "wsh",
}

_MLB_HEX: dict[str, str] = {
    "Arizona Diamondbacks":  "#A7192F",
    "Atlanta Braves":        "#CE1141",
    "Baltimore Orioles":     "#DF6D1D",
    "Boston Red Sox":        "#BD3039",
    "Chicago Cubs":          "#0E3386",
    "Chicago White Sox":     "#27251F",
    "Cincinnati Reds":       "#C6001F",
    "Cleveland Guardians":   "#003865",
    "Colorado Rockies":      "#330071",
    "Detroit Tigers":        "#0C2340",
    "Houston Astros":        "#002D62",
    "Kansas City Royals":    "#004687",
    "Los Angeles Angels":    "#BA0021",
    "Los Angeles Dodgers":   "#005A9C",
    "Miami Marlins":         "#00A3E0",
    "Milwaukee Brewers":     "#002855",
    "Minnesota Twins":       "#002B7F",
    "New York Mets":         "#002D72",
    "New York Yankees":      "#0C2340",
    "Athletics":             "#003831",
    "Oakland Athletics":     "#003831",
    "Philadelphia Phillies": "#E8182A",
    "Pittsburgh Pirates":    "#FDB827",
    "San Diego Padres":      "#2F241D",
    "San Francisco Giants":  "#FD5A1E",
    "Seattle Mariners":      "#005C5C",
    "St. Louis Cardinals":   "#C41E3A",
    "Tampa Bay Rays":        "#092CB8",
    "Texas Rangers":         "#003278",
    "Toronto Blue Jays":     "#134A8E",
    "Washington Nationals":  "#AB0003",
}

_SPORT_LABELS = {
    "baseball_mlb": "MLB", "basketball_nba": "NBA",
    "basketball_ncaab": "NCAAB", "americanfootball_nfl": "NFL",
    "mlb": "MLB", "nba": "NBA", "nfl": "NFL", "ncaab": "NCAAB",
}


def _odds_int(odds) -> int:
    try:
        x = float(odds)
    except (TypeError, ValueError):
        return 0
    return 0 if math.isnan(x) else int(round(x))


def _edge_color(edge: float, market: str) -> str:
    if market == "moneyline":
        if edge >= 0.08: return "#39FF78"   # neon green
        if edge >= 0.04: return "#FFA514"   # amber
        return "#6480FF"                     # blue
    else:
        if edge >= 1.5: return "#39FF78"
        if edge >= 0.8: return "#FFA514"
        return "#6480FF"


def _logo_url(team: str) -> str:
    abbr = _ESPN_ABBR.get(team)
    if abbr:
        return f"https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/{abbr}.png"
    return ""


# card_type → (pill label, accent hex, border/glow hex)
_CARD_TYPE_STYLES = {
    "moneyline": ("MLB",       "#FFBE00", "#FFBE00"),
    "spread":    ("RUN LINE",  "#39FF78", "#39FF78"),
    "total":     ("OVER/UNDER","#00D4E0", "#00D4E0"),
}


def _build_html(picks: list[dict], sport: str, d: date, card_type: str = "moneyline") -> str:
    sport_lbl = _SPORT_LABELS.get(sport.lower(), sport.upper())
    date_str  = d.strftime("%b %d, %Y").upper()
    pill_label, accent, glow = _CARD_TYPE_STYLES.get(card_type, _CARD_TYPE_STYLES["moneyline"])

    pick_rows_html = ""
    for idx, pick in enumerate(picks[:5]):
        market   = str(pick.get("Market", "moneyline") or "moneyline").lower()
        team     = str(pick.get("Team", "") or "")
        opponent = str(pick.get("Opponent", "") or "")
        bet_line = str(pick.get("BetLine", "") or "")
        edge     = float(pick.get("Edge", 0) or 0)
        odds     = _odds_int(pick.get("BestOdds", 0))
        book     = str(pick.get("Sportsbook", "") or "").strip()

        ec       = _edge_color(edge, market)
        team_hex = _MLB_HEX.get(team, _MLB_HEX.get(opponent, "#4080FF"))
        logo_url = _logo_url(team) or _logo_url(opponent)
        is_best  = idx == 0

        if market == "moneyline":
            edge_txt = f"+{edge*100:.1f}% edge"
            mkt_tag  = ""
        elif market == "spread":
            edge_txt = f"+{edge:.2f} run edge"
            mkt_tag  = '<span class="mkt-tag">RUN LINE</span>'
        else:
            edge_txt = f"+{edge:.2f} run edge"
            mkt_tag  = '<span class="mkt-tag">O/U</span>'

        if market == "spread" and bet_line:
            team_disp = f"{team}&nbsp;&nbsp;{bet_line}"
        else:
            team_disp = team

        vs_txt = f"vs&nbsp;&nbsp;{opponent}" if market in ("moneyline", "spread") else opponent
        odds_str = f"{odds:+d}" if odds else ""
        top_play = '<span class="top-play">⚡ TOP PLAY</span>' if is_best else ""
        card_class = "pick-card best-bet" if is_best else "pick-card"

        # Logo or fallback initial circle
        if logo_url:
            logo_html = f'<img class="team-logo" src="{logo_url}" alt="{team}">'
        else:
            initials = "".join(w[0] for w in team.split()[:2]).upper()
            logo_html = f'<div class="team-logo logo-fallback" style="background:{team_hex}">{initials}</div>'

        pick_rows_html += f"""
        <div class="{card_class}" style="--team-color:{team_hex};--edge-color:{ec}">
          <div class="accent-bar"></div>
          <div class="logo-wrap">
            {logo_html}
          </div>
          <div class="pick-info">
            <div class="team-row">
              <span class="team-name">{team_disp}</span>
              {mkt_tag}
            </div>
            <div class="vs-row">{vs_txt}</div>
            <div class="bottom-row">
              <span class="edge-txt" style="color:{ec}">{edge_txt}</span>
              {top_play}
            </div>
          </div>
          <div class="odds-wrap">
            <span class="odds-num" style="color:{ec};--ec:{ec}">{odds_str}</span>
            {'<span class="book-pill">' + book + '</span>' if book else ''}
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}

  body {{
    width: 1080px;
    background: #070810;
    font-family: 'Inter', -apple-system, sans-serif;
    overflow: hidden;
  }}

  .card-wrap {{
    width: 1080px;
    background:
      radial-gradient(ellipse 80% 40% at 50% 0%, {glow}12 0%, transparent 70%),
      radial-gradient(ellipse 60% 60% at 80% 100%, rgba(57,255,120,0.04) 0%, transparent 60%),
      linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
    padding-bottom: 28px;
  }}

  /* ── Header ── */
  .header {{
    padding: 28px 44px 22px;
    border-bottom: 1px solid {accent}40;
    background: linear-gradient(180deg, {accent}10 0%, transparent 100%);
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
  }}

  .brand {{
    display: flex;
    align-items: baseline;
    gap: 0;
    line-height: 1;
  }}

  .brand-chef {{
    font-size: 72px;
    font-weight: 900;
    color: #F8F8FC;
    letter-spacing: -2px;
  }}

  .brand-bets {{
    font-size: 56px;
    font-weight: 900;
    color: #FFBE00;
    letter-spacing: -1px;
    margin-left: 4px;
  }}

  .brand-ai {{
    font-size: 34px;
    font-weight: 800;
    background: linear-gradient(135deg, #00D4E0, #7B61FF);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-left: 10px;
    margin-bottom: 6px;
    filter: drop-shadow(0 0 12px rgba(0,210,220,0.5));
  }}

  .brand-sub {{
    font-size: 16px;
    color: #555870;
    font-weight: 400;
    margin-top: 8px;
    letter-spacing: 0.02em;
  }}

  .header-right {{
    text-align: right;
  }}

  .header-date {{
    font-size: 18px;
    font-weight: 700;
    color: #F8F8FC;
    letter-spacing: 0.05em;
  }}

  .sport-pill {{
    display: inline-block;
    margin-top: 8px;
    padding: 5px 14px;
    background: {accent}20;
    border: 1px solid {accent}50;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    color: {accent};
    letter-spacing: 0.08em;
  }}

  /* ── Pick cards ── */
  .picks-list {{
    padding: 18px 44px 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }}

  .pick-card {{
    position: relative;
    display: flex;
    align-items: center;
    gap: 0;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 20px;
    overflow: hidden;
    padding: 24px 28px 24px 0;
    min-height: 140px;
    backdrop-filter: blur(4px);
    transition: all 0.2s;
  }}

  .pick-card.best-bet {{
    background: linear-gradient(
      135deg,
      color-mix(in srgb, var(--team-color) 15%, #0E1220) 0%,
      rgba(14,18,32,0.95) 50%
    );
    border: 1px solid rgba(255,190,0,0.4);
    box-shadow:
      0 0 0 1px rgba(255,190,0,0.1),
      0 0 40px rgba(255,190,0,0.08),
      inset 0 1px 0 rgba(255,255,255,0.06);
    min-height: 156px;
  }}

  /* Colored left bar */
  .accent-bar {{
    width: 6px;
    align-self: stretch;
    background: var(--team-color);
    border-radius: 3px;
    margin-right: 20px;
    flex-shrink: 0;
    box-shadow: 0 0 16px var(--team-color), 0 0 6px var(--team-color);
  }}

  /* Logo */
  .logo-wrap {{
    width: 96px;
    height: 96px;
    flex-shrink: 0;
    margin-right: 24px;
    position: relative;
  }}

  .best-bet .logo-wrap {{
    width: 110px;
    height: 110px;
  }}

  .team-logo {{
    width: 100%;
    height: 100%;
    object-fit: contain;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,0.18) 0%, rgba(255,255,255,0.08) 100%);
    padding: 6px;
    box-shadow:
      0 0 0 3px var(--team-color),
      0 0 0 5px color-mix(in srgb, var(--team-color) 30%, transparent),
      0 0 28px color-mix(in srgb, var(--team-color) 80%, transparent),
      0 0 56px color-mix(in srgb, var(--team-color) 35%, transparent),
      inset 0 0 16px rgba(255,255,255,0.06);
  }}

  .logo-fallback {{
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    font-size: 22px;
    font-weight: 900;
    color: white;
    box-shadow: 0 0 0 2px var(--team-color), 0 0 20px color-mix(in srgb, var(--team-color) 50%, transparent);
  }}

  /* Text block */
  .pick-info {{
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }}

  .team-row {{
    display: flex;
    align-items: center;
    gap: 10px;
  }}

  .team-name {{
    font-size: 42px;
    font-weight: 900;
    color: #F8F8FC;
    letter-spacing: -0.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.1;
  }}

  .best-bet .team-name {{
    font-size: 48px;
  }}

  .mkt-tag {{
    font-size: 11px;
    font-weight: 700;
    color: rgba(255,255,255,0.4);
    letter-spacing: 0.1em;
    border: 1px solid rgba(255,255,255,0.12);
    padding: 2px 8px;
    border-radius: 4px;
    flex-shrink: 0;
  }}

  .vs-row {{
    font-size: 17px;
    color: #6B7090;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}

  .bottom-row {{
    display: flex;
    align-items: center;
    gap: 14px;
    margin-top: 2px;
  }}

  .edge-txt {{
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 0.03em;
  }}

  .top-play {{
    font-size: 14px;
    font-weight: 700;
    color: #FFBE00;
    background: rgba(255,190,0,0.1);
    border: 1px solid rgba(255,190,0,0.25);
    padding: 3px 12px;
    border-radius: 999px;
    letter-spacing: 0.04em;
  }}

  /* Odds */
  .odds-wrap {{
    flex-shrink: 0;
    text-align: right;
    min-width: 160px;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
  }}

  .odds-num {{
    font-size: 68px;
    font-weight: 900;
    letter-spacing: -1px;
    line-height: 1;
    filter: drop-shadow(0 0 20px var(--ec));
  }}

  .best-bet .odds-num {{
    font-size: 78px;
  }}

  .book-pill {{
    display: block;
    margin-top: 8px;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.80);
    text-align: center;
    white-space: nowrap;
  }}

  /* ── Footer ── */
  .footer {{
    margin: 20px 44px 0;
    padding-top: 16px;
    border-top: 1px solid rgba(255,190,0,0.2);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}

  .footer-left {{
    font-size: 14px;
    color: #555870;
    font-weight: 500;
    letter-spacing: 0.04em;
  }}

  .footer-handle {{
    font-size: 20px;
    font-weight: 800;
    color: #FFBE00;
    letter-spacing: 0.02em;
  }}

  .footer-right {{
    font-size: 13px;
    color: #555870;
    font-weight: 400;
  }}
</style>
</head>
<body>
<div class="card-wrap">
  <div class="header">
    <div>
      <div class="brand">
        <span class="brand-chef">ChefTony</span>
        <span class="brand-bets">Bets</span>
        <span class="brand-ai">AI</span>
      </div>
      <div class="brand-sub">A.I. Edge Detection &nbsp;·&nbsp; @ChefTonyBets</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="sport-pill">{pill_label}</div>
    </div>
  </div>

  <div class="picks-list">
    {pick_rows_html}
  </div>

  <div class="footer">
    <div class="footer-left">{pill_label} &nbsp;·&nbsp; {date_str}</div>
    <div class="footer-handle">@ChefTonyBets</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""


def _playwright_render(html: str, html_path: Path, png_path: Path) -> Path | None:
    """Write HTML and render to PNG via Playwright. Shared by all card renderers."""
    html_path.write_text(html, encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1080, "height": 2400})
            page.goto(f"file://{html_path.resolve()}", wait_until="networkidle")
            card = page.query_selector(".card-wrap")
            if card:
                card.screenshot(path=str(png_path), type="png")
            else:
                page.screenshot(path=str(png_path), full_page=True)
            browser.close()
        return png_path
    except Exception as e:
        print(f"  [card] Playwright render failed: {e}")
        return None


def render_pick_card_html(
    picks: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
) -> Path | None:
    """Render moneyline pick card to PNG via Playwright."""
    d = card_date or date.today()
    html = _build_html(picks, sport, d, card_type="moneyline")

    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    html_path = save_dir / "pick_card.html"
    png_path  = save_dir / "pick_card.png"

    return _playwright_render(html, html_path, png_path)


def render_runline_card_html(
    picks: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
) -> Path | None:
    """Render run line (spread) pick card to PNG."""
    d = card_date or date.today()
    html = _build_html(picks, sport, d, card_type="spread")
    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "runline_card.html", save_dir / "runline_card.png")


def render_totals_card_html(
    picks: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
) -> Path | None:
    """Render over/under totals pick card to PNG."""
    d = card_date or date.today()
    html = _build_html(picks, sport, d, card_type="total")
    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "totals_card.html", save_dir / "totals_card.png")


# ─────────────────────────────────────────────────────────────────────────────
# Props card
# ─────────────────────────────────────────────────────────────────────────────

_MARKET_LABEL = {
    "pitcher_strikeouts": "K's",
    "batter_hits": "Hits",
    "batter_home_runs": "HR",
    "batter_total_bases": "Bases",
    "batter_rbis": "RBI",
    "batter_strikeouts": "K's (Bat)",
    "pitcher_hits_allowed": "Hits All.",
    "pitcher_earned_runs": "ER",
}

_MARKET_COLOR = {
    "pitcher_strikeouts": "#7B61FF",   # purple — strikeouts
    "batter_hits":        "#39FF78",   # green — hits
    "batter_home_runs":   "#FF4D4D",   # red — power
    "batter_total_bases": "#FFA514",   # amber — bases
    "batter_rbis":        "#00D4E0",   # cyan — RBI
}


def _build_props_html(props: list[dict], sport: str, d: date) -> str:
    sport_lbl = _SPORT_LABELS.get(sport.lower(), sport.upper())
    date_str  = d.strftime("%b %d, %Y").upper()

    rows_html = ""
    for idx, prop in enumerate(props[:8]):
        market   = prop.get("market", "pitcher_strikeouts")
        player   = str(prop.get("player", ""))
        team     = str(prop.get("team", ""))
        opp      = str(prop.get("opp", ""))
        line     = prop.get("line", 0)
        direction = str(prop.get("direction", "OVER")).upper()
        projected = prop.get("projected", 0)
        edge_pct  = prop.get("edge_pct", 0)
        odds      = int(prop.get("odds", 0) or 0)
        book      = str(prop.get("book", ""))
        is_best   = idx == 0

        mkt_label = _MARKET_LABEL.get(market, market.replace("_", " ").title())
        mkt_color = _MARKET_COLOR.get(market, "#6480FF")
        team_hex  = _MLB_HEX.get(team, "#4080FF")
        ec        = "#39FF78" if edge_pct >= 8 else ("#FFA514" if edge_pct >= 5 else "#6480FF")
        odds_str  = f"{odds:+d}" if odds else ""

        # Direction pill color
        dir_color = "#39FF78" if direction == "OVER" else "#FF6B6B"
        dir_bg    = "rgba(57,255,120,0.12)" if direction == "OVER" else "rgba(255,107,107,0.12)"
        dir_border = "rgba(57,255,120,0.3)" if direction == "OVER" else "rgba(255,107,107,0.3)"

        # Smart projection display:
        # For markets where expected value < 1 (HRs, RBI, etc.) show as probability %
        # For counting stats > 1 (Ks, hits) show as projected count
        _low_count_markets = {"batter_home_runs", "batter_rbis", "pitcher_earned_runs"}
        if market in _low_count_markets or (isinstance(projected, float) and projected < 1.0):
            proj_display = f"{int(round(projected * 100))}% chance"
        else:
            proj_display = f"proj {projected}"

        # Big prop statement: "OVER 6.5 K's" — the actual bet, prominent
        prop_stmt = f"{direction} {line} {mkt_label}"

        # Team logo from ESPN CDN (same as picks card)
        team_logo_url = _logo_url(team)
        if team_logo_url:
            avatar_html = f'<img class="prop-team-logo" src="{team_logo_url}" alt="{team}">'
        else:
            parts    = player.split()
            initials = (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else player[:2].upper()
            avatar_html = f'<span class="prop-initials">{initials}</span>'

        card_class = "prop-card best-prop" if is_best else "prop-card"
        top_play  = '<span class="top-play">⚡ BEST BET</span>' if is_best else ""

        rows_html += f"""
        <div class="{card_class}" style="--team-color:{team_hex};--ec:{ec}">
          <div class="prop-accent-bar" style="background:{mkt_color};box-shadow:0 0 14px {mkt_color}"></div>
          <div class="prop-avatar" style="background:radial-gradient(circle,rgba(255,255,255,0.18) 0%,rgba(255,255,255,0.08) 100%);box-shadow:0 0 0 3px {team_hex},0 0 0 5px color-mix(in srgb,{team_hex} 30%,transparent),0 0 24px color-mix(in srgb,{team_hex} 70%,transparent)">
            {avatar_html}
          </div>
          <div class="prop-info">
            <div class="prop-player-row">
              <span class="prop-player">{player}</span>
            </div>
            <div class="prop-bet-row">
              <span class="prop-stmt" style="color:{dir_color}">{prop_stmt}</span>
              <span class="prop-mkt-badge" style="color:{mkt_color};border-color:{mkt_color}40;background:{mkt_color}18">{mkt_label}</span>
            </div>
            <div class="prop-sub">vs {opp} &nbsp;·&nbsp; {team}</div>
            <div class="prop-bottom-row">
              <span class="prop-proj" style="color:{ec}">{proj_display}</span>
              <span class="prop-edge" style="color:{ec}">+{edge_pct}% edge</span>
              {top_play}
            </div>
          </div>
          <div class="prop-odds-wrap">
            <span class="prop-odds" style="color:{ec};filter:drop-shadow(0 0 16px {ec})">{odds_str}</span>
            <span class="prop-book">{book.upper()}</span>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}

  body {{
    width: 1080px;
    background: #070810;
    font-family: 'Inter', -apple-system, sans-serif;
    overflow: hidden;
  }}

  .card-wrap {{
    width: 1080px;
    background:
      radial-gradient(ellipse 80% 40% at 50% 0%, rgba(123,97,255,0.08) 0%, transparent 70%),
      radial-gradient(ellipse 60% 60% at 80% 100%, rgba(57,255,120,0.04) 0%, transparent 60%),
      linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
    padding-bottom: 28px;
  }}

  /* ── Header ── */
  .header {{
    padding: 28px 44px 22px;
    border-bottom: 1px solid rgba(123,97,255,0.3);
    background: linear-gradient(180deg, rgba(123,97,255,0.06) 0%, transparent 100%);
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
  }}

  .brand {{ display:flex; align-items:baseline; gap:0; line-height:1; }}
  .brand-chef {{ font-size:72px; font-weight:900; color:#F8F8FC; letter-spacing:-2px; }}
  .brand-bets {{ font-size:56px; font-weight:900; color:#FFBE00; letter-spacing:-1px; margin-left:4px; }}
  .brand-ai {{
    font-size:34px; font-weight:800; margin-left:10px; margin-bottom:6px;
    background: linear-gradient(135deg, #00D4E0, #7B61FF);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    filter: drop-shadow(0 0 12px rgba(0,210,220,0.5));
  }}
  .brand-sub {{ font-size:16px; color:#555870; font-weight:400; margin-top:8px; }}

  .header-right {{ text-align:right; }}
  .header-date {{ font-size:18px; font-weight:700; color:#F8F8FC; letter-spacing:0.05em; }}
  .props-pill {{
    display:inline-block; margin-top:8px; padding:5px 14px;
    background:rgba(123,97,255,0.15); border:1px solid rgba(123,97,255,0.4);
    border-radius:999px; font-size:13px; font-weight:700; color:#7B61FF; letter-spacing:0.08em;
  }}

  /* ── Section label ── */
  .section-label {{
    margin: 14px 44px 0;
    font-size: 12px;
    font-weight: 700;
    color: #555870;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }}

  /* ── Prop rows ── */
  .props-list {{ padding:12px 44px 0; display:flex; flex-direction:column; gap:10px; }}

  .prop-card {{
    position:relative; display:flex; align-items:center; gap:0;
    background:rgba(255,255,255,0.03);
    border:1px solid rgba(255,255,255,0.07);
    border-radius:18px; overflow:hidden;
    padding:18px 22px 18px 0;
    min-height:110px;
    backdrop-filter:blur(4px);
  }}

  .prop-card.best-prop {{
    background: linear-gradient(135deg,
      rgba(123,97,255,0.12) 0%,
      rgba(14,18,32,0.95) 50%);
    border:1px solid rgba(123,97,255,0.35);
    box-shadow: 0 0 0 1px rgba(123,97,255,0.1), 0 0 36px rgba(123,97,255,0.08);
    min-height:124px;
  }}

  .prop-accent-bar {{
    width:6px; align-self:stretch; border-radius:3px;
    margin-right:18px; flex-shrink:0;
  }}

  .prop-avatar {{
    width:80px; height:80px; border-radius:50%;
    flex-shrink:0; margin-right:20px;
    display:flex; align-items:center; justify-content:center;
  }}

  .best-prop .prop-avatar {{ width:90px; height:90px; }}

  .prop-team-logo {{
    width: 78%;
    height: 78%;
    object-fit: contain;
    border-radius: 50%;
    padding: 3px;
  }}

  .best-prop .prop-team-logo {{ width:82%; height:82%; }}

  .prop-initials {{
    font-size:26px; font-weight:900; color:rgba(255,255,255,0.9);
    text-shadow: 0 0 12px rgba(255,255,255,0.3);
  }}

  .best-prop .prop-initials {{ font-size:30px; }}

  /* Info block */
  .prop-info {{ flex:1; min-width:0; display:flex; flex-direction:column; gap:4px; }}

  .prop-player-row {{ display:flex; align-items:baseline; }}
  .prop-player {{
    font-size:36px; font-weight:900; color:#FFFFFF;
    letter-spacing:-0.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    line-height:1.1;
  }}
  .best-prop .prop-player {{ font-size:42px; }}

  /* The actual bet — big and clear */
  .prop-bet-row {{ display:flex; align-items:center; gap:10px; margin-top:1px; }}
  .prop-stmt {{
    font-size:22px; font-weight:900;
    letter-spacing:-0.2px; white-space:nowrap;
    line-height:1.1;
  }}
  .best-prop .prop-stmt {{ font-size:26px; }}

  .prop-mkt-badge {{
    flex-shrink:0; font-size:11px; font-weight:800;
    letter-spacing:0.06em; padding:2px 8px;
    border-radius:6px; border:1px solid;
    white-space:nowrap;
  }}

  .prop-sub {{ font-size:14px; color:#6B7090; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:1px; }}

  .prop-bottom-row {{ display:flex; align-items:center; gap:12px; margin-top:3px; flex-wrap:nowrap; }}

  .prop-proj {{ font-size:13px; font-weight:700; letter-spacing:0.02em; }}
  .prop-edge {{ font-size:14px; font-weight:700; letter-spacing:0.02em; }}

  .top-play {{
    font-size:13px; font-weight:700; color:#FFBE00;
    background:rgba(255,190,0,0.1); border:1px solid rgba(255,190,0,0.25);
    padding:3px 12px; border-radius:999px; letter-spacing:0.04em;
  }}

  /* Odds side */
  .prop-odds-wrap {{
    flex-shrink:0; text-align:right; min-width:150px;
    display:flex; flex-direction:column; align-items:flex-end;
  }}
  .prop-odds {{
    font-size:60px; font-weight:900; letter-spacing:-1px; line-height:1;
  }}
  .best-prop .prop-odds {{ font-size:68px; }}
  .prop-book {{
    display:block; margin-top:6px;
    font-size:13px; font-weight:800; letter-spacing:0.08em;
    color:rgba(255,255,255,0.80);
  }}

  /* ── Footer ── */
  .footer {{
    margin:18px 44px 0; padding-top:16px;
    border-top:1px solid rgba(123,97,255,0.2);
    display:flex; align-items:center; justify-content:space-between;
  }}
  .footer-left {{ font-size:14px; color:#555870; font-weight:500; letter-spacing:0.04em; }}
  .footer-handle {{ font-size:20px; font-weight:800; color:#FFBE00; letter-spacing:0.02em; }}
  .footer-right {{ font-size:13px; color:#555870; font-weight:400; }}
</style>
</head>
<body>
<div class="card-wrap">
  <div class="header">
    <div>
      <div class="brand">
        <span class="brand-chef">ChefTony</span>
        <span class="brand-bets">Bets</span>
        <span class="brand-ai">AI</span>
      </div>
      <div class="brand-sub">A.I. Edge Detection &nbsp;·&nbsp; @ChefTonyBets</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="props-pill">PLAYER PROPS</div>
    </div>
  </div>

  <div class="section-label">Best prop edges for today's slate</div>

  <div class="props-list">
    {rows_html}
  </div>

  <div class="footer">
    <div class="footer-left">{sport_lbl} Props &nbsp;·&nbsp; {date_str}</div>
    <div class="footer-handle">@ChefTonyBets</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""


def render_props_card_html(
    props: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
) -> Path | None:
    """Render player props card to PNG via Playwright. Returns path or None."""
    d = card_date or date.today()
    html = _build_props_html(props, sport, d)

    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    html_path = save_dir / "props_card.html"
    png_path  = save_dir / "props_card.png"

    html_path.write_text(html, encoding="utf-8")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1080, "height": 2400})
            page.goto(f"file://{html_path.resolve()}", wait_until="networkidle")
            card = page.query_selector(".card-wrap")
            if card:
                card.screenshot(path=str(png_path), type="png")
            else:
                page.screenshot(path=str(png_path), full_page=True)
            browser.close()
        return png_path
    except Exception as e:
        print(f"  [props card] Playwright render failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# NRFI card
# ─────────────────────────────────────────────────────────────────────────────

def _build_nrfi_html(games: list[dict], sport: str, d: date) -> str:
    """Build NRFI/YRFI card HTML. games = list from find_nrfi_edges()."""
    date_str = d.strftime("%b %-d, %Y").upper()
    accent = "#B44FFF"  # violet — distinct from other cards

    rows_html = ""
    for i, g in enumerate(games[:5]):
        direction   = g.get("direction", "NRFI")
        home_team   = g.get("home_team", "")
        away_team   = g.get("away_team", "")
        home_sp     = g.get("home_sp", "TBD")
        away_sp     = g.get("away_sp", "TBD")
        proj_nrfi   = g.get("projected_nrfi", 0.0)
        odds        = g.get("odds")
        book        = g.get("book", "")
        edge_pct    = g.get("edge_pct")

        odds_str = f"{int(odds):+d}" if odds is not None else "—"
        edge_str = f"+{edge_pct:.1f}% edge" if edge_pct is not None else f"proj {proj_nrfi*100:.0f}%"
        is_top   = i == 0
        dir_color = "#B44FFF" if direction == "NRFI" else "#FF6B35"

        home_logo = _logo_url(home_team)
        away_logo = _logo_url(away_team)
        home_init = home_team[:2].upper()
        away_init = away_team[:2].upper()

        top_badge = '<span class="top-play">⚡ BEST BET</span>' if is_top else ""

        rows_html += f"""
        <div class="pick-row {'top-pick' if is_top else ''}">
          <div class="logos-pair">
            <div class="logo-mini" style="background-image:url('{away_logo}')">
              {'<span class="logo-fallback">' + away_init + '</span>' if not away_logo else ''}
            </div>
            <span class="vs-sep">@</span>
            <div class="logo-mini" style="background-image:url('{home_logo}')">
              {'<span class="logo-fallback">' + home_init + '</span>' if not home_logo else ''}
            </div>
          </div>
          <div class="pick-info">
            <div class="direction" style="color:{dir_color}">{direction}</div>
            <div class="matchup-line">{away_team} @ {home_team}</div>
            <div class="sp-line">{away_sp} vs {home_sp}</div>
            <div class="edge-line">{edge_str} {top_badge}</div>
          </div>
          <div class="odds-block {'top-odds' if is_top else ''}">
            {odds_str}
            <div class="book-pill">{book.upper() if book else 'MODEL'}</div>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0a0a0f; font-family:'Inter',sans-serif; }}

  .card-wrap {{
    width: 1080px;
    background: linear-gradient(160deg, #0d0d1a 0%, #0a0a0f 50%, #130820 100%);
    padding: 52px 56px 44px;
    border-top: 4px solid {accent};
    box-shadow: 0 0 80px rgba(180,79,255,0.12);
  }}

  /* Header */
  .header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:32px; }}
  .brand {{ display:flex; align-items:baseline; gap:0; }}
  .brand-chef {{ font-size:52px; font-weight:900; color:#fff; letter-spacing:-1px; }}
  .brand-tony {{ font-size:52px; font-weight:900; color:#FFBE00; letter-spacing:-1px; }}
  .brand-bets {{ font-size:52px; font-weight:900; color:#fff; letter-spacing:-1px; }}
  .brand-ai   {{ font-size:22px; font-weight:700; color:{accent}; margin-left:8px; }}
  .header-right {{ text-align:right; }}
  .date-str {{ font-size:22px; font-weight:600; color:rgba(255,255,255,0.55); }}
  .market-pill {{
    display:inline-block; margin-top:8px;
    background: rgba(180,79,255,0.15); border:1.5px solid {accent};
    color:{accent}; font-size:14px; font-weight:700;
    padding:4px 14px; border-radius:20px; letter-spacing:1px;
  }}

  .sub-header {{
    font-size:13px; font-weight:600; color:rgba(255,255,255,0.30);
    letter-spacing:2px; text-transform:uppercase; margin-bottom:24px;
  }}

  /* Pick rows */
  .pick-row {{
    display:flex; align-items:center; gap:20px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius:16px; padding:20px 24px;
    margin-bottom:14px;
    transition: all 0.2s;
  }}
  .top-pick {{
    background: rgba(180,79,255,0.08);
    border: 1.5px solid rgba(180,79,255,0.35);
    box-shadow: 0 0 24px rgba(180,79,255,0.12);
  }}

  .logos-pair {{
    display:flex; align-items:center; gap:6px; flex-shrink:0;
  }}
  .logo-mini {{
    width:52px; height:52px; border-radius:50%;
    background: rgba(255,255,255,0.10) center/contain no-repeat;
    display:flex; align-items:center; justify-content:center;
    flex-shrink:0;
  }}
  .logo-fallback {{ font-size:14px; font-weight:800; color:rgba(255,255,255,0.7); }}
  .vs-sep {{ font-size:13px; font-weight:700; color:rgba(255,255,255,0.3); }}

  .pick-info {{ flex:1; min-width:0; }}
  .direction {{
    font-size:30px; font-weight:900; letter-spacing:-0.5px;
    line-height:1;
  }}
  .matchup-line {{
    font-size:14px; font-weight:600; color:rgba(255,255,255,0.55);
    margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }}
  .sp-line {{
    font-size:12px; font-weight:500; color:rgba(255,255,255,0.35);
    margin-top:2px;
  }}
  .edge-line {{
    font-size:13px; font-weight:700; color:rgba(255,255,255,0.45);
    margin-top:6px; display:flex; align-items:center; gap:8px;
  }}
  .top-play {{
    background: linear-gradient(90deg, #B44FFF, #7B2FBE);
    color:#fff; font-size:11px; font-weight:700;
    padding:3px 10px; border-radius:20px; letter-spacing:0.5px;
  }}

  .odds-block {{
    font-size:52px; font-weight:900; color:rgba(255,255,255,0.55);
    text-align:right; flex-shrink:0; min-width:130px; line-height:1;
  }}
  .top-odds {{ color:{accent}; text-shadow: 0 0 24px rgba(180,79,255,0.6); }}
  .book-pill {{
    font-size:11px; font-weight:700; color:rgba(255,255,255,0.80);
    text-align:right; margin-top:6px; letter-spacing:0.5px;
  }}

  /* Footer */
  .footer {{
    display:flex; justify-content:space-between; align-items:center;
    margin-top:28px; padding-top:20px;
    border-top:1px solid rgba(255,255,255,0.08);
  }}
  .footer-left {{ font-size:13px; color:rgba(255,255,255,0.25); }}
  .footer-handle {{ font-size:18px; font-weight:800; color:#FFBE00; }}
  .footer-right {{ font-size:13px; color:rgba(255,255,255,0.25); }}
</style>
</head>
<body>
<div class="card-wrap">
  <div class="header">
    <div class="brand">
      <span class="brand-chef">Chef</span><span class="brand-tony">Tony</span><span class="brand-bets">Bets</span>
      <span class="brand-ai">AI</span>
    </div>
    <div class="header-right">
      <div class="date-str">{date_str}</div>
      <div class="market-pill">NRFI / YRFI</div>
    </div>
  </div>
  <div class="sub-header">First Inning — No Run / Yes Run Edge</div>
  {rows_html}
  <div class="footer">
    <div class="footer-left">MLB · {d.strftime('%b %-d, %Y')} · A.I. Edge Detection</div>
    <div class="footer-handle">@ChefTonyBets</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""


def render_nrfi_card_html(
    games: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
) -> Path | None:
    """Render NRFI/YRFI card to PNG via Playwright."""
    d = card_date or date.today()
    html = _build_nrfi_html(games, sport, d)

    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "nrfi_card.html", save_dir / "nrfi_card.png")

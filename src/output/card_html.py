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

# ── Book name display normalization ─────────────────────────────────────────

_BOOK_DISPLAY: dict[str, str] = {
    "draftkings":    "DRAFTKINGS",
    "fanduel":       "FANDUEL",
    "betmgm":        "BETMGM",
    "betrivers":     "BETRIVERS",
    "caesars":       "CAESARS",
    "bet365":        "BET365",
    "espnbet":       "ESPN BET",
    "hardrockbet":   "HARD ROCK",
    "betparx":       "BETPARX",
    "pinnacle":      "PINNACLE",
    "bovada":        "BOVADA",
    "lowvig":        "LOWVIG",
    "lowvig.ag":     "LOWVIG",
    "mybookieag":    "MYBOOKIE",
    "mybookie.ag":   "MYBOOKIE",
    "betonlineag":   "BETONLINE",
}


def _clean_book(name: str) -> str:
    return _BOOK_DISPLAY.get(name.lower().strip(), name.upper().replace(".AG", "").replace(".COM", "").strip())


# ── NBA Team data ─────────────────────────────────────────────────────────────

_NBA_ESPN_ABBR: dict[str, str] = {
    "Atlanta Hawks":            "atl",  "Boston Celtics":           "bos",
    "Brooklyn Nets":            "bkn",  "Charlotte Hornets":        "cha",
    "Chicago Bulls":            "chi",  "Cleveland Cavaliers":      "cle",
    "Dallas Mavericks":         "dal",  "Denver Nuggets":           "den",
    "Detroit Pistons":          "det",  "Golden State Warriors":    "gs",
    "Houston Rockets":          "hou",  "Indiana Pacers":           "ind",
    "Los Angeles Clippers":     "lac",  "Los Angeles Lakers":       "lal",
    "Memphis Grizzlies":        "mem",  "Miami Heat":               "mia",
    "Milwaukee Bucks":          "mil",  "Minnesota Timberwolves":   "min",
    "New Orleans Pelicans":     "no",   "New York Knicks":          "ny",
    "Oklahoma City Thunder":    "okc",  "Orlando Magic":            "orl",
    "Philadelphia 76ers":       "phi",  "Phoenix Suns":             "phx",
    "Portland Trail Blazers":   "por",  "Sacramento Kings":         "sac",
    "San Antonio Spurs":        "sa",   "Toronto Raptors":          "tor",
    "Utah Jazz":                "utah", "Washington Wizards":       "wsh",
}

_NBA_HEX: dict[str, str] = {
    "Atlanta Hawks":            "#C8102E",
    "Boston Celtics":           "#007A33",
    "Brooklyn Nets":            "#444444",
    "Charlotte Hornets":        "#1D1160",
    "Chicago Bulls":            "#CE1141",
    "Cleveland Cavaliers":      "#860038",
    "Dallas Mavericks":         "#00538C",
    "Denver Nuggets":           "#0E2240",
    "Detroit Pistons":          "#C8102E",
    "Golden State Warriors":    "#1D428A",
    "Houston Rockets":          "#CE1141",
    "Indiana Pacers":           "#002D62",
    "Los Angeles Clippers":     "#C8102E",
    "Los Angeles Lakers":       "#552583",
    "Memphis Grizzlies":        "#5D76A9",
    "Miami Heat":               "#98002E",
    "Milwaukee Bucks":          "#00471B",
    "Minnesota Timberwolves":   "#0C2340",
    "New Orleans Pelicans":     "#0C2340",
    "New York Knicks":          "#006BB6",
    "Oklahoma City Thunder":    "#007AC1",
    "Orlando Magic":            "#0077C0",
    "Philadelphia 76ers":       "#006BB6",
    "Phoenix Suns":             "#1D1160",
    "Portland Trail Blazers":   "#E03A3E",
    "Sacramento Kings":         "#5A2D81",
    "San Antonio Spurs":        "#8A8D8F",
    "Toronto Raptors":          "#CE1141",
    "Utah Jazz":                "#002B5C",
    "Washington Wizards":       "#002B5C",
}

_NBA_TEAM_ABBR: dict[str, str] = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def _nba_logo_url(team: str) -> str:
    abbr = _NBA_ESPN_ABBR.get(team)
    if abbr:
        return f"https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/{abbr}.png"
    return ""


def _nba_team_abbr(name: str) -> str:
    return _NBA_TEAM_ABBR.get(name, name[:3].upper())


_NBA_MARKET_LABEL = {
    "player_points":                   "PTS",
    "player_rebounds":                 "REB",
    "player_assists":                  "AST",
    "player_threes":                   "3PM",
    "player_points_rebounds_assists":  "PRA",
    "player_pra":                      "PRA",
    "player_blocks":                   "BLK",
    "player_steals":                   "STL",
}

_NBA_MARKET_COLOR = {
    "player_points":                   "#FF6B00",
    "player_rebounds":                 "#006BB6",
    "player_assists":                  "#39FF78",
    "player_threes":                   "#7B61FF",
    "player_points_rebounds_assists":  "#FFA514",
    "player_pra":                      "#FFA514",
    "player_blocks":                   "#00D4E0",
    "player_steals":                   "#00D4E0",
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


def _team_abbr(name: str) -> str:
    """Short 2-3 letter team abbreviation for compact display."""
    _ABBR = {
        "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
        "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
        "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
        "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
        "Colorado Rockies": "COL", "Detroit Tigers": "DET",
        "Houston Astros": "HOU", "Kansas City Royals": "KC",
        "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
        "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
        "Minnesota Twins": "MIN", "New York Mets": "NYM",
        "New York Yankees": "NYY", "Athletics": "OAK",
        "Oakland Athletics": "OAK", "Philadelphia Phillies": "PHI",
        "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD",
        "San Francisco Giants": "SF", "Seattle Mariners": "SEA",
        "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
        "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR",
        "Washington Nationals": "WSH",
    }
    return _ABBR.get(name, name[:3].upper())


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
        matchup  = str(pick.get("Matchup", "") or opponent)

        ec       = _edge_color(edge, market)
        is_best  = idx == 0
        odds_str = f"{odds:+d}" if odds else ""
        top_play = '<span class="top-play">⚡ TOP PLAY</span>' if is_best else ""
        card_class = "pick-card best-bet" if is_best else "pick-card"

        # ── Totals picks: dual-logo layout ──────────────────────────────────
        if market == "total" or card_type == "total":
            direction = str(pick.get("Direction", "UNDER")).upper()
            line_val  = pick.get("MarketLine") or pick.get("BetLine") or ""
            edge_txt  = f"+{edge:.1f}% edge"
            dir_color = "#39FF78" if direction == "OVER" else "#FF6B6B"

            # Parse teams from matchup "Away @ Home"
            parts = matchup.replace(" @ ", "@").split("@")
            away_team = parts[0].strip() if parts else ""
            home_team = parts[1].strip() if len(parts) > 1 else ""
            if not away_team:
                away_team = str(pick.get("AwayTeam", ""))
            if not home_team:
                home_team = str(pick.get("HomeTeam", ""))

            away_logo = _logo_url(away_team)
            home_logo = _logo_url(home_team)
            away_hex  = _MLB_HEX.get(away_team, "#4080FF")
            home_hex  = _MLB_HEX.get(home_team, "#4080FF")
            away_abbr = _team_abbr(away_team)
            home_abbr = _team_abbr(home_team)

            def _logo_img(url, abbr, hex_col, cls=""):
                if url:
                    return f'<img class="total-logo {cls}" src="{url}" alt="{abbr}" style="--tc:{hex_col}">'
                return f'<div class="total-logo total-logo-fallback {cls}" style="background:{hex_col}">{abbr}</div>'

            pick_rows_html += f"""
        <div class="{card_class}" style="--team-color:{dir_color};--edge-color:{ec}">
          <div class="accent-bar" style="background:{dir_color};box-shadow:0 0 16px {dir_color}"></div>
          <div class="total-matchup">
            <div class="total-team away-team">
              {_logo_img(away_logo, away_abbr, away_hex)}
              <span class="total-abbr" style="color:{away_hex}">{away_abbr}</span>
            </div>
            <div class="total-center">
              <span class="total-direction" style="color:{dir_color}">{direction}</span>
              <span class="total-line">{line_val}</span>
              <span class="total-slash" style="color:rgba(255,255,255,0.2)">@</span>
            </div>
            <div class="total-team home-team">
              {_logo_img(home_logo, home_abbr, home_hex)}
              <span class="total-abbr" style="color:{home_hex}">{home_abbr}</span>
            </div>
          </div>
          <div class="total-right">
            <div class="total-odds-row">
              <span class="odds-num" style="color:{ec};--ec:{ec}">{odds_str}</span>
            </div>
            <div class="total-meta">
              <span class="edge-txt" style="color:{ec}">{edge_txt}</span>
              {'<span class="book-pill">' + book + '</span>' if book else ''}
              {top_play}
            </div>
          </div>
        </div>"""
            continue

        # ── Moneyline / spread: single-team layout ──────────────────────────
        team_hex = _MLB_HEX.get(team, _MLB_HEX.get(opponent, "#4080FF"))
        logo_url = _logo_url(team) or _logo_url(opponent)

        if market == "moneyline":
            edge_txt = f"+{edge*100:.1f}% edge"
            mkt_tag  = ""
        else:
            edge_txt = f"+{edge:.2f} run edge"
            mkt_tag  = '<span class="mkt-tag">RUN LINE</span>'

        team_disp = f"{team}&nbsp;&nbsp;{bet_line}" if market == "spread" and bet_line else team
        vs_txt    = f"vs&nbsp;&nbsp;{opponent}"

        if logo_url:
            logo_html = f'<img class="team-logo" src="{logo_url}" alt="{team}">'
        else:
            initials  = "".join(w[0] for w in team.split()[:2]).upper()
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
  .beta-badge {{
    display: inline-block;
    margin-top: 6px;
    padding: 3px 10px;
    background: rgba(255,165,0,0.15);
    border: 1px solid rgba(255,165,0,0.4);
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    color: #FFA500;
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
    padding: 20px 24px 20px 0;
    min-height: 120px;
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
    width: 80px;
    height: 80px;
    flex-shrink: 0;
    margin-right: 20px;
    position: relative;
  }}

  .best-bet .logo-wrap {{
    width: 90px;
    height: 90px;
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
    font-size: 32px;
    font-weight: 900;
    color: #F8F8FC;
    letter-spacing: -0.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.15;
    max-width: 520px;
  }}

  .best-bet .team-name {{
    font-size: 36px;
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
    font-size: 56px;
    font-weight: 900;
    letter-spacing: -1px;
    line-height: 1;
    filter: drop-shadow(0 0 20px var(--ec));
  }}

  .best-bet .odds-num {{
    font-size: 64px;
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

  /* ── Totals dual-logo layout ── */
  .total-matchup {{
    display: flex;
    align-items: center;
    gap: 0;
    flex: 1;
    padding-left: 0;
    min-width: 0;
  }}

  .total-team {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    width: 110px;
    flex-shrink: 0;
  }}

  .total-logo {{
    width: 80px;
    height: 80px;
    object-fit: contain;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,0.15) 0%, rgba(255,255,255,0.06) 100%);
    padding: 5px;
    box-shadow:
      0 0 0 2px var(--tc, #4080FF),
      0 0 18px color-mix(in srgb, var(--tc, #4080FF) 50%, transparent);
  }}

  .best-bet .total-logo {{
    width: 90px;
    height: 90px;
  }}

  .total-logo-fallback {{
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 17px;
    font-weight: 900;
    color: #fff;
  }}

  .total-abbr {{
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }}

  .total-center {{
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 0 8px;
  }}

  .total-direction {{
    font-size: 36px;
    font-weight: 900;
    letter-spacing: -0.5px;
    line-height: 1;
  }}

  .best-bet .total-direction {{ font-size: 42px; }}

  .total-line {{
    font-size: 28px;
    font-weight: 900;
    color: rgba(255,255,255,0.85);
    letter-spacing: -0.5px;
    line-height: 1;
  }}

  .best-bet .total-line {{ font-size: 33px; }}

  .total-slash {{
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.05em;
    margin-top: 2px;
  }}

  .total-right {{
    flex-shrink: 0;
    min-width: 150px;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
  }}

  .total-odds-row {{ display: flex; align-items: baseline; }}

  .total-meta {{
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 5px;
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
      <div class="brand-sub">A.I. Edge Detection &nbsp;·&nbsp; @ChefTonyAIBets</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="sport-pill">{pill_label}</div>
      {('<div class="beta-badge">MODEL IN TESTING</div>' if card_type == "total" else "")}
    </div>
  </div>

  <div class="picks-list">
    {pick_rows_html}
  </div>

  <div class="footer">
    <div class="footer-left">{pill_label} &nbsp;·&nbsp; {date_str}</div>
    <div class="footer-handle">@ChefTonyAIBets</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""


def _playwright_render(html: str, html_path: Path, png_path: Path,
                       target_height: int = 1350) -> Path | None:
    """
    Write HTML and render to PNG via Playwright.
    Default viewport targets 1080×1350 (Instagram 4:5 portrait).
    The card-wrap element is screenshot directly so actual height matches content.
    """
    html_path.write_text(html, encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1080, "height": target_height})
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
      <div class="brand-sub">A.I. Edge Detection &nbsp;·&nbsp; @ChefTonyAIBets</div>
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
    <div class="footer-handle">@ChefTonyAIBets</div>
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
    """Build NRFI/YRFI card HTML — clean sports-card layout."""
    date_str = d.strftime("%b %-d, %Y").upper()

    rows_html = ""
    for i, g in enumerate(games[:5]):
        direction = g.get("direction", "NRFI")
        home_team = g.get("home_team", "")
        away_team = g.get("away_team", "")
        home_sp   = g.get("home_sp", "TBD")
        away_sp   = g.get("away_sp", "TBD")
        proj_pct  = int(round(g.get("projected_nrfi", 0.5) * 100))
        odds      = g.get("odds")
        book      = g.get("book", "")
        edge_pct  = g.get("edge_pct")
        is_top    = i == 0

        # Determine colors
        if direction == "NRFI":
            dir_color  = "#39FF78"
            dir_bg     = "rgba(57,255,120,0.10)"
            dir_border = "rgba(57,255,120,0.30)"
        else:
            dir_color  = "#FF6B35"
            dir_bg     = "rgba(255,107,53,0.10)"
            dir_border = "rgba(255,107,53,0.30)"

        odds_str  = f"{int(odds):+d}" if odds is not None else "—"
        edge_str  = f"+{edge_pct:.1f}% edge" if edge_pct else f"{proj_pct}% proj"

        away_logo_url = _logo_url(away_team)
        home_logo_url = _logo_url(home_team)
        away_hex  = _MLB_HEX.get(away_team, "#4080FF")
        home_hex  = _MLB_HEX.get(home_team, "#4080FF")
        away_abbr = _team_abbr(away_team)
        home_abbr = _team_abbr(home_team)

        def _nrfi_logo(url, abbr, hex_col):
            if url:
                return f'<img class="nrfi-logo" src="{url}" alt="{abbr}" style="--tc:{hex_col}">'
            return f'<div class="nrfi-logo nrfi-logo-fb" style="background:{hex_col}">{abbr}</div>'

        top_badge = '<span class="nrfi-best">⚡ BEST BET</span>' if is_top else ""

        rows_html += f"""
    <div class="nrfi-row {'nrfi-top' if is_top else ''}">
      <div class="nrfi-logos">
        {_nrfi_logo(away_logo_url, away_abbr, away_hex)}
        <span class="nrfi-at">@</span>
        {_nrfi_logo(home_logo_url, home_abbr, home_hex)}
      </div>
      <div class="nrfi-info">
        <div class="nrfi-matchup">{away_abbr} @ {home_abbr}</div>
        <div class="nrfi-pitchers">{away_sp} &nbsp;vs&nbsp; {home_sp}</div>
        <div class="nrfi-bottom">
          <span class="nrfi-edge">{edge_str}</span>
          {top_badge}
        </div>
      </div>
      <div class="nrfi-right">
        <div class="nrfi-dir-pill" style="color:{dir_color};background:{dir_bg};border-color:{dir_border}">{direction}</div>
        <div class="nrfi-odds" style="color:{'#fff' if not is_top else dir_color}">{odds_str}</div>
        <div class="nrfi-book">{book.upper() if book else 'MODEL'}</div>
      </div>
    </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#08090F; font-family:'Inter',sans-serif; }}

  .card-wrap {{
    width: 1080px;
    background: #08090F;
    padding: 44px 52px 40px;
  }}

  /* ── Header ── */
  .nrfi-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    padding-bottom: 20px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    margin-bottom: 28px;
  }}

  .brand {{ display:flex; align-items:baseline; line-height:1; }}
  .brand-chef {{ font-size:60px; font-weight:900; color:#F8F8FC; letter-spacing:-1.5px; }}
  .brand-bets {{ font-size:60px; font-weight:900; color:#FFBE00; letter-spacing:-1.5px; }}
  .brand-ai {{
    font-size:24px; font-weight:800; margin-left:8px; margin-bottom:6px;
    background: linear-gradient(135deg, #39FF78, #00D4E0);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
  }}

  .header-right {{ text-align:right; }}
  .header-date {{ font-size:16px; font-weight:600; color:rgba(255,255,255,0.40); letter-spacing:0.06em; }}
  .header-pill {{
    display: inline-block; margin-top: 8px;
    padding: 5px 16px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 999px;
    font-size: 12px; font-weight: 700;
    color: rgba(255,255,255,0.50);
    letter-spacing: 0.10em;
  }}

  /* ── Section heading ── */
  .section-head {{
    font-size: 11px; font-weight: 700; letter-spacing: 0.16em;
    color: rgba(255,255,255,0.25); text-transform: uppercase;
    margin-bottom: 16px;
  }}

  /* ── Rows ── */
  .nrfi-rows {{ display: flex; flex-direction: column; gap: 14px; }}

  .nrfi-row {{
    display: flex;
    align-items: center;
    gap: 24px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 18px;
    padding: 22px 26px;
    min-height: 120px;
  }}

  .nrfi-top {{
    background: rgba(255,255,255,0.055);
    border: 1px solid rgba(255,255,255,0.14);
  }}

  /* Logos */
  .nrfi-logos {{
    display: flex; align-items: center; gap: 10px; flex-shrink: 0;
  }}

  .nrfi-logo {{
    width: 88px; height: 88px; border-radius: 50%;
    object-fit: contain;
    background: rgba(255,255,255,0.18);
    padding: 8px;
    border: 2.5px solid var(--tc, rgba(255,255,255,0.35));
    box-shadow: 0 0 14px rgba(255,255,255,0.10);
  }}

  .nrfi-top .nrfi-logo {{ width: 96px; height: 96px; }}

  .nrfi-logo-fb {{
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 900; color: #fff;
  }}

  .nrfi-at {{
    font-size: 16px; font-weight: 700;
    color: rgba(255,255,255,0.25);
  }}

  /* Info */
  .nrfi-info {{ flex: 1; min-width: 0; }}

  .nrfi-matchup {{
    font-size: 28px; font-weight: 800; color: #F0F0F8;
    letter-spacing: -0.5px; line-height: 1;
  }}

  .nrfi-top .nrfi-matchup {{ font-size: 32px; }}

  .nrfi-pitchers {{
    font-size: 16px; font-weight: 600;
    color: rgba(255,255,255,0.72);
    margin-top: 6px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}

  .nrfi-bottom {{
    display: flex; align-items: center; gap: 10px; margin-top: 9px;
  }}

  .nrfi-edge {{
    font-size: 14px; font-weight: 700;
    color: rgba(255,255,255,0.45);
    letter-spacing: 0.02em;
  }}

  .nrfi-best {{
    font-size: 12px; font-weight: 800; color: #FFBE00;
    background: rgba(255,190,0,0.12);
    border: 1px solid rgba(255,190,0,0.30);
    padding: 3px 12px; border-radius: 999px;
  }}

  /* Right column */
  .nrfi-right {{
    flex-shrink: 0;
    display: flex; flex-direction: column; align-items: flex-end; gap: 6px;
    min-width: 160px;
  }}

  .nrfi-dir-pill {{
    font-size: 22px; font-weight: 900; letter-spacing: 0.10em;
    padding: 7px 22px; border-radius: 999px;
    border: 2px solid;
    white-space: nowrap;
  }}

  .nrfi-top .nrfi-dir-pill {{ font-size: 26px; padding: 9px 26px; }}

  .nrfi-odds {{
    font-size: 46px; font-weight: 900;
    letter-spacing: -1px; line-height: 1;
  }}

  .nrfi-top .nrfi-odds {{ font-size: 54px; }}

  .nrfi-book {{
    font-size: 13px; font-weight: 700;
    color: rgba(255,255,255,0.60);
    letter-spacing: 0.06em;
  }}

  /* ── Footer ── */
  .nrfi-footer {{
    display: flex; justify-content: space-between; align-items: center;
    margin-top: 24px; padding-top: 18px;
    border-top: 1px solid rgba(255,255,255,0.06);
  }}

  .footer-l {{ font-size: 13px; color: rgba(255,255,255,0.20); font-weight: 500; }}
  .footer-handle {{ font-size: 18px; font-weight: 800; color: #FFBE00; }}
  .footer-r {{ font-size: 13px; color: rgba(255,255,255,0.20); }}
</style>
</head>
<body>
<div class="card-wrap">
  <div class="nrfi-header">
    <div>
      <div class="brand">
        <span class="brand-chef">ChefTony</span><span class="brand-bets">Bets</span>
        <span class="brand-ai">AI</span>
      </div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="header-pill">NRFI / YRFI</div>
    </div>
  </div>

  <div class="section-head">First Inning Run Scoring</div>

  <div class="nrfi-rows">
    {rows_html}
  </div>

  <div class="nrfi-footer">
    <div class="footer-l">MLB · {date_str}</div>
    <div class="footer-handle">@ChefTonyAIBets</div>
    <div class="footer-r">AI Verified</div>
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


# ─────────────────────────────────────────────────────────────────────────────
# NBA Game Picks Card — dual-logo matchup layout with projected scores
# ─────────────────────────────────────────────────────────────────────────────

def _parse_matchup(matchup: str) -> tuple[str, str]:
    """Parse 'Away @ Home' → (away_team, home_team)."""
    parts = matchup.replace(" @ ", "@").split("@", 1)
    away = parts[0].strip() if parts else ""
    home = parts[1].strip() if len(parts) > 1 else ""
    return away, home


def _nba_logo_img(url: str, abbr: str, hex_col: str, size: int = 80) -> str:
    if url:
        return (
            f'<img class="nba-logo" src="{url}" alt="{abbr}" '
            f'style="width:{size}px;height:{size}px;--tc:{hex_col}">'
        )
    return (
        f'<div class="nba-logo nba-logo-fb" '
        f'style="width:{size}px;height:{size}px;background:{hex_col}">{abbr}</div>'
    )


def _build_nba_html(picks: list[dict], d: date, context_label: str = "NBA",
                    top_props: list[dict] | None = None) -> str:
    """
    Build NBA game picks card with optional top props section at the bottom.
    Only positive-edge picks should be passed in.
    """
    date_str = d.strftime("%b %d, %Y").upper()
    is_playoff = "PLAYOFF" in context_label.upper() or "PLAY-IN" in context_label.upper()
    accent = "#FF6B00" if is_playoff else "#FFBE00"

    rows_html = ""
    for idx, pick in enumerate(picks[:6]):
        matchup     = pick.get("matchup", "")
        market      = pick.get("market", "spread")
        team_str    = pick.get("team", "")
        direction   = pick.get("direction", "COVER")
        bet_line    = pick.get("bet_line")
        odds        = int(pick.get("best_odds", 0) or 0)
        book        = str(pick.get("sportsbook", "") or "")
        edge_pct    = float(pick.get("edge_pct", 0) or 0)
        proj_total  = pick.get("proj_total")
        proj_spread = pick.get("proj_spread")   # = -home_advantage (negative when home favored)
        is_best     = pick.get("is_best", idx == 0)

        away_team, home_team = _parse_matchup(matchup)
        away_abbr = _nba_team_abbr(away_team)
        home_abbr = _nba_team_abbr(home_team)
        away_hex  = _NBA_HEX.get(away_team, "#4080FF")
        home_hex  = _NBA_HEX.get(home_team, "#4080FF")
        away_logo = _nba_logo_url(away_team)
        home_logo = _nba_logo_url(home_team)

        # ── Clean bet label ──────────────────────────────────────────────
        if market in ("moneyline", "h2h"):
            bet_team = team_str
            side_hex = _NBA_HEX.get(bet_team, "#4080FF")
            abbr     = _nba_team_abbr(bet_team)
            bet_disp = f"{abbr} ML"
            mkt_badge = "MONEYLINE"
        elif market == "spread":
            bet_team = team_str.rsplit(" ", 1)[0] if " " in team_str else team_str
            side_hex = _NBA_HEX.get(bet_team, "#4080FF")
            abbr     = _nba_team_abbr(bet_team)
            line_num = f"{float(bet_line):+.1f}" if bet_line is not None else ""
            bet_disp = f"{abbr} {line_num}"
            mkt_badge = "SPREAD"
        else:  # total
            side_hex  = "#39FF78" if direction == "OVER" else "#FF6B6B"
            line_val  = f"{bet_line}" if bet_line is not None else ""
            bet_disp  = f"{direction} {line_val}"
            mkt_badge = "TOTAL"

        ec       = "#39FF78" if edge_pct >= 10 else ("#FFA514" if edge_pct >= 5 else "#6480FF")
        odds_str = f"{odds:+d}" if odds else ""

        # ── Projected score (corrected formula) ─────────────────────────
        # proj_spread = -home_advantage → home_advantage = -proj_spread
        if proj_spread is not None and proj_total is not None:
            home_adv  = -proj_spread
            proj_home = round((proj_total + home_adv) / 2, 0)
            proj_away = round((proj_total - home_adv) / 2, 0)
            score_disp = f"{int(proj_away)} – {int(proj_home)}"
            score_label = f"{away_abbr}  {int(proj_away)}   –   {int(proj_home)}  {home_abbr}"
        else:
            score_disp  = ""
            score_label = ""

        card_cls  = "nba-card best-nba-card" if is_best else "nba-card"
        logo_size = 86 if is_best else 76
        best_banner = f"""
        <div class="best-banner">
          <span class="best-star">★</span> BEST BET <span class="best-star">★</span>
        </div>""" if is_best else ""

        rows_html += f"""
    <div class="{card_cls}" style="--sc:{side_hex};--ec:{ec}">
      {best_banner}
      <div class="nba-accent" style="background:{side_hex};box-shadow:0 0 20px {side_hex}99"></div>
      <div class="nba-body">
        <div class="nba-teams-row">
          <div class="nba-team">
            {_nba_logo_img(away_logo, away_abbr, away_hex, logo_size)}
            <span class="nba-abbr" style="color:{away_hex}">{away_abbr}</span>
          </div>
          <div class="nba-center">
            {'<span class="proj-score">' + score_disp + '</span>' if score_disp else '<span class="vs-at">vs</span>'}
            <span class="proj-label">PROJ</span>
          </div>
          <div class="nba-team">
            {_nba_logo_img(home_logo, home_abbr, home_hex, logo_size)}
            <span class="nba-abbr" style="color:{home_hex}">{home_abbr}</span>
          </div>
        </div>
        <div class="nba-bet-row">
          <div class="bet-left">
            <span class="bet-disp" style="color:{side_hex}">{bet_disp}</span>
            <span class="mkt-badge">{mkt_badge}</span>
            <span class="edge-pill" style="color:{ec};border-color:{ec}44;background:{ec}10">+{edge_pct:.1f}%</span>
          </div>
          <div class="bet-book">{_clean_book(book)}</div>
        </div>
      </div>
      <div class="nba-odds-col">
        <span class="nba-odds" style="color:{ec};filter:drop-shadow(0 0 20px {ec})">{odds_str}</span>
      </div>
    </div>"""

    # ── Top props section ────────────────────────────────────────────────────
    props_html = ""
    if top_props:
        props_rows = ""
        for prop in top_props[:4]:
            mkt      = prop.get("market", "player_points")
            player   = str(prop.get("player", ""))
            line     = prop.get("line", 0)
            dirn     = str(prop.get("direction", "OVER")).upper()
            proj     = prop.get("projected", 0)
            ep       = float(prop.get("edge_pct", 0) or 0)
            o        = int(prop.get("odds", 0) or 0)
            bk       = str(prop.get("book", ""))
            lbl      = _NBA_MARKET_LABEL.get(mkt, mkt.split("_")[-1].upper())
            mc       = _NBA_MARKET_COLOR.get(mkt, "#6480FF")
            dc       = "#39FF78" if dirn == "OVER" else "#FF6B6B"
            ec2      = "#39FF78" if ep >= 8 else ("#FFA514" if ep >= 5 else "#6480FF")
            last     = player.split()[-1] if player else ""

            props_rows += f"""
      <div class="prop-row">
        <div class="prop-bar" style="background:{mc}"></div>
        <span class="prop-name">{last}</span>
        <span class="prop-bet" style="color:{dc}">{dirn} {line} {lbl}</span>
        <span class="prop-proj" style="color:{ec2}">proj {proj:.1f}</span>
        <span class="prop-edge" style="color:{ec2}">+{ep:.1f}%</span>
        <span class="prop-odds" style="color:{ec2}">{o:+d}</span>
        <span class="prop-book">{_clean_book(bk)}</span>
      </div>"""

        props_html = f"""
  <div class="props-section">
    <div class="props-hdr">
      <span class="props-hdr-lbl">PROP BETS</span>
      <span class="props-hdr-sub">Model edge vs book line</span>
    </div>
    <div class="props-rows">{props_rows}
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
  body {{ width:1080px; background:#070810; font-family:'Inter',sans-serif; overflow:hidden; }}

  .card-wrap {{
    width:1080px;
    background:
      radial-gradient(ellipse 80% 40% at 50% 0%, {accent}12 0%, transparent 65%),
      linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
    padding-bottom:32px;
  }}

  .header {{
    padding:28px 44px 20px;
    border-bottom:1px solid {accent}35;
    background:linear-gradient(180deg, {accent}08 0%, transparent 100%);
    display:flex; align-items:flex-end; justify-content:space-between;
  }}
  .brand {{ display:flex; align-items:baseline; line-height:1; }}
  .brand-chef {{ font-size:72px; font-weight:900; color:#F8F8FC; letter-spacing:-2px; }}
  .brand-bets {{ font-size:56px; font-weight:900; color:{accent}; letter-spacing:-1px; margin-left:4px; }}
  .brand-ai {{
    font-size:34px; font-weight:800; margin-left:10px; margin-bottom:6px;
    background:linear-gradient(135deg,#00D4E0,#7B61FF);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
    filter:drop-shadow(0 0 12px rgba(0,210,220,0.45));
  }}
  .brand-sub {{ font-size:15px; color:#555870; margin-top:8px; }}
  .header-right {{ text-align:right; }}
  .header-date {{ font-size:18px; font-weight:700; color:#F8F8FC; letter-spacing:0.05em; }}
  .ctx-pill {{
    display:inline-block; margin-top:8px; padding:5px 16px;
    background:{accent}16; border:1px solid {accent}45;
    border-radius:999px; font-size:11px; font-weight:800;
    color:{accent}; letter-spacing:0.12em;
  }}

  /* ── Pick cards ── */
  .picks-list {{ padding:16px 44px 0; display:flex; flex-direction:column; gap:10px; }}

  .nba-card {{
    position:relative; display:flex; align-items:stretch; gap:0;
    background:rgba(255,255,255,0.026);
    border:1px solid rgba(255,255,255,0.065);
    border-radius:18px; overflow:hidden; min-height:118px;
  }}
  .best-nba-card {{
    position:relative;
    background:linear-gradient(135deg,
      color-mix(in srgb,var(--sc) 14%,#0C0E1A) 0%,
      rgba(12,14,26,0.97) 55%);
    border:1px solid #FFD70055;
    box-shadow:0 0 48px rgba(255,210,0,0.08), inset 0 1px 0 rgba(255,255,255,0.04);
    min-height:150px;
  }}

  .nba-accent {{
    width:5px; align-self:stretch; flex-shrink:0;
  }}

  .nba-body {{
    flex:1; min-width:0; overflow:hidden; padding:14px 8px 14px 18px;
    display:flex; flex-direction:column; gap:10px;
  }}

  /* Teams row */
  .nba-teams-row {{ display:flex; align-items:center; gap:0; }}

  .nba-team {{
    display:flex; flex-direction:column; align-items:center; gap:4px;
    width:96px; flex-shrink:0;
  }}
  .best-nba-card .nba-team {{ width:108px; }}

  .nba-logo {{
    object-fit:contain; border-radius:50%;
    background:radial-gradient(circle,rgba(255,255,255,0.14) 0%,rgba(255,255,255,0.05) 100%);
    padding:5px;
    box-shadow:
      0 0 0 2.5px var(--tc,#4080FF),
      0 0 0 5px color-mix(in srgb,var(--tc,#4080FF) 22%,transparent),
      0 0 28px color-mix(in srgb,var(--tc,#4080FF) 55%,transparent),
      0 0 56px color-mix(in srgb,var(--tc,#4080FF) 20%,transparent);
  }}
  .nba-logo-fb {{
    display:flex; align-items:center; justify-content:center;
    font-size:17px; font-weight:900; color:#fff; border-radius:50%;
    box-shadow:0 0 0 2px var(--tc,#4080FF),0 0 18px color-mix(in srgb,var(--tc,#4080FF) 45%,transparent);
  }}
  .nba-abbr {{
    font-size:13px; font-weight:800; letter-spacing:0.07em;
  }}

  .nba-center {{
    flex:1; display:flex; flex-direction:column; align-items:center; gap:2px; padding:0 4px;
  }}
  .proj-score {{
    font-size:26px; font-weight:900; color:#F2F2FA;
    letter-spacing:-0.5px; line-height:1; white-space:nowrap;
  }}
  .best-nba-card .proj-score {{ font-size:30px; }}
  .vs-at {{ font-size:12px; color:rgba(255,255,255,0.20); font-weight:600; }}
  .proj-label {{
    font-size:9px; font-weight:700; letter-spacing:0.14em;
    color:rgba(255,255,255,0.22); text-transform:uppercase; margin-top:1px;
  }}

  /* Bet row */
  .nba-bet-row {{
    display:flex; align-items:center; justify-content:space-between;
    padding-top:8px; border-top:1px solid rgba(255,255,255,0.055);
  }}
  .bet-left {{ display:flex; align-items:center; gap:8px; flex-wrap:nowrap; }}
  .bet-disp {{
    font-size:22px; font-weight:900; letter-spacing:-0.3px; white-space:nowrap;
  }}
  .best-nba-card .bet-disp {{ font-size:26px; }}
  .mkt-badge {{
    font-size:10px; font-weight:700; letter-spacing:0.10em;
    color:rgba(255,255,255,0.35); border:1px solid rgba(255,255,255,0.12);
    padding:2px 7px; border-radius:4px; white-space:nowrap;
  }}
  .edge-pill {{
    font-size:12px; font-weight:700; letter-spacing:0.03em;
    padding:2px 10px; border-radius:999px; border:1px solid;
    white-space:nowrap;
  }}
  /* BEST BET full-width banner */
  .best-banner {{
    position:absolute; top:0; left:0; right:0;
    background:linear-gradient(90deg,
      rgba(255,190,0,0.0) 0%,
      rgba(255,190,0,0.22) 30%,
      rgba(255,190,0,0.28) 50%,
      rgba(255,190,0,0.22) 70%,
      rgba(255,190,0,0.0) 100%);
    border-bottom:1px solid rgba(255,190,0,0.45);
    padding:7px 0 6px;
    text-align:center;
    font-size:15px; font-weight:900; letter-spacing:0.25em;
    color:#FFD700;
    text-shadow:0 0 16px rgba(255,210,0,0.8);
    z-index:2;
  }}
  .best-star {{ font-size:13px; opacity:0.85; }}
  .best-nba-card {{
    padding-top:36px;
  }}
  .bet-book {{
    font-size:13px; font-weight:800; color:rgba(255,255,255,0.82);
    letter-spacing:0.08em; white-space:nowrap; flex-shrink:0;
  }}

  /* Odds column */
  .nba-odds-col {{
    flex-shrink:0; width:180px; display:flex; flex-direction:column;
    align-items:flex-end; justify-content:center; padding-right:28px;
    min-width:0;
  }}
  .nba-odds {{
    font-size:58px; font-weight:900; letter-spacing:-1px; line-height:1;
    white-space:nowrap;
  }}
  .best-nba-card .nba-odds {{ font-size:66px; }}

  /* ── Props section ── */
  .props-section {{
    margin:16px 44px 0;
    border:1px solid rgba(255,255,255,0.07);
    border-radius:16px; overflow:hidden;
    background:rgba(255,255,255,0.018);
  }}
  .props-hdr {{
    display:flex; align-items:baseline; gap:12px;
    padding:11px 18px 10px;
    border-bottom:1px solid rgba(255,255,255,0.06);
    background:rgba(255,255,255,0.02);
  }}
  .props-hdr-lbl {{
    font-size:11px; font-weight:800; color:rgba(255,255,255,0.55); letter-spacing:0.14em;
  }}
  .props-hdr-sub {{
    font-size:11px; font-weight:500; color:rgba(255,255,255,0.22);
  }}
  .props-rows {{ display:flex; flex-direction:column; }}
  .prop-row {{
    display:flex; align-items:center; gap:0;
    padding:10px 18px; min-height:44px;
    border-bottom:1px solid rgba(255,255,255,0.04);
  }}
  .prop-row:last-child {{ border-bottom:none; }}
  .prop-bar {{ width:3px; height:28px; border-radius:2px; flex-shrink:0; margin-right:14px; }}
  .prop-name {{
    font-size:15px; font-weight:800; color:#F0F0F8; width:130px; flex-shrink:0;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }}
  .prop-bet {{
    font-size:14px; font-weight:700; flex:1; white-space:nowrap;
  }}
  .prop-proj {{
    font-size:12px; font-weight:600; width:72px; text-align:right; flex-shrink:0;
  }}
  .prop-edge {{
    font-size:12px; font-weight:700; width:62px; text-align:right; flex-shrink:0;
  }}
  .prop-odds {{
    font-size:16px; font-weight:900; width:58px; text-align:right; flex-shrink:0;
  }}
  .prop-book {{
    font-size:13px; font-weight:700; color:rgba(255,255,255,0.82);
    width:88px; text-align:right; letter-spacing:0.06em; flex-shrink:0;
  }}

  /* ── Footer ── */
  .footer {{
    margin:18px 44px 0; padding-top:14px;
    border-top:1px solid {accent}25;
    display:flex; align-items:center; justify-content:space-between;
  }}
  .footer-left {{ font-size:13px; color:#555870; }}
  .footer-handle {{ font-size:19px; font-weight:800; color:{accent}; }}
  .footer-right {{ font-size:12px; color:#555870; }}
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
      <div class="brand-sub">A.I. Edge Detection  ·  @ChefTonyAIBets</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="ctx-pill">{context_label}</div>
    </div>
  </div>

  <div class="picks-list">
    {rows_html}
  </div>
  {props_html}
  <div class="footer">
    <div class="footer-left">{context_label}  ·  {date_str}</div>
    <div class="footer-handle">@ChefTonyAIBets</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""


def _build_nba_props_html(props: list[dict], d: date, context_label: str = "NBA") -> str:
    """NBA player props card — supports PTS, REB, AST, 3PM, PRA, BLK, STL."""
    date_str = d.strftime("%b %d, %Y").upper()
    is_playoff = "PLAYOFF" in context_label.upper() or "PLAY-IN" in context_label.upper()
    accent = "#FF6B00" if is_playoff else "#7B61FF"

    rows_html = ""
    for idx, prop in enumerate(props[:8]):
        market    = prop.get("market", "player_points")
        player    = str(prop.get("player", ""))
        matchup   = str(prop.get("matchup", ""))
        away_team, home_team = _parse_matchup(matchup)
        team_guess = prop.get("home_team", home_team)
        line      = prop.get("line", 0)
        direction = str(prop.get("direction", "OVER")).upper()
        projected = prop.get("projected", 0)
        edge_pct  = float(prop.get("edge_pct", 0) or 0)
        odds      = int(prop.get("odds", 0) or 0)
        book      = str(prop.get("book", ""))
        is_best   = idx == 0

        mkt_label  = _NBA_MARKET_LABEL.get(market, market.split("_")[-1].upper())
        mkt_color  = _NBA_MARKET_COLOR.get(market, "#6480FF")
        team_hex   = _NBA_HEX.get(team_guess, "#4080FF")
        team_logo  = _nba_logo_url(team_guess)
        ec         = "#39FF78" if edge_pct >= 8 else ("#FFA514" if edge_pct >= 5 else "#6480FF")
        odds_str   = f"{odds:+d}" if odds else ""
        dir_color  = "#39FF78" if direction == "OVER" else "#FF6B6B"

        proj_str = f"proj {projected:.1f} {mkt_label}"

        prop_stmt = f"{direction} {line} {mkt_label}"

        if team_logo:
            avatar_html = f'<img class="prop-logo" src="{team_logo}" alt="{team_guess}">'
        else:
            parts    = player.split()
            initials = (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else player[:2].upper()
            avatar_html = f'<span class="prop-initials">{initials}</span>'

        card_cls  = "prop-row best-prop" if is_best else "prop-row"
        top_badge = '<span class="top-badge">⚡ BEST BET</span>' if is_best else ""

        rows_html += f"""
    <div class="{card_cls}" style="--tc:{team_hex};--ec:{ec}">
      <div class="prop-bar" style="background:{mkt_color};box-shadow:0 0 14px {mkt_color}88"></div>
      <div class="prop-avatar" style="box-shadow:0 0 0 2px {team_hex},0 0 0 4px {team_hex}44,0 0 22px {team_hex}88">
        {avatar_html}
      </div>
      <div class="prop-body">
        <div class="prop-player-row">
          <span class="prop-player">{player}</span>
          <span class="prop-mkt" style="color:{mkt_color};background:{mkt_color}18;border-color:{mkt_color}40">{mkt_label}</span>
        </div>
        <div class="prop-stmt" style="color:{dir_color}">{prop_stmt}</div>
        <div class="prop-meta">
          <span class="prop-proj" style="color:{ec}">{proj_str}</span>
          <span class="prop-edge" style="color:{ec}">+{edge_pct:.1f}% edge</span>
          {top_badge}
        </div>
      </div>
      <div class="prop-odds-col">
        <span class="prop-odds" style="color:{ec};filter:drop-shadow(0 0 16px {ec})">{odds_str}</span>
        <span class="prop-book">{_clean_book(book)}</span>
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
  body {{ width:1080px; background:#070810; font-family:'Inter',sans-serif; overflow:hidden; }}

  .card-wrap {{
    width:1080px;
    background:
      radial-gradient(ellipse 80% 40% at 50% 0%, {accent}10 0%, transparent 70%),
      linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
    padding-bottom:28px;
  }}

  .header {{
    padding:28px 44px 22px;
    border-bottom:1px solid {accent}35;
    background:linear-gradient(180deg, {accent}08 0%, transparent 100%);
    display:flex; align-items:flex-end; justify-content:space-between;
  }}
  .brand {{ display:flex; align-items:baseline; line-height:1; }}
  .brand-chef {{ font-size:72px; font-weight:900; color:#F8F8FC; letter-spacing:-2px; }}
  .brand-bets {{ font-size:56px; font-weight:900; color:#FFBE00; letter-spacing:-1px; margin-left:4px; }}
  .brand-ai {{
    font-size:34px; font-weight:800; margin-left:10px; margin-bottom:6px;
    background:linear-gradient(135deg, #00D4E0, #7B61FF);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
  }}
  .brand-sub {{ font-size:16px; color:#555870; margin-top:8px; }}
  .header-right {{ text-align:right; }}
  .header-date {{ font-size:18px; font-weight:700; color:#F8F8FC; letter-spacing:0.05em; }}
  .context-pill {{
    display:inline-block; margin-top:8px; padding:5px 16px;
    background:{accent}18; border:1px solid {accent}50;
    border-radius:999px; font-size:12px; font-weight:800;
    color:{accent}; letter-spacing:0.10em;
  }}

  .section-lbl {{ margin:14px 44px 0; font-size:11px; font-weight:700; color:#555870; letter-spacing:0.14em; text-transform:uppercase; }}

  .props-list {{ padding:12px 44px 0; display:flex; flex-direction:column; gap:10px; }}

  .prop-row {{
    position:relative; display:flex; align-items:stretch; gap:0;
    background:rgba(255,255,255,0.03);
    border:1px solid rgba(255,255,255,0.07);
    border-radius:18px; overflow:hidden;
    min-height:108px;
  }}
  .best-prop {{
    background:linear-gradient(135deg, rgba(123,97,255,0.10) 0%, rgba(14,18,32,0.95) 55%);
    border:1px solid rgba(123,97,255,0.32);
    box-shadow:0 0 0 1px rgba(123,97,255,0.08), 0 0 36px rgba(123,97,255,0.06);
    min-height:124px;
  }}

  .prop-bar {{ width:6px; align-self:stretch; border-radius:3px 0 0 3px; flex-shrink:0; }}

  .prop-avatar {{
    width:76px; height:76px; border-radius:50%; flex-shrink:0;
    margin:auto 18px;
    display:flex; align-items:center; justify-content:center;
    background:radial-gradient(circle,rgba(255,255,255,0.15) 0%,rgba(255,255,255,0.06) 100%);
  }}
  .best-prop .prop-avatar {{ width:86px; height:86px; }}
  .prop-logo {{ width:80%; height:80%; object-fit:contain; border-radius:50%; padding:3px; }}
  .prop-initials {{ font-size:24px; font-weight:900; color:rgba(255,255,255,0.9); }}

  .prop-body {{ flex:1; min-width:0; display:flex; flex-direction:column; gap:5px; justify-content:center; }}

  .prop-player-row {{ display:flex; align-items:center; gap:10px; }}
  .prop-player {{ font-size:34px; font-weight:900; color:#FFFFFF; letter-spacing:-0.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; line-height:1.1; }}
  .best-prop .prop-player {{ font-size:40px; }}
  .prop-mkt {{ font-size:11px; font-weight:800; letter-spacing:0.06em; padding:2px 8px; border-radius:6px; border:1px solid; white-space:nowrap; flex-shrink:0; }}

  .prop-stmt {{ font-size:23px; font-weight:900; letter-spacing:-0.2px; white-space:nowrap; }}
  .best-prop .prop-stmt {{ font-size:27px; }}

  .prop-meta {{ display:flex; align-items:center; gap:12px; margin-top:2px; }}
  .prop-proj {{ font-size:13px; font-weight:700; }}
  .prop-edge {{ font-size:14px; font-weight:700; }}
  .top-badge {{
    font-size:13px; font-weight:700; color:#FFBE00;
    background:rgba(255,190,0,0.10); border:1px solid rgba(255,190,0,0.25);
    padding:3px 12px; border-radius:999px;
  }}

  .prop-odds-col {{ flex-shrink:0; min-width:150px; display:flex; flex-direction:column; align-items:flex-end; justify-content:center; padding-right:24px; gap:5px; }}
  .prop-odds {{ font-size:60px; font-weight:900; letter-spacing:-1px; line-height:1; }}
  .best-prop .prop-odds {{ font-size:68px; }}
  .prop-book {{ font-size:12px; font-weight:800; letter-spacing:0.08em; color:rgba(255,255,255,0.75); text-transform:uppercase; }}

  .footer {{
    margin:18px 44px 0; padding-top:16px;
    border-top:1px solid {accent}25;
    display:flex; align-items:center; justify-content:space-between;
  }}
  .footer-left {{ font-size:14px; color:#555870; }}
  .footer-handle {{ font-size:20px; font-weight:800; color:#FFBE00; }}
  .footer-right {{ font-size:13px; color:#555870; }}
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
      <div class="brand-sub">A.I. Edge Detection &nbsp;·&nbsp; @ChefTonyAIBets</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="context-pill">PLAYER PROPS</div>
    </div>
  </div>

  <div class="section-lbl">Best prop edges — {context_label}</div>

  <div class="props-list">
    {rows_html}
  </div>

  <div class="footer">
    <div class="footer-left">{context_label} Props &nbsp;·&nbsp; {date_str}</div>
    <div class="footer-handle">@ChefTonyAIBets</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""


def render_nba_pick_card_html(
    picks: list[dict],
    card_date: date | None = None,
    context_label: str = "NBA",
    top_props: list[dict] | None = None,
) -> Path | None:
    """Render NBA game picks card (spreads + moneylines + totals) to PNG."""
    d = card_date or date.today()
    html = _build_nba_html(picks, d, context_label, top_props=top_props)
    save_dir = OUTPUT_DIR / "basketball_nba" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "nba_pick_card.html", save_dir / "nba_pick_card.png")


def render_nba_spread_card_html(
    picks: list[dict],
    card_date: date | None = None,
    context_label: str = "NBA",
) -> Path | None:
    """Render NBA spread picks card to PNG."""
    d = card_date or date.today()
    spread_picks = [p for p in picks if p.get("market") == "spread"][:5]
    if not spread_picks:
        return None
    html = _build_nba_html(spread_picks, d, context_label)
    save_dir = OUTPUT_DIR / "basketball_nba" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "nba_spread_card.html", save_dir / "nba_spread_card.png")


def render_nba_moneyline_card_html(
    picks: list[dict],
    card_date: date | None = None,
    context_label: str = "NBA",
) -> Path | None:
    """Render NBA moneyline picks card to PNG."""
    d = card_date or date.today()
    ml_picks = [p for p in picks if p.get("market") in ("moneyline", "h2h")][:5]
    if not ml_picks:
        return None
    html = _build_nba_html(ml_picks, d, context_label)
    save_dir = OUTPUT_DIR / "basketball_nba" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "nba_ml_card.html", save_dir / "nba_ml_card.png")


def render_nba_totals_card_html(
    picks: list[dict],
    card_date: date | None = None,
    context_label: str = "NBA",
) -> Path | None:
    """Render NBA totals (O/U) picks card to PNG."""
    d = card_date or date.today()
    total_picks = [p for p in picks if p.get("market") == "total"][:5]
    if not total_picks:
        return None
    html = _build_nba_html(total_picks, d, context_label)
    save_dir = OUTPUT_DIR / "basketball_nba" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "nba_totals_card.html", save_dir / "nba_totals_card.png")


def render_nba_pick_of_day_html(
    pick: dict,
    card_date: date | None = None,
    context_label: str = "NBA",
) -> Path | None:
    """Render NBA pick of the day card to PNG."""
    d = card_date or date.today()
    # Reuse the NBA card builder with a single pick marked as best
    pick_copy = dict(pick)
    pick_copy["is_best"] = True
    html = _build_nba_html([pick_copy], d, context_label)
    save_dir = OUTPUT_DIR / "basketball_nba" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "nba_pick_of_day.html", save_dir / "nba_pick_of_day.png")


def render_nba_slate_card_html(
    picks: list[dict],
    card_date: date | None = None,
    context_label: str = "NBA",
) -> Path | None:
    """Render NBA full slate card (top 5 across all markets) to PNG."""
    d = card_date or date.today()
    # Convert NBA edge format to slate format
    slate_picks = []
    for p in picks[:5]:
        mkt = p.get("market", "spread")
        raw_team = p.get("team", "")
        matchup = p.get("matchup", "")
        away, home = _parse_matchup(matchup)

        # Strip bet line from team name: "Toronto Raptors +9.5" -> "Toronto Raptors"
        if mkt == "total":
            # Totals: label is "OVER/UNDER line @ matchup"
            direction = p.get("direction", "OVER")
            bet_line = p.get("bet_line", "")
            clean_team = f"{direction} {bet_line}"
            opponent = matchup
        else:
            # Strip trailing spread/line (last token if it looks like +/-number)
            parts = raw_team.rsplit(" ", 1)
            if len(parts) == 2 and parts[1] and (parts[1][0] in ("+", "-")) and parts[1][1:].replace(".", "").isdigit():
                clean_team = parts[0]
            else:
                clean_team = raw_team
            opponent = home if clean_team.lower() in away.lower() else away

        slate_picks.append({
            "type": mkt if mkt != "h2h" else "moneyline",
            "label": clean_team,
            "opponent": opponent,
            "odds": p.get("best_odds", 0),
            "edge": p.get("edge_pct", 0) / 100.0 if p.get("edge_pct", 0) > 1 else p.get("edge_pct", 0),
            "book": p.get("sportsbook", ""),
        })
    if not slate_picks:
        return None
    html = _build_slate_html(slate_picks, "basketball_nba", d)
    save_dir = OUTPUT_DIR / "basketball_nba" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "nba_slate_card.html", save_dir / "nba_slate_card.png")


def render_nba_props_card_html(
    props: list[dict],
    card_date: date | None = None,
    context_label: str = "NBA",
) -> Path | None:
    """Render NBA player props card to PNG."""
    d = card_date or date.today()
    html = _build_nba_props_html(props, d, context_label)
    save_dir = OUTPUT_DIR / "basketball_nba" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(
        html, save_dir / "nba_props_card.html", save_dir / "nba_props_card.png",
        target_height=2400,
    )


# ── IG Story card (1080×1920) ─────────────────────────────────────────────────

def _build_mlb_story_html(picks: list[dict], d: date) -> str:
    """Full-bleed 1080×1920 IG Story card — full slate, all markets, grouped by game."""
    date_str = d.strftime("%b %-d, %Y").upper()

    # ── Group picks by game (Matchup or Team vs Opponent) ──────────────────
    from collections import defaultdict

    def _game_key(p: dict) -> str:
        matchup = p.get("Matchup") or p.get("matchup")
        if matchup:
            return matchup
        team = p.get("Team") or p.get("team", "")
        opp  = p.get("Opponent") or p.get("opponent", "")
        return f"{team} vs {opp}" if opp else team

    def _away_home(game_key: str) -> tuple[str, str]:
        """Return (away, home) from 'Away @ Home' or 'Team vs Opp'."""
        if " @ " in game_key:
            parts = game_key.split(" @ ", 1)
            return parts[0].strip(), parts[1].strip()
        if " vs " in game_key:
            parts = game_key.split(" vs ", 1)
            return parts[0].strip(), parts[1].strip()
        return game_key, ""

    # preserve insertion order
    game_picks: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        game_picks[_game_key(p)].append(p)

    # market badge colors
    _mkt_colors = {
        "moneyline": ("#5aabff", "rgba(90,171,255,0.12)", "ML"),
        "spread":    ("#be6fff", "rgba(190,111,255,0.12)", "SPR"),
        "total":     ("#00D4E0", "rgba(0,212,224,0.10)",  "TOT"),
    }

    rows_html = ""
    for game_key, game_p in game_picks.items():
        away, home = _away_home(game_key)
        away_abbr = _team_abbr(away)
        home_abbr = _team_abbr(home)
        away_logo = _logo_url(away)
        home_logo = _logo_url(home)
        away_hex  = _MLB_HEX.get(away, "#4080FF")
        home_hex  = _MLB_HEX.get(home, "#4080FF")

        def _logo_img(url, abbr, hex_col, sz=52):
            if url:
                return f'<img class="sl-logo" src="{url}" alt="{abbr}" style="width:{sz}px;height:{sz}px;border-color:{hex_col}55;background:rgba(255,255,255,0.15)">'
            return f'<div class="sl-logo sl-logo-fb" style="width:{sz}px;height:{sz}px;background:{hex_col};font-size:{sz//3}px">{abbr}</div>'

        # build pick badges
        pick_badges = ""
        for p in game_p:
            mkt_raw  = str(p.get("Market") or p.get("market", "moneyline")).lower()
            mkt_key  = mkt_raw if mkt_raw in _mkt_colors else "moneyline"
            mc, mbg, mlbl = _mkt_colors[mkt_key]

            team     = p.get("Team") or p.get("team", "")
            odds_raw = p.get("BestOdds") or p.get("best_odds") or 0
            odds     = int(float(odds_raw)) if odds_raw else 0
            odds_str = f"{odds:+d}" if odds else "—"
            book     = str(p.get("Sportsbook") or p.get("sportsbook") or "")
            edge_raw = float(p.get("Edge") or p.get("edge_pct") or 0)
            edge_pct = edge_raw * 100 if edge_raw < 1 else edge_raw

            # pick label
            if mkt_key == "moneyline":
                pick_lbl = f"{_team_abbr(team)} ML"
            elif mkt_key == "spread":
                bet_line = p.get("BetLine") or p.get("bet_line", "")
                pick_lbl = f"{_team_abbr(team)} {bet_line}"
            else:
                # total — team field is like "OVER 8.0"
                pick_lbl = str(team)

            odds_color = "#39FF78" if (odds > 0 and edge_pct >= 8) else ("#ffffff" if odds < 0 else "#FFBE00")
            ec = "#39FF78" if edge_pct >= 10 else ("#FFBE00" if edge_pct >= 5 else "#8888aa")

            pick_badges += f"""
      <div class="sl-pick">
        <span class="sl-mkt-badge" style="color:{mc};background:{mbg};border-color:{mc}44">{mlbl}</span>
        <span class="sl-pick-lbl">{pick_lbl}</span>
        <span class="sl-pick-odds" style="color:{odds_color}">{odds_str}</span>
        <span class="sl-pick-edge" style="color:{ec}">+{edge_pct:.1f}%</span>
        <span class="sl-pick-book">{book}</span>
      </div>"""

        rows_html += f"""
  <div class="sl-game">
    <div class="sl-matchup-row">
      <div class="sl-logos">
        {_logo_img(away_logo, away_abbr, away_hex)}
        <div class="sl-vs">@</div>
        {_logo_img(home_logo, home_abbr, home_hex)}
      </div>
      <div class="sl-matchup-text">
        <span class="sl-away" style="color:{away_hex if away_hex != '#27251F' else '#aaaacc'}">{away_abbr}</span>
        <span class="sl-at"> @ </span>
        <span class="sl-home" style="color:{home_hex if home_hex != '#27251F' else '#aaaacc'}">{home_abbr}</span>
      </div>
    </div>
    <div class="sl-picks">{pick_badges}</div>
  </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#08090F; font-family:'Inter',sans-serif; }}

  .card-wrap {{
    width:1080px;
    min-height:1920px;
    background:#08090F;
    display:flex; flex-direction:column;
    padding:64px 56px 64px;
    position:relative; overflow:hidden;
  }}

  .card-wrap::before {{
    content:""; position:absolute;
    top:-180px; left:-180px; width:600px; height:600px;
    background:radial-gradient(circle, rgba(0,212,224,0.05) 0%, transparent 70%);
    pointer-events:none;
  }}

  /* ── Header ── */
  .s-header {{
    display:flex; justify-content:space-between; align-items:flex-start;
    margin-bottom:40px;
  }}
  .brand {{ display:flex; align-items:baseline; line-height:1; }}
  .brand-chef {{ font-size:64px; font-weight:900; color:#F8F8FC; letter-spacing:-2px; }}
  .brand-bets {{ font-size:64px; font-weight:900; color:#FFBE00; letter-spacing:-2px; }}
  .brand-ai {{
    font-size:26px; font-weight:800; margin-left:8px; margin-bottom:4px;
    background:linear-gradient(135deg,#39FF78,#00D4E0);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
  }}
  .brand-sub {{ font-size:18px; color:rgba(255,255,255,0.30); font-weight:500; margin-top:4px; }}

  .s-header-right {{ text-align:right; }}
  .s-date {{ font-size:20px; font-weight:700; color:rgba(255,255,255,0.40); letter-spacing:0.06em; margin-bottom:8px; }}
  .s-sport-pill {{
    display:inline-block;
    background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.12);
    border-radius:999px; padding:5px 18px;
    font-size:15px; font-weight:700; letter-spacing:0.10em; color:rgba(255,255,255,0.45);
  }}

  .s-divider {{
    height:1px;
    background:linear-gradient(90deg,transparent,rgba(255,255,255,0.10),transparent);
    margin-bottom:32px;
  }}

  .s-label {{
    font-size:13px; font-weight:700; letter-spacing:0.18em;
    color:rgba(255,255,255,0.22); text-transform:uppercase; margin-bottom:22px;
  }}

  /* ── Game blocks ── */
  .sl-game {{
    background:rgba(255,255,255,0.03);
    border:1px solid rgba(255,255,255,0.07);
    border-radius:18px;
    padding:18px 22px 16px;
    margin-bottom:14px;
  }}

  .sl-matchup-row {{
    display:flex; align-items:center; gap:14px;
    margin-bottom:12px;
    padding-bottom:10px;
    border-bottom:1px solid rgba(255,255,255,0.06);
  }}

  .sl-logos {{ display:flex; align-items:center; gap:6px; flex-shrink:0; }}

  .sl-logo {{
    border-radius:50%; object-fit:contain;
    padding:4px; border:2px solid;
    box-shadow:0 0 10px rgba(255,255,255,0.06);
  }}
  .sl-logo-fb {{
    border-radius:50%; display:flex; align-items:center; justify-content:center;
    font-weight:900; color:#fff; border:2px solid rgba(255,255,255,0.20);
  }}

  .sl-vs {{ font-size:13px; font-weight:600; color:rgba(255,255,255,0.20); }}

  .sl-matchup-text {{ font-size:26px; font-weight:800; letter-spacing:-0.3px; }}
  .sl-at {{ color:rgba(255,255,255,0.25); }}

  /* ── Pick rows ── */
  .sl-picks {{ display:flex; flex-direction:column; gap:8px; }}

  .sl-pick {{
    display:flex; align-items:center; gap:10px;
    min-height:36px;
  }}

  .sl-mkt-badge {{
    font-size:11px; font-weight:800; letter-spacing:0.10em;
    padding:3px 9px; border-radius:6px; border:1px solid;
    flex-shrink:0; width:42px; text-align:center;
  }}

  .sl-pick-lbl {{
    font-size:22px; font-weight:800; color:#F0F0F8;
    letter-spacing:-0.3px; flex:1;
  }}

  .sl-pick-odds {{
    font-size:32px; font-weight:900; letter-spacing:-1px;
    flex-shrink:0; min-width:96px; text-align:right;
  }}

  .sl-pick-edge {{
    font-size:13px; font-weight:700; flex-shrink:0; min-width:60px; text-align:right;
  }}

  .sl-pick-book {{
    font-size:13px; font-weight:700;
    color:rgba(255,255,255,0.55); flex-shrink:0;
    min-width:90px; text-align:right; letter-spacing:0.04em;
  }}

  /* ── Footer ── */
  .s-footer {{
    margin-top:auto; padding-top:24px;
    border-top:1px solid rgba(255,255,255,0.07);
    display:flex; justify-content:space-between; align-items:center;
  }}
  .s-footer-l {{ font-size:16px; color:rgba(255,255,255,0.22); font-weight:500; }}
  .s-footer-handle {{ font-size:26px; font-weight:900; color:#FFBE00; }}
  .s-footer-r {{ font-size:16px; color:rgba(255,255,255,0.22); }}
  .s-disclaimer {{
    text-align:center; margin-top:16px;
    font-size:14px; color:rgba(255,255,255,0.16); font-weight:500;
  }}
</style>
</head>
<body>
<div class="card-wrap">
  <div class="s-header">
    <div>
      <div class="brand">
        <span class="brand-chef">ChefTony</span><span class="brand-bets">Bets</span>
        <span class="brand-ai">AI</span>
      </div>
      <div class="brand-sub">A.I. Edge Detection &nbsp;·&nbsp; @ChefTonyAIBets</div>
    </div>
    <div class="s-header-right">
      <div class="s-date">{date_str}</div>
      <div class="s-sport-pill">MLB SLATE</div>
    </div>
  </div>

  <div class="s-divider"></div>
  <div class="s-label">Today's Full Slate — All Picks</div>

  {rows_html}

  <div class="s-footer">
    <div class="s-footer-l">MLB · {date_str}</div>
    <div class="s-footer-handle">@ChefTonyAIBets</div>
    <div class="s-footer-r">AI Verified</div>
  </div>
  <div class="s-disclaimer">Not financial advice. Bet responsibly. 21+</div>
</div>
</body>
</html>"""


def render_mlb_story_card(
    picks: list[dict],
    card_date: date | None = None,
) -> Path | None:
    """Render 1080×1920 IG Story card with all MLB ML picks."""
    d = card_date or date.today()
    html = _build_mlb_story_html(picks, d)
    save_dir = OUTPUT_DIR / "baseball_mlb" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(
        html,
        save_dir / "mlb_story_card.html",
        save_dir / "mlb_story_card.png",
        target_height=1920,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pick of the Day card — hero single pick
# ─────────────────────────────────────────────────────────────────────────────

def _build_pick_of_day_html(pick: dict, sport: str, d: date) -> str:
    date_str  = d.strftime("%b %d, %Y").upper()
    team      = str(pick.get("Team") or pick.get("team") or "")
    opponent  = str(pick.get("Opponent") or pick.get("opponent") or "")
    odds      = int(pick.get("BestOdds") or pick.get("best_odds") or pick.get("odds") or 0)
    book      = str(pick.get("Sportsbook") or pick.get("sportsbook") or pick.get("book") or "")
    model_prob = float(pick.get("ModelProb") or pick.get("model_prob") or 0)
    edge      = float(pick.get("Edge") or pick.get("edge") or 0)
    edge_pct  = round(edge * 100, 1) if abs(edge) < 1 else round(edge, 1)
    why       = str(pick.get("Why") or pick.get("why") or "")
    market    = str(pick.get("Market") or pick.get("market") or "moneyline").upper()
    bet_line  = pick.get("BetLine") or pick.get("bet_line") or ""

    team_hex  = _MLB_HEX.get(team, "#4080FF")
    logo_url  = _logo_url(team)
    if logo_url:
        logo_html = f'<img class="pod-logo" src="{logo_url}" alt="{team}">'
    else:
        abbr = _ESPN_ABBR.get(team, team[:3].upper())
        logo_html = f'<div class="pod-logo pod-logo-fb" style="background:{team_hex}">{abbr}</div>'

    odds_str  = f"{odds:+d}" if odds else "–"
    conf_pct  = round(model_prob * 100, 1)

    label_map = {"MONEYLINE": "MONEYLINE", "SPREAD": f"RUN LINE {bet_line}", "TOTAL": f"TOTAL {bet_line}"}
    bet_label = label_map.get(market, market)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Inter', sans-serif;
    background: #0A0A0F;
    width: 1080px; height: 1080px;
    display: flex; align-items: center; justify-content: center;
  }}
  .pod-wrap {{
    width: 960px; height: 960px;
    background: linear-gradient(135deg, #0F1117 0%, #161B2E 50%, #0F1117 100%);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 32px;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    gap: 28px; padding: 56px;
    position: relative; overflow: hidden;
  }}
  .pod-wrap::before {{
    content: '';
    position: absolute; inset: 0;
    background: radial-gradient(ellipse at 50% 0%, {team_hex}22 0%, transparent 60%);
  }}
  .pod-badge {{
    background: linear-gradient(90deg, {team_hex}, {team_hex}CC);
    color: #fff; font-size: 13px; font-weight: 700;
    letter-spacing: 3px; text-transform: uppercase;
    padding: 6px 20px; border-radius: 999px;
  }}
  .pod-logo {{ width: 140px; height: 140px; object-fit: contain; filter: drop-shadow(0 0 24px {team_hex}88); }}
  .pod-logo-fb {{
    width: 140px; height: 140px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 36px; font-weight: 900; color: #fff;
  }}
  .pod-team {{
    font-size: 52px; font-weight: 900; color: #FFFFFF;
    text-align: center; line-height: 1.1;
    text-shadow: 0 0 40px {team_hex}66;
  }}
  .pod-vs {{ font-size: 18px; color: #666; font-weight: 500; }}
  .pod-opponent {{ font-size: 26px; color: #AAA; font-weight: 600; }}
  .pod-bet {{
    display: flex; align-items: center; gap: 16px;
  }}
  .pod-bet-type {{
    font-size: 13px; font-weight: 700; letter-spacing: 2px;
    color: #888; text-transform: uppercase;
  }}
  .pod-odds {{
    font-size: 64px; font-weight: 900;
    background: linear-gradient(90deg, {team_hex}, #FFFFFF);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
  }}
  .pod-book {{ font-size: 15px; color: #555; font-weight: 600; }}
  .pod-stats {{
    display: flex; gap: 32px; align-items: center;
  }}
  .pod-stat {{
    text-align: center;
  }}
  .pod-stat-val {{ font-size: 28px; font-weight: 800; color: #FFF; }}
  .pod-stat-lbl {{ font-size: 11px; font-weight: 600; color: #555; letter-spacing: 1.5px; text-transform: uppercase; margin-top: 4px; }}
  .pod-why {{
    font-size: 14px; color: #666; font-style: italic;
    text-align: center; max-width: 600px; line-height: 1.5;
  }}
  .pod-footer {{
    position: absolute; bottom: 28px; left: 0; right: 0;
    display: flex; justify-content: space-between; padding: 0 48px;
    font-size: 12px; color: #333; font-weight: 600;
  }}
</style>
</head>
<body>
<div class="pod-wrap">
  <div class="pod-badge">PICK OF THE DAY</div>
  {logo_html}
  <div class="pod-team">{team}</div>
  <div style="display:flex;align-items:center;gap:12px">
    <span class="pod-vs">vs</span>
    <span class="pod-opponent">{opponent}</span>
  </div>
  <div style="text-align:center">
    <div class="pod-bet-type">{bet_label}</div>
    <div class="pod-odds">{odds_str}</div>
    <div class="pod-book">{book}</div>
  </div>
  <div class="pod-stats">
    <div class="pod-stat">
      <div class="pod-stat-val">{conf_pct:.0f}%</div>
      <div class="pod-stat-lbl">Model Conf</div>
    </div>
    <div style="width:1px;height:40px;background:#333"></div>
    <div class="pod-stat">
      <div class="pod-stat-val">{edge_pct:+.1f}%</div>
      <div class="pod-stat-lbl">Edge vs Line</div>
    </div>
    <div style="width:1px;height:40px;background:#333"></div>
    <div class="pod-stat">
      <div class="pod-stat-val">AI</div>
      <div class="pod-stat-lbl">Verified</div>
    </div>
  </div>
  {"<div class='pod-why'>" + why + "</div>" if why else ""}
  <div class="pod-footer">
    <span>MLB · {date_str}</span>
    <span>@ChefTonyAIBets</span>
    <span>Not financial advice</span>
  </div>
</div>
</body>
</html>"""


def render_pick_of_day_card_html(
    pick: dict,
    sport: str = "mlb",
    card_date: date | None = None,
) -> Path | None:
    """Render hero 'Pick of the Day' card to PNG (1080×1080 square)."""
    d = card_date or date.today()
    html = _build_pick_of_day_html(pick, sport, d)
    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "pick_of_day_card.html", save_dir / "pick_of_day_card.png")


# ─────────────────────────────────────────────────────────────────────────────
# Slate card — full day overview, all pick types
# ─────────────────────────────────────────────────────────────────────────────

def _build_slate_html(picks: list[dict], sport: str, d: date) -> str:
    date_str  = d.strftime("%b %d, %Y").upper()
    sport_lbl = _SPORT_LABELS.get(sport.lower(), sport.upper())

    _type_label = {
        "moneyline": "ML",
        "spread":    "RL",
        "total":     "O/U",
        "nrfi":      "NRFI",
        "prop":      "PROP",
    }
    _type_color = {
        "moneyline": "#4CAF50",
        "spread":    "#2196F3",
        "total":     "#FF9800",
        "nrfi":      "#9C27B0",
        "prop":      "#00BCD4",
    }

    is_nba = sport.lower() in ("basketball_nba", "nba")

    rows_html = ""
    for i, p in enumerate(picks):
        ptype   = str(p.get("type", "moneyline")).lower()
        label   = str(p.get("label") or p.get("team") or "")
        opp     = str(p.get("opponent") or "")
        odds    = p.get("odds", 0) or 0
        edge    = float(p.get("edge") or 0)
        book    = str(p.get("book") or "")
        t_label = _type_label.get(ptype, ptype.upper())
        t_color = _type_color.get(ptype, "#888")
        odds_str = f"{int(odds):+d}" if odds else ""
        edge_pct = round(edge * 100, 1) if abs(edge) < 1 else round(edge, 1)
        edge_color = "#39FF78" if edge_pct >= 5 else ("#FFA514" if edge_pct >= 2 else "#666")
        is_best = i == 0

        # Team logo and hex color — use sport-appropriate lookup
        if is_nba:
            team_hex = _NBA_HEX.get(label, "#4080FF")
            logo_url = _nba_logo_url(label)
        else:
            team_hex = _MLB_HEX.get(label, "#4080FF")
            logo_url = _logo_url(label)
        if logo_url:
            logo_html = f'<img class="s-logo" src="{logo_url}" alt="{label}" style="--tc:{team_hex}">'
        else:
            initials = "".join(w[0] for w in label.split()[:2]).upper()
            logo_html = f'<div class="s-logo s-logo-fb" style="background:{team_hex}">{initials}</div>'

        card_cls = "s-card s-best" if is_best else "s-card"
        top_play = '<span class="s-top">TOP PLAY</span>' if is_best else ""

        rows_html += f"""
    <div class="{card_cls}" style="--tc:{team_hex};--ec:{edge_color}">
      <div class="s-bar" style="background:{t_color};box-shadow:0 0 12px {t_color}"></div>
      <div class="s-logo-wrap">{logo_html}</div>
      <div class="s-info">
        <div class="s-team-row">
          <span class="s-team">{label}</span>
          <span class="s-badge" style="background:{t_color}22;color:{t_color};border-color:{t_color}44">{t_label}</span>
        </div>
        <div class="s-opp">{"vs " + opp if opp else ""}</div>
        <div class="s-meta">
          <span class="s-edge" style="color:{edge_color}">{edge_pct:+.1f}% edge</span>
          {top_play}
        </div>
      </div>
      <div class="s-odds-wrap">
        <span class="s-odds" style="color:{edge_color}">{odds_str}</span>
        {'<span class="s-book">' + book + '</span>' if book else ''}
      </div>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Inter', -apple-system, sans-serif; background: #070810; width: 1080px; overflow: hidden; }}

  .s-wrap {{
    width: 1080px;
    background:
      radial-gradient(ellipse 80% 40% at 50% 0%, rgba(64,128,255,0.07) 0%, transparent 70%),
      linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
    padding-bottom: 28px;
  }}

  .s-header {{
    padding: 28px 44px 22px;
    border-bottom: 1px solid rgba(64,128,255,0.25);
    background: linear-gradient(180deg, rgba(64,128,255,0.06) 0%, transparent 100%);
    display: flex; align-items: flex-end; justify-content: space-between;
  }}
  .s-brand {{ display: flex; align-items: baseline; gap: 0; line-height: 1; }}
  .s-brand-chef {{ font-size: 72px; font-weight: 900; color: #F8F8FC; letter-spacing: -2px; }}
  .s-brand-bets {{ font-size: 56px; font-weight: 900; color: #FFBE00; letter-spacing: -1px; margin-left: 4px; }}
  .s-brand-ai {{ font-size: 34px; font-weight: 800; background: linear-gradient(135deg, #00D4E0, #7B61FF);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    margin-left: 10px; filter: drop-shadow(0 0 12px rgba(0,210,220,0.5)); }}
  .s-brand-sub {{ font-size: 16px; color: #555870; font-weight: 400; margin-top: 8px; }}
  .s-header-right {{ text-align: right; }}
  .s-header-date {{ font-size: 18px; font-weight: 700; color: #F8F8FC; letter-spacing: 0.05em; }}
  .s-sport-pill {{
    display: inline-block; margin-top: 8px; padding: 5px 14px;
    background: rgba(64,128,255,0.15); border: 1px solid rgba(64,128,255,0.35);
    border-radius: 999px; font-size: 13px; font-weight: 700; color: #4080FF; letter-spacing: 0.08em;
  }}

  .s-list {{ padding: 18px 44px 0; display: flex; flex-direction: column; gap: 12px; }}

  .s-card {{
    position: relative; display: flex; align-items: center; gap: 0;
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
    border-radius: 20px; overflow: hidden; padding: 20px 28px 20px 0;
    min-height: 110px; backdrop-filter: blur(4px);
  }}
  .s-best {{
    background: linear-gradient(135deg, color-mix(in srgb, var(--tc) 15%, #0E1220) 0%, rgba(14,18,32,0.95) 50%);
    border: 1px solid rgba(255,190,0,0.4);
    box-shadow: 0 0 40px rgba(255,190,0,0.08), inset 0 1px 0 rgba(255,255,255,0.06);
    min-height: 120px;
  }}

  .s-bar {{ width: 6px; align-self: stretch; border-radius: 3px; margin-right: 16px; flex-shrink: 0; }}

  .s-logo-wrap {{ width: 72px; height: 72px; flex-shrink: 0; margin-right: 20px; }}
  .s-best .s-logo-wrap {{ width: 80px; height: 80px; }}
  .s-logo {{
    width: 100%; height: 100%; object-fit: contain; border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,0.15) 0%, rgba(255,255,255,0.06) 100%);
    padding: 5px;
    box-shadow: 0 0 0 2px var(--tc), 0 0 20px color-mix(in srgb, var(--tc) 50%, transparent);
  }}
  .s-logo-fb {{
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 900; color: white;
  }}

  .s-info {{ flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }}
  .s-team-row {{ display: flex; align-items: center; gap: 10px; }}
  .s-team {{ font-size: 32px; font-weight: 900; color: #F8F8FC; letter-spacing: -0.5px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.1; }}
  .s-best .s-team {{ font-size: 36px; }}
  .s-badge {{
    font-size: 10px; font-weight: 700; letter-spacing: 1px;
    padding: 3px 8px; border-radius: 999px; border: 1px solid; flex-shrink: 0;
  }}
  .s-opp {{ font-size: 15px; color: #6B7090; font-weight: 500; }}
  .s-meta {{ display: flex; align-items: center; gap: 12px; margin-top: 2px; }}
  .s-edge {{ font-size: 14px; font-weight: 700; letter-spacing: 0.03em; }}
  .s-top {{
    font-size: 11px; font-weight: 700; color: #FFBE00;
    background: rgba(255,190,0,0.1); border: 1px solid rgba(255,190,0,0.25);
    padding: 2px 10px; border-radius: 999px; letter-spacing: 0.04em;
  }}

  .s-odds-wrap {{ flex-shrink: 0; text-align: right; min-width: 130px;
    display: flex; flex-direction: column; align-items: flex-end; }}
  .s-odds {{ font-size: 52px; font-weight: 900; letter-spacing: -1px; line-height: 1;
    filter: drop-shadow(0 0 16px var(--ec)); }}
  .s-best .s-odds {{ font-size: 60px; }}
  .s-book {{ display: block; margin-top: 6px; font-size: 12px; font-weight: 800;
    letter-spacing: 0.08em; text-transform: uppercase; color: rgba(255,255,255,0.6); }}

  .s-footer {{
    margin: 24px 44px 0; padding-top: 16px;
    border-top: 1px solid rgba(255,255,255,0.06);
    display: flex; justify-content: space-between;
    font-size: 12px; color: #333; font-weight: 600;
  }}
  .s-footer-handle {{ color: rgba(64,128,255,0.8); font-weight: 700; }}
</style>
</head>
<body>
<div class="s-wrap">
  <div class="s-header">
    <div>
      <div class="s-brand">
        <span class="s-brand-chef">Chef</span><span class="s-brand-chef">Tony</span><span class="s-brand-bets">Bets</span>
        <span class="s-brand-ai">AI</span>
      </div>
      <div class="s-brand-sub">A.I. Edge Detection · @ChefTonyAIBets</div>
    </div>
    <div class="s-header-right">
      <div class="s-header-date">{date_str}</div>
      <div class="s-sport-pill">FULL SLATE</div>
    </div>
  </div>
  <div class="s-list">
    {rows_html}
  </div>
  <div class="s-footer">
    <span>{sport_lbl} · {date_str}</span>
    <span class="s-footer-handle">@ChefTonyAIBets</span>
  </div>
</div>
</body>
</html>"""


def render_slate_card_html(
    picks: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
) -> Path | None:
    """Render full-slate overview card (all bet types) to PNG."""
    d = card_date or date.today()
    html = _build_slate_html(picks, sport, d)
    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "slate_card.html", save_dir / "slate_card.png")

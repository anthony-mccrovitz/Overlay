"""
HTML/CSS pick card renderer — Overlay AI.

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


# Sportsbook brand colors and abbreviations for inline badges
_BOOK_BRANDS: dict[str, tuple[str, str, str]] = {
    # key (lowercase)  → (bg_color, text_color, display_label)
    "draftkings":      ("#1B5E20", "#FFFFFF", "DraftKings"),
    "fanduel":         ("#1493FF", "#FFFFFF", "FanDuel"),
    "betmgm":          ("#D4AF37", "#000000", "BetMGM"),
    "betrivers":       ("#003087", "#FFFFFF", "BetRivers"),
    "hard rock bet":   ("#C8102E", "#FFFFFF", "Hard Rock"),
    "thescore bet":    ("#E4002B", "#FFFFFF", "theScore"),
    "fliff":           ("#6C2BD9", "#FFFFFF", "Fliff"),
    "caesars":         ("#002D72", "#FFD700", "Caesars"),
    "fanatics":        ("#E4002B", "#FFFFFF", "Fanatics"),
    "novig":           ("#0A0A0A", "#FFFFFF", "Novig"),
    "betfred":         ("#B22222", "#FFFFFF", "Betfred"),
    "pointsbet":       ("#FF0000", "#FFFFFF", "PointsBet"),
}


def _book_badge_html(book: str, font_size: int = 15, padding: str = "6px 16px", radius: str = "8px") -> str:
    """Return an inline HTML badge for a sportsbook using brand colors."""
    key = book.lower().strip()
    if key in _BOOK_BRANDS:
        bg, fg, label = _BOOK_BRANDS[key]
    else:
        clean = _clean_book(book)
        bg, fg, label = "#1E1E1E", "#888888", clean
    return (
        f'<span style="background:{bg};color:{fg};font-size:{font_size}px;font-weight:800;'
        f'padding:{padding};border-radius:{radius};letter-spacing:0.5px;'
        f'white-space:nowrap;display:inline-block">{label}</span>'
    )


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


_NBA_LOGO_B64_CACHE: dict[str, str] = {}

def _nba_logo_url(team: str) -> str:
    """Return base64 data URI for an NBA team logo, fetched once and cached."""
    abbr = _NBA_ESPN_ABBR.get(team)
    if not abbr:
        return ""
    if abbr in _NBA_LOGO_B64_CACHE:
        return _NBA_LOGO_B64_CACHE[abbr]
    try:
        import requests, base64
        url = f"https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/{abbr}.png"
        r = requests.get(url, timeout=6)
        if r.status_code == 200 and len(r.content) > 1000:
            b64 = base64.b64encode(r.content).decode()
            data_uri = f"data:image/png;base64,{b64}"
            _NBA_LOGO_B64_CACHE[abbr] = data_uri
            return data_uri
    except Exception:
        pass
    _NBA_LOGO_B64_CACHE[abbr] = ""
    return ""


def _nba_team_abbr(name: str) -> str:
    return _NBA_TEAM_ABBR.get(name, name[:3].upper())


_PLAYER_HEADSHOT_CACHE: dict[str, str] = {}

def _strip_name_suffix(name: str) -> str:
    """Remove generational suffixes (II, III, IV, Jr., Sr.) from player names for API lookup."""
    import re
    return re.sub(r"\s+(II|III|IV|Jr\.?|Sr\.?)\s*$", "", name.strip(), flags=re.IGNORECASE).strip()


def _nba_player_headshot_b64(player_name: str) -> str:
    """Return base64 data URI for a player headshot, or '' on failure."""
    if player_name in _PLAYER_HEADSHOT_CACHE:
        return _PLAYER_HEADSHOT_CACHE[player_name]
    try:
        from nba_api.stats.static import players as _nba_players
        import requests, base64
        # Try exact name first, then fallback to stripped suffix
        results = _nba_players.find_players_by_full_name(player_name)
        if not results:
            stripped = _strip_name_suffix(player_name)
            if stripped and stripped != player_name:
                results = _nba_players.find_players_by_full_name(stripped)
        if results:
            pid = results[0]["id"]
            cdn_url = f"https://ak-static.cms.nba.com/wp-content/uploads/headshots/nba/latest/260x190/{pid}.png"
            resp = requests.get(cdn_url, timeout=5)
            if resp.status_code == 200:
                b64 = base64.b64encode(resp.content).decode()
                data_uri = f"data:image/png;base64,{b64}"
                _PLAYER_HEADSHOT_CACHE[player_name] = data_uri
                return data_uri
    except Exception:
        pass
    _PLAYER_HEADSHOT_CACHE[player_name] = ""
    return ""


_MLB_PLAYER_ID_CACHE: dict[str, int] = {}

def _mlb_player_headshot_b64(player_name: str) -> str:
    """Return base64 data URI for an MLB player headshot, or '' on failure."""
    cache_key = f"mlb:{player_name}"
    if cache_key in _PLAYER_HEADSHOT_CACHE:
        return _PLAYER_HEADSHOT_CACHE[cache_key]
    try:
        import requests, base64, re
        # Search MLB Stats API for player ID
        clean = re.sub(r"\s+(II|III|IV|Jr\.?|Sr\.?)\s*$", "", player_name.strip(), flags=re.IGNORECASE).strip()
        if clean not in _MLB_PLAYER_ID_CACHE:
            resp = requests.get(
                "https://statsapi.mlb.com/api/v1/people/search",
                params={"names": clean, "active": "true", "sportIds": 1},
                timeout=6,
            )
            if resp.status_code == 200:
                people = resp.json().get("people", [])
                if people:
                    _MLB_PLAYER_ID_CACHE[clean] = people[0]["id"]
        pid = _MLB_PLAYER_ID_CACHE.get(clean)
        if pid:
            img_url = (
                f"https://img.mlbstatic.com/mlb-photos/image/upload/"
                f"w_213,q_auto:best/v1/people/{pid}/headshot/67/current"
            )
            ir = requests.get(img_url, timeout=6)
            if ir.status_code == 200 and len(ir.content) > 5000:
                b64 = base64.b64encode(ir.content).decode()
                ext = "jpeg" if ir.headers.get("content-type", "").endswith("jpeg") else "png"
                data_uri = f"data:image/{ext};base64,{b64}"
                _PLAYER_HEADSHOT_CACHE[cache_key] = data_uri
                return data_uri
    except Exception:
        pass
    _PLAYER_HEADSHOT_CACHE[cache_key] = ""
    return ""


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


_MLB_LOGO_B64_CACHE: dict[str, str] = {}

def _logo_url(team: str) -> str:
    """Return base64 data URI for an MLB team logo, fetched once and cached."""
    abbr = _ESPN_ABBR.get(team)
    if not abbr:
        return ""
    if abbr in _MLB_LOGO_B64_CACHE:
        return _MLB_LOGO_B64_CACHE[abbr]
    try:
        import requests, base64
        url = f"https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/{abbr}.png"
        r = requests.get(url, timeout=6)
        if r.status_code == 200 and len(r.content) > 1000:
            b64 = base64.b64encode(r.content).decode()
            data_uri = f"data:image/png;base64,{b64}"
            _MLB_LOGO_B64_CACHE[abbr] = data_uri
            return data_uri
    except Exception:
        pass
    _MLB_LOGO_B64_CACHE[abbr] = ""
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



# ── V2 card design helpers ────────────────────────────────────────────────────

_MUT    = "rgba(255,255,255,0.65)"   # readable secondary text
_BORDER = "rgba(255,255,255,0.09)"   # dividers / borders


def _v2_book_badge(book: str) -> str:
    key = book.lower().strip()
    if key in _BOOK_BRANDS:
        bg, fg, label = _BOOK_BRANDS[key]
    else:
        bg, fg, label = "#1E293B", "rgba(255,255,255,0.75)", _clean_book(book)
    return (
        f'<span style="background:{bg};color:{fg};font-size:15px;font-weight:800;'
        f'padding:5px 16px;border-radius:8px;letter-spacing:0.04em;white-space:nowrap">'
        f'{label}</span>'
    )


def _v2_data_strip(ec: str, prob_pct: float, edge_pct: float, book: str) -> str:
    lbl = f"font-size:13px;color:{_MUT};letter-spacing:0.1em;font-family:'Courier New',monospace;margin-bottom:5px"
    return (
        f'<div style="display:flex;gap:0;margin-top:14px;padding-top:14px;border-top:1px solid {_BORDER}">'
        f'<div style="flex:1;text-align:center">'
        f'<div style="{lbl}">WIN PROB</div>'
        f'<div style="font-size:22px;font-weight:900;color:{ec}">{prob_pct}%</div>'
        f'</div>'
        f'<div style="width:1px;background:{_BORDER}"></div>'
        f'<div style="flex:1;text-align:center">'
        f'<div style="{lbl}">ML EDGE</div>'
        f'<div style="font-size:22px;font-weight:900;color:{ec}">+{edge_pct:.1f}%</div>'
        f'</div>'
        f'<div style="width:1px;background:{_BORDER}"></div>'
        f'<div style="flex:1;text-align:center">'
        f'<div style="{lbl}">BET AT</div>'
        f'<div>{_v2_book_badge(book)}</div>'
        f'</div>'
        f'</div>'
    )


def _v2_bet_pill(label: str) -> str:
    return (
        f'<span style="font-size:16px;font-weight:800;color:{_MUT};'
        f'background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.14);'
        f'padding:5px 16px;border-radius:999px;letter-spacing:0.08em">{label}</span>'
    )


def _v2_logo_img(url: str, abbr: str, color: str, size: int) -> str:
    if url:
        return (
            f'<img src="{url}" style="width:{size}px;height:{size}px;'
            f'object-fit:contain;filter:drop-shadow(0 0 16px {color});'
            f'padding:4px;flex-shrink:0">'
        )
    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;'
        f'background:{color};display:flex;align-items:center;justify-content:center;'
        f'font-size:20px;font-weight:900;color:#fff;flex-shrink:0">{abbr}</div>'
    )


# RGB lookup for team-color gradient backgrounds
_TEAM_RGB: dict[str, str] = {
    "#552583": "85,37,131",   # Lakers
    "#007AC1": "0,122,193",   # Thunder
    "#C8102E": "200,16,46",   # several
    "#860038": "134,0,56",    # Cavaliers
    "#1D1160": "29,17,96",    # Suns
    "#006BB6": "0,107,182",   # Knicks
    "#002D62": "0,45,98",     # Pacers
    "#0E2240": "14,34,64",    # Nuggets
    "#00471B": "0,71,27",     # Bucks
    "#007A33": "0,122,51",    # Celtics
    # MLB
    "#A7192F": "167,25,47",   "#CE1141": "206,17,65",
    "#DF6D1D": "223,109,29",  "#BD3039": "189,48,57",
    "#0E3386": "14,51,134",   "#27251F": "39,37,31",
    "#C6001F": "198,0,31",    "#003865": "0,56,101",
    "#330071": "51,0,113",    "#0C2340": "12,35,64",
    "#002D62": "0,45,98",     "#004687": "0,70,135",
    "#BA0021": "186,0,33",    "#005A9C": "0,90,156",
    "#00A3E0": "0,163,224",   "#002855": "0,40,85",
    "#002B7F": "0,43,127",    "#002D72": "0,45,114",
    "#003831": "0,56,49",     "#E8182A": "232,24,42",
    "#FDB827": "253,184,39",  "#2F241D": "47,36,29",
    "#FD5A1E": "253,90,30",   "#005C5C": "0,92,92",
    "#C41E3A": "196,30,58",   "#092CB8": "9,44,184",
    "#003278": "0,50,120",    "#134A8E": "19,74,142",
    "#AB0003": "171,0,3",
}


def _build_html(picks: list[dict], sport: str, d: date, card_type: str = "moneyline", record_str: str = "") -> str:
    sport_lbl = _SPORT_LABELS.get(sport.lower(), sport.upper())
    date_str  = d.strftime("%b %d, %Y").upper()
    is_nba    = sport.lower() in ("nba", "basketball_nba")

    pick_rows_html = ""
    for idx, pick in enumerate(picks[:5]):
        market     = str(pick.get("Market", "moneyline") or "moneyline").lower()
        team       = str(pick.get("Team", "") or "")
        opponent   = str(pick.get("Opponent", "") or "")
        bet_line   = str(pick.get("BetLine", "") or "")
        raw_edge   = float(pick.get("Edge", 0) or 0)
        odds_val   = _odds_int(pick.get("BestOdds", 0))
        book       = str(pick.get("Sportsbook", "") or "").strip()
        matchup    = str(pick.get("Matchup", "") or opponent)
        model_prob = float(pick.get("ModelProb", 0) or 0)
        is_best    = idx == 0
        odds_str   = f"{odds_val:+d}" if odds_val else ""
        prob_pct   = round(model_prob * 100, 1)

        # Edge normalisation: moneyline stored as decimal in card dict, others as percentage
        if market == "moneyline":
            edge_pct = round(raw_edge * 100, 1)
        else:
            edge_pct = round(raw_edge, 1)

        # Odds gradient + edge color
        odds_grad = "linear-gradient(180deg,#00FF9D,#00C8FF)" if edge_pct >= 12 else "linear-gradient(180deg,#FFD700,#FF8C00)"
        ec        = "#00FF9D" if edge_pct >= 12 else "#FFD700"

        # ── TOTAL ──────────────────────────────────────────────────────────────
        if market == "total" or card_type == "total":
            direction = str(pick.get("Direction", "OVER")).upper()
            line_val  = str(pick.get("MarketLine") or pick.get("BetLine") or "")
            dir_c     = "#00FF9D" if direction == "OVER" else "#FF6B6B"
            dir_grad  = "linear-gradient(180deg,#00FF9D,#00C8FF)" if direction == "OVER" else "linear-gradient(180deg,#FF6B6B,#FF3030)"

            # Parse away / home from matchup
            parts     = matchup.replace(" @ ", "@").split("@")
            away_team = parts[0].strip() if parts else ""
            home_team = parts[1].strip() if len(parts) > 1 else ""
            if not away_team: away_team = str(pick.get("AwayTeam", ""))
            if not home_team: home_team = str(pick.get("HomeTeam", ""))

            if is_nba:
                away_logo = _nba_logo_url(away_team)
                home_logo = _nba_logo_url(home_team)
                away_hex  = _NBA_HEX.get(away_team, "#4080FF")
                home_hex  = _NBA_HEX.get(home_team, "#4080FF")
                away_abbr = _nba_team_abbr(away_team)
                home_abbr = _nba_team_abbr(home_team)
            else:
                away_logo = _logo_url(away_team)
                home_logo = _logo_url(home_team)
                away_hex  = _MLB_HEX.get(away_team, "#4080FF")
                home_hex  = _MLB_HEX.get(home_team, "#4080FF")
                away_abbr = _team_abbr(away_team)
                home_abbr = _team_abbr(home_team)

            # last word of team name for "Thunder @ Lakers" style label
            awn = away_team.split()[-1] if away_team else away_abbr
            hwn = home_team.split()[-1] if home_team else home_abbr

            lsz     = 96 if is_best else 80
            over_sz = 62 if is_best else 50
            line_sz = 46 if is_best else 36
            odds_sz = 70 if is_best else 56
            pad     = "22px 24px 18px" if is_best else "16px 20px 14px"
            mt_pill = "margin-top:28px;" if is_best else ""

            top_b = (
                '<div style="position:absolute;top:14px;left:50%;transform:translateX(-50%);'
                'padding:6px 18px;background:linear-gradient(135deg,#FFD700,#FF8C00);'
                'border-radius:999px;font-size:15px;font-weight:900;color:#000;'
                'letter-spacing:0.06em;white-space:nowrap">⚡ TOP PLAY</div>'
            ) if is_best else ""

            card_bg  = f"rgba(0,255,157,0.05)" if is_best else "rgba(255,255,255,0.025)"
            card_bdr = f"rgba(0,255,157,0.25)"  if is_best else "rgba(255,255,255,0.08)"

            pick_rows_html += (
                f'<div style="position:relative;display:flex;align-items:stretch;gap:0;'
                f'background:{card_bg};border-radius:18px;margin-bottom:14px;'
                f'border:1px solid {card_bdr};overflow:hidden">'
                f'<div style="width:6px;flex-shrink:0;background:{dir_c};box-shadow:0 0 14px {dir_c}"></div>'
                f'<div style="flex:1;padding:{pad}">'
                f'{top_b}'
                # bet type + matchup
                f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;{mt_pill}">'
                f'{_v2_bet_pill("GAME TOTAL")}'
                f'<span style="font-size:16px;font-weight:600;color:{_MUT}">{awn} @ {hwn}</span>'
                f'</div>'
                # logos / direction / odds
                f'<div style="display:flex;align-items:center;gap:16px">'
                f'<div style="display:flex;flex-direction:column;align-items:center;gap:6px">'
                f'{_v2_logo_img(away_logo, away_abbr, away_hex, lsz)}'
                f'<span style="font-size:17px;font-weight:800;color:rgba(255,255,255,0.8);letter-spacing:0.06em">{away_abbr}</span>'
                f'</div>'
                f'<div style="flex:1;text-align:center">'
                f'<div style="font-size:{over_sz}px;font-weight:900;color:{dir_c};'
                f'letter-spacing:-1px;line-height:1;text-shadow:0 0 28px {dir_c}">{direction}</div>'
                f'<div style="font-size:{line_sz}px;font-weight:900;color:#fff;'
                f'letter-spacing:-0.5px;line-height:1.1">{line_val}</div>'
                f'</div>'
                f'<div style="display:flex;flex-direction:column;align-items:center;gap:6px">'
                f'{_v2_logo_img(home_logo, home_abbr, home_hex, lsz)}'
                f'<span style="font-size:17px;font-weight:800;color:rgba(255,255,255,0.8);letter-spacing:0.06em">{home_abbr}</span>'
                f'</div>'
                f'<div style="min-width:130px;text-align:right;padding-left:16px;flex-shrink:0">'
                f'<div style="font-size:{odds_sz}px;font-weight:900;background:{dir_grad};'
                f'-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
                f'background-clip:text;letter-spacing:-1px;line-height:1">{odds_str}</div>'
                f'</div>'
                f'</div>'
                + _v2_data_strip(dir_c, prob_pct, edge_pct, book)
                + f'</div></div>'
            )
            continue

        # ── MONEYLINE / SPREAD ─────────────────────────────────────────────────
        if is_nba:
            team_hex = _NBA_HEX.get(team, _NBA_HEX.get(opponent, "#4080FF"))
            logo_url = _nba_logo_url(team) or _nba_logo_url(opponent)
        else:
            team_hex = _MLB_HEX.get(team, _MLB_HEX.get(opponent, "#4080FF"))
            logo_url = _logo_url(team) or _logo_url(opponent)

        if market == "spread":
            pill_lbl = "RUN LINE" if not is_nba else "SPREAD"
            team_disp = f"{team} {bet_line}".strip() if bet_line else team
        else:
            pill_lbl  = "MONEYLINE"
            team_disp = team

        lsz    = 108 if is_best else 86
        logo   = _v2_logo_img(logo_url, team[:3].upper(), team_hex, lsz)

        top_b  = (
            '<div style="position:absolute;top:16px;right:20px;padding:7px 18px;'
            'background:linear-gradient(135deg,#FFD700,#FF8C00);border-radius:999px;'
            'font-size:15px;font-weight:900;color:#000;letter-spacing:0.06em">⚡ TOP PLAY</div>'
        ) if is_best else ""

        rgb      = _TEAM_RGB.get(team_hex, "64,128,255")
        card_bg  = f"linear-gradient(135deg,rgba({rgb},0.22) 0%,rgba(8,12,24,1) 55%)" if is_best else "rgba(255,255,255,0.025)"
        card_bdr = f"rgba({rgb},0.45)" if is_best else "rgba(255,255,255,0.08)"
        pad      = "22px 160px 18px 22px" if is_best else "16px 22px"
        name_sz  = 44 if is_best else 34
        odds_sz  = 84 if is_best else 64

        pick_rows_html += (
            f'<div style="position:relative;display:flex;align-items:stretch;gap:0;'
            f'background:{card_bg};border-radius:18px;margin-bottom:14px;'
            f'border:1px solid {card_bdr};overflow:hidden">'
            f'<div style="width:6px;flex-shrink:0;background:{team_hex};box-shadow:0 0 18px {team_hex}"></div>'
            f'{top_b}'
            f'<div style="flex:1;padding:{pad};display:flex;align-items:center;gap:22px">'
            f'{logo}'
            f'<div style="flex:1;min-width:0">'
            f'<div style="margin-bottom:10px">{_v2_bet_pill(pill_lbl)}</div>'
            f'<div style="font-size:{name_sz}px;font-weight:900;color:#fff;'
            f'letter-spacing:-0.5px;line-height:1.1;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis">{team_disp}</div>'
            # confidence bar
            f'<div style="height:4px;background:rgba(255,255,255,0.08);border-radius:2px;'
            f'margin-top:12px;max-width:380px;overflow:hidden">'
            f'<div style="height:100%;width:{min(prob_pct,100)}%;background:{odds_grad};'
            f'box-shadow:0 0 10px {ec}"></div></div>'
            + _v2_data_strip(ec, prob_pct, edge_pct, book)
            + f'</div>'
            f'<div style="min-width:150px;text-align:right;flex-shrink:0;padding-left:16px">'
            f'<div style="font-size:{odds_sz}px;font-weight:900;background:{odds_grad};'
            f'-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
            f'background-clip:text;letter-spacing:-2px;line-height:1">{odds_str}</div>'
            f'</div>'
            f'</div></div>'
        )

    # ── Header ─────────────────────────────────────────────────────────────────
    # Compute min/max edge for header stats box
    all_edges: list[float] = []
    for p in picks[:5]:
        mkt = str(p.get("Market", "moneyline") or "moneyline").lower()
        re  = float(p.get("Edge", 0) or 0)
        all_edges.append(round(re * 100, 1) if mkt == "moneyline" else round(re, 1))
    min_edge = min(all_edges) if all_edges else 0
    max_edge = max(all_edges) if all_edges else 0
    n_picks  = len(picks[:5])

    sport_emoji = "🏀" if is_nba else "⚾"

    header = (
        f'<div style="height:5px;background:linear-gradient(90deg,#00FF9D,#00C8FF,#7B61FF,#FF00AA,#FFD700)"></div>'
        f'<div style="padding:30px 48px 26px;display:flex;align-items:flex-start;justify-content:space-between;'
        f'border-bottom:1px solid {_BORDER}">'
        f'<div>'
        f'<div style="font-size:14px;font-weight:700;color:{_MUT};letter-spacing:0.14em;margin-bottom:10px">'
        f'{sport_emoji} {sport_lbl} &nbsp;·&nbsp; {date_str}</div>'
        f'<div style="font-size:56px;font-weight:900;letter-spacing:-2px;line-height:1">'
        f'<span style="color:#fff">Overlay</span>'
        f'</div>'
        f'<div style="font-size:16px;color:{_MUT};margin-top:8px;letter-spacing:0.04em">'
        f'@getoverlay &nbsp;·&nbsp; ML Picks Model</div>'
        f'</div>'
        f'<div style="text-align:right;padding-top:6px">'
        f'<div style="display:inline-flex;align-items:center;gap:12px;padding:12px 20px;'
        f'background:rgba(0,255,157,0.06);border:1px solid rgba(0,255,157,0.2);border-radius:12px">'
        f'<div style="text-align:center">'
        f'<div style="font-size:13px;color:{_MUT};letter-spacing:0.1em;font-family:Courier New,monospace;margin-bottom:4px">MIN EDGE</div>'
        f'<div style="font-size:26px;font-weight:900;color:#00FF9D">+{min_edge:.1f}%</div>'
        f'</div>'
        f'<div style="width:1px;height:40px;background:{_BORDER}"></div>'
        f'<div style="text-align:center">'
        f'<div style="font-size:13px;color:{_MUT};letter-spacing:0.1em;font-family:Courier New,monospace;margin-bottom:4px">TOP EDGE</div>'
        f'<div style="font-size:26px;font-weight:900;color:#FFD700">+{max_edge:.1f}%</div>'
        f'</div>'
        f'</div>'
        f'<div style="font-size:16px;font-weight:700;color:{_MUT};letter-spacing:0.08em;margin-top:10px">'
        f'{n_picks} MODEL PICK{"S" if n_picks != 1 else ""}</div>'
        f'</div>'
        f'</div>'
    )

    footer_left = (record_str + "  ·  ") if record_str else ""
    footer = (
        f'<div style="margin:20px 48px 0;padding-top:16px;border-top:1px solid {_BORDER};'
        f'display:flex;justify-content:space-between;align-items:center">'
        f'<div style="font-size:15px;color:{_MUT}">{footer_left}Results posted daily · Not financial advice · 21+</div>'
        f'<div style="font-size:22px;font-weight:900;background:linear-gradient(135deg,#00FF9D,#00C8FF);'
        f'-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;'
        f'letter-spacing:0.02em">@getoverlay</div>'
        f'</div>'
    )

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">'
        '<style>*{margin:0;padding:0;box-sizing:border-box}</style>'
        '</head><body style="background:#070B14;font-family:Inter,sans-serif;width:1080px">'
        '<div class="card-wrap" style="width:1080px;background:linear-gradient(180deg,#0C1020 0%,#080C18 50%,#070B14 100%);padding-bottom:42px">'
        + header
        + f'<div style="padding:22px 48px 0">{pick_rows_html}</div>'
        + footer
        + '</div></body></html>'
    )


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



def _format_record_str(sport: str) -> str:
    """Pull a clean season record line for the card footer.

    Reads sport-specific stats from public_stats.json by_sport[<sport>]. The
    sport key is normalized so 'baseball_mlb', 'basketball_nba', 'mlb', 'nba',
    'NBA' all resolve to the same bucket. Falls back to overall summary only
    when no sport-specific bucket exists (e.g. mixed cards).
    """
    try:
        stats_path = Path("data/public_stats.json")
        if not stats_path.exists():
            return ""
        with open(stats_path) as f:
            stats = json.load(f)
        sport_key = (sport or "").lower()
        for prefix in ("baseball_", "basketball_", "icehockey_", "hockey_"):
            sport_key = sport_key.replace(prefix, "")
        bucket = stats.get("by_sport", {}).get(sport_key)
        if not bucket:
            # No per-sport bucket yet — fall back to overall
            bucket = stats.get("summary", {})
        w = int(bucket.get("wins", 0) or 0)
        l = int(bucket.get("losses", 0) or 0)
        u = bucket.get("profit_units")
        if u is None:
            u = bucket.get("units_profit", 0) or 0
        roi = bucket.get("roi")
        if roi is None:
            # Compute on the fly if not stored
            settled = w + l
            roi = (u / settled) if settled else 0
        wr = (w / (w + l)) if (w + l) else 0
        sign_u = "+" if u >= 0 else ""
        sign_r = "+" if roi >= 0 else ""
        return f"{w}-{l} ({wr*100:.1f}%) {sign_u}{u:.2f}u · ROI {sign_r}{roi*100:.1f}%"
    except Exception:
        return ""


def render_pick_card_html(
    picks: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
    record_str: str | None = None,
) -> Path | None:
    """Render moneyline pick card to PNG (Overlay-branded)."""
    from src.output.overlay_cards import render_overlay_mlb_card, render_overlay_nba_card
    d = card_date or date.today()
    rec = record_str if record_str is not None else _format_record_str(sport)
    if sport.lower() in ("nba", "basketball_nba"):
        # NBA path: data uses lowercase keys; convert from MLB-shaped picks if needed
        return render_overlay_nba_card(picks, card_date=d, record_str=rec, filename="pick_card")
    return render_overlay_mlb_card(picks, card_date=d, record_str=rec, card_type="moneyline", filename="pick_card")



def render_totals_card_html(
    picks: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
    record_str: str | None = None,
) -> Path | None:
    """Render over/under totals pick card to PNG (Overlay-branded)."""
    from src.output.overlay_cards import render_overlay_mlb_card
    d = card_date or date.today()
    rec = record_str if record_str is not None else _format_record_str(sport)
    return render_overlay_mlb_card(picks, card_date=d, record_str=rec, card_type="total", filename="totals_card")


# ─────────────────────────────────────────────────────────────────────────────
# Game slate cards — show ALL games today with ML / spread / total
# ─────────────────────────────────────────────────────────────────────────────

def _build_game_slate_html(
    games: list[dict],
    sport: str,
    d: date,
    accent: str,
    pill_label: str,
    logo_fn,
    hex_fn,
    abbr_fn,
) -> str:
    """
    Shared HTML builder for MLB and NBA full-slate cards.

    Each game dict should have:
      away_team, home_team,
      away_ml, home_ml        (int American odds, 0 if unknown)
      spread_line             (float, e.g. -1.5)
      away_spread_odds        (int)
      home_spread_odds        (int)
      total                   (float, e.g. 8.5)
      over_odds, under_odds   (int)
      game_time               (str, e.g. "7:10 PM ET")
    """
    date_str = d.strftime("%b %d, %Y").upper()
    glow     = accent

    def _fmt_odds(o) -> str:
        try:
            v = int(o)
            return f"+{v}" if v > 0 else str(v)
        except (TypeError, ValueError):
            return "—"

    def _fmt_line(line) -> str:
        try:
            v = float(line)
            return f"+{v}" if v > 0 else str(v)
        except (TypeError, ValueError):
            return ""

    rows_html = ""
    for game in games:
        away      = str(game.get("away_team", ""))
        home      = str(game.get("home_team", ""))
        away_logo = logo_fn(away)
        home_logo = logo_fn(home)
        away_hex  = hex_fn(away)
        home_hex  = hex_fn(home)
        away_abbr = abbr_fn(away)
        home_abbr = abbr_fn(home)
        away_ml   = _fmt_odds(game.get("away_ml", 0))
        home_ml   = _fmt_odds(game.get("home_ml", 0))
        spread    = _fmt_line(game.get("spread_line", ""))
        away_sp_o = _fmt_odds(game.get("away_spread_odds", 0))
        home_sp_o = _fmt_odds(game.get("home_spread_odds", 0))
        total     = game.get("total", "")
        over_o    = _fmt_odds(game.get("over_odds", 0))
        under_o   = _fmt_odds(game.get("under_odds", 0))
        gametime  = str(game.get("game_time", ""))

        def _logo_tag(url, abbr, hx, side=""):
            if url:
                return f'<img class="sl-logo sl-logo-{side}" src="{url}" alt="{abbr}" style="--tc:{hx}">'
            return f'<div class="sl-logo sl-logo-{side} sl-logo-fallback" style="background:{hx}">{abbr[:3]}</div>'

        spread_disp = f"{away_abbr} {spread} · {away_sp_o}" if spread else "—"
        total_disp  = f"O {total} ({over_o}) / U ({under_o})" if total else "—"

        rows_html += f"""
      <div class="sl-row">
        <div class="sl-teams">
          <div class="sl-team away">
            {_logo_tag(away_logo, away_abbr, away_hex, 'away')}
            <span class="sl-abbr" style="color:{away_hex}">{away_abbr}</span>
          </div>
          <div class="sl-at">@</div>
          <div class="sl-team home">
            {_logo_tag(home_logo, home_abbr, home_hex, 'home')}
            <span class="sl-abbr" style="color:{home_hex}">{home_abbr}</span>
          </div>
          {('<div class="sl-time">' + gametime + '</div>') if gametime else ''}
        </div>
        <div class="sl-markets">
          <div class="sl-cell">
            <div class="sl-cell-label">MONEYLINE</div>
            <div class="sl-ml-row">
              <span class="sl-ml away-ml">{away_ml}</span>
              <span class="sl-ml-sep">/</span>
              <span class="sl-ml home-ml">{home_ml}</span>
            </div>
          </div>
          <div class="sl-cell">
            <div class="sl-cell-label">SPREAD</div>
            <div class="sl-val">{spread_disp}</div>
          </div>
          <div class="sl-cell">
            <div class="sl-cell-label">TOTAL</div>
            <div class="sl-val">{total_disp}</div>
          </div>
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
    min-height: 1080px;
    background:
      radial-gradient(ellipse 80% 40% at 50% 0%, {glow}12 0%, transparent 70%),
      radial-gradient(ellipse 60% 60% at 80% 100%, rgba(57,255,120,0.04) 0%, transparent 60%),
      linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
    padding-bottom: 28px;
  }}
  .header {{
    padding: 28px 44px 22px;
    border-bottom: 1px solid {accent}40;
    background: linear-gradient(180deg, {accent}10 0%, transparent 100%);
    display: flex; align-items: flex-end; justify-content: space-between;
  }}
  .brand {{ display: flex; align-items: baseline; gap: 0; line-height: 1; }}
  .brand-chef {{ font-size: 72px; font-weight: 900; color: #F8F8FC; letter-spacing: -2px; }}
  .brand-bets {{ font-size: 56px; font-weight: 900; color: #FFBE00; letter-spacing: -1px; margin-left: 4px; }}
  .brand-ai {{
    font-size: 34px; font-weight: 800;
    background: linear-gradient(135deg, #00D4E0, #7B61FF);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; margin-left: 10px; margin-bottom: 6px;
    filter: drop-shadow(0 0 12px rgba(0,210,220,0.5));
  }}
  .brand-sub {{ font-size: 16px; color: #555870; font-weight: 400; margin-top: 8px; letter-spacing: 0.02em; }}
  .header-right {{ text-align: right; }}
  .header-date {{ font-size: 18px; font-weight: 700; color: #F8F8FC; letter-spacing: 0.05em; }}
  .sport-pill {{
    display: inline-block; margin-top: 8px; padding: 5px 14px;
    background: {accent}20; border: 1px solid {accent}50;
    border-radius: 999px; font-size: 13px; font-weight: 700;
    color: {accent}; letter-spacing: 0.08em;
  }}

  /* Slate grid */
  .slate {{ padding: 14px 36px 0; display: flex; flex-direction: column; gap: 8px; }}

  .sl-row {{
    display: flex; align-items: center; gap: 0;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px; overflow: hidden;
    padding: 14px 20px;
  }}

  .sl-teams {{
    display: flex; align-items: center; gap: 8px;
    min-width: 240px; flex-shrink: 0;
  }}

  .sl-team {{ display: flex; flex-direction: column; align-items: center; gap: 4px; }}
  .sl-at {{ font-size: 14px; font-weight: 700; color: rgba(255,255,255,0.3); margin: 0 6px; }}

  .sl-logo {{
    width: 42px; height: 42px; object-fit: contain;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,0.15) 0%, rgba(255,255,255,0.06) 100%);
    padding: 3px;
    box-shadow: 0 0 0 1.5px var(--tc, #4080FF), 0 0 8px color-mix(in srgb, var(--tc, #4080FF) 50%, transparent);
  }}

  .sl-logo-fallback {{
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 900; color: #fff;
  }}

  .sl-abbr {{ font-size: 13px; font-weight: 800; letter-spacing: 0.04em; }}

  .sl-time {{
    font-size: 10px; color: rgba(255,255,255,0.3); margin-left: 6px; white-space: nowrap;
    align-self: center;
  }}

  .sl-markets {{ display: flex; flex: 1; gap: 0; margin-left: 16px; }}
  .sl-cell {{
    flex: 1; padding: 0 12px;
    border-left: 1px solid rgba(255,255,255,0.06);
  }}
  .sl-cell:first-child {{ border-left: none; }}
  .sl-cell-label {{ font-size: 9px; font-weight: 700; color: rgba(255,255,255,0.3); letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 5px; }}
  .sl-ml-row {{ display: flex; align-items: center; gap: 6px; }}
  .sl-ml {{ font-size: 15px; font-weight: 800; color: #F8F8FC; }}
  .sl-ml-sep {{ font-size: 12px; color: rgba(255,255,255,0.25); }}
  .sl-val {{ font-size: 13px; font-weight: 600; color: rgba(255,255,255,0.75); line-height: 1.3; }}

  /* Footer */
  .footer {{
    margin: 16px 44px 0; padding-top: 14px;
    border-top: 1px solid rgba(255,190,0,0.2);
    display: flex; align-items: center; justify-content: space-between;
  }}
  .footer-left {{ font-size: 14px; color: #555870; font-weight: 500; letter-spacing: 0.04em; }}
  .footer-handle {{ font-size: 20px; font-weight: 800; color: #FFBE00; letter-spacing: 0.02em; }}
  .footer-right {{ font-size: 13px; color: #555870; font-weight: 400; }}
</style>
</head>
<body>
<div class="card-wrap">
  <div class="header">
    <div>
      <div class="brand">
        <span class="brand-chef">Overlay</span>
      </div>
      <div class="brand-sub">EVERY PICK TIMESTAMPED BEFORE GAME TIME</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="sport-pill">{pill_label}</div>
    </div>
  </div>

  <div class="slate">{rows_html}</div>

  <div class="footer">
    <div class="footer-left">{pill_label} · {date_str}</div>
    <div class="footer-handle">@getoverlay</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""


def _build_mlb_game_slate_html(games: list[dict], d: date) -> str:
    return _build_game_slate_html(
        games, "mlb", d,
        accent="#FFBE00", pill_label="MLB FULL SLATE",
        logo_fn=_logo_url,
        hex_fn=lambda t: _MLB_HEX.get(t, "#4080FF"),
        abbr_fn=_team_abbr,
    )


def _build_nba_game_slate_html(games: list[dict], d: date) -> str:
    return _build_game_slate_html(
        games, "nba", d,
        accent="#00D4E0", pill_label="NBA FULL SLATE",
        logo_fn=_nba_logo_url,
        hex_fn=lambda t: _NBA_HEX.get(t, "#4080FF"),
        abbr_fn=_nba_team_abbr,
    )




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


def _build_props_html(props: list[dict], sport: str, d: date,
                      pill_label: str = "PLAYER PROPS") -> str:
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

        # Player headshot → team logo fallback → initials
        headshot = _mlb_player_headshot_b64(player)
        if headshot:
            avatar_html = f'<img class="prop-team-logo" src="{headshot}" alt="{player}" style="border-radius:50%;object-fit:cover;">'
        else:
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
    min-height: 1080px;
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
        <span class="brand-chef">Overlay</span>
      </div>
      <div class="brand-sub">EVERY PICK TIMESTAMPED BEFORE GAME TIME</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="props-pill">{pill_label}</div>
    </div>
  </div>

  <div class="section-label">Best prop edges for today's slate</div>

  <div class="props-list">
    {rows_html}
  </div>

  <div class="footer">
    <div class="footer-left">{sport_lbl} Props &nbsp;·&nbsp; {date_str}</div>
    <div class="footer-handle">@getoverlay</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""


def render_props_card_html(
    props: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
    pill_label: str = "PLAYER PROPS",
    filename: str = "props_card",
) -> Path | None:
    """Render player props card to PNG via Playwright. Returns path or None."""
    d = card_date or date.today()
    html = _build_props_html(props, sport, d, pill_label=pill_label)

    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    html_path = save_dir / f"{filename}.html"
    png_path  = save_dir / f"{filename}.png"

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


_PROP_TYPE_PILL = {
    "pitcher_strikeouts":  "PITCHER STRIKEOUTS",
    "batter_home_runs":    "BATTER HOME RUNS",
    "batter_hits":         "BATTER HITS",
    "batter_total_bases":  "TOTAL BASES",
    "batter_rbis":         "BATTER RBIs",
    "player_points":       "PLAYER POINTS",
    "player_rebounds":     "PLAYER REBOUNDS",
    "player_assists":      "PLAYER ASSISTS",
    "player_pra":          "POINTS + REB + AST",
    "player_blocks":       "PLAYER BLOCKS",
    "player_steals":       "PLAYER STEALS",
    "player_threes":       "THREE POINTERS MADE",
}


def render_props_cards_by_type(
    props: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
    min_per_card: int = 1,
    max_per_card: int = 8,
) -> dict[str, Path]:
    """Render one prop card per prop type (e.g. pitcher_strikeouts, batter_home_runs).

    Groups `props` by their `market` field, then calls `render_props_card_html`
    for each group with a sport-typed filename like `props_pitcher_strikeouts_card.png`.

    Skips groups with fewer than `min_per_card` picks. Returns {market: png_path}.
    """
    from collections import defaultdict

    by_market: dict[str, list[dict]] = defaultdict(list)
    for p in props:
        mkt = p.get("market") or p.get("prop_market") or "unknown"
        by_market[mkt].append(p)

    results: dict[str, Path] = {}
    for market, group in by_market.items():
        if len(group) < min_per_card:
            continue
        group_sorted = sorted(group, key=lambda x: float(x.get("edge_pct") or 0), reverse=True)
        pill = _PROP_TYPE_PILL.get(market, market.replace("_", " ").upper())
        filename = f"props_{market}_card"
        png = render_props_card_html(
            group_sorted[:max_per_card],
            sport=sport,
            card_date=card_date,
            pill_label=pill,
            filename=filename,
        )
        if png:
            results[market] = png
    return results


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
    min-height: 1080px;
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
        <span class="brand-chef">Overlay</span>
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
    <div class="footer-handle">@getoverlay</div>
    <div class="footer-r">Verified Picks</div>
  </div>
</div>
</body>
</html>"""



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



def _build_nba_props_html(props: list[dict], d: date, context_label: str = "NBA",
                          pill_label: str = "PLAYER PROPS") -> str:
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

        headshot_url = _nba_player_headshot_b64(player)
        if headshot_url:
            avatar_html = f'<img class="prop-logo" src="{headshot_url}" alt="{player}" style="border-radius:50%;object-fit:cover;">'
        elif team_logo:
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
    min-height:1080px;
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
        <span class="brand-chef">Overlay</span>
      </div>
      <div class="brand-sub">EVERY PICK TIMESTAMPED BEFORE GAME TIME</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="context-pill">{pill_label}</div>
    </div>
  </div>

  <div class="section-lbl">Best prop edges — {context_label}</div>

  <div class="props-list">
    {rows_html}
  </div>

  <div class="footer">
    <div class="footer-left">{context_label} Props &nbsp;·&nbsp; {date_str}</div>
    <div class="footer-handle">@getoverlay</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""








def render_nba_props_card_html(
    props: list[dict],
    card_date: date | None = None,
    context_label: str = "NBA",
    pill_label: str = "PLAYER PROPS",
    filename: str = "nba_props_card",
) -> Path | None:
    """Render NBA player props card to PNG."""
    d = card_date or date.today()
    html = _build_nba_props_html(props, d, context_label, pill_label=pill_label)
    save_dir = OUTPUT_DIR / "basketball_nba" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(
        html, save_dir / f"{filename}.html", save_dir / f"{filename}.png",
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
        <span class="brand-chef">Overlay</span>
      </div>
      <div class="brand-sub">EVERY PICK TIMESTAMPED BEFORE GAME TIME</div>
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
    <div class="s-footer-handle">@getoverlay</div>
    <div class="s-footer-r">Verified Picks</div>
  </div>
  <div class="s-disclaimer">Not financial advice. Bet responsibly. 21+</div>
</div>
</body>
</html>"""



# ─────────────────────────────────────────────────────────────────────────────
# Pick of the Day card — hero single pick
# ─────────────────────────────────────────────────────────────────────────────

def _load_totals_record_str() -> str:
    """Return e.g. 'Totals 41-31 (57% WR)' from public_stats.json."""
    try:
        import json as _json
        p = Path("data/public_stats.json")
        if not p.exists():
            return ""
        stats = _json.loads(p.read_text())
        t = stats.get("by_market", {}).get("total", {})
        w, l = t.get("wins", 0), t.get("losses", 0)
        n = w + l
        if n < 5:
            return ""
        return f"Totals {w}-{l} ({round(w/n*100,1)}% WR)"
    except Exception:
        return ""



def render_pick_of_day_card_html(
    pick: dict,
    sport: str = "mlb",
    card_date: date | None = None,
) -> Path | None:
    """Render hero 1080×1080 'Pick of the Day' card (Overlay-branded)."""
    from src.output.overlay_cards import render_overlay_pick_of_day
    d = card_date or date.today()
    rec = _format_record_str(sport)
    return render_overlay_pick_of_day(pick, sport=sport, card_date=d, record_str=rec)


# ─────────────────────────────────────────────────────────────────────────────
# Clean totals card — 2-3 picks, readable at Instagram thumbnail size
# ─────────────────────────────────────────────────────────────────────────────

def _build_clean_totals_html(picks: list[dict], sport: str, d: date) -> str:
    _is_nba   = "nba" in sport.lower()
    date_str  = d.strftime("%b %d, %Y").upper()
    sport_lbl = _SPORT_LABELS.get(sport.lower(), sport.upper())
    record_str = _load_totals_record_str()

    totals = [p for p in picks if str(p.get("market","")).lower() in ("total","f5_total")][:3]
    if not totals:
        return ""

    rows = ""
    for p in totals:
        matchup   = p.get("matchup", "")
        direction = str(p.get("direction","OVER")).upper()
        bet_line  = p.get("bet_line") or p.get("line","")
        odds_raw  = p.get("best_odds") or p.get("odds") or p.get("BestOdds") or 0
        odds      = int(odds_raw) if odds_raw else 0
        odds_str  = f"{odds:+d}" if odds else "–"
        book      = (p.get("sportsbook") or p.get("Sportsbook","")).strip()
        edge_pct  = float(p.get("edge_pct") or p.get("Edge") or 0)
        edge_color = "#00E676" if edge_pct >= 8 else ("#FFA514" if edge_pct >= 4 else "#6B8CFF")

        away_t = home_t = ""
        if matchup and " @ " in matchup:
            away_t, home_t = matchup.split(" @ ", 1)
            away_t = away_t.strip(); home_t = home_t.strip()

        if _is_nba:
            away_logo = _nba_logo_url(away_t) if away_t else ""
            home_logo = _nba_logo_url(home_t) if home_t else ""
            away_abbr = _nba_team_abbr(away_t)
            home_abbr = _nba_team_abbr(home_t)
            away_hex  = _NBA_HEX.get(away_t, "#4080FF")
            home_hex  = _NBA_HEX.get(home_t, "#4080FF")
        else:
            away_logo = _logo_url(away_t) if away_t else ""
            home_logo = _logo_url(home_t) if home_t else ""
            away_abbr = _ESPN_ABBR.get(away_t, away_t[:3].upper()) if away_t else "AWY"
            home_abbr = _ESPN_ABBR.get(home_t, home_t[:3].upper()) if home_t else "HME"
            away_hex  = _MLB_HEX.get(away_t, "#4080FF")
            home_hex  = _MLB_HEX.get(home_t, "#4080FF")

        away_img = f'<img class="logo" src="{away_logo}">' if away_logo else f'<div class="logo logo-fb" style="background:{away_hex}">{away_abbr}</div>'
        home_img = f'<img class="logo" src="{home_logo}">' if home_logo else f'<div class="logo logo-fb" style="background:{home_hex}">{home_abbr}</div>'
        dir_color = "#00E676" if direction == "OVER" else "#FF5C5C"

        rows += f"""
  <div class="pick-section">
    <div class="matchup-row">
      <div class="team-block">
        {away_img}
        <span class="team-name">{away_abbr}</span>
      </div>
      <span class="at-sign">@</span>
      <div class="team-block">
        {home_img}
        <span class="team-name">{home_abbr}</span>
      </div>
    </div>
    <div class="bet-display">
      <span class="direction" style="color:{dir_color}">{direction}</span>
      <span class="line">{bet_line}</span>
    </div>
    <div class="meta-row">
      <span class="odds">{odds_str}</span>
      {_book_badge_html(book, font_size=15, padding="5px 14px", radius="8px")}
      <span class="edge-pill" style="color:{edge_color};border-color:{edge_color}55">AI SCORE {min(99, max(50, 50 + round(edge_pct * 4.0)))}</span>
    </div>
  </div>"""

    n = len(totals)
    # Dividers between picks
    rows = rows.replace('</div>\n  <div class="pick-section">', '</div>\n  <div class="divider-line"></div>\n  <div class="pick-section">', n - 1)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system,'Helvetica Neue',Arial,sans-serif;
    background: #080808; width: 1080px; height: 1080px;
  }}
  .card-wrap {{
    width: 1080px; height: 1080px; background: #080808;
    display: flex; flex-direction: column; position: relative; overflow: hidden;
  }}
  /* HEADER */
  .header {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 34px 52px 30px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    flex-shrink: 0;
  }}
  .h-sport {{
    font-size: 26px; font-weight: 900; color: #fff;
    letter-spacing: 2px; text-transform: uppercase;
  }}
  .h-date {{
    font-size: 18px; font-weight: 700; color: rgba(255,255,255,0.55);
    letter-spacing: 1px;
  }}
  .h-brand {{
    font-size: 18px; font-weight: 900; color: #00E676;
    letter-spacing: 1.5px;
  }}
  /* PICK SECTIONS */
  .picks-body {{ flex: 1; display: flex; flex-direction: column; }}
  .pick-section {{
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    padding: 24px 52px; gap: 18px;
  }}
  .divider-line {{
    height: 1px; background: rgba(255,255,255,0.08);
    flex-shrink: 0; margin: 0 52px;
  }}
  /* LOGOS */
  .matchup-row {{
    display: flex; align-items: center; justify-content: center; gap: 36px;
  }}
  .team-block {{
    display: flex; flex-direction: column; align-items: center; gap: 12px;
  }}
  .logo {{
    width: 120px; height: 120px; object-fit: contain;
    filter: drop-shadow(0 0 20px rgba(255,255,255,0.15));
  }}
  .logo-fb {{
    width: 120px; height: 120px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 30px; font-weight: 900; color: #fff;
  }}
  .team-name {{
    font-size: 20px; font-weight: 900; color: rgba(255,255,255,0.8);
    letter-spacing: 2px; text-transform: uppercase;
  }}
  .at-sign {{
    font-size: 26px; font-weight: 700; color: rgba(255,255,255,0.3);
    margin-top: -20px;
  }}
  /* BET HERO */
  .bet-display {{ display: flex; align-items: baseline; gap: 18px; }}
  .direction {{
    font-size: 96px; font-weight: 900; line-height: 1; letter-spacing: -2px;
    filter: drop-shadow(0 0 50px currentColor);
  }}
  .line {{
    font-size: 78px; font-weight: 900; color: #fff; line-height: 1; letter-spacing: -1px;
  }}
  /* META */
  .meta-row {{ display: flex; align-items: center; gap: 14px; }}
  .odds {{ font-size: 32px; font-weight: 900; color: #fff; }}
  .edge-pill {{
    font-size: 16px; font-weight: 800; letter-spacing: 1px;
    border: 1.5px solid; border-radius: 999px; padding: 5px 18px;
  }}
  /* FOOTER */
  .footer {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 20px 52px 30px;
    border-top: 1px solid rgba(255,255,255,0.07);
    flex-shrink: 0;
  }}
  .footer-record {{ font-size: 18px; font-weight: 900; color: #00E676; }}
  .footer-note {{ font-size: 13px; font-weight: 500; color: rgba(255,255,255,0.3); }}
</style>
</head>
<body>
<div class="card-wrap">
  <div class="header">
    <div>
      <span class="h-sport" style="font-size:36px;font-weight:900;color:#fff;letter-spacing:-0.5px">Overlay</span>
      <div style="font-size:12px;color:rgba(255,255,255,0.38);letter-spacing:0.15em;margin-top:4px">EVERY PICK TIMESTAMPED BEFORE GAME TIME</div>
    </div>
    <div style="background:#6480ff18;border:1.5px solid #6480ff55;border-radius:999px;padding:10px 24px;
         font-size:14px;font-weight:800;color:#6480ff;letter-spacing:0.14em">{sport_lbl.upper()} TOTALS</div>
    <span class="h-date">{date_str}</span>
  </div>

  <div class="picks-body">
    {rows}
  </div>

  <div class="footer">
    <span class="footer-record">{record_str}</span>
    <span style="font-size:16px;font-weight:900;color:#6480ff;letter-spacing:0.14em">@GETOVERLAY</span>
    <span class="footer-note">overlay-gray.vercel.app</span>
  </div>
</div>
</body>
</html>"""


def render_clean_totals_card(
    picks: list[dict],
    sport: str,
    card_date: date | None = None,
) -> Path | None:
    """Render clean totals card (2-3 picks) optimized for Instagram."""
    d = card_date or date.today()
    totals = [p for p in picks if str(p.get("market","")).lower() in ("total","f5_total")]
    if not totals:
        return None
    html = _build_clean_totals_html(picks, sport, d)
    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "totals_clean_card.html", save_dir / "totals_clean_card.png")


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
        "f5_total":  "F5",
        "nrfi":      "NRFI",
        "prop":      "PROP",
    }
    _type_color = {
        "moneyline": "#4CAF50",
        "spread":    "#2196F3",
        "total":     "#FF9800",
        "f5_total":  "#FF9800",
        "nrfi":      "#9C27B0",
        "prop":      "#00BCD4",
    }

    # Adaptive sizing: fewer picks = bigger cards, more picks = compact
    n = len(picks)
    if n <= 5:
        card_h, logo_sz, team_fs, best_fs, odds_fs, best_odds_fs, gap, pad_v = 108, 68, 30, 34, 50, 56, 11, 18
    elif n <= 8:
        card_h, logo_sz, team_fs, best_fs, odds_fs, best_odds_fs, gap, pad_v = 88, 56, 25, 28, 42, 46, 9, 14
    elif n <= 11:
        card_h, logo_sz, team_fs, best_fs, odds_fs, best_odds_fs, gap, pad_v = 74, 46, 21, 23, 34, 37, 7, 10
    else:
        card_h, logo_sz, team_fs, best_fs, odds_fs, best_odds_fs, gap, pad_v = 62, 38, 18, 19, 28, 30, 6, 8

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
        cur_odds_fs = best_odds_fs if is_best else odds_fs

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
        <span class="s-odds" style="font-size:{cur_odds_fs}px;color:{edge_color}">{odds_str}</span>
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
    padding-bottom: {pad_v}px;
  }}

  .s-header {{
    padding: {pad_v + 10}px 44px {pad_v}px;
    border-bottom: 1px solid rgba(64,128,255,0.25);
    background: linear-gradient(180deg, rgba(64,128,255,0.06) 0%, transparent 100%);
    display: flex; align-items: flex-end; justify-content: space-between;
  }}
  .s-brand {{ display: flex; align-items: baseline; gap: 0; line-height: 1; }}
  .s-brand-chef {{ font-size: {min(72, 48 + max(0, 5-n)*5)}px; font-weight: 900; color: #F8F8FC; letter-spacing: -2px; }}
  .s-brand-bets {{ font-size: {min(56, 38 + max(0, 5-n)*4)}px; font-weight: 900; color: #FFBE00; letter-spacing: -1px; margin-left: 4px; }}
  .s-brand-ai {{ font-size: {min(34, 24 + max(0, 5-n)*2)}px; font-weight: 800; background: linear-gradient(135deg, #00D4E0, #7B61FF);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    margin-left: 10px; filter: drop-shadow(0 0 12px rgba(0,210,220,0.5)); }}
  .s-brand-sub {{ font-size: {min(16, 11 + max(0, 5-n))}px; color: #555870; font-weight: 400; margin-top: 6px; }}
  .s-header-right {{ text-align: right; }}
  .s-header-date {{ font-size: {min(18, 14 + max(0, 5-n))}px; font-weight: 700; color: #F8F8FC; letter-spacing: 0.05em; }}
  .s-sport-pill {{
    display: inline-block; margin-top: 6px; padding: 4px 12px;
    background: rgba(64,128,255,0.15); border: 1px solid rgba(64,128,255,0.35);
    border-radius: 999px; font-size: 12px; font-weight: 700; color: #4080FF; letter-spacing: 0.08em;
  }}

  .s-list {{ padding: {pad_v}px 44px 0; display: flex; flex-direction: column; gap: {gap}px; }}

  .s-card {{
    position: relative; display: flex; align-items: center; gap: 0;
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
    border-radius: {min(20, 10 + max(0, 5-n)*2)}px; overflow: hidden;
    padding: {pad_v - 4}px 24px {pad_v - 4}px 0;
    min-height: {card_h}px; backdrop-filter: blur(4px);
  }}
  .s-best {{
    background: linear-gradient(135deg, color-mix(in srgb, var(--tc) 15%, #0E1220) 0%, rgba(14,18,32,0.95) 50%);
    border: 1px solid rgba(255,190,0,0.4);
    box-shadow: 0 0 40px rgba(255,190,0,0.08), inset 0 1px 0 rgba(255,255,255,0.06);
    min-height: {card_h + 10}px;
  }}

  .s-bar {{ width: 5px; align-self: stretch; border-radius: 3px; margin-right: 14px; flex-shrink: 0; }}

  .s-logo-wrap {{ width: {logo_sz}px; height: {logo_sz}px; flex-shrink: 0; margin-right: {max(12, logo_sz//4)}px; }}
  .s-best .s-logo-wrap {{ width: {logo_sz + 8}px; height: {logo_sz + 8}px; }}
  .s-logo {{
    width: 100%; height: 100%; object-fit: contain; border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,0.15) 0%, rgba(255,255,255,0.06) 100%);
    padding: 4px;
    box-shadow: 0 0 0 2px var(--tc), 0 0 16px color-mix(in srgb, var(--tc) 50%, transparent);
  }}
  .s-logo-fb {{
    display: flex; align-items: center; justify-content: center;
    font-size: {max(12, logo_sz//4)}px; font-weight: 900; color: white;
  }}

  .s-info {{ flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }}
  .s-team-row {{ display: flex; align-items: center; gap: 8px; }}
  .s-team {{ font-size: {team_fs}px; font-weight: 900; color: #F8F8FC; letter-spacing: -0.5px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.15; }}
  .s-best .s-team {{ font-size: {best_fs}px; }}
  .s-badge {{
    font-size: {max(9, team_fs//3)}px; font-weight: 700; letter-spacing: 1px;
    padding: 2px 7px; border-radius: 999px; border: 1px solid; flex-shrink: 0;
  }}
  .s-opp {{ font-size: {max(11, team_fs - 10)}px; color: #6B7090; font-weight: 500; }}
  .s-meta {{ display: flex; align-items: center; gap: 10px; margin-top: 1px; }}
  .s-edge {{ font-size: {max(11, team_fs - 10)}px; font-weight: 700; letter-spacing: 0.03em; }}
  .s-top {{
    font-size: {max(9, team_fs - 14)}px; font-weight: 700; color: #FFBE00;
    background: rgba(255,190,0,0.1); border: 1px solid rgba(255,190,0,0.25);
    padding: 2px 8px; border-radius: 999px; letter-spacing: 0.04em;
  }}

  .s-odds-wrap {{ flex-shrink: 0; text-align: right; min-width: 110px;
    display: flex; flex-direction: column; align-items: flex-end; }}
  .s-odds {{ font-weight: 900; letter-spacing: -1px; line-height: 1;
    filter: drop-shadow(0 0 12px var(--ec)); }}
  .s-book {{ display: block; margin-top: 4px; font-size: {max(9, team_fs - 14)}px; font-weight: 800;
    letter-spacing: 0.08em; text-transform: uppercase; color: rgba(255,255,255,0.6); }}

  .s-footer {{
    margin: {pad_v}px 44px 0; padding-top: 12px;
    border-top: 1px solid rgba(255,255,255,0.06);
    display: flex; justify-content: space-between;
    font-size: 11px; color: #333; font-weight: 600;
  }}
  .s-footer-handle {{ color: rgba(64,128,255,0.8); font-weight: 700; }}
</style>
</head>
<body>
<div class="s-wrap">
  <div class="s-header">
    <div>
      <div class="s-brand">
        <span class="s-brand-chef">Overlay</span>
      </div>
      <div class="s-brand-sub">EVERY PICK TIMESTAMPED BEFORE GAME TIME</div>
    </div>
    <div class="s-header-right">
      <div class="s-header-date">{date_str}</div>
      <div class="s-sport-pill">FULL SLATE · {n} PICKS</div>
    </div>
  </div>
  <div class="s-list">
    {rows_html}
  </div>
  <div class="s-footer">
    <span>{sport_lbl} · {date_str}</span>
    <span class="s-footer-handle">@getoverlay</span>
  </div>
</div>
</body>
</html>"""



# ─────────────────────────────────────────────────────────────────────────────
# F5 (First 5 Innings) Totals Card
# ─────────────────────────────────────────────────────────────────────────────

def _build_f5_html(plays: list[dict], sport: str, d: date) -> str:
    date_str = d.strftime("%b %d, %Y").upper()
    accent = "#60A5FA"
    glow   = "#60A5FA"

    pick_rows_html = ""
    for idx, p in enumerate(plays[:5]):
        direction  = str(p.get("direction", "OVER")).upper()
        line       = p.get("line", "")
        odds       = _odds_int(p.get("odds", 0))
        edge       = float(p.get("edge_pct", 0) or 0)
        book       = str(p.get("book") or p.get("sportsbook", "")).strip()
        matchup    = str(p.get("matchup", ""))
        proj       = p.get("projected_total", "")
        away_team  = str(p.get("away_team", ""))
        home_team  = str(p.get("home_team", ""))
        if not away_team or not home_team:
            parts = matchup.replace(" @ ", "@").split("@")
            away_team = parts[0].strip() if parts else away_team
            home_team = parts[1].strip() if len(parts) > 1 else home_team

        ec        = _edge_color(edge, "total")
        is_best   = idx == 0
        odds_str  = f"{odds:+d}" if odds else ""
        edge_txt  = f"+{edge:.1f}% edge"
        dir_color = "#39FF78" if direction == "OVER" else "#FF6B6B"
        card_cls  = "pick-card best-bet" if is_best else "pick-card"
        top_play  = '<span class="top-play">⚡ TOP PLAY</span>' if is_best else ""
        proj_str  = f"proj {proj}" if proj else ""

        away_logo = _logo_url(away_team)
        home_logo = _logo_url(home_team)
        away_hex  = _MLB_HEX.get(away_team, "#4080FF")
        home_hex  = _MLB_HEX.get(home_team, "#4080FF")
        away_abbr = _team_abbr(away_team)
        home_abbr = _team_abbr(home_team)

        def _logo_img(url, abbr, hex_col):
            if url:
                return f'<img class="total-logo" src="{url}" alt="{abbr}" style="--tc:{hex_col}">'
            return f'<div class="total-logo total-logo-fallback" style="background:{hex_col}">{abbr}</div>'

        pick_rows_html += f"""
        <div class="{card_cls}" style="--team-color:{dir_color};--edge-color:{ec}">
          <div class="accent-bar" style="background:{dir_color};box-shadow:0 0 16px {dir_color}"></div>
          <div class="total-matchup">
            <div class="total-team away-team">
              {_logo_img(away_logo, away_abbr, away_hex)}
              <span class="total-abbr" style="color:{away_hex}">{away_abbr}</span>
            </div>
            <div class="total-center">
              <span class="f5-tag">F5</span>
              <span class="total-direction" style="color:{dir_color}">{direction}</span>
              <span class="total-line">{line}</span>
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
              {'<span class="proj-txt">' + proj_str + '</span>' if proj_str else ''}
              {top_play}
            </div>
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
  body {{ width:1080px; background:#070810; font-family:'Inter',-apple-system,sans-serif; overflow:hidden; }}
  .card-wrap {{
    width:1080px; min-height:1080px;
    background:
      radial-gradient(ellipse 80% 40% at 50% 0%, {glow}12 0%, transparent 70%),
      radial-gradient(ellipse 60% 60% at 80% 100%, rgba(57,255,120,0.04) 0%, transparent 60%),
      linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
    padding-bottom:28px;
  }}
  .header {{ padding:28px 44px 22px; border-bottom:1px solid {accent}40; background:linear-gradient(180deg,{accent}10 0%,transparent 100%); display:flex; align-items:flex-end; justify-content:space-between; }}
  .brand {{ display:flex; align-items:baseline; gap:0; line-height:1; }}
  .brand-chef {{ font-size:72px; font-weight:900; color:#F8F8FC; letter-spacing:-2px; }}
  .brand-bets {{ font-size:56px; font-weight:900; color:#FFBE00; letter-spacing:-1px; margin-left:4px; }}
  .brand-ai {{ font-size:34px; font-weight:800; background:linear-gradient(135deg,#00D4E0,#7B61FF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; margin-left:10px; margin-bottom:6px; filter:drop-shadow(0 0 12px rgba(0,210,220,0.5)); }}
  .brand-sub {{ font-size:16px; color:#555870; font-weight:400; margin-top:8px; letter-spacing:0.02em; }}
  .header-right {{ text-align:right; }}
  .header-date {{ font-size:18px; font-weight:700; color:#F8F8FC; letter-spacing:0.05em; }}
  .sport-pill {{ display:inline-block; margin-top:8px; padding:5px 14px; background:{accent}20; border:1px solid {accent}50; border-radius:999px; font-size:13px; font-weight:700; color:{accent}; letter-spacing:0.08em; }}
  .picks-list {{ padding:18px 44px 0; display:flex; flex-direction:column; gap:12px; }}
  .pick-card {{ position:relative; display:flex; align-items:center; gap:0; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.07); border-radius:20px; overflow:hidden; padding:20px 24px 20px 0; min-height:120px; }}
  .pick-card.best-bet {{ background:linear-gradient(135deg,color-mix(in srgb,var(--team-color) 15%,#0E1220) 0%,rgba(14,18,32,0.95) 50%); border:1px solid rgba(255,190,0,0.4); box-shadow:0 0 0 1px rgba(255,190,0,0.1),0 0 40px rgba(255,190,0,0.08),inset 0 1px 0 rgba(255,255,255,0.06); min-height:156px; }}
  .accent-bar {{ width:6px; align-self:stretch; border-radius:3px; margin-right:20px; flex-shrink:0; }}
  .total-matchup {{ display:flex; align-items:center; flex:1; padding-left:0; min-width:0; }}
  .total-team {{ display:flex; flex-direction:column; align-items:center; gap:6px; width:110px; flex-shrink:0; }}
  .total-logo {{ width:80px; height:80px; object-fit:contain; border-radius:50%; background:radial-gradient(circle,rgba(255,255,255,0.15) 0%,rgba(255,255,255,0.06) 100%); padding:5px; box-shadow:0 0 0 2px var(--tc,#4080FF),0 0 18px color-mix(in srgb,var(--tc,#4080FF) 50%,transparent); }}
  .best-bet .total-logo {{ width:90px; height:90px; }}
  .total-logo-fallback {{ display:flex; align-items:center; justify-content:center; font-size:17px; font-weight:900; color:#fff; }}
  .total-abbr {{ font-size:15px; font-weight:800; letter-spacing:0.04em; text-transform:uppercase; }}
  .total-center {{ flex:1; display:flex; flex-direction:column; align-items:center; gap:2px; padding:0 8px; }}
  .f5-tag {{ font-size:11px; font-weight:800; color:{accent}; letter-spacing:0.15em; background:{accent}18; border:1px solid {accent}40; border-radius:4px; padding:2px 7px; }}
  .total-direction {{ font-size:36px; font-weight:900; letter-spacing:-0.5px; line-height:1; }}
  .best-bet .total-direction {{ font-size:42px; }}
  .total-line {{ font-size:28px; font-weight:900; color:rgba(255,255,255,0.85); letter-spacing:-0.5px; line-height:1; }}
  .best-bet .total-line {{ font-size:33px; }}
  .total-right {{ flex-shrink:0; min-width:150px; display:flex; flex-direction:column; align-items:flex-end; gap:6px; }}
  .total-odds-row {{ display:flex; align-items:baseline; }}
  .total-meta {{ display:flex; flex-direction:column; align-items:flex-end; gap:5px; }}
  .odds-num {{ font-size:56px; font-weight:900; letter-spacing:-1px; line-height:1; filter:drop-shadow(0 0 20px var(--ec)); }}
  .best-bet .odds-num {{ font-size:64px; }}
  .edge-txt {{ font-size:16px; font-weight:700; letter-spacing:0.03em; }}
  .book-pill {{ display:block; margin-top:2px; font-size:13px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; color:rgba(255,255,255,0.80); }}
  .proj-txt {{ font-size:12px; color:#555870; }}
  .top-play {{ font-size:14px; font-weight:700; color:#FFBE00; background:rgba(255,190,0,0.1); border:1px solid rgba(255,190,0,0.25); padding:3px 12px; border-radius:999px; letter-spacing:0.04em; }}
  .footer {{ margin:20px 44px 0; padding-top:16px; border-top:1px solid rgba(255,190,0,0.2); display:flex; align-items:center; justify-content:space-between; }}
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
        <span class="brand-chef">Overlay</span>
      </div>
      <div class="brand-sub">EVERY PICK TIMESTAMPED BEFORE GAME TIME</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="sport-pill">F5 TOTALS</div>
    </div>
  </div>
  <div class="picks-list">{pick_rows_html}</div>
  <div class="footer">
    <div class="footer-left">MLB F5 TOTALS &nbsp;·&nbsp; {date_str}</div>
    <div class="footer-handle">@getoverlay</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""


def render_f5_card_html(
    plays: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
) -> Path | None:
    """Render F5 totals card to PNG via Playwright."""
    if not plays:
        return None
    d = card_date or date.today()
    html = _build_f5_html(plays, sport, d)
    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(html, save_dir / "f5_card.html", save_dir / "f5_card.png")


# ─────────────────────────────────────────────────────────────────────────────
# Batter Props Card (Hits / HRs / RBIs / Total Bases)
# ─────────────────────────────────────────────────────────────────────────────

def _build_batter_props_html(props: list[dict], sport: str, d: date) -> str:
    date_str = d.strftime("%b %d, %Y").upper()
    accent   = "#C084FC"
    glow     = "#C084FC"

    _MKT_LABEL = {
        "batter_hits":        "Hits",
        "batter_home_runs":   "HRs",
        "batter_rbis":        "RBIs",
        "batter_total_bases": "TB",
    }
    _MKT_COLOR = {
        "batter_hits":        "#39FF78",
        "batter_home_runs":   "#FF4D4D",
        "batter_total_bases": "#FFA514",
        "batter_rbis":        "#00D4E0",
    }

    rows_html = ""
    for idx, p in enumerate(props[:8]):
        market    = str(p.get("market", ""))
        player    = str(p.get("player", ""))
        matchup   = str(p.get("matchup", ""))
        away_team = str(p.get("away_team", ""))
        home_team = str(p.get("home_team", ""))
        direction = str(p.get("direction", "OVER")).upper()
        line      = p.get("line", "")
        edge_pct  = float(p.get("edge_pct", 0) or 0)
        odds      = int(p.get("odds", 0) or 0)
        book      = str(p.get("book") or p.get("sportsbook", ""))
        projected = p.get("projected", 0)
        is_best   = idx == 0

        mkt_label = _MKT_LABEL.get(market, market.replace("batter_", "").title())
        mkt_color = _MKT_COLOR.get(market, "#C084FC")
        ec        = "#39FF78" if edge_pct >= 8 else ("#FFA514" if edge_pct >= 5 else "#C084FC")
        odds_str  = f"{odds:+d}" if odds else ""
        dir_color = "#39FF78" if direction == "OVER" else "#FF6B6B"
        dir_bg    = "rgba(57,255,120,0.12)" if direction == "OVER" else "rgba(255,107,107,0.12)"
        dir_border = "rgba(57,255,120,0.3)" if direction == "OVER" else "rgba(255,107,107,0.3)"
        prop_stmt = f"{direction} {line} {mkt_label}"

        _low = {"batter_home_runs", "batter_rbis"}
        if market in _low or (isinstance(projected, float) and projected < 1.0):
            proj_display = f"{int(round(projected * 100))}% chance"
        else:
            proj_display = f"proj {projected:.1f}" if projected else ""

        # Avatar: MLB player headshot → team logo → initials
        headshot = _mlb_player_headshot_b64(player)
        team_hex = _MLB_HEX.get(away_team, _MLB_HEX.get(home_team, "#C084FC"))
        if headshot:
            avatar_html = f'<img class="prop-team-logo" src="{headshot}" alt="{player}" style="border-radius:50%;object-fit:cover;">'
        else:
            team_logo_url = _logo_url(away_team) or _logo_url(home_team)
            if team_logo_url:
                avatar_html = f'<img class="prop-team-logo" src="{team_logo_url}" alt="{player}">'
            else:
                parts    = player.split()
                initials = (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else player[:2].upper()
                avatar_html = f'<span class="prop-initials">{initials}</span>'

        card_cls = "prop-card best-prop" if is_best else "prop-card"
        top_play = '<span class="top-play">⚡ BEST BET</span>' if is_best else ""
        opp_txt  = f"vs {home_team}" if away_team else matchup

        rows_html += f"""
        <div class="{card_cls}" style="--team-color:{team_hex};--ec:{ec}">
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
            <div class="prop-sub">{opp_txt} &nbsp;·&nbsp; {away_team}</div>
            <div class="prop-bottom-row">
              {'<span class="prop-proj" style="color:' + ec + '">' + proj_display + '</span>' if proj_display else ''}
              <span class="prop-edge" style="color:{ec}">+{edge_pct:.1f}% edge</span>
              {top_play}
            </div>
          </div>
          <div class="prop-odds-wrap">
            <span class="prop-odds-num" style="color:{ec};--ec:{ec}">{odds_str}</span>
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
  body {{ width:1080px; background:#070810; font-family:'Inter',-apple-system,sans-serif; overflow:hidden; }}
  .card-wrap {{
    width:1080px; min-height:1080px;
    background:
      radial-gradient(ellipse 80% 40% at 50% 0%, {glow}12 0%, transparent 70%),
      radial-gradient(ellipse 60% 60% at 80% 100%, rgba(57,255,120,0.04) 0%, transparent 60%),
      linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
    padding-bottom:28px;
  }}
  .header {{ padding:28px 44px 22px; border-bottom:1px solid {accent}40; background:linear-gradient(180deg,{accent}10 0%,transparent 100%); display:flex; align-items:flex-end; justify-content:space-between; }}
  .brand {{ display:flex; align-items:baseline; gap:0; line-height:1; }}
  .brand-chef {{ font-size:72px; font-weight:900; color:#F8F8FC; letter-spacing:-2px; }}
  .brand-bets {{ font-size:56px; font-weight:900; color:#FFBE00; letter-spacing:-1px; margin-left:4px; }}
  .brand-ai {{ font-size:34px; font-weight:800; background:linear-gradient(135deg,#00D4E0,#7B61FF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; margin-left:10px; margin-bottom:6px; filter:drop-shadow(0 0 12px rgba(0,210,220,0.5)); }}
  .brand-sub {{ font-size:16px; color:#555870; font-weight:400; margin-top:8px; letter-spacing:0.02em; }}
  .header-right {{ text-align:right; }}
  .header-date {{ font-size:18px; font-weight:700; color:#F8F8FC; letter-spacing:0.05em; }}
  .sport-pill {{ display:inline-block; margin-top:8px; padding:5px 14px; background:{accent}20; border:1px solid {accent}50; border-radius:999px; font-size:13px; font-weight:700; color:{accent}; letter-spacing:0.08em; }}
  .picks-list {{ padding:18px 44px 0; display:flex; flex-direction:column; gap:12px; }}
  .prop-card {{ position:relative; display:flex; align-items:center; gap:0; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.07); border-radius:20px; overflow:hidden; padding:18px 24px 18px 0; min-height:110px; }}
  .prop-card.best-prop {{ background:linear-gradient(135deg,color-mix(in srgb,var(--team-color) 15%,#0E1220) 0%,rgba(14,18,32,0.95) 50%); border:1px solid rgba(255,190,0,0.4); box-shadow:0 0 0 1px rgba(255,190,0,0.1),0 0 40px rgba(255,190,0,0.08),inset 0 1px 0 rgba(255,255,255,0.06); min-height:140px; }}
  .prop-accent-bar {{ width:6px; align-self:stretch; border-radius:3px; margin-right:16px; flex-shrink:0; }}
  .prop-avatar {{ width:72px; height:72px; border-radius:50%; flex-shrink:0; margin-right:18px; display:flex; align-items:center; justify-content:center; overflow:hidden; }}
  .best-prop .prop-avatar {{ width:82px; height:82px; }}
  .prop-team-logo {{ width:100%; height:100%; object-fit:contain; border-radius:50%; padding:4px; }}
  .prop-initials {{ font-size:20px; font-weight:900; color:#fff; }}
  .prop-info {{ flex:1; min-width:0; display:flex; flex-direction:column; gap:4px; }}
  .prop-player-row {{ display:flex; align-items:center; gap:8px; }}
  .prop-player {{ font-size:26px; font-weight:900; color:#F8F8FC; letter-spacing:-0.3px; line-height:1.1; }}
  .best-prop .prop-player {{ font-size:30px; }}
  .prop-bet-row {{ display:flex; align-items:center; gap:8px; }}
  .prop-stmt {{ font-size:18px; font-weight:800; }}
  .prop-mkt-badge {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px; border:1px solid; letter-spacing:0.06em; }}
  .prop-sub {{ font-size:14px; color:#6B7090; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .prop-bottom-row {{ display:flex; align-items:center; gap:12px; margin-top:2px; }}
  .prop-proj {{ font-size:14px; font-weight:600; }}
  .prop-edge {{ font-size:15px; font-weight:700; letter-spacing:0.03em; }}
  .top-play {{ font-size:13px; font-weight:700; color:#FFBE00; background:rgba(255,190,0,0.1); border:1px solid rgba(255,190,0,0.25); padding:2px 10px; border-radius:999px; }}
  .prop-odds-wrap {{ flex-shrink:0; text-align:right; min-width:130px; display:flex; flex-direction:column; align-items:flex-end; }}
  .prop-odds-num {{ font-size:52px; font-weight:900; letter-spacing:-1px; line-height:1; filter:drop-shadow(0 0 20px var(--ec)); }}
  .best-prop .prop-odds-num {{ font-size:58px; }}
  .book-pill {{ display:block; margin-top:6px; font-size:12px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; color:rgba(255,255,255,0.75); }}
  .footer {{ margin:20px 44px 0; padding-top:16px; border-top:1px solid rgba(255,190,0,0.2); display:flex; align-items:center; justify-content:space-between; }}
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
        <span class="brand-chef">Overlay</span>
      </div>
      <div class="brand-sub">EVERY PICK TIMESTAMPED BEFORE GAME TIME</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      <div class="sport-pill">BATTER PROPS</div>
    </div>
  </div>
  <div class="picks-list">{rows_html}</div>
  <div class="footer">
    <div class="footer-left">MLB BATTER PROPS &nbsp;·&nbsp; {date_str}</div>
    <div class="footer-handle">@getoverlay</div>
    <div class="footer-right">A.I. Verified</div>
  </div>
</div>
</body>
</html>"""



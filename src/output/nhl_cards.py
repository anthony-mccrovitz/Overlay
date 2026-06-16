"""
NHL pick card renderer — head-to-head logos, puck line + moneyline + totals + props.

Generates:
  nhl_picks_card.png            — all picks (puck line + moneyline + O/U)
  nhl_totals_card.png           — totals-only clean card
  nhl_{market}_card.png         — one per prop market (goals/assists/shots/points)

Player headshots fetched from ESPN CDN by player name lookup.
"""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Team data
# ─────────────────────────────────────────────────────────────────────────────

_NHL_HEX: dict[str, str] = {
    "Anaheim Ducks":          "#F47A38",
    "Boston Bruins":          "#FFB81C",
    "Buffalo Sabres":         "#003087",
    "Calgary Flames":         "#C8102E",
    "Carolina Hurricanes":    "#CC0000",
    "Chicago Blackhawks":     "#CF0A2C",
    "Colorado Avalanche":     "#6F263D",
    "Columbus Blue Jackets":  "#002654",
    "Dallas Stars":           "#006847",
    "Detroit Red Wings":      "#CE1126",
    "Edmonton Oilers":        "#FF4C00",
    "Florida Panthers":       "#C8102E",
    "Los Angeles Kings":      "#A2AAAD",
    "Minnesota Wild":         "#154734",
    "Montreal Canadiens":     "#AF1E2D",
    "Nashville Predators":    "#FFB81C",
    "New Jersey Devils":      "#CE1126",
    "New York Islanders":     "#003087",
    "New York Rangers":       "#0038A8",
    "Ottawa Senators":        "#E31837",
    "Philadelphia Flyers":    "#F74902",
    "Pittsburgh Penguins":    "#FCB514",
    "San Jose Sharks":        "#006D75",
    "Seattle Kraken":         "#99D9D9",
    "St. Louis Blues":        "#002F87",
    "Tampa Bay Lightning":    "#002868",
    "Toronto Maple Leafs":    "#00205B",
    "Utah Hockey Club":       "#69B3E7",
    "Vancouver Canucks":      "#00205B",
    "Vegas Golden Knights":   "#B4975A",
    "Washington Capitals":    "#C8102E",
    "Winnipeg Jets":          "#041E42",
}

_NHL_ABBR: dict[str, str] = {
    "Anaheim Ducks":          "ANA", "Boston Bruins":          "BOS",
    "Buffalo Sabres":         "BUF", "Calgary Flames":         "CGY",
    "Carolina Hurricanes":    "CAR", "Chicago Blackhawks":     "CHI",
    "Colorado Avalanche":     "COL", "Columbus Blue Jackets":  "CBJ",
    "Dallas Stars":           "DAL", "Detroit Red Wings":      "DET",
    "Edmonton Oilers":        "EDM", "Florida Panthers":       "FLA",
    "Los Angeles Kings":      "LAK", "Minnesota Wild":         "MIN",
    "Montreal Canadiens":     "MTL", "Nashville Predators":    "NSH",
    "New Jersey Devils":      "NJD", "New York Islanders":     "NYI",
    "New York Rangers":       "NYR", "Ottawa Senators":        "OTT",
    "Philadelphia Flyers":    "PHI", "Pittsburgh Penguins":    "PIT",
    "San Jose Sharks":        "SJS", "Seattle Kraken":         "SEA",
    "St. Louis Blues":        "STL", "Tampa Bay Lightning":    "TBL",
    "Toronto Maple Leafs":    "TOR", "Utah Hockey Club":       "UTA",
    "Vancouver Canucks":      "VAN", "Vegas Golden Knights":   "VGK",
    "Washington Capitals":    "WSH", "Winnipeg Jets":          "WPG",
}

_ESPN_NHL_ABBR: dict[str, str] = {
    "Anaheim Ducks":          "ana",  "Boston Bruins":          "bos",
    "Buffalo Sabres":         "buf",  "Calgary Flames":         "cgy",
    "Carolina Hurricanes":    "car",  "Chicago Blackhawks":     "chi",
    "Colorado Avalanche":     "col",  "Columbus Blue Jackets":  "cbj",
    "Dallas Stars":           "dal",  "Detroit Red Wings":      "det",
    "Edmonton Oilers":        "edm",  "Florida Panthers":       "fla",
    "Los Angeles Kings":      "la",   "Minnesota Wild":         "min",
    "Montreal Canadiens":     "mtl",  "Nashville Predators":    "nsh",
    "New Jersey Devils":      "nj",   "New York Islanders":     "nyi",
    "New York Rangers":       "nyr",  "Ottawa Senators":        "ott",
    "Philadelphia Flyers":    "phi",  "Pittsburgh Penguins":    "pit",
    "San Jose Sharks":        "sj",   "Seattle Kraken":         "sea",
    "St. Louis Blues":        "stl",  "Tampa Bay Lightning":    "tb",
    "Toronto Maple Leafs":    "tor",  "Utah Hockey Club":       "utah",
    "Vancouver Canucks":      "van",  "Vegas Golden Knights":   "vgk",
    "Washington Capitals":    "wsh",  "Winnipeg Jets":          "wpg",
}

# ─────────────────────────────────────────────────────────────────────────────
# Image fetching (cached)
# ─────────────────────────────────────────────────────────────────────────────

_IMG_CACHE: dict[str, str] = {}


def _fetch_b64(url: str) -> str:
    """Fetch URL and return base64 data URI, or '' on failure. Cached."""
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    try:
        import requests
        r = requests.get(url, timeout=4)
        if r.status_code == 200 and len(r.content) > 500:
            b64 = base64.b64encode(r.content).decode()
            ext = "png" if b64[:10].find("PNG") != -1 or url.endswith(".png") else "jpeg"
            uri = f"data:image/{ext};base64,{b64}"
            _IMG_CACHE[url] = uri
            return uri
    except Exception:
        pass
    _IMG_CACHE[url] = ""
    return ""


def _team_logo(team: str, sz: int = 80) -> str:
    abbr = _ESPN_NHL_ABBR.get(team, "")
    if abbr:
        url = f"https://a.espncdn.com/i/teamlogos/nhl/500/scoreboard/{abbr}.png"
        uri = _fetch_b64(url)
        if uri:
            return (f'<img src="{uri}" width="{sz}" height="{sz}" '
                    f'style="object-fit:contain;filter:drop-shadow(0 0 10px rgba(255,255,255,0.2))">')
    hex_c = _NHL_HEX.get(team, "#6B8CFF")
    abbr_txt = _NHL_ABBR.get(team, team[:3].upper() if team else "?")
    return (f'<div style="width:{sz}px;height:{sz}px;border-radius:50%;'
            f'background:{hex_c};display:flex;align-items:center;justify-content:center;'
            f'font-size:{sz//3}px;font-weight:900;color:#fff">{abbr_txt}</div>')


_PLAYER_ID_CACHE: dict[str, str] = {}


def _espn_player_id(name: str) -> str:
    """Look up ESPN player ID by name. Cached."""
    if name in _PLAYER_ID_CACHE:
        return _PLAYER_ID_CACHE[name]
    try:
        import requests
        url = f"https://site.api.espn.com/apis/common/v3/search?query={requests.utils.quote(name)}&sport=hockey&lang=en&type=player&limit=1"
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            items = r.json().get("items", [])
            if items and items[0].get("type") == "player":
                pid = str(items[0]["id"])
                _PLAYER_ID_CACHE[name] = pid
                return pid
    except Exception:
        pass
    _PLAYER_ID_CACHE[name] = ""
    return ""


def _player_headshot(name: str, team: str, sz: int = 110) -> str:
    """Return <img> with ESPN headshot or team logo fallback."""
    pid = _espn_player_id(name)
    if pid:
        url = f"https://a.espncdn.com/i/headshots/nhl/players/full/{pid}.png"
        uri = _fetch_b64(url)
        if uri:
            return (f'<img src="{uri}" width="{sz}" height="{sz}" '
                    f'style="object-fit:cover;border-radius:50%;'
                    f'border:3px solid rgba(255,255,255,0.15);'
                    f'filter:drop-shadow(0 0 12px rgba(0,0,0,0.6))">')
    # Fallback: team logo
    return _team_logo(team, sz)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _book_pill(book: str, fs: int = 13) -> str:
    colors = {
        "draftkings": "#53D337", "fanduel": "#1493FF", "betmgm": "#C9A84C",
        "caesars": "#C8A85B", "bet365": "#027B5B", "pinnacle": "#0046A6",
        "betrivers": "#E31837", "pointsbet": "#FF4C00",
    }
    key = book.lower().replace(" ", "").replace(".", "")
    c = colors.get(key, "#6B8CFF")
    return (f'<span style="font-size:{fs}px;font-weight:800;letter-spacing:0.08em;'
            f'background:{c}22;border:1.5px solid {c}88;border-radius:8px;'
            f'padding:3px 12px;color:{c}">{book.upper()}</span>')


def _nhl_record_str() -> str:
    try:
        import json
        stats = json.loads(Path("data/public_stats.json").read_text())
        nhl = stats.get("by_sport", {}).get("nhl", {})
        w = int(nhl.get("wins", 0))
        l = int(nhl.get("losses", 0))
        if w + l == 0:
            return "NHL Model — Overlay"
        pct = w / (w + l) * 100
        return f"NHL {w}-{l} ({pct:.1f}%)"
    except Exception:
        return "NHL Model — Overlay"


OUTPUT_DIR = Path("output/picks")


def _save(html: str, sport_dir: str, card_date: date, filename: str) -> Optional[Path]:
    from src.output.card_html import _playwright_render
    save_dir = OUTPUT_DIR / sport_dir / card_date.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    html_path = save_dir / f"{filename}.html"
    png_path  = save_dir / f"{filename}.png"
    html_path.write_text(html, encoding="utf-8")
    return _playwright_render(html, html_path, png_path, target_height=1080)


def _card_header(date_str: str, pill: str) -> str:
    return f"""
  <div style="display:flex;justify-content:space-between;align-items:center;
       padding:36px 52px 28px;border-bottom:1px solid rgba(255,255,255,0.08);flex-shrink:0">
    <div>
      <div style="font-size:40px;font-weight:900;color:#fff;letter-spacing:-1px">Overlay</div>
      <div style="font-size:13px;color:rgba(255,255,255,0.38);letter-spacing:0.15em;margin-top:4px">EVERY PICK TIMESTAMPED BEFORE GAME TIME</div>
    </div>
    <div style="background:#6480ff18;border:1.5px solid #6480ff55;border-radius:999px;
         padding:10px 24px;font-size:14px;font-weight:800;color:#6480ff;letter-spacing:0.14em">
      {pill}
    </div>
    <div style="text-align:right">
      <div style="font-size:16px;font-weight:700;color:rgba(255,255,255,0.55)">{date_str}</div>
    </div>
  </div>"""


def _card_footer(record: str) -> str:
    return f"""
  <div style="display:flex;justify-content:space-between;align-items:center;
       padding:16px 52px 28px;border-top:1px solid rgba(255,255,255,0.07);flex-shrink:0">
    <div style="font-size:15px;font-weight:700;color:rgba(255,255,255,0.55)">{record}</div>
    <div style="font-size:16px;font-weight:900;color:#6480ff;letter-spacing:0.14em">@GETOVERLAY</div>
    <div style="font-size:12px;color:rgba(255,255,255,0.28)">overlay-gray.vercel.app</div>
  </div>"""


# ─────────────────────────────────────────────────────────────────────────────
# Card 1: NHL Picks Card  (puck line + moneyline + totals)
# ─────────────────────────────────────────────────────────────────────────────

def render_nhl_picks_card(picks: list[dict], card_date: date | None = None) -> Optional[Path]:
    if not picks:
        return None

    d = card_date or date.today()
    date_str = d.strftime("%b %d, %Y").upper()
    record = _nhl_record_str()

    _MKT_LABEL = {
        "puck_line": "PUCK LINE", "moneyline": "MONEYLINE",
        "total": "TOTAL", "totals": "TOTAL", "h2h": "MONEYLINE",
    }

    n = len(picks[:5])
    # Adaptive pick card height so picks fill the space
    pick_min_h = max(150, (1080 - 180 - 90) // n)  # 180 header, 90 footer

    pick_rows = ""
    for i, p in enumerate(picks[:5]):
        matchup   = str(p.get("matchup") or "")
        team      = str(p.get("team") or "")
        market    = str(p.get("market") or "moneyline").lower()
        direction = str(p.get("direction") or "").upper()
        odds      = int(p.get("odds") or 0)
        edge_pct  = float(p.get("edge_pct") or 0)
        book      = str(p.get("sportsbook") or p.get("book") or "")
        line      = p.get("line")
        notes     = p.get("notes") or []

        away_t = home_t = ""
        if " @ " in matchup:
            away_t, home_t = matchup.split(" @ ", 1)
            away_t = away_t.strip(); home_t = home_t.strip()

        away_abbr = _NHL_ABBR.get(away_t, away_t[:3].upper() if away_t else "AWY")
        home_abbr = _NHL_ABBR.get(home_t, home_t[:3].upper() if home_t else "HME")
        logo_sz = max(80, min(100, pick_min_h // 2))
        away_logo = _team_logo(away_t, logo_sz)
        home_logo = _team_logo(home_t, logo_sz)

        mkt_label = _MKT_LABEL.get(market, market.upper())
        odds_str = f"{odds:+d}" if odds else "—"

        pick_team_base = team.split(" +")[0].split(" -")[0].strip()
        pick_side = "AWAY" if away_t and away_t.lower() in pick_team_base.lower() else "HOME"
        pick_hex = _NHL_HEX.get(pick_team_base, "#6B8CFF")

        # Highlight picked side, fade other
        away_op = "1" if pick_side == "AWAY" else "0.35"
        home_op = "1" if pick_side == "HOME" else "0.35"
        away_fw = "900" if pick_side == "AWAY" else "600"
        home_fw = "900" if pick_side == "HOME" else "600"

        edge_color = "#00E676" if edge_pct >= 10 else ("#FFA514" if edge_pct >= 5 else "#6480ff")
        is_best = (i == 0)
        bg = f"linear-gradient(135deg,{pick_hex}18 0%,rgba(0,0,0,0) 60%)" if is_best else "rgba(255,255,255,0.03)"
        bdr = f"{pick_hex}55" if is_best else "rgba(255,255,255,0.08)"
        accent_bar = f'<div style="position:absolute;left:0;top:0;bottom:0;width:5px;background:{pick_hex};border-radius:3px 0 0 3px"></div>' if is_best else ""
        top_badge = (
            '<div style="position:absolute;top:12px;right:16px;background:linear-gradient(135deg,#FFD700,#FF8C00);'
            'padding:5px 14px;border-radius:999px;font-size:12px;font-weight:900;color:#000;letter-spacing:0.1em">⚡ TOP PLAY</div>'
        ) if is_best else ""

        # Center display
        if market == "puck_line":
            center_main = direction or team
            center_sub = ""
        elif market in ("total", "totals"):
            dir_c = "#00E676" if "OVER" in direction else "#FF5C5C"
            line_str = str(line) if line else ""
            center_main = f'<span style="color:{dir_c}">{direction.split()[0]}</span> {line_str}'
            center_sub = ""
        else:
            center_main = odds_str
            center_sub = ""
            odds_str = ""

        # First model note (trimmed)
        note_html = ""
        if notes and isinstance(notes, list):
            snippet = str(notes[0])[:72]
            note_html = f'<div style="font-size:13px;color:rgba(255,255,255,0.4);margin-top:8px;text-align:center">{snippet}</div>'

        pick_rows += f"""
  <div style="position:relative;display:flex;align-items:center;
       background:{bg};border:1px solid {bdr};border-radius:18px;
       min-height:{pick_min_h}px;padding:24px 28px;gap:20px;margin-bottom:12px;overflow:hidden">
    {accent_bar}{top_badge}
    <!-- away team -->
    <div style="display:flex;flex-direction:column;align-items:center;gap:8px;opacity:{away_op};min-width:{logo_sz+8}px">
      {away_logo}
      <span style="font-size:15px;font-weight:{away_fw};letter-spacing:2px;color:#fff">{away_abbr}</span>
    </div>
    <!-- center -->
    <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px">
      <div style="font-size:11px;font-weight:800;color:rgba(255,255,255,0.35);letter-spacing:0.2em">{mkt_label}</div>
      <div style="font-size:42px;font-weight:900;color:#fff;letter-spacing:-1px;line-height:1;text-align:center">{center_main}</div>
      {f'<div style="font-size:26px;font-weight:900;color:rgba(255,255,255,0.75)">{odds_str}</div>' if odds_str else ''}
      <div style="display:flex;align-items:center;gap:10px;margin-top:4px">
        <span style="font-size:14px;font-weight:800;color:{edge_color};border:1.5px solid {edge_color}55;border-radius:999px;padding:4px 14px">+{edge_pct:.1f}% EDGE</span>
        {_book_pill(book, 13)}
      </div>
      {note_html}
    </div>
    <!-- home team -->
    <div style="display:flex;flex-direction:column;align-items:center;gap:8px;opacity:{home_op};min-width:{logo_sz+8}px">
      {home_logo}
      <span style="font-size:15px;font-weight:{home_fw};letter-spacing:2px;color:#fff">{home_abbr}</span>
    </div>
  </div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#0a0b14; font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;
  width:1080px; height:1080px; color:#fff; }}</style></head>
<body>
<div style="width:1080px;height:1080px;background:linear-gradient(160deg,#0e1022 0%,#080810 50%);
     display:flex;flex-direction:column;overflow:hidden">
  {_card_header(date_str, "NHL PICKS")}
  <div style="flex:1;padding:20px 44px 0;display:flex;flex-direction:column;justify-content:center">
    {pick_rows}
  </div>
  {_card_footer(record)}
</div></body></html>"""

    return _save(html, "icehockey_nhl", d, "nhl_picks_card")


# ─────────────────────────────────────────────────────────────────────────────
# Card 2: NHL Totals (clean team logos)
# ─────────────────────────────────────────────────────────────────────────────

def render_nhl_totals_card(picks: list[dict], card_date: date | None = None) -> Optional[Path]:
    totals = [p for p in picks if str(p.get("market") or "").lower() in ("total", "totals")]
    if not totals:
        return None

    d = card_date or date.today()
    date_str = d.strftime("%b %d, %Y").upper()
    record = _nhl_record_str()

    n = len(totals[:3])
    section_h = (1080 - 180 - 90) // n

    rows = ""
    for i, p in enumerate(totals[:3]):
        matchup   = str(p.get("matchup") or "")
        direction = str(p.get("direction") or "OVER").upper().split()[0]
        line      = p.get("line") or p.get("bet_line") or ""
        odds      = int(p.get("odds") or 0)
        odds_str  = f"{odds:+d}" if odds else "—"
        book      = str(p.get("sportsbook") or p.get("book") or "")
        edge_pct  = float(p.get("edge_pct") or 0)

        away_t = home_t = ""
        if " @ " in matchup:
            away_t, home_t = matchup.split(" @ ", 1)
            away_t = away_t.strip(); home_t = home_t.strip()

        away_abbr = _NHL_ABBR.get(away_t, away_t[:3].upper() if away_t else "AWY")
        home_abbr = _NHL_ABBR.get(home_t, home_t[:3].upper() if home_t else "HME")
        logo_sz = min(110, section_h // 3)
        away_logo = _team_logo(away_t, logo_sz)
        home_logo = _team_logo(home_t, logo_sz)

        dir_color = "#00E676" if direction == "OVER" else "#FF5C5C"
        edge_color = "#00E676" if edge_pct >= 8 else ("#FFA514" if edge_pct >= 4 else "#6480ff")
        divider = '<div style="height:1px;background:rgba(255,255,255,0.07);margin:0 52px;flex-shrink:0"></div>' if i > 0 else ""

        rows += f"""
  {divider}
  <div style="flex:1;display:flex;flex-direction:column;align-items:center;
       justify-content:center;padding:20px 52px;gap:14px">
    <div style="display:flex;align-items:center;gap:28px">
      <div style="display:flex;flex-direction:column;align-items:center;gap:8px">
        {away_logo}
        <span style="font-size:15px;font-weight:900;color:rgba(255,255,255,0.75);letter-spacing:2px">{away_abbr}</span>
      </div>
      <span style="font-size:20px;color:rgba(255,255,255,0.2);font-weight:700">@</span>
      <div style="display:flex;flex-direction:column;align-items:center;gap:8px">
        {home_logo}
        <span style="font-size:15px;font-weight:900;color:rgba(255,255,255,0.75);letter-spacing:2px">{home_abbr}</span>
      </div>
    </div>
    <div style="display:flex;align-items:baseline;gap:12px">
      <span style="font-size:72px;font-weight:900;line-height:1;color:{dir_color};
            filter:drop-shadow(0 0 30px {dir_color}80)">{direction}</span>
      <span style="font-size:60px;font-weight:900;color:#fff;letter-spacing:-1px">{line}</span>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <span style="font-size:24px;font-weight:900;color:#fff">{odds_str}</span>
      {_book_pill(book, 14)}
      <span style="font-size:14px;font-weight:800;color:{edge_color};
            border:1.5px solid {edge_color}55;border-radius:999px;padding:4px 14px">+{edge_pct:.1f}% EDGE</span>
    </div>
  </div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#080808; font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;
  width:1080px; height:1080px; color:#fff; }}</style></head>
<body>
<div style="width:1080px;height:1080px;background:#080808;
     display:flex;flex-direction:column;overflow:hidden">
  {_card_header(date_str, "NHL TOTALS")}
  <div style="flex:1;display:flex;flex-direction:column">{rows}</div>
  {_card_footer(record)}
</div></body></html>"""

    return _save(html, "icehockey_nhl", d, "nhl_totals_card")


# ─────────────────────────────────────────────────────────────────────────────
# Card 3: NHL Player Props with headshots
# ─────────────────────────────────────────────────────────────────────────────

def render_nhl_props_card(
    props: list[dict],
    card_date: date | None = None,
    market: str = "player_goals",
) -> Optional[Path]:
    if not props:
        return None

    d = card_date or date.today()
    date_str = d.strftime("%b %d, %Y").upper()

    _MKT_DISPLAY = {
        "player_goals":         ("PLAYER GOALS",    "#FF5C5C"),
        "player_assists":       ("PLAYER ASSISTS",   "#6480ff"),
        "player_points":        ("PLAYER POINTS",    "#FFA514"),
        "player_shots_on_goal": ("SHOTS ON GOAL",    "#00E5FF"),
    }
    mkt_label, accent = _MKT_DISPLAY.get(market, (market.upper().replace("_", " "), "#6480ff"))
    filename = f"nhl_{market}_card"

    # Pre-fetch headshots (network calls upfront)
    player_imgs: dict[str, str] = {}
    for p in props[:6]:
        name = str(p.get("player") or "")
        team = str(p.get("team") or "")
        if name and name not in player_imgs:
            player_imgs[name] = _player_headshot(name, team, 100)

    n = len(props[:6])
    row_h = max(120, (1080 - 180 - 90) // n)

    rows = ""
    for p in props[:6]:
        player    = str(p.get("player") or "")
        team      = str(p.get("team") or "")
        direction = str(p.get("direction") or "OVER").upper()
        line      = p.get("line") or ""
        odds      = int(p.get("odds") or p.get("best_odds") or 0)
        edge_pct  = float(p.get("edge_pct") or 0)
        book      = str(p.get("sportsbook") or p.get("book") or "")
        odds_str  = f"{odds:+d}" if odds else "—"
        dir_color = "#00E676" if direction == "OVER" else "#FF5C5C"
        edge_color = "#00E676" if edge_pct >= 8 else ("#FFA514" if edge_pct >= 4 else "#6480ff")
        team_abbr = _NHL_ABBR.get(team, team[:3].upper() if team else "")
        headshot  = player_imgs.get(player, _team_logo(team, 90))

        rows += f"""
  <div style="display:flex;align-items:center;gap:20px;padding:16px 24px;
       background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);
       border-radius:16px;margin-bottom:10px;min-height:{row_h}px">
    <!-- headshot -->
    <div style="flex-shrink:0">{headshot}</div>
    <!-- player info -->
    <div style="flex:1;min-width:0">
      <div style="font-size:24px;font-weight:900;color:#fff;
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{player}</div>
      <div style="font-size:14px;color:rgba(255,255,255,0.45);margin-top:4px;letter-spacing:1px">{team_abbr}</div>
    </div>
    <!-- direction + line -->
    <div style="text-align:center;min-width:100px">
      <div style="font-size:14px;font-weight:800;color:{dir_color};letter-spacing:0.1em">{direction}</div>
      <div style="font-size:38px;font-weight:900;color:#fff;letter-spacing:-1px;line-height:1.1">{line}</div>
    </div>
    <!-- odds + edge -->
    <div style="text-align:right;min-width:110px">
      <div style="font-size:26px;font-weight:900;color:#fff">{odds_str}</div>
      <div style="font-size:13px;font-weight:800;color:{edge_color};
           border:1.5px solid {edge_color}55;border-radius:999px;
           padding:3px 10px;display:inline-block;margin-top:6px">+{edge_pct:.1f}%</div>
      <div style="margin-top:6px">{_book_pill(book, 11)}</div>
    </div>
  </div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#0a0b14; font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;
  width:1080px; height:1080px; color:#fff; }}</style></head>
<body>
<div style="width:1080px;height:1080px;background:linear-gradient(160deg,#0e1022 0%,#080810 50%);
     display:flex;flex-direction:column;overflow:hidden">
  {_card_header(date_str, mkt_label)}
  <div style="flex:1;padding:20px 44px 0;display:flex;flex-direction:column;justify-content:center">
    {rows}
  </div>
  {_card_footer("NHL Props — Overlay")}
</div></body></html>"""

    return _save(html, "icehockey_nhl", d, filename)


# ─────────────────────────────────────────────────────────────────────────────
# Render all NHL cards at once
# ─────────────────────────────────────────────────────────────────────────────

def render_all_nhl_cards(
    picks: list[dict],
    props: list[dict] | None = None,
    card_date: date | None = None,
) -> dict[str, Optional[Path]]:
    d = card_date or date.today()
    out: dict[str, Optional[Path]] = {}

    out["nhl_picks_card"] = render_nhl_picks_card(picks, d)

    totals = [p for p in picks if str(p.get("market") or "").lower() in ("total", "totals")]
    if totals:
        out["nhl_totals_card"] = render_nhl_totals_card(totals, d)

    if props:
        by_market: dict[str, list] = defaultdict(list)
        for p in props:
            m = str(p.get("market") or p.get("prop_market") or "")
            if m:
                by_market[m].append(p)
        for mkt, group in by_market.items():
            out[f"nhl_{mkt}_card"] = render_nhl_props_card(group, d, market=mkt)

    return out

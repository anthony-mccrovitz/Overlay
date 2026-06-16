"""
Card V2 — Clean social-first design.

Design principles:
  - The PICK is the hero. Everything else is supporting context.
  - Logos on team-color discs — always readable, looks intentional.
  - Flags as clean standalone images, not background fills.
  - Barlow Condensed 900 for all numbers and picks.
  - Subtle noise grain + team-color background glow.
  - No split backgrounds. No gimmicks. Big clear hierarchy.

Card types:
  render_mlb_moneyline_v2(picks, card_date)   → hero (1-2) or list (3)
  render_mlb_totals_v2(picks, card_date)       → hero (1) or list (2-3)
  render_world_cup_v2(picks, card_date, out_dir) → one card per game
  render_nba_totals_v2(picks, card_date)
  render_mlb_cards_v2(picks, card_date)        → convenience dispatch
"""
from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Brand palette ─────────────────────────────────────────────────────────────
_INDIGO = "#6480FF"
_GREEN  = "#00D46A"
_RED    = "#FF4050"
_GOLD   = "#FFD700"
_BG     = "#07090F"
_WHITE  = "#FFFFFF"
_MUTED  = "rgba(255,255,255,0.50)"

# Sportsbook brand colors
_BOOK_CLR: dict[str, tuple[str, str]] = {
    "draftkings":       ("#1B5E20", "#FFFFFF"),
    "fanduel":          ("#0070E0", "#FFFFFF"),
    "betmgm":           ("#B8932A", "#FFFFFF"),
    "caesars":          ("#002366", "#FFD700"),
    "bet365":           ("#1B7A3E", "#FFFFFF"),
    "betrivers":        ("#003087", "#FFFFFF"),
    "hard rock bet":    ("#A00020", "#FFFFFF"),
    "espnbet":          ("#CC0000", "#FFFFFF"),
    "betonline":        ("#1A1A2E", "#FFD700"),
    "fanatics":         ("#CC0000", "#FFFFFF"),
    "thescore bet":     ("#E8000D", "#FFFFFF"),
    "thescore":         ("#E8000D", "#FFFFFF"),
    "pointsbet":        ("#E00034", "#FFFFFF"),
    "mybookie":         ("#003366", "#FFFFFF"),
    "bovada":           ("#1A1A2E", "#FFD700"),
    "pinnacle":         ("#E5A100", "#000000"),
    "fliff":            ("#7B2FBE", "#FFFFFF"),
}

# ── Image cache ───────────────────────────────────────────────────────────────
_IMG_CACHE: dict[str, str] = {}

def _fetch_b64(url: str) -> str:
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    try:
        import requests
        r = requests.get(url, timeout=7)
        if r.status_code == 200 and len(r.content) > 500:
            ext = "png" if ".png" in url else "jpeg"
            uri = f"data:image/{ext};base64,{base64.b64encode(r.content).decode()}"
            _IMG_CACHE[url] = uri
            return uri
    except Exception:
        pass
    _IMG_CACHE[url] = ""
    return ""

# ── MLB ────────────────────────────────────────────────────────────────────────
_MLB_ESPN = {
    "Arizona Diamondbacks":"ari","Atlanta Braves":"atl","Baltimore Orioles":"bal",
    "Boston Red Sox":"bos","Chicago Cubs":"chc","Chicago White Sox":"chw",
    "Cincinnati Reds":"cin","Cleveland Guardians":"cle","Colorado Rockies":"col",
    "Detroit Tigers":"det","Houston Astros":"hou","Kansas City Royals":"kc",
    "Los Angeles Angels":"laa","Los Angeles Dodgers":"lad","Miami Marlins":"mia",
    "Milwaukee Brewers":"mil","Minnesota Twins":"min","New York Mets":"nym",
    "New York Yankees":"nyy","Athletics":"oak","Oakland Athletics":"oak",
    "Philadelphia Phillies":"phi","Pittsburgh Pirates":"pit","San Diego Padres":"sd",
    "San Francisco Giants":"sf","Seattle Mariners":"sea","St. Louis Cardinals":"stl",
    "Tampa Bay Rays":"tb","Texas Rangers":"tex","Toronto Blue Jays":"tor",
    "Washington Nationals":"wsh",
}
_MLB_HEX = {
    "Arizona Diamondbacks":"#A7192F","Atlanta Braves":"#CE1141","Baltimore Orioles":"#DF6D1D",
    "Boston Red Sox":"#BD3039","Chicago Cubs":"#0E3386","Chicago White Sox":"#27251F",
    "Cincinnati Reds":"#C6001F","Cleveland Guardians":"#003865","Colorado Rockies":"#330071",
    "Detroit Tigers":"#0C2340","Houston Astros":"#002D62","Kansas City Royals":"#004687",
    "Los Angeles Angels":"#BA0021","Los Angeles Dodgers":"#005A9C","Miami Marlins":"#00A3E0",
    "Milwaukee Brewers":"#002855","Minnesota Twins":"#002B7F","New York Mets":"#002D72",
    "New York Yankees":"#1C2841","Athletics":"#003831","Oakland Athletics":"#003831",
    "Philadelphia Phillies":"#E8182A","Pittsburgh Pirates":"#FDB827","San Diego Padres":"#2F241D",
    "San Francisco Giants":"#FD5A1E","Seattle Mariners":"#005C5C","St. Louis Cardinals":"#C41E3A",
    "Tampa Bay Rays":"#092CB8","Texas Rangers":"#003278","Toronto Blue Jays":"#134A8E",
    "Washington Nationals":"#AB0003",
}

def _mlb_logo(team: str) -> str:
    abbr = _MLB_ESPN.get(team, "")
    if not abbr:
        return ""
    return _fetch_b64(f"https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/{abbr}.png")

def _mlb_abbr(team: str) -> str:
    a = _MLB_ESPN.get(team, "")
    return a.upper() if a else team[:3].upper()

def _mlb_hex(team: str) -> str:
    return _MLB_HEX.get(team, _INDIGO)

# ── NBA ────────────────────────────────────────────────────────────────────────
_NBA_ESPN = {
    "Atlanta Hawks":"atl","Boston Celtics":"bos","Brooklyn Nets":"bkn",
    "Charlotte Hornets":"cha","Chicago Bulls":"chi","Cleveland Cavaliers":"cle",
    "Dallas Mavericks":"dal","Denver Nuggets":"den","Detroit Pistons":"det",
    "Golden State Warriors":"gs","Houston Rockets":"hou","Indiana Pacers":"ind",
    "Los Angeles Clippers":"lac","Los Angeles Lakers":"lal","Memphis Grizzlies":"mem",
    "Miami Heat":"mia","Milwaukee Bucks":"mil","Minnesota Timberwolves":"min",
    "New Orleans Pelicans":"no","New York Knicks":"ny","Oklahoma City Thunder":"okc",
    "Orlando Magic":"orl","Philadelphia 76ers":"phi","Phoenix Suns":"phx",
    "Portland Trail Blazers":"por","Sacramento Kings":"sac","San Antonio Spurs":"sa",
    "Toronto Raptors":"tor","Utah Jazz":"utah","Washington Wizards":"wsh",
}
_NBA_HEX = {
    "Atlanta Hawks":"#C8102E","Boston Celtics":"#007A33","Brooklyn Nets":"#444",
    "Charlotte Hornets":"#1D1160","Chicago Bulls":"#CE1141","Cleveland Cavaliers":"#860038",
    "Dallas Mavericks":"#00538C","Denver Nuggets":"#0E2240","Detroit Pistons":"#C8102E",
    "Golden State Warriors":"#1D428A","Houston Rockets":"#CE1141","Indiana Pacers":"#002D62",
    "Los Angeles Clippers":"#C8102E","Los Angeles Lakers":"#552583","Memphis Grizzlies":"#5D76A9",
    "Miami Heat":"#98002E","Milwaukee Bucks":"#00471B","Minnesota Timberwolves":"#0C2340",
    "New Orleans Pelicans":"#0C2340","New York Knicks":"#006BB6","Oklahoma City Thunder":"#007AC1",
    "Orlando Magic":"#0077C0","Philadelphia 76ers":"#006BB6","Phoenix Suns":"#1D1160",
    "Portland Trail Blazers":"#E03A3E","Sacramento Kings":"#5A2D81","San Antonio Spurs":"#8A8D8F",
    "Toronto Raptors":"#CE1141","Utah Jazz":"#002B5C","Washington Wizards":"#002B5C",
}

def _nba_logo(team: str) -> str:
    abbr = _NBA_ESPN.get(team, "")
    return _fetch_b64(f"https://a.espncdn.com/i/teamlogos/nba/500/scoreboard/{abbr}.png") if abbr else ""

def _nba_abbr(team: str) -> str:
    a = _NBA_ESPN.get(team, "")
    return a.upper() if a else team[:3].upper()

def _nba_hex(team: str) -> str:
    return _NBA_HEX.get(team, _INDIGO)

# ── World Cup flags ───────────────────────────────────────────────────────────
_WC_FLAGS = {
    "Algeria":"dz","Argentina":"ar","Australia":"au","Austria":"at","Belgium":"be",
    "Bolivia":"bo","Brazil":"br","Cameroon":"cm","Canada":"ca","Chile":"cl",
    "China":"cn","Colombia":"co","Costa Rica":"cr","Croatia":"hr","Cuba":"cu",
    "Czech Republic":"cz","Denmark":"dk","Ecuador":"ec","Egypt":"eg","England":"gb-eng",
    "France":"fr","Germany":"de","Ghana":"gh","Greece":"gr","Honduras":"hn",
    "Hungary":"hu","Iceland":"is","Indonesia":"id","Iran":"ir","Iraq":"iq",
    "Italy":"it","Jamaica":"jm","Japan":"jp","Kenya":"ke","Mali":"ml","Mexico":"mx",
    "Morocco":"ma","Netherlands":"nl","New Zealand":"nz","Nigeria":"ng",
    "North Korea":"kp","Panama":"pa","Paraguay":"py","Peru":"pe","Philippines":"ph",
    "Poland":"pl","Portugal":"pt","Qatar":"qa","Romania":"ro","Saudi Arabia":"sa",
    "Scotland":"gb-sct","Senegal":"sn","Serbia":"rs","Slovakia":"sk","Slovenia":"si",
    "South Africa":"za","South Korea":"kr","Spain":"es","Sweden":"se",
    "Switzerland":"ch","Thailand":"th","Trinidad and Tobago":"tt","Tunisia":"tn",
    "Turkey":"tr","Ukraine":"ua","United States":"us","Uruguay":"uy",
    "Uzbekistan":"uz","Venezuela":"ve","Wales":"gb-wls",
}

def _wc_flag_uri(country: str) -> str:
    code = _WC_FLAGS.get(country.strip(), "")
    if not code:
        return ""
    return _fetch_b64(f"https://flagcdn.com/w320/{code}.png")

# ── Shared visual helpers ─────────────────────────────────────────────────────

def _fmt_odds(odds) -> str:
    try:
        o = int(float(odds))
        return f"+{o}" if o > 0 else str(o)
    except (TypeError, ValueError):
        return "—"

def _book_badge(book: str, fs: int = 15) -> str:
    key = (book or "").lower().strip()
    bg, fg = _BOOK_CLR.get(key, ("rgba(255,255,255,0.12)", "rgba(255,255,255,0.70)"))
    label_map = {
        "draftkings":"DRAFTKINGS","fanduel":"FANDUEL","betmgm":"BETMGM",
        "caesars":"CAESARS","bet365":"BET365","betrivers":"BETRIVERS",
        "espnbet":"ESPN BET","hard rock bet":"HARD ROCK","betonline":"BETONLINE",
        "fanatics":"FANATICS","thescore bet":"THESCORE","thescore":"THESCORE",
        "pointsbet":"POINTSBET","mybookie":"MYBOOKIE","bovada":"BOVADA",
        "pinnacle":"PINNACLE","fliff":"FLIFF",
    }
    label = label_map.get(key, book.upper()[:12] if book else "—")
    return (
        f'<span style="background:{bg};color:{fg};font-size:{fs}px;font-weight:800;'
        f'padding:7px 18px;border-radius:8px;letter-spacing:0.5px;white-space:nowrap;'
        f'display:inline-block">{label}</span>'
    )

def _team_disc(uri: str, abbr: str, hex_c: str, sz: int = 160) -> str:
    """Logo centered on solid team-color disc. Always readable — logos are designed for their own colors."""
    inner_sz = int(sz * 0.74)
    if uri:
        inner = (
            f'<img src="{uri}" width="{inner_sz}" height="{inner_sz}" '
            f'style="object-fit:contain;filter:brightness(1.05)">'
        )
    else:
        inner = (
            f'<span style="font-family:\'Barlow Condensed\',sans-serif;'
            f'font-size:{inner_sz // 2}px;font-weight:900;color:#fff;letter-spacing:-1px">{abbr}</span>'
        )
    return (
        f'<div style="width:{sz}px;height:{sz}px;border-radius:50%;background:{hex_c};'
        f'display:flex;align-items:center;justify-content:center;flex-shrink:0;'
        f'box-shadow:0 0 0 3px rgba(255,255,255,0.14),0 10px 36px rgba(0,0,0,0.70)">'
        f'{inner}</div>'
    )

def _flag_img(uri: str, country: str, w: int = 220, op: float = 1.0) -> str:
    """Standalone flag image with border and shadow."""
    h = int(w * 0.625)
    opacity = f"{op:.2f}"
    if uri:
        return (
            f'<img src="{uri}" width="{w}" height="{h}" alt="{country}" '
            f'style="object-fit:cover;border-radius:10px;opacity:{opacity};'
            f'box-shadow:0 6px 28px rgba(0,0,0,0.70);'
            f'filter:brightness(1.08) saturate(1.10)">'
        )
    return (
        f'<div style="width:{w}px;height:{h}px;border-radius:10px;background:#1e2a4a;'
        f'display:flex;align-items:center;justify-content:center;opacity:{opacity};'
        f'font-size:{w // 4}px;font-weight:900;color:rgba(255,255,255,0.45)">'
        f'{country[:3].upper()}</div>'
    )

def _record_str(sport: str, market: str | None = None) -> str:
    try:
        pfile = _ROOT / "data" / "pnl" / "picks.json"
        if not pfile.exists():
            return ""
        raw = json.loads(pfile.read_text())
        all_p = raw if isinstance(raw, list) else raw.get("picks", [])
        sp = (sport.lower()
              .replace("baseball_","").replace("basketball_","")
              .replace("icehockey_","").replace("soccer_","")
              .replace("americanfootball_",""))
        settled = [
            p for p in all_p
            if isinstance(p, dict) and p.get("card_pick")
            and p.get("result") in ("win", "loss")
            and (p.get("sport", "").lower()
                 .replace("baseball_","").replace("basketball_","")
                 .replace("icehockey_","").replace("soccer_","")
                 .replace("americanfootball_","")) == sp
            and (not market or p.get("market", "").lower() == market.lower())
        ]
        w = sum(1 for p in settled if p["result"] == "win")
        l = sum(1 for p in settled if p["result"] == "loss")
        if w + l < 3:
            return ""
        return f"{w}-{l} ({round(w / (w + l) * 100)}%)"
    except Exception:
        return ""

def _playwright_render(html: str, html_path: Path, png_path: Path, h: int = 1080) -> Optional[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1080, "height": h})
            page.set_content(html, wait_until="networkidle")
            png_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": 1080, "height": h})
            browser.close()
        return png_path
    except Exception as e:
        print(f"  [card_v2] {e}")
        return None

# ── Shared card shell ─────────────────────────────────────────────────────────

def _shell(
    body: str,
    pill: str,
    pill_bg: str,
    pill_fg: str,
    date_str: str,
    record: str = "",
    bg_glow_color: str = _INDIGO,
    bg_glow2: str = "",
    footer_note: str = "Not financial advice · 21+",
) -> str:
    """1080×1080 card shell: header + noise grain + team glow + footer."""
    glow2 = bg_glow2 or bg_glow_color
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Barlow+Condensed:wght@700;800;900&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{
  width:1080px;height:1080px;overflow:hidden;
  font-family:'Inter',-apple-system,sans-serif;color:#fff;
  background:{_BG};
  background-image:
    radial-gradient(ellipse 70% 55% at 20% 0%, {bg_glow_color}22 0%, transparent 60%),
    radial-gradient(ellipse 60% 45% at 85% 100%, {glow2}16 0%, transparent 55%);
}}
body::after{{
  content:'';position:fixed;inset:0;pointer-events:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='1'/%3E%3C/svg%3E");
  opacity:0.030;mix-blend-mode:overlay;
}}
.card{{width:1080px;height:1080px;display:flex;flex-direction:column}}
.hdr{{display:flex;align-items:center;justify-content:space-between;padding:30px 52px 22px;border-bottom:1px solid rgba(255,255,255,0.07);flex-shrink:0}}
.brand{{font-size:34px;font-weight:900;color:#fff;letter-spacing:-1px;line-height:1}}
.brand-sub{{font-size:9px;color:rgba(255,255,255,0.30);letter-spacing:0.16em;margin-top:5px;text-transform:uppercase;font-weight:600}}
.pill{{background:{pill_bg};color:{pill_fg};font-size:13px;font-weight:900;letter-spacing:0.14em;padding:10px 24px;border-radius:999px;white-space:nowrap;text-transform:uppercase}}
.hdate{{font-size:14px;font-weight:700;color:rgba(255,255,255,0.35);white-space:nowrap}}
.body{{flex:1;display:flex;flex-direction:column;justify-content:space-evenly;align-items:center;padding:16px 56px;min-height:0}}
.ftr{{display:flex;align-items:center;justify-content:space-between;padding:14px 52px 24px;border-top:1px solid rgba(255,255,255,0.07);flex-shrink:0}}
.ftr-rec{{font-size:15px;font-weight:800;color:rgba(255,255,255,0.45)}}
.ftr-hdl{{font-size:19px;font-weight:900;color:{_INDIGO};letter-spacing:0.10em}}
.ftr-note{{font-size:11px;color:rgba(255,255,255,0.20)}}
</style></head>
<body><div class="card">
<div class="hdr">
  <div><div class="brand">Overlay</div><div class="brand-sub">Every pick timestamped before game time</div></div>
  <div class="pill">{pill}</div>
  <div class="hdate">{date_str}</div>
</div>
<div class="body">{body}</div>
<div class="ftr">
  <div class="ftr-rec">{record}</div>
  <div class="ftr-hdl">@GETOVERLAY</div>
  <div class="ftr-note">{footer_note}</div>
</div>
</div></body></html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Card 1 — MLB Moneyline V2
# ─────────────────────────────────────────────────────────────────────────────

def render_mlb_moneyline_v2(
    picks: list[dict],
    card_date: date | None = None,
) -> Optional[Path]:
    """
    Hero (1-2 picks): picked team on large color disc, opponent dimmed.
    List (3 picks): full-height rows with team-color discs.
    """
    if not picks:
        return None
    card_date = card_date or date.today()
    ts   = card_date.strftime("%Y%m%d")
    dstr = card_date.strftime("%b %d, %Y").upper()
    out_dir = _ROOT / "output" / "picks" / "baseball_mlb" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / "mlb_moneyline_card.png"

    rows: list[dict] = []
    for p in picks[:3]:
        team    = str(p.get("Team") or p.get("team") or "")
        matchup = str(p.get("Matchup") or p.get("matchup") or "")
        opp     = str(p.get("Opponent") or p.get("opponent") or "")
        if not matchup and opp:
            matchup = f"{team} @ {opp}"
        away_t = home_t = ""
        if " @ " in matchup:
            away_t, home_t = matchup.split(" @ ", 1)
        away_t = (away_t or team).strip()
        home_t = (home_t or opp).strip()
        pick_side = "AWAY" if away_t and team and away_t.lower() in team.lower() else "HOME"
        rows.append({
            "pick": team.strip(),
            "away": away_t, "home": home_t,
            "pick_side": pick_side,
            "odds": p.get("BestOdds") or p.get("odds") or 0,
            "book": p.get("Sportsbook") or p.get("sportsbook") or "",
        })

    rec = _record_str("mlb", "moneyline")

    # ── HERO (1-2 picks) ──────────────────────────────────────────────────────
    if len(rows) <= 2:
        r         = rows[0]
        is_away   = (r["pick_side"] == "AWAY")
        pick_name = r["pick"]
        opp_name  = r["home"] if is_away else r["away"]
        pick_hex  = _mlb_hex(pick_name)
        opp_hex   = _mlb_hex(opp_name)

        pick_disc = _team_disc(_mlb_logo(pick_name), _mlb_abbr(pick_name), pick_hex, 240)
        opp_disc  = _team_disc(_mlb_logo(opp_name),  _mlb_abbr(opp_name),  opp_hex,  160)

        plen    = len(pick_name)
        pick_fs = 88 if plen <= 10 else (74 if plen <= 14 else (62 if plen <= 18 else 52))

        extra = ""
        if len(rows) == 2:
            r2 = rows[1]
            extra = (
                f'<div style="display:flex;align-items:center;gap:16px;padding:12px 24px;'
                f'border:1px solid rgba(255,255,255,0.08);border-radius:12px;'
                f'background:rgba(255,255,255,0.04);width:100%;margin-top:4px">'
                f'<span style="font-size:20px;font-weight:900;color:rgba(255,255,255,0.70)">{r2["pick"]}</span>'
                f'<span style="font-size:20px;font-weight:900;color:{_GREEN};margin-left:auto">{_fmt_odds(r2["odds"])}</span>'
                f'{_book_badge(r2["book"], fs=13)}</div>'
            )

        body = f"""
<div style="width:100%;display:flex;flex-direction:column;align-items:center;gap:28px">

  <!-- Teams: picked (large disc) + opponent (small, dimmed) -->
  <div style="display:flex;align-items:center;gap:28px">
    <div style="display:flex;flex-direction:column;align-items:center;gap:16px">
      {pick_disc}
      <span style="font-size:16px;font-weight:900;letter-spacing:5px;color:#fff;text-transform:uppercase">{_mlb_abbr(pick_name)}</span>
    </div>
    <span style="font-size:28px;font-weight:700;color:rgba(255,255,255,0.20)">@</span>
    <div style="display:flex;flex-direction:column;align-items:center;gap:12px;opacity:0.50">
      {opp_disc}
      <span style="font-size:14px;font-weight:900;letter-spacing:5px;color:#fff;text-transform:uppercase">{_mlb_abbr(opp_name)}</span>
    </div>
  </div>

  <div style="width:85%;height:1px;background:rgba(255,255,255,0.08)"></div>

  <!-- Pick text -->
  <div style="text-align:center">
    <div style="font-size:13px;font-weight:800;color:rgba(255,255,255,0.35);letter-spacing:0.24em;margin-bottom:12px">MONEYLINE PICK</div>
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:{pick_fs}px;font-weight:900;
         color:#fff;letter-spacing:-1px;line-height:0.92;text-transform:uppercase">{pick_name.upper()}</div>
  </div>

  <!-- Odds + book -->
  <div style="display:flex;align-items:center;gap:22px">
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:110px;font-weight:900;
         color:{_GREEN};letter-spacing:-2px;line-height:1;filter:drop-shadow(0 0 28px {_GREEN}55)">{_fmt_odds(r["odds"])}</div>
    {_book_badge(r["book"], fs=17)}
  </div>

  {extra}
</div>"""

        html = _shell(body, pill="MLB MONEYLINE", pill_bg=f"{_GREEN}22",
                      pill_fg=_GREEN, date_str=dstr, record=rec,
                      bg_glow_color=pick_hex, bg_glow2=opp_hex)

    # ── LIST (3 picks) ────────────────────────────────────────────────────────
    else:
        n     = len(rows)
        row_h = max(220, 820 // n)

        rows_html = ""
        for i, r in enumerate(rows):
            ph       = _mlb_hex(r["pick"])
            pick_d   = _team_disc(_mlb_logo(r["pick"]), _mlb_abbr(r["pick"]), ph, 110)
            opp_name = r["home"] if r["pick_side"] == "AWAY" else r["away"]
            opp_hex  = _mlb_hex(opp_name)
            opp_d    = _team_disc(_mlb_logo(opp_name), _mlb_abbr(opp_name), opp_hex, 80)
            is_top   = (i == 0)
            bg  = f"linear-gradient(135deg,{ph}18 0%,transparent 60%)" if is_top else "rgba(255,255,255,0.025)"
            bdr = f"1px solid {ph}45" if is_top else "1px solid rgba(255,255,255,0.07)"
            bar = f'<div style="position:absolute;left:0;top:0;bottom:0;width:5px;background:{ph};border-radius:20px 0 0 20px"></div>' if is_top else ""

            rows_html += f"""
<div style="display:flex;align-items:center;background:{bg};border:{bdr};border-radius:20px;
     height:{row_h}px;padding:0 32px 0 36px;gap:22px;width:100%;
     margin-bottom:{'14' if i < n-1 else '0'}px;position:relative;overflow:hidden">
  {bar}
  <div style="display:flex;align-items:center;gap:14px;flex-shrink:0">
    {pick_d}
    <span style="font-size:13px;color:rgba(255,255,255,0.25);font-weight:700">vs</span>
    <div style="opacity:0.65">{opp_d}</div>
  </div>
  <div style="flex:1;min-width:0">
    <div style="font-size:14px;font-weight:800;color:{ph};letter-spacing:0.18em;margin-bottom:8px">MONEYLINE</div>
    <div style="font-size:30px;font-weight:900;color:#fff;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{r["pick"]}</div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:12px;flex-shrink:0">
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:66px;font-weight:900;color:{_GREEN};letter-spacing:-1px;line-height:1">{_fmt_odds(r["odds"])}</div>
    {_book_badge(r["book"], fs=13)}
  </div>
</div>"""

        body = f'<div style="width:100%;display:flex;flex-direction:column">{rows_html}</div>'
        html = _shell(body, pill="MLB MONEYLINE", pill_bg=f"{_GREEN}22",
                      pill_fg=_GREEN, date_str=dstr, record=rec,
                      bg_glow_color=_mlb_hex(rows[0]["pick"]),
                      bg_glow2=_mlb_hex(rows[-1]["pick"]))

    return _playwright_render(html, png.with_suffix(".html"), png)


# ─────────────────────────────────────────────────────────────────────────────
# Card 2 — MLB Totals V2
# ─────────────────────────────────────────────────────────────────────────────

def render_mlb_totals_v2(
    picks: list[dict],
    card_date: date | None = None,
) -> Optional[Path]:
    """Hero (1 pick): OVER/UNDER dominates. List (2-3): full-height rows."""
    if not picks:
        return None
    card_date = card_date or date.today()
    ts   = card_date.strftime("%Y%m%d")
    dstr = card_date.strftime("%b %d, %Y").upper()
    out_dir = _ROOT / "output" / "picks" / "baseball_mlb" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / "mlb_totals_card.png"

    rows: list[dict] = []
    for p in picks[:3]:
        direction = str(p.get("Direction") or p.get("direction") or "")
        line      = p.get("MarketLine") or p.get("BetLine") or p.get("line") or ""
        matchup   = str(p.get("Matchup") or p.get("matchup") or "")
        ts_team   = str(p.get("Team") or p.get("team") or "")
        if not direction:
            for kw in ("OVER", "UNDER"):
                if kw in ts_team.upper():
                    direction = kw; break
        if not line:
            for part in ts_team.split():
                try: float(part); line = part; break
                except ValueError: pass
        away_t = home_t = ""
        if " @ " in matchup:
            away_t, home_t = matchup.split(" @ ", 1)
        rows.append({
            "direction": (direction or "OVER").upper(),
            "line":  str(line),
            "away":  away_t.strip(),
            "home":  home_t.strip(),
            "odds":  p.get("BestOdds") or p.get("odds") or 0,
            "book":  p.get("Sportsbook") or p.get("sportsbook") or "",
        })

    rec = _record_str("mlb", "total")

    # ── HERO (1 pick) ─────────────────────────────────────────────────────────
    if len(rows) == 1:
        r         = rows[0]
        dir_color = _GREEN if r["direction"] == "OVER" else _RED
        away_hex  = _mlb_hex(r["away"])
        home_hex  = _mlb_hex(r["home"])
        away_disc = _team_disc(_mlb_logo(r["away"]), _mlb_abbr(r["away"]), away_hex, 170)
        home_disc = _team_disc(_mlb_logo(r["home"]), _mlb_abbr(r["home"]), home_hex, 170)

        body = f"""
<div style="width:100%;display:flex;flex-direction:column;align-items:center;gap:24px">

  <!-- Matchup teams — supporting context, equal weight -->
  <div style="display:flex;align-items:center;gap:24px">
    <div style="display:flex;flex-direction:column;align-items:center;gap:12px;opacity:0.72">
      {away_disc}
      <span style="font-size:14px;font-weight:900;letter-spacing:4px;color:rgba(255,255,255,0.80)">{_mlb_abbr(r["away"])}</span>
    </div>
    <span style="font-size:24px;font-weight:700;color:rgba(255,255,255,0.20)">@</span>
    <div style="display:flex;flex-direction:column;align-items:center;gap:12px;opacity:0.72">
      {home_disc}
      <span style="font-size:14px;font-weight:900;letter-spacing:4px;color:rgba(255,255,255,0.80)">{_mlb_abbr(r["home"])}</span>
    </div>
  </div>

  <div style="width:85%;height:1px;background:rgba(255,255,255,0.08)"></div>

  <!-- THE PICK — this is the whole card -->
  <div style="text-align:center;line-height:0.88">
    <div style="font-size:13px;font-weight:800;color:rgba(255,255,255,0.35);letter-spacing:0.24em;margin-bottom:14px">TOTAL RUNS</div>
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:160px;font-weight:900;
         color:{dir_color};letter-spacing:-3px;text-transform:uppercase;
         filter:drop-shadow(0 0 50px {dir_color}70)">{r["direction"]}</div>
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:130px;font-weight:900;
         color:#fff;letter-spacing:-2px;margin-top:-12px">{r["line"]}</div>
  </div>

  <!-- Odds + book -->
  <div style="display:flex;align-items:center;gap:22px">
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:82px;font-weight:900;
         color:rgba(255,255,255,0.88);letter-spacing:-1px;line-height:1">{_fmt_odds(r["odds"])}</div>
    {_book_badge(r["book"], fs=17)}
  </div>
</div>"""

        html = _shell(body, pill="MLB TOTALS", pill_bg=f"{dir_color}22",
                      pill_fg=dir_color, date_str=dstr, record=rec,
                      bg_glow_color=away_hex, bg_glow2=home_hex)

    # ── LIST (2-3 picks) ──────────────────────────────────────────────────────
    else:
        n     = len(rows)
        row_h = max(220, 820 // n)
        rows_html = ""
        for i, r in enumerate(rows):
            dir_color = _GREEN if r["direction"] == "OVER" else _RED
            away_disc = _team_disc(_mlb_logo(r["away"]), _mlb_abbr(r["away"]), _mlb_hex(r["away"]), 80)
            home_disc = _team_disc(_mlb_logo(r["home"]), _mlb_abbr(r["home"]), _mlb_hex(r["home"]), 80)
            is_top    = (i == 0)
            bg  = f"linear-gradient(135deg,{dir_color}12,transparent 60%)" if is_top else "rgba(255,255,255,0.025)"
            bdr = f"1px solid {dir_color}40" if is_top else "1px solid rgba(255,255,255,0.07)"
            bar = f'<div style="position:absolute;left:0;top:0;bottom:0;width:5px;background:{dir_color};border-radius:20px 0 0 20px;opacity:{"1" if is_top else "0.35"}"></div>'

            rows_html += f"""
<div style="display:flex;align-items:center;background:{bg};border:{bdr};border-radius:20px;
     height:{row_h}px;padding:0 32px 0 36px;gap:22px;width:100%;
     margin-bottom:{'14' if i < n-1 else '0'}px;overflow:hidden;position:relative">
  {bar}
  <div style="display:flex;align-items:center;gap:10px;flex-shrink:0;opacity:0.75">
    {away_disc}
    <span style="font-size:12px;color:rgba(255,255,255,0.20);font-weight:700">vs</span>
    {home_disc}
  </div>
  <div style="flex:1;padding-left:8px">
    <div style="font-size:14px;font-weight:800;color:rgba(255,255,255,0.40);letter-spacing:0.18em;margin-bottom:8px">TOTAL RUNS</div>
    <div style="display:flex;align-items:baseline;gap:12px">
      <span style="font-family:'Barlow Condensed',sans-serif;font-size:60px;font-weight:900;color:{dir_color};line-height:1">{r["direction"]}</span>
      <span style="font-family:'Barlow Condensed',sans-serif;font-size:52px;font-weight:900;color:#fff;line-height:1">{r["line"]}</span>
    </div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:12px;flex-shrink:0">
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:60px;font-weight:900;color:rgba(255,255,255,0.88);line-height:1">{_fmt_odds(r["odds"])}</div>
    {_book_badge(r["book"], fs=13)}
  </div>
</div>"""

        body = f'<div style="width:100%;display:flex;flex-direction:column">{rows_html}</div>'
        html = _shell(body, pill="MLB TOTALS", pill_bg=f"{_GREEN}22",
                      pill_fg=_GREEN, date_str=dstr, record=rec, bg_glow_color=_GREEN)

    return _playwright_render(html, png.with_suffix(".html"), png)


# ─────────────────────────────────────────────────────────────────────────────
# Card 3 — World Cup V2
# ONE card per GAME, best-edge pick. Clean flag layout.
# ─────────────────────────────────────────────────────────────────────────────

def render_world_cup_v2(
    picks: list[dict],
    card_date: date | None = None,
    out_dir: Path | None = None,
) -> list[Path]:
    """One card per unique matchup. Flags as clean standalone images. Pick as hero text."""
    if not picks:
        return []
    card_date = card_date or date.today()
    ts   = card_date.strftime("%Y%m%d")
    dstr = card_date.strftime("%b %d, %Y").upper()
    if out_dir is None:
        out_dir = _ROOT / "output" / "picks" / "soccer_fifa_world_cup" / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    rec = _record_str("soccer")

    by_game: dict[str, list[dict]] = {}
    for p in picks:
        key = (p.get("matchup") or "unknown").strip()
        by_game.setdefault(key, []).append(p)

    paths: list[Path] = []
    for game_idx, (matchup, game_picks) in enumerate(by_game.items()):
        best = max(game_picks, key=lambda p: float(p.get("edge_pct") or 0))

        market    = (best.get("market") or "moneyline").lower()
        direction = best.get("direction") or best.get("team") or ""
        odds_str  = _fmt_odds(best.get("odds") or best.get("best_odds") or 0)
        book      = best.get("sportsbook") or ""
        line      = str(best.get("line") or "")

        away_t = home_t = ""
        if " @ " in matchup:
            away_t, home_t = matchup.split(" @ ", 1)
        away_t = away_t.strip(); home_t = home_t.strip()

        away_uri = _wc_flag_uri(away_t)
        home_uri = _wc_flag_uri(home_t)

        is_draw  = direction.lower() == "draw"
        is_total = market in ("total", "totals")
        is_btts  = market in ("btts", "both_teams_to_score")

        if is_total:
            dir_color  = _GREEN if "OVER" in direction.upper() else _RED
            market_lbl = "TOTAL GOALS"
            pick_text  = f"{direction.upper()} {line}".strip()
            away_op    = 1.0; home_op = 1.0   # both teams equal for totals
        elif is_btts:
            dir_color  = _INDIGO; market_lbl = "BOTH TEAMS TO SCORE"
            pick_text  = direction.upper()
            away_op    = 1.0; home_op = 1.0
        elif is_draw:
            dir_color  = _GOLD; market_lbl = "MATCH RESULT"
            pick_text  = "DRAW"
            away_op    = 0.65; home_op = 0.65
        else:
            dir_color  = _GOLD; market_lbl = "MATCH WINNER"
            pick_text  = direction.upper()
            is_away_pk = away_t and direction.strip().lower() in away_t.strip().lower()
            away_op    = 1.0 if is_away_pk else 0.55
            home_op    = 0.55 if is_away_pk else 1.0

        plen    = len(pick_text)
        pick_fs = 110 if plen <= 6 else (92 if plen <= 10 else (78 if plen <= 14 else 64))

        away_flag_el = _flag_img(away_uri, away_t, w=260, op=away_op)
        home_flag_el = _flag_img(home_uri, home_t, w=260, op=home_op)

        body = f"""
<div style="width:100%;display:flex;flex-direction:column;align-items:center;gap:28px">

  <!-- Flags — clean standalone images, generous size -->
  <div style="display:flex;align-items:center;gap:36px">
    <div style="display:flex;flex-direction:column;align-items:center;gap:14px">
      {away_flag_el}
      <span style="font-size:17px;font-weight:900;letter-spacing:4px;color:rgba(255,255,255,{away_op:.2f});text-transform:uppercase">{away_t.upper()[:16]}</span>
    </div>
    <span style="font-size:18px;font-weight:800;color:rgba(255,255,255,0.28);letter-spacing:3px">VS</span>
    <div style="display:flex;flex-direction:column;align-items:center;gap:14px">
      {home_flag_el}
      <span style="font-size:17px;font-weight:900;letter-spacing:4px;color:rgba(255,255,255,{home_op:.2f});text-transform:uppercase">{home_t.upper()[:16]}</span>
    </div>
  </div>

  <div style="width:85%;height:1px;background:rgba(255,255,255,0.08)"></div>

  <!-- Market label — colored, clear -->
  <div style="text-align:center">
    <div style="font-size:18px;font-weight:900;color:{dir_color};letter-spacing:0.22em;
         text-transform:uppercase;margin-bottom:12px;opacity:0.88">{market_lbl}</div>
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:{pick_fs}px;font-weight:900;
         color:{dir_color};letter-spacing:-1px;line-height:0.90;text-transform:uppercase;
         filter:drop-shadow(0 0 40px {dir_color}65)">{pick_text}</div>
  </div>

  <!-- Odds + book -->
  <div style="display:flex;align-items:center;gap:22px">
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:96px;font-weight:900;
         color:#fff;letter-spacing:-1px;line-height:1">{odds_str}</div>
    {_book_badge(book, fs=18)}
  </div>
</div>"""

        suffix = "" if game_idx == 0 else f"_{game_idx + 1}"
        png = out_dir / f"world_cup_card{suffix}.png"
        html = _shell(
            body, pill="WORLD CUP 2026", pill_bg=f"{_GOLD}22",
            pill_fg=_GOLD, date_str=dstr, record=rec,
            bg_glow_color=_GOLD, bg_glow2="#FF8C00",
            footer_note="Dixon-Coles Model  ·  Not financial advice",
        )
        result = _playwright_render(html, png.with_suffix(".html"), png)
        if result:
            paths.append(result)

    return paths


# ─────────────────────────────────────────────────────────────────────────────
# Card 4 — NBA Totals V2
# ─────────────────────────────────────────────────────────────────────────────

def render_nba_totals_v2(
    picks: list[dict],
    card_date: date | None = None,
) -> Optional[Path]:
    """NBA totals — mirrors MLB totals with NBA team discs."""
    if not picks:
        return None
    card_date = card_date or date.today()
    ts   = card_date.strftime("%Y%m%d")
    dstr = card_date.strftime("%b %d, %Y").upper()
    out_dir = _ROOT / "output" / "picks" / "basketball_nba" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / "nba_totals_card.png"

    rows: list[dict] = []
    for p in picks[:3]:
        direction = (p.get("direction") or p.get("Direction") or "OVER").upper()
        line      = p.get("line") or p.get("bet_line") or p.get("BetLine") or ""
        matchup   = p.get("matchup") or p.get("Matchup") or ""
        away_t = home_t = ""
        if matchup and " @ " in matchup:
            away_t, home_t = matchup.split(" @ ", 1)
        rows.append({
            "direction": direction, "line": str(line),
            "away": away_t.strip(), "home": home_t.strip(),
            "odds": p.get("odds") or p.get("BestOdds") or 0,
            "book": p.get("sportsbook") or p.get("Sportsbook") or "",
        })

    rec = _record_str("nba", "total")

    if len(rows) == 1:
        r         = rows[0]
        dir_color = _GREEN if r["direction"] == "OVER" else _RED
        away_disc = _team_disc(_nba_logo(r["away"]), _nba_abbr(r["away"]), _nba_hex(r["away"]), 140)
        home_disc = _team_disc(_nba_logo(r["home"]), _nba_abbr(r["home"]), _nba_hex(r["home"]), 140)

        body = f"""
<div style="width:100%;display:flex;flex-direction:column;align-items:center;gap:24px">
  <div style="display:flex;align-items:center;gap:24px">
    <div style="display:flex;flex-direction:column;align-items:center;gap:12px;opacity:0.72">
      {away_disc}
      <span style="font-size:14px;font-weight:900;letter-spacing:4px;color:rgba(255,255,255,0.80)">{_nba_abbr(r["away"])}</span>
    </div>
    <span style="font-size:24px;font-weight:700;color:rgba(255,255,255,0.20)">@</span>
    <div style="display:flex;flex-direction:column;align-items:center;gap:12px;opacity:0.72">
      {home_disc}
      <span style="font-size:14px;font-weight:900;letter-spacing:4px;color:rgba(255,255,255,0.80)">{_nba_abbr(r["home"])}</span>
    </div>
  </div>
  <div style="width:85%;height:1px;background:rgba(255,255,255,0.08)"></div>
  <div style="text-align:center;line-height:0.88">
    <div style="font-size:13px;font-weight:800;color:rgba(255,255,255,0.35);letter-spacing:0.24em;margin-bottom:14px">TOTAL POINTS</div>
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:160px;font-weight:900;
         color:{dir_color};letter-spacing:-3px;text-transform:uppercase;
         filter:drop-shadow(0 0 50px {dir_color}70)">{r["direction"]}</div>
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:130px;font-weight:900;
         color:#fff;letter-spacing:-2px;margin-top:-12px">{r["line"]}</div>
  </div>
  <div style="display:flex;align-items:center;gap:22px">
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:82px;font-weight:900;
         color:rgba(255,255,255,0.88);letter-spacing:-1px">{_fmt_odds(r["odds"])}</div>
    {_book_badge(r["book"], fs=17)}
  </div>
</div>"""

        html = _shell(body, pill="NBA TOTALS", pill_bg="#3a86ff22",
                      pill_fg="#3a86ff", date_str=dstr, record=rec,
                      bg_glow_color=_nba_hex(r["away"]), bg_glow2=_nba_hex(r["home"]))
    else:
        n     = len(rows); row_h = max(220, 820 // n)
        rows_html = ""
        for i, r in enumerate(rows):
            dir_color = _GREEN if r["direction"] == "OVER" else _RED
            away_d = _team_disc(_nba_logo(r["away"]), _nba_abbr(r["away"]), _nba_hex(r["away"]), 80)
            home_d = _team_disc(_nba_logo(r["home"]), _nba_abbr(r["home"]), _nba_hex(r["home"]), 80)
            is_top = (i == 0)
            bg  = f"linear-gradient(135deg,{dir_color}12,transparent 60%)" if is_top else "rgba(255,255,255,0.025)"
            bdr = f"1px solid {dir_color}40" if is_top else "1px solid rgba(255,255,255,0.07)"
            bar = f'<div style="position:absolute;left:0;top:0;bottom:0;width:5px;background:{dir_color};border-radius:20px 0 0 20px;opacity:{"1" if is_top else "0.35"}"></div>'

            rows_html += f"""
<div style="display:flex;align-items:center;background:{bg};border:{bdr};border-radius:20px;
     height:{row_h}px;padding:0 32px 0 36px;gap:22px;width:100%;
     margin-bottom:{'14' if i<n-1 else '0'}px;overflow:hidden;position:relative">
  {bar}
  <div style="display:flex;align-items:center;gap:10px;flex-shrink:0;opacity:0.75">
    {away_d}<span style="font-size:12px;color:rgba(255,255,255,0.20);font-weight:700">vs</span>{home_d}
  </div>
  <div style="flex:1;padding-left:8px">
    <div style="font-size:14px;font-weight:800;color:rgba(255,255,255,0.40);letter-spacing:0.18em;margin-bottom:8px">TOTAL POINTS</div>
    <div style="display:flex;align-items:baseline;gap:12px">
      <span style="font-family:'Barlow Condensed',sans-serif;font-size:60px;font-weight:900;color:{dir_color};line-height:1">{r["direction"]}</span>
      <span style="font-family:'Barlow Condensed',sans-serif;font-size:52px;font-weight:900;color:#fff;line-height:1">{r["line"]}</span>
    </div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:12px;flex-shrink:0">
    <div style="font-family:'Barlow Condensed',sans-serif;font-size:60px;font-weight:900;color:rgba(255,255,255,0.88);line-height:1">{_fmt_odds(r["odds"])}</div>
    {_book_badge(r["book"], fs=13)}
  </div>
</div>"""

        body = f'<div style="width:100%;display:flex;flex-direction:column">{rows_html}</div>'
        html = _shell(body, pill="NBA TOTALS", pill_bg="#3a86ff22",
                      pill_fg="#3a86ff", date_str=dstr, record=rec, bg_glow_color="#3a86ff")

    return _playwright_render(html, png.with_suffix(".html"), png)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience
# ─────────────────────────────────────────────────────────────────────────────

def render_mlb_cards_v2(picks: list[dict], card_date: date | None = None) -> dict[str, Optional[Path]]:
    out: dict[str, Optional[Path]] = {}
    ml  = [p for p in picks if (p.get("Market") or p.get("market", "")).lower() == "moneyline"]
    tot = [p for p in picks if (p.get("Market") or p.get("market", "")).lower() in ("total", "f5_total")]
    if ml:
        out["mlb_moneyline"] = render_mlb_moneyline_v2(ml, card_date)
    if tot:
        out["mlb_totals"] = render_mlb_totals_v2(tot, card_date)
    return out

"""
Result cards + weekly recap cards for Overlay.

Result card  — 1080×1080 square. Centered, logo-forward, bold.
Weekly recap — 1080×1350 portrait. Generated every Sunday.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT       = Path(__file__).resolve().parent.parent.parent
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"
OUTPUT_DIR = ROOT / "output" / "result_cards"

# ── ESPN logo CDN mappings ────────────────────────────────────────────────────

_MLB_LOGOS: dict[str, str] = {
    "atlanta braves": "atl", "arizona diamondbacks": "ari", "baltimore orioles": "bal",
    "boston red sox": "bos", "chicago cubs": "chc", "chicago white sox": "cws",
    "cincinnati reds": "cin", "cleveland guardians": "cle", "colorado rockies": "col",
    "detroit tigers": "det", "houston astros": "hou", "kansas city royals": "kc",
    "los angeles angels": "laa", "los angeles dodgers": "lad", "miami marlins": "mia",
    "milwaukee brewers": "mil", "minnesota twins": "min", "new york mets": "nym",
    "new york yankees": "nyy", "oakland athletics": "oak", "philadelphia phillies": "phi",
    "pittsburgh pirates": "pit", "san diego padres": "sd", "san francisco giants": "sf",
    "seattle mariners": "sea", "st. louis cardinals": "stl", "tampa bay rays": "tb",
    "texas rangers": "tex", "toronto blue jays": "tor", "washington nationals": "wsh",
}

_NBA_LOGOS: dict[str, str] = {
    "atlanta hawks": "atl", "boston celtics": "bos", "brooklyn nets": "bkn",
    "charlotte hornets": "cha", "chicago bulls": "chi", "cleveland cavaliers": "cle",
    "dallas mavericks": "dal", "denver nuggets": "den", "detroit pistons": "det",
    "golden state warriors": "gs", "houston rockets": "hou", "indiana pacers": "ind",
    "los angeles clippers": "lac", "los angeles lakers": "lal", "memphis grizzlies": "mem",
    "miami heat": "mia", "milwaukee bucks": "mil", "minnesota timberwolves": "min",
    "new orleans pelicans": "no", "new york knicks": "ny", "oklahoma city thunder": "okc",
    "orlando magic": "orl", "philadelphia 76ers": "phi", "phoenix suns": "phx",
    "portland trail blazers": "por", "sacramento kings": "sac", "san antonio spurs": "sa",
    "toronto raptors": "tor", "utah jazz": "utah", "washington wizards": "wsh",
    "minnesota lynx": "min", "las vegas aces": "lv", "seattle storm": "sea",
    "dallas wings": "dal", "indiana fever": "ind", "golden state valkyries": "gsv",
}

_LEAGUE_LOGOS: dict[str, str] = {
    "mlb":  "https://a.espncdn.com/i/teamlogos/leagues/500/mlb.png",
    "nba":  "https://a.espncdn.com/i/teamlogos/leagues/500/nba.png",
    "nhl":  "https://a.espncdn.com/i/teamlogos/leagues/500/nhl.png",
    "wnba": "https://a.espncdn.com/i/teamlogos/leagues/500/wnba.png",
}

def _logo_url(team: str, sport: str) -> str:
    t = team.lower().strip()
    s = sport.lower()

    if "nba" in s or "wnba" in s:
        abbrev = _NBA_LOGOS.get(t)
        league = "wnba" if "wnba" in s else "nba"
    else:
        abbrev = _MLB_LOGOS.get(t)
        league = "mlb" if "mlb" in s else "nhl"

    if not abbrev:
        # Fuzzy match
        pool = _NBA_LOGOS if "nba" in s or "wnba" in s else _MLB_LOGOS
        for word in [w for w in t.split() if len(w) > 3]:
            for k, v in pool.items():
                if word in k:
                    abbrev = v
                    break
            if abbrev:
                break

    if not abbrev:
        # Totals/spread bet — no team name, fall back to league logo
        for key in ("nba","wnba","nhl","mlb"):
            if key in s:
                return _LEAGUE_LOGOS[key]
        return _LEAGUE_LOGOS.get("mlb", "")

    return f"https://a.espncdn.com/i/teamlogos/{league}/500/{abbrev}.png"


# ── Shared helpers ────────────────────────────────────────────────────────────

def _render(html: str, out_path: Path, width: int = 1080, height: int = 1080) -> Optional[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(html, wait_until="networkidle")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_path),
                            clip={"x": 0, "y": 0, "width": width, "height": height})
            browser.close()
        return out_path
    except Exception as e:
        print(f"  [result_cards] render error: {e}")
        return None


def _load_picks() -> list[dict]:
    raw = json.loads(PICKS_FILE.read_text())
    picks = raw if isinstance(raw, list) else raw.get("picks", [])
    return [p for p in picks if isinstance(p, dict)]


def _fmt_odds(odds) -> str:
    try:
        o = int(float(odds))
        return f"+{o}" if o > 0 else str(o)
    except Exception:
        return "N/A"


def _sport_label(sport: str) -> str:
    s = (sport or "").lower()
    if "mlb" in s or "baseball" in s:   return "MLB"
    if "wnba" in s:                      return "WNBA"
    if "nba" in s or "basketball" in s:  return "NBA"
    if "nhl" in s or "icehockey" in s:   return "NHL"
    if "soccer" in s or "football" in s: return "SOCCER"
    if "tennis" in s:                    return "TENNIS"
    if "ufc" in s or "mma" in s:         return "UFC"
    if "pga" in s or "golf" in s:        return "PGA"
    return s.upper()


def _market_label(market: str) -> str:
    return {
        "moneyline":"MONEYLINE","ml":"MONEYLINE","total":"GAME TOTAL",
        "totals":"GAME TOTAL","f5_total":"F5 TOTAL","spread":"SPREAD",
        "run_line":"RUN LINE","puck_line":"PUCK LINE","nrfi":"NRFI",
    }.get((market or "").lower(), (market or "").upper())


def _season_record() -> tuple[int, int, float]:
    all_picks = _load_picks()
    settled = [p for p in all_picks
               if p.get("card_pick") and p.get("result") in ("win","loss","push")]
    w = sum(1 for p in settled if p["result"] == "win")
    l = sum(1 for p in settled if p["result"] == "loss")
    profit = sum(p.get("profit") or 0 for p in settled)
    return w, l, profit


# ── Result card ───────────────────────────────────────────────────────────────

def render_result_card(pick: dict, out_dir: Path | None = None) -> Optional[Path]:
    result   = (pick.get("result") or "").lower()
    if result not in ("win", "loss", "push"):
        return None

    if result == "win":
        accent      = "#00e87a"
        accent_dark = "#004d2a"
        accent_text = "#000000"
        badge_icon  = "✓"
        badge_label = "WINNER"
        glow_color  = "rgba(0,232,122,0.18)"
    elif result == "loss":
        accent      = "#ff4444"
        accent_dark = "#4d0000"
        accent_text = "#ffffff"
        badge_icon  = "✗"
        badge_label = "NO HIT"
        glow_color  = "rgba(255,68,68,0.15)"
    else:
        accent      = "#888888"
        accent_dark = "#333333"
        accent_text = "#ffffff"
        badge_icon  = "~"
        badge_label = "PUSH"
        glow_color  = "rgba(136,136,136,0.12)"

    profit     = pick.get("profit") or 0
    odds       = _fmt_odds(pick.get("odds"))
    sport      = _sport_label(pick.get("sport", ""))
    market     = _market_label(pick.get("market", ""))
    team       = str(pick.get("team") or pick.get("Team") or "")
    pick_date  = pick.get("date", str(date.today()))
    logo_url   = _logo_url(team, pick.get("sport", ""))

    profit_str = f"+{profit:.2f}u" if profit >= 0 else f"{profit:.2f}u"
    profit_col = accent if profit >= 0 else "#ff4444"

    sw, sl, sp = _season_record()
    sp_str     = f"+{sp:.1f}u" if sp >= 0 else f"{sp:.1f}u"
    wr_str     = f"{sw/(sw+sl)*100:.1f}%" if (sw+sl) else "—"

    # Logo HTML — big centred ghost behind content
    logo_html = (
        f'<img src="{logo_url}" class="team-logo" onerror="this.style.display=\'none\'">'
        if logo_url else ""
    )

    # Shorten long team/bet names
    display_team = team
    if len(team) > 22:
        display_team = team[:22].rstrip() + "…"

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1080px; overflow:hidden;
  background: radial-gradient(ellipse at 50% 40%, {glow_color} 0%, #080c10 55%);
  background-color: #080c10;
  font-family: 'Inter', sans-serif;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  position: relative;
}}

/* Subtle grid texture */
body::before {{
  content:''; position:absolute; inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
  background-size: 60px 60px;
  pointer-events:none;
}}

/* Accent corner bars */
.corner-tl, .corner-tr, .corner-bl, .corner-br {{
  position:absolute; width:48px; height:48px;
}}
.corner-tl {{ top:32px; left:32px; border-top:3px solid {accent}; border-left:3px solid {accent}; }}
.corner-tr {{ top:32px; right:32px; border-top:3px solid {accent}; border-right:3px solid {accent}; }}
.corner-bl {{ bottom:32px; left:32px; border-bottom:3px solid {accent}; border-left:3px solid {accent}; }}
.corner-br {{ bottom:32px; right:32px; border-bottom:3px solid {accent}; border-right:3px solid {accent}; }}

/* Ghost logo */
.team-logo {{
  position:absolute;
  width:560px; height:560px;
  object-fit:contain;
  opacity:0.07;
  top:50%; left:50%;
  transform:translate(-50%,-50%);
  pointer-events:none;
  filter: saturate(0) brightness(2);
}}

/* Main centered content */
.card-inner {{
  position:relative; z-index:10;
  display:flex; flex-direction:column;
  align-items:center; text-align:center;
  gap:0;
  padding: 0 80px;
}}

.brand {{
  font-size:13px; font-weight:700; letter-spacing:0.25em;
  color:#c0d4e8; text-transform:uppercase; margin-bottom:28px;
}}

/* Big result badge */
.result-wrap {{
  display:flex; align-items:center; gap:16px;
  background:{accent_dark};
  border:2px solid {accent};
  border-radius:60px;
  padding:14px 40px;
  margin-bottom:40px;
}}
.result-icon {{
  font-size:28px; font-weight:900; color:{accent}; line-height:1;
}}
.result-label {{
  font-size:22px; font-weight:900; letter-spacing:0.25em;
  color:{accent}; text-transform:uppercase;
}}

/* Team name */
.team-name {{
  font-family:'Bebas Neue', 'Inter', sans-serif;
  font-size:96px; font-weight:400;
  color:#ffffff; line-height:0.95;
  letter-spacing:0.03em;
  text-shadow: 0 4px 40px rgba(0,0,0,0.8);
}}

/* Market + odds pill row */
.meta-row {{
  display:flex; align-items:center; gap:14px;
  margin-top:22px; flex-wrap:wrap; justify-content:center;
}}
.meta-pill {{
  font-size:20px; font-weight:800; letter-spacing:0.1em;
  color:#c8ddf0; text-transform:uppercase;
  background:#111820; border:1px solid #2a3a50;
  border-radius:28px; padding:12px 28px;
}}
.odds-pill {{
  font-size:36px; font-weight:900;
  color:{accent};
  background:#111820; border:2px solid {accent}88;
  border-radius:28px; padding:10px 32px;
  text-shadow: 0 0 30px {accent}66;
}}

/* Profit number */
.profit-block {{
  margin-top:36px;
}}
.profit-label {{
  font-size:13px; font-weight:700; letter-spacing:0.2em;
  color:#b0c8e0; text-transform:uppercase; margin-bottom:8px;
}}
.profit-val {{
  font-family:'Bebas Neue', 'Inter', sans-serif;
  font-size:88px; font-weight:400;
  color:{profit_col}; line-height:1;
  letter-spacing:0.02em;
  text-shadow: 0 0 60px {profit_col}66;
}}

/* Season record strip */
.record-strip {{
  display:flex; align-items:center; gap:20px;
  background:#0e1419; border:1px solid #243040;
  border-radius:16px; padding:18px 32px;
  margin-top:36px;
}}
.rec-item {{
  display:flex; flex-direction:column; align-items:center;
}}
.rec-label {{
  font-size:11px; font-weight:700; letter-spacing:0.18em;
  color:#b0c8e0; text-transform:uppercase; margin-bottom:4px;
}}
.rec-val {{
  font-size:20px; font-weight:900; color:#fff;
}}
.rec-div {{
  width:1px; height:32px; background:#243040;
}}

/* Footer */
.footer {{
  position:absolute; bottom:44px; left:0; right:0;
  display:flex; justify-content:space-between;
  padding:0 56px; z-index:10;
}}
.footer-brand {{ font-size:13px; font-weight:800; color:#a0bcd4; letter-spacing:0.15em; }}
.footer-date  {{ font-size:12px; color:#8aaac0; }}
</style>
</head><body>

<div class="corner-tl"></div>
<div class="corner-tr"></div>
<div class="corner-bl"></div>
<div class="corner-br"></div>

{logo_html}

<div class="card-inner">
  <div class="brand">Overlay &nbsp;·&nbsp; AI Model</div>

  <div class="result-wrap">
    <span class="result-icon">{badge_icon}</span>
    <span class="result-label">{badge_label}</span>
  </div>

  <div class="team-name">{display_team}</div>

  <div class="meta-row">
    <span class="meta-pill">{sport}</span>
    <span class="meta-pill">{market}</span>
    <span class="odds-pill">{odds}</span>
  </div>

  <div class="profit-block">
    <div class="profit-label">Profit / Loss</div>
    <div class="profit-val">{profit_str}</div>
  </div>

  <div class="record-strip">
    <div class="rec-item">
      <div class="rec-label">Season</div>
      <div class="rec-val">{sw}–{sl}</div>
    </div>
    <div class="rec-div"></div>
    <div class="rec-item">
      <div class="rec-label">Profit</div>
      <div class="rec-val">{sp_str}</div>
    </div>
    <div class="rec-div"></div>
    <div class="rec-item">
      <div class="rec-label">Win Rate</div>
      <div class="rec-val">{wr_str}</div>
    </div>
    <div class="rec-div"></div>
    <div class="rec-item">
      <div class="rec-label">Date</div>
      <div class="rec-val" style="font-size:15px">{pick_date}</div>
    </div>
  </div>
</div>

<div class="footer">
  <span class="footer-brand">OVERLAY-GRAY.VERCEL.APP</span>
  <span class="footer-date">Picks logged before first pitch · Verified record</span>
</div>

</body></html>"""

    if out_dir is None:
        ts = str(pick_date).replace("-", "")
        out_dir = OUTPUT_DIR / ts

    slug = team.lower().replace(" ", "_").replace("/", "_")[:30]
    out_path = out_dir / f"result_{result}_{slug}.png"
    return _render(html, out_path)


# ── Weekly recap card ─────────────────────────────────────────────────────────

def render_weekly_recap_card(week_end: date | None = None) -> Optional[Path]:
    if week_end is None:
        week_end = date.today()
    week_start = week_end - timedelta(days=6)

    all_picks = _load_picks()
    card      = [p for p in all_picks if p.get("card_pick")]

    week_picks = [
        p for p in card
        if p.get("result") in ("win","loss","push")
        and str(week_start) <= (p.get("date") or "") <= str(week_end)
    ]
    w      = sum(1 for p in week_picks if p["result"] == "win")
    l      = sum(1 for p in week_picks if p["result"] == "loss")
    profit = sum(p.get("profit") or 0 for p in week_picks)
    wr     = f"{w/(w+l)*100:.1f}%" if (w+l) else "—"

    sw, sl, sp = _season_record()
    sp_str = f"+{sp:.1f}u" if sp >= 0 else f"{sp:.1f}u"

    profit_col = "#00e87a" if profit >= 0 else "#ff4444"
    profit_str = f"+{profit:.2f}u" if profit >= 0 else f"{profit:.2f}u"

    # By sport
    sport_stats: dict[str, dict] = defaultdict(lambda: {"w":0,"l":0,"profit":0.0})
    for p in week_picks:
        s = _sport_label(p.get("sport","?"))
        if p["result"] == "win":   sport_stats[s]["w"] += 1
        elif p["result"] == "loss": sport_stats[s]["l"] += 1
        sport_stats[s]["profit"] += p.get("profit") or 0

    sport_rows = ""
    for sname, d in sorted(sport_stats.items()):
        pp = d["profit"]
        pcol = "#00e87a" if pp >= 0 else "#ff4444"
        psign = "+" if pp >= 0 else ""
        sport_rows += f"""
      <div class="sport-row">
        <div class="sport-left">
          <div class="sport-name">{sname}</div>
          <div class="sport-wl">{d['w']}W &nbsp;–&nbsp; {d['l']}L</div>
        </div>
        <div class="sport-profit" style="color:{pcol}">{psign}{pp:.2f}u</div>
      </div>"""

    best = max(week_picks, key=lambda p: p.get("profit") or 0, default=None)
    best_html = ""
    if best and (best.get("profit") or 0) > 0:
        b_team   = str(best.get("team") or "")[:28]
        b_sport  = _sport_label(best.get("sport",""))
        b_market = _market_label(best.get("market",""))
        b_odds   = _fmt_odds(best.get("odds"))
        b_profit = best.get("profit") or 0
        b_logo   = _logo_url(b_team, best.get("sport",""))
        b_logo_html = f'<img src="{b_logo}" class="best-logo" onerror="this.style.display=\'none\'">' if b_logo else ""
        best_html = f"""
    <div class="section-label">Best Pick of the Week</div>
    <div class="best-pick">
      {b_logo_html}
      <div class="best-inner">
        <div class="best-meta">{b_sport} · {b_market} · {b_odds}</div>
        <div class="best-team">{b_team}</div>
        <div class="best-profit">+{b_profit:.2f}u</div>
      </div>
    </div>"""

    date_range = f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d, %Y')}"

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1350px; overflow:hidden;
  background:#080c10;
  font-family:'Inter', sans-serif;
  position:relative;
}}
body::before {{
  content:''; position:absolute; inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
  background-size:60px 60px;
}}
.accent-bar {{
  height:3px;
  background:#00e87a;
}}
.content {{
  position:relative; z-index:10;
  padding:52px 64px 48px;
  display:flex; flex-direction:column;
  height:calc(1350px - 6px);
}}
.brand {{ font-size:13px; font-weight:700; letter-spacing:0.25em; color:#c0d4e8; text-transform:uppercase; }}
.title {{
  font-family:'Bebas Neue', sans-serif;
  font-size:72px; color:#fff;
  letter-spacing:0.04em; line-height:1;
  margin-top:6px;
}}
.subtitle {{ font-size:18px; color:#8aaac0; margin-top:4px; letter-spacing:0.05em; }}

/* Big stats row */
.big-stats {{
  display:grid; grid-template-columns:1fr 1fr 1fr;
  gap:16px; margin-top:36px;
}}
.big-stat {{
  background:#0e1419; border:1px solid #243040;
  border-radius:20px; padding:28px 24px;
  display:flex; flex-direction:column; align-items:center;
}}
.big-stat-label {{
  font-size:11px; font-weight:700; letter-spacing:0.2em;
  color:#b0c8e0; text-transform:uppercase; margin-bottom:10px;
}}
.big-stat-val {{
  font-family:'Bebas Neue', sans-serif;
  font-size:64px; color:#fff; line-height:1;
}}
.big-stat-val.green {{ color:#00e87a; text-shadow:0 0 40px #00e87a44; }}

.section-label {{
  font-size:12px; font-weight:700; letter-spacing:0.2em;
  color:#b0c8e0; text-transform:uppercase;
  margin-top:32px; margin-bottom:14px;
}}

/* Sport breakdown */
.sport-grid {{ display:flex; flex-direction:column; gap:10px; }}
.sport-row {{
  background:#0e1419; border:1px solid #243040;
  border-radius:14px; padding:16px 24px;
  display:flex; justify-content:space-between; align-items:center;
}}
.sport-left {{ display:flex; align-items:center; gap:20px; }}
.sport-name {{ font-size:16px; font-weight:800; color:#c8ddf0; letter-spacing:0.05em; min-width:80px; }}
.sport-wl   {{ font-size:20px; font-weight:900; color:#fff; }}
.sport-profit {{ font-size:18px; font-weight:900; }}

/* Best pick */
.best-pick {{
  background:#0e1419; border:1px solid #1e3a2a;
  border-radius:18px; padding:22px 28px;
  display:flex; align-items:center; gap:20px;
  position:relative; overflow:hidden;
}}
.best-pick::before {{
  content:''; position:absolute; inset:0;
  background:linear-gradient(135deg, #00e87a0a 0%, transparent 60%);
}}
.best-logo {{
  width:72px; height:72px; object-fit:contain;
  opacity:0.9; flex-shrink:0; position:relative; z-index:1;
}}
.best-inner {{ position:relative; z-index:1; }}
.best-meta  {{ font-size:13px; font-weight:700; letter-spacing:0.12em; color:#00e87a; text-transform:uppercase; }}
.best-team  {{ font-family:'Bebas Neue', sans-serif; font-size:42px; color:#fff; line-height:1; margin:4px 0; }}
.best-profit {{ font-size:22px; font-weight:900; color:#00e87a; }}

/* Season footer bar */
.season-bar {{
  margin-top:auto; padding-top:24px;
  border-top:1px solid #1a2230;
  display:flex; justify-content:space-between; align-items:center;
}}
.season-stat {{ display:flex; flex-direction:column; }}
.season-label {{ font-size:11px; font-weight:700; letter-spacing:0.18em; color:#b0c8e0; text-transform:uppercase; }}
.season-val   {{ font-size:22px; font-weight:900; color:#fff; margin-top:3px; }}
.footer-brand {{ font-size:12px; font-weight:800; color:#a0bcd4; letter-spacing:0.15em; align-self:flex-end; }}
</style>
</head><body>
<div class="accent-bar"></div>
<div class="content">
  <div class="brand">Overlay &nbsp;·&nbsp; AI Model</div>
  <div class="title">Week in Review</div>
  <div class="subtitle">{date_range}</div>

  <div class="big-stats">
    <div class="big-stat">
      <div class="big-stat-label">Record</div>
      <div class="big-stat-val">{w}–{l}</div>
    </div>
    <div class="big-stat">
      <div class="big-stat-label">Profit</div>
      <div class="big-stat-val green">{profit_str}</div>
    </div>
    <div class="big-stat">
      <div class="big-stat-label">Win Rate</div>
      <div class="big-stat-val">{wr}</div>
    </div>
  </div>

  <div class="section-label">By Sport</div>
  <div class="sport-grid">{sport_rows}</div>

  {best_html}

  <div class="season-bar">
    <div class="season-stat">
      <div class="season-label">Season Record</div>
      <div class="season-val">{sw}W – {sl}L</div>
    </div>
    <div class="season-stat">
      <div class="season-label">Season Profit</div>
      <div class="season-val" style="color:#00e87a">{sp_str}</div>
    </div>
    <div class="season-stat">
      <div class="season-label">Season ROI</div>
      <div class="season-val">+{sp/(sw+sl)*100:.1f}%</div>
    </div>
    <div class="footer-brand">OVERLAY-GRAY.VERCEL.APP</div>
  </div>
</div>
</body></html>"""

    ts       = week_end.strftime("%Y%m%d")
    out_path = OUTPUT_DIR / ts / "weekly_recap.png"
    return _render(html, out_path, width=1080, height=1350)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "recap":
        path = render_weekly_recap_card()
        print(f"Weekly recap → {path}")
    else:
        picks = _load_picks()
        settled = [p for p in picks if p.get("card_pick") and p.get("result") in ("win","loss","push")]
        if settled:
            last = sorted(settled, key=lambda p: p.get("resulted_at") or p.get("date",""))[-1]
            path = render_result_card(last)
            print(f"Result card → {path}")

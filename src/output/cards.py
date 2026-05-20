"""
New card design system — ChefTonyBets 2026.
Clean, bold, math-backed. 1080×1350px (4:5 portrait).

Cards generated only for active markets:
  - MLB Moneyline (Tier 2)
  - MLB Totals (Tier 1)
  - MLB Pitcher Ks (Tier 2)
  - NBA Totals (Tier 1)
  - Tennis (Tier 1)
  - Soccer (Tier 1)
  - PGA outright (Tier 2)
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Shared utilities
# ─────────────────────────────────────────────────────────────────────────────

def _render_html_to_png(html: str, out_path: Path) -> Optional[Path]:
    """Render HTML string to PNG via Playwright. Returns path or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [cards] Playwright not installed — skipping PNG render.")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1080, "height": 1350})
            page.set_content(html, wait_until="networkidle")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=str(out_path),
                clip={"x": 0, "y": 0, "width": 1080, "height": 1350},
            )
            browser.close()
        return out_path
    except Exception as e:
        print(f"  [cards] Playwright render error: {e}")
        return None


def _fmt_odds(odds) -> str:
    """Format odds as +140 or -110."""
    try:
        o = int(float(odds))
    except (TypeError, ValueError):
        return "N/A"
    return f"+{o}" if o > 0 else str(o)


def _edge_bar_pct(edge_pct: float) -> int:
    """Convert edge % to bar fill % (max 100). Scale: 12% edge = full bar."""
    return min(int(edge_pct / 12 * 100), 100)


def _resolve_edge_pct(pick: dict) -> float:
    """
    Normalize edge from either edge_pct (already in %) or Edge (fraction or %).
    MLB predict.py stores Edge as a fraction (0.074 = 7.4%) for moneyline,
    but also as raw run-diff for totals (e.g. 1.9). We clamp to sane range.
    """
    if "edge_pct" in pick and pick["edge_pct"] is not None:
        val = float(pick["edge_pct"])
        # edge_pct should already be in percentage points (e.g. 8.4)
        return max(0.0, val)
    if "Edge" in pick and pick["Edge"] is not None:
        val = float(pick["Edge"])
        # If Edge < 1 it's a fraction — convert to pct
        if abs(val) < 1:
            val = val * 100
        return max(0.0, val)
    return 0.0


def _sport_badge(sport: str, label: str | None = None, color: str | None = None) -> str:
    """Return HTML for the sport badge pill in top-right."""
    _BADGE_COLORS = {
        "mlb":            ("#00e87a", "#000"),
        "baseball_mlb":   ("#00e87a", "#000"),
        "nba":            ("#3a86ff", "#fff"),
        "basketball_nba": ("#3a86ff", "#fff"),
        "tennis":         ("#ff6b35", "#fff"),
        "soccer":         ("#00c9b1", "#000"),
        "pga":            ("#f5c518", "#000"),
        "golf":           ("#f5c518", "#000"),
    }
    sport_lower = (sport or "").lower()
    # Find matching key
    bg, fg = ("#00e87a", "#000")
    for key, colors in _BADGE_COLORS.items():
        if key in sport_lower:
            bg, fg = colors
            break
    if color:
        bg = color
        fg = "#000"

    if not label:
        label = sport_lower.replace("baseball_mlb", "MLB").replace("basketball_nba", "NBA PLAYOFFS").upper()
        label = label.replace("BASEBALL_MLB", "MLB").replace("BASKETBALL_NBA", "NBA PLAYOFFS")
        # Simplify long sport keys
        if "FRENCH_OPEN" in label or "ATP_FRENCH_OPEN" in label:
            label = "ROLAND-GARROS"
        elif "WIMBLEDON" in label:
            label = "WIMBLEDON"
        elif "US_OPEN" in label and "TENNIS" in label:
            label = "US OPEN"
        elif "AUSTRALIAN" in label:
            label = "AUS OPEN"

    return (
        f'<span style="background:{bg};color:{fg};font-size:14px;font-weight:800;'
        f'letter-spacing:0.08em;padding:8px 20px;border-radius:24px;'
        f'text-transform:uppercase;font-family:Inter,sans-serif;">{label}</span>'
    )


def _card_html(
    sport_label: str,
    date_str: str,
    body_html: str,
    badge_color: str = "#00e87a",
    badge_label: str | None = None,
    sport_key: str = "mlb",
    market_banner: str | None = None,
    record_strip_html: str | None = None,
    form_strip_html: str | None = None,
) -> str:
    """
    Wrap body_html in the full card template.
    Returns complete HTML string for a 1080×1350px card.
    """
    badge = _sport_badge(sport_key, label=badge_label or sport_label, color=badge_color)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=1080" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Barlow+Condensed:wght@700;800;900&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --bg:           #080c14;
      --surface:      #0f1623;
      --surface-border: rgba(255,255,255,0.07);
      --top-border:   rgba(0,232,122,0.25);
      --accent:       #00e87a;
      --text:         #ffffff;
      --text-sec:     rgba(255,255,255,0.45);
      --text-muted:   rgba(255,255,255,0.25);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      width: 1080px;
      height: 1350px;
      background: var(--bg);
      font-family: 'Inter', sans-serif;
      color: var(--text);
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}

    /* ── Header ── */
    .header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 44px 56px 32px;
      flex-shrink: 0;
    }}
    .logo-block {{
      display: flex;
      flex-direction: column;
    }}
    .logo {{
      font-family: 'Inter', sans-serif;
      font-size: 52px;
      font-weight: 800;
      letter-spacing: -0.03em;
      color: #fff;
      line-height: 1;
    }}
    .logo .accent {{ color: var(--accent); }}
    .logo-sub {{
      font-size: 15px;
      font-weight: 600;
      color: var(--accent);
      letter-spacing: 0.04em;
      margin-top: 6px;
    }}
    .header-right {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 10px;
    }}
    .header-date {{
      font-size: 14px;
      color: rgba(255,255,255,0.45);
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}

    /* ── Picks area ── */
    .picks {{
      flex: 1;
      display: flex;
      flex-direction: column;
      justify-content: center;
      padding: 8px 56px;
      gap: 16px;
    }}
    /* When few picks, let each row breathe vertically so we don't get dead space */
    .picks .pick-row {{ min-height: 180px; }}

    /* ── Pick row ── */
    .pick-row {{
      background: var(--surface);
      border: 1px solid var(--surface-border);
      border-radius: 16px;
      padding: 28px 32px;
      display: flex;
      align-items: center;
      gap: 24px;
      position: relative;
    }}
    .pick-row.top-play {{
      border-color: var(--top-border);
    }}

    /* TOP PLAY badge */
    .top-play-badge {{
      position: absolute;
      top: -12px;
      left: 28px;
      background: var(--accent);
      color: #000;
      font-size: 10px;
      font-weight: 900;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      padding: 3px 12px;
      border-radius: 20px;
      font-family: 'Inter', sans-serif;
    }}

    /* ── Market banner (full-width type identifier) ── */
    .market-banner {{
      padding: 0 56px 28px;
      flex-shrink: 0;
    }}
    .market-banner-text {{
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.20em;
      text-transform: uppercase;
      color: rgba(255,255,255,0.18);
      border-top: 1px solid rgba(255,255,255,0.07);
      padding-top: 20px;
    }}

    /* ── Left section ── */
    .pick-left {{
      flex: 1;
      min-width: 0;
    }}
    .market-label {{
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 6px;
    }}
    .team-name {{
      font-size: 26px;
      font-weight: 800;
      color: var(--text);
      letter-spacing: -0.01em;
      line-height: 1.1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .matchup {{
      font-size: 13px;
      color: var(--text-sec);
      margin-top: 5px;
      font-weight: 500;
    }}

    /* ── Center section (direction/line) ── */
    .pick-center {{
      display: flex;
      flex-direction: column;
      align-items: center;
      min-width: 110px;
    }}
    .direction-label {{
      font-size: 20px;
      font-weight: 900;
      letter-spacing: 0.04em;
      color: var(--text);
      text-transform: uppercase;
    }}
    .line-label {{
      font-size: 15px;
      font-weight: 700;
      color: var(--text-sec);
      margin-top: 2px;
    }}
    .proj-label {{
      font-size: 11px;
      font-weight: 700;
      color: var(--accent);
      margin-top: 4px;
      letter-spacing: 0.04em;
    }}

    /* ── Odds section ── */
    .pick-odds {{
      display: flex;
      flex-direction: column;
      align-items: center;
      min-width: 100px;
    }}
    .odds-number {{
      font-family: 'Barlow Condensed', sans-serif;
      font-size: 64px;
      font-weight: 900;
      color: var(--text);
      line-height: 1;
      letter-spacing: -0.02em;
    }}
    .odds-book {{
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(255,255,255,0.70);
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.12);
      padding: 3px 10px;
      border-radius: 20px;
      margin-top: 8px;
    }}

    /* ── Edge section ── */
    .pick-edge {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      min-width: 120px;
    }}
    .edge-value {{
      font-size: 22px;
      font-weight: 800;
      color: var(--accent);
      letter-spacing: -0.01em;
    }}
    .edge-label {{
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-top: 3px;
    }}
    .edge-bar-track {{
      width: 100%;
      height: 3px;
      background: rgba(255,255,255,0.1);
      border-radius: 2px;
      margin-top: 8px;
      overflow: hidden;
    }}
    .edge-bar-fill {{
      height: 100%;
      background: var(--accent);
      border-radius: 2px;
    }}

    /* ── Surface dot (tennis) ── */
    .surface-dot {{
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      margin-right: 5px;
      vertical-align: middle;
    }}
    .surface-tag {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.06em;
      color: var(--text-sec);
      margin-top: 4px;
    }}

    /* ── Weather badge ── */
    .weather-badge {{
      display: inline-block;
      font-size: 11px;
      font-weight: 600;
      color: var(--accent);
      background: rgba(0,232,122,0.12);
      border: 1px solid rgba(0,232,122,0.25);
      padding: 2px 10px;
      border-radius: 20px;
      margin-top: 5px;
    }}

    /* ── League pill (soccer) ── */
    .league-pill {{
      display: inline-block;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-muted);
      background: rgba(255,255,255,0.06);
      padding: 2px 9px;
      border-radius: 20px;
      margin-top: 4px;
    }}

    /* ── Rank (PGA) ── */
    .rank-num {{
      font-size: 18px;
      font-weight: 700;
      color: var(--text-muted);
      min-width: 28px;
      flex-shrink: 0;
    }}

    /* ── Record strip ── */
    .record-strip {{
      display: flex;
      align-items: center;
      gap: 20px;
      padding: 12px 56px 24px;
      flex-shrink: 0;
    }}
    .record-item {{
      font-size: 13px;
      font-weight: 700;
      color: rgba(255,255,255,0.55);
      letter-spacing: 0.03em;
    }}
    .record-item .rec-val {{
      color: var(--accent);
      font-weight: 800;
    }}
    .record-dot {{
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: rgba(255,255,255,0.2);
      flex-shrink: 0;
    }}

    /* ── Game time ── */
    .game-time {{
      font-size: 12px;
      font-weight: 600;
      color: rgba(255,255,255,0.35);
      letter-spacing: 0.04em;
      margin-top: 4px;
    }}

    /* ── Units badge ── */
    .units-badge {{
      display: inline-block;
      font-size: 12px;
      font-weight: 800;
      color: #fff;
      background: rgba(255,255,255,0.10);
      border: 1px solid rgba(255,255,255,0.18);
      padding: 2px 9px;
      border-radius: 20px;
      margin-top: 6px;
      letter-spacing: 0.04em;
    }}

    /* ── Confidence label ── */
    .confidence-label {{
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      margin-top: 4px;
    }}
    .conf-high   {{ color: var(--accent); }}
    .conf-strong {{ color: #7ee8a2; }}
    .conf-good   {{ color: rgba(255,255,255,0.50); }}

    /* ── Receipts (last 14 days) strip ── */
    .form-strip {{
      display: flex;
      align-items: center;
      gap: 14px;
      padding: 8px 56px 0;
      font-size: 13px;
      font-weight: 700;
    }}
    .form-label {{
      color: rgba(255,255,255,0.40);
      letter-spacing: 0.14em;
    }}
    .form-stats {{
      color: var(--accent);
      letter-spacing: 0.02em;
    }}

    /* ── Hero matchup logos ── */
    .hero-logos {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 36px;
      margin-bottom: 18px;
    }}
    .hero-logo-img {{
      width: 110px;
      height: 110px;
      object-fit: contain;
      filter: drop-shadow(0 6px 16px rgba(0,0,0,0.5));
    }}
    .hero-vs {{
      font-family: 'Barlow Condensed', 'Inter', sans-serif;
      font-size: 38px;
      font-weight: 800;
      color: rgba(255,255,255,0.30);
      letter-spacing: 0.04em;
    }}

    /* ── Hero single-pick layout ── */
    .hero-wrap {{
      flex: 1;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      padding: 30px 56px 0;
      gap: 28px;
    }}
    .hero-matchup-block {{
      text-align: center;
      padding-top: 20px;
    }}
    .hero-market-label {{
      font-size: 16px;
      font-weight: 800;
      letter-spacing: 0.22em;
      color: var(--accent);
      margin-bottom: 18px;
    }}
    .hero-matchup {{
      font-family: 'Barlow Condensed', 'Inter', sans-serif;
      font-size: 64px;
      font-weight: 800;
      line-height: 1.05;
      color: #fff;
      letter-spacing: -0.01em;
    }}
    .hero-subtitle {{
      font-size: 18px;
      font-weight: 600;
      color: rgba(255,255,255,0.55);
      margin-top: 10px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .hero-selection-block {{
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }}
    .hero-selection-top {{
      font-family: 'Barlow Condensed', 'Inter', sans-serif;
      font-size: 86px;
      font-weight: 900;
      line-height: 1;
      color: var(--accent);
      letter-spacing: -0.02em;
      text-transform: uppercase;
    }}
    .hero-selection-bottom {{
      font-family: 'Barlow Condensed', 'Inter', sans-serif;
      font-size: 220px;
      font-weight: 900;
      line-height: 0.9;
      color: #fff;
      letter-spacing: -0.04em;
      margin-top: 4px;
    }}
    .hero-edge-row {{
      display: flex;
      align-items: center;
      gap: 24px;
      background: var(--surface);
      border: 1px solid var(--top-border);
      border-radius: 20px;
      padding: 26px 32px;
    }}
    .hero-odds-chip {{
      font-family: 'Barlow Condensed', 'Inter', sans-serif;
      font-size: 78px;
      font-weight: 900;
      line-height: 0.95;
      color: #fff;
      min-width: 180px;
      letter-spacing: -0.03em;
    }}
    .hero-edge-block {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .hero-edge-pct {{
      font-family: 'Barlow Condensed', 'Inter', sans-serif;
      font-size: 52px;
      font-weight: 900;
      line-height: 1;
      color: var(--accent);
      letter-spacing: -0.02em;
    }}
    .hero-edge-block .confidence-label {{
      font-size: 13px;
      margin-top: 4px;
    }}
    .hero-edge-bar {{
      margin-top: 10px;
      height: 6px;
      background: rgba(255,255,255,0.08);
      border-radius: 3px;
      overflow: hidden;
    }}
    .hero-edge-fill {{
      height: 100%;
      background: var(--accent);
      border-radius: 3px;
    }}
    .hero-units {{
      font-size: 17px;
      font-weight: 800;
      color: var(--accent);
      background: rgba(0,232,122,0.12);
      padding: 8px 16px;
      border-radius: 10px;
      letter-spacing: 0.04em;
      border: 1px solid rgba(0,232,122,0.30);
    }}
    .hero-meta {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 32px;
      padding-bottom: 4px;
      font-size: 15px;
      font-weight: 700;
      color: rgba(255,255,255,0.55);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .hero-book, .hero-time {{
      display: inline-flex;
      align-items: center;
    }}

    /* ── Footer ── */
    .footer {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 20px 56px 36px;
      flex-shrink: 0;
      border-top: 1px solid rgba(255,255,255,0.06);
    }}
    .footer-handle {{
      font-size: 17px;
      font-weight: 800;
      color: var(--accent);
      letter-spacing: 0.01em;
    }}
    .footer-disclaimer {{
      font-size: 13px;
      color: rgba(255,255,255,0.40);
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <!-- Header -->
  <div class="header">
    <div class="logo-block">
      <div class="logo">ChefTony<span class="accent">Bets</span></div>
      <div class="logo-sub">@ChefTonyAIBets</div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_str}</div>
      {badge}
    </div>
  </div>

  <!-- Market type banner -->
  {f'<div class="market-banner"><div class="market-banner-text">{market_banner}</div></div>' if market_banner else ''}

  <!-- Record strip -->
  {record_strip_html or ''}

  <!-- Recent form (last 14 days) -->
  {form_strip_html or ''}

  <!-- Picks -->
  <div class="picks">
    {body_html}
  </div>

  <!-- Footer -->
  <div class="footer">
    <div class="footer-handle">TAIL @ChefTonyAIBets &nbsp;·&nbsp; Link in bio</div>
    <div class="footer-disclaimer">Not financial advice &nbsp;·&nbsp; 21+</div>
  </div>
</body>
</html>"""


def _confidence_html(edge_pct: float) -> str:
    if edge_pct >= 8:
        return '<div class="confidence-label conf-high">HIGH CONFIDENCE</div>'
    elif edge_pct >= 5:
        return '<div class="confidence-label conf-strong">STRONG EDGE</div>'
    else:
        return '<div class="confidence-label conf-good">GOOD VALUE</div>'


# ── Inline SVG icons (no emoji) ──────────────────────────────────────────────

_ICON_LOCK = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" '
    'fill="currentColor" style="vertical-align:middle;margin-right:4px;">'
    '<path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12'
    'c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9'
    'V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/>'
    '</svg>'
)

_ICON_CLOCK = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" '
    'fill="currentColor" style="vertical-align:middle;margin-right:4px;opacity:0.6;">'
    '<path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2z'
    'M12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23'
    '-4.5-2.67V7z"/>'
    '</svg>'
)

_ICON_FLAME = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" '
    'fill="currentColor" style="vertical-align:middle;margin-right:4px;color:#ff6b35;">'
    '<path d="M13.5.67s.74 2.65.74 4.8c0 2.06-1.35 3.73-3.41 3.73-2.07 0-3.63-1.67-3.63-3.73'
    'l.03-.36C5.21 7.51 4 10.62 4 14c0 4.42 3.58 8 8 8s8-3.58 8-8C20 8.61 17.41 3.8 13.5.67z'
    'M11.71 19c-1.78 0-3.22-1.4-3.22-3.14 0-1.62 1.05-2.76 2.81-3.12 1.77-.36 3.6-1.21 4.62-2.58'
    '.39 1.29.59 2.65.59 4.04 0 2.65-2.15 4.8-4.8 4.8z"/>'
    '</svg>'
)

_ICON_SNOWFLAKE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" '
    'fill="currentColor" style="vertical-align:middle;margin-right:4px;color:#7ee8ff;">'
    '<path d="M22 11h-4.17l3.24-3.24-1.41-1.42L15 11h-2V9l4.66-4.66-1.42-1.41L13 6.17V2h-2v4.17'
    'L7.76 2.93 6.34 4.34 11 9v2H9L4.34 6.34 2.93 7.76 6.17 11H2v2h4.17l-3.24 3.24 1.41 1.42'
    'L9 13h2v2l-4.66 4.66 1.42 1.41L11 17.83V22h2v-4.17l3.24 3.24 1.42-1.41L13 15v-2h2l4.66 4.66'
    '1.41-1.42L17.83 13H22v-2z"/>'
    '</svg>'
)


def _fmt_game_time(commence_time: str | None) -> str | None:
    """Parse ISO commence_time → '7:05 PM ET'."""
    if not commence_time:
        return None
    try:
        from datetime import datetime, timezone, timedelta
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        # UTC → ET (UTC-4 during EDT)
        et = dt - timedelta(hours=4)
        return et.strftime("%-I:%M %p ET").replace("AM", "AM").replace("PM", "PM")
    except Exception:
        return None


# ── Team logos (ESPN CDN — free, public, hot-linkable) ─────────────────────
# Maps lowercase team name fragments → ESPN abbreviation slug.
# URL pattern: https://a.espncdn.com/i/teamlogos/{league}/500/{slug}.png

_NBA_TEAM_SLUGS = {
    "hawks":"atl","celtics":"bos","nets":"bkn","hornets":"cha","bulls":"chi",
    "cavaliers":"cle","mavericks":"dal","nuggets":"den","pistons":"det",
    "warriors":"gs","rockets":"hou","pacers":"ind","clippers":"lac",
    "lakers":"lal","grizzlies":"mem","heat":"mia","bucks":"mil",
    "timberwolves":"min","pelicans":"no","knicks":"ny","thunder":"okc",
    "magic":"orl","76ers":"phi","suns":"phx","trail blazers":"por",
    "blazers":"por","kings":"sac","spurs":"sa","raptors":"tor","jazz":"utah","wizards":"wsh",
}

_MLB_TEAM_SLUGS = {
    "diamondbacks":"ari","braves":"atl","orioles":"bal","red sox":"bos",
    "cubs":"chc","white sox":"chw","reds":"cin","guardians":"cle",
    "rockies":"col","tigers":"det","astros":"hou","royals":"kc",
    "angels":"laa","dodgers":"lad","marlins":"mia","brewers":"mil",
    "twins":"min","mets":"nym","yankees":"nyy","athletics":"oak",
    "phillies":"phi","pirates":"pit","padres":"sd","giants":"sf",
    "mariners":"sea","cardinals":"stl","rays":"tb","rangers":"tex",
    "blue jays":"tor","nationals":"wsh",
}


def _team_logo_url(team: str, sport_key: str) -> str | None:
    """Return ESPN CDN logo URL for a team name, or None if not found."""
    if not team:
        return None
    name = team.lower().strip()
    if "nba" in sport_key.lower() or "basketball" in sport_key.lower():
        league = "nba"; slugs = _NBA_TEAM_SLUGS
    elif "mlb" in sport_key.lower() or "baseball" in sport_key.lower():
        league = "mlb"; slugs = _MLB_TEAM_SLUGS
    else:
        return None
    # Match by last word or longest matching fragment
    for frag, slug in slugs.items():
        if frag in name:
            return f"https://a.espncdn.com/i/teamlogos/{league}/500/{slug}.png"
    return None


def _split_matchup(matchup: str) -> tuple[str, str] | None:
    """Return (away, home) team names from a matchup string, or None."""
    if not matchup:
        return None
    for sep in (" @ ", " vs. ", " vs ", " at "):
        if sep in matchup:
            parts = matchup.split(sep, 1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
    return None


def _load_recent_form_strip(sport_key: str) -> str:
    """Pull the 'last 14 days' record line from receipts_post.txt for the sport.

    Returns HTML for a small receipts strip shown directly below the record
    strip — quick social proof ('last 14 days: 19-6, +11.8u, ROI +47.3%').
    """
    from datetime import date as _date
    folder_map = {
        "basketball_nba": "basketball_nba",
        "baseball_mlb":   "baseball_mlb",
    }
    folder = folder_map.get(sport_key)
    if not folder:
        return ""
    ts = _date.today().strftime("%Y%m%d")
    path = Path("output/picks") / folder / ts / "receipts_post.txt"
    if not path.exists():
        return ""
    try:
        lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
        if len(lines) < 2:
            return ""
        # Line 1: "NBA Totals model — last 14 days"
        # Line 2: "19-6 · +11.8u · ROI +47.3% · CLV -2.20c (N=2)"
        title = lines[0]
        stats = lines[1]
        return f"""<div class="form-strip">
  <span class="form-label">LAST 14 DAYS</span>
  <span class="form-stats">{stats}</span>
</div>"""
    except Exception:
        return ""


def _load_record_strip(sport: str, market: str | None) -> str:
    """Load W-L record from public_stats.json and return record strip HTML."""
    try:
        import json
        stats_path = Path("data/public_stats.json")
        if not stats_path.exists():
            return ""
        stats = json.loads(stats_path.read_text())
        by_market = stats.get("by_market", {})
        data = by_market.get(market or "", {})
        wins = data.get("wins", 0)
        losses = data.get("losses", 0)
        total = wins + losses
        if total < 3:
            return ""
        profit = data.get("units_profit", 0)
        wr = round(wins / total * 100, 1) if total else 0
        streak = int(data.get("streak", 0))
        streak_html = ""
        if streak >= 3:
            streak_html = f'<div class="record-dot"></div><div class="record-item">{_ICON_FLAME}<span class="rec-val">{streak}-PICK WIN STREAK</span></div>'
        elif streak <= -3:
            streak_html = f'<div class="record-dot"></div><div class="record-item">{_ICON_SNOWFLAKE}<span class="rec-val">{abs(streak)}-PICK COLD STREAK</span></div>'
        sign = "+" if profit >= 0 else ""
        return f"""<div class="record-strip">
  <div class="record-item">RECORD <span class="rec-val">{wins}-{losses}</span></div>
  <div class="record-dot"></div>
  <div class="record-item"><span class="rec-val">{sign}{profit:.1f}u</span> profit</div>
  <div class="record-dot"></div>
  <div class="record-item"><span class="rec-val">{wr}%</span> WR</div>
  {streak_html}
</div>"""
    except Exception:
        return ""


def _pick_row_html(
    *,
    market_label: str,
    team_name: str,
    matchup_line: str,
    odds: int | float | str,
    sportsbook: str,
    edge_pct: float,
    is_top_play: bool = False,
    center_html: str = "",
    extra_left_html: str = "",
    game_time: str | None = None,
    units: str = "1u",
) -> str:
    """Render a single pick row."""
    bar_pct = _edge_bar_pct(edge_pct)
    top_badge = f'<div class="top-play-badge">{_ICON_LOCK}TAIL THIS</div>' if is_top_play else ""
    row_class = "pick-row top-play" if is_top_play else "pick-row"
    center_block = f'<div class="pick-center">{center_html}</div>' if center_html else ""
    time_html = f'<div class="game-time">{_ICON_CLOCK}{game_time}</div>' if game_time else ""
    conf_html = _confidence_html(edge_pct)

    return f"""
<div class="{row_class}">
  {top_badge}
  <div class="pick-left">
    <div class="market-label">{market_label}</div>
    <div class="team-name">{team_name}</div>
    <div class="matchup">{matchup_line}</div>
    {time_html}
    {extra_left_html}
  </div>
  {center_block}
  <div class="pick-odds">
    <div class="odds-number">{_fmt_odds(odds)}</div>
    <div class="odds-book">{sportsbook}</div>
  </div>
  <div class="pick-edge">
    <div class="edge-value">+{edge_pct:.1f}%</div>
    {conf_html}
    <div class="edge-bar-track">
      <div class="edge-bar-fill" style="width:{bar_pct}%"></div>
    </div>
    <div class="units-badge">{units}</div>
  </div>
</div>"""


def _hero_pick_html(
    *,
    sport_label: str,
    market_label: str,
    matchup: str,
    selection_top: str,
    selection_bottom: str,
    odds: int | float,
    sportsbook: str,
    edge_pct: float,
    game_time: str | None = None,
    units: str = "1.0u",
    extra_subtitle: str | None = None,
    sport_key: str = "",
) -> str:
    """Hero single-pick layout — dominant matchup + selection + odds.

    Fills the vertical canvas when there's only one pick on the card so we
    don't have 600px of dead space. Big matchup, huge selection number,
    bold odds chip, prominent edge bar, footer with book + game time.
    """
    odds_str = f"+{int(odds)}" if odds > 0 else str(int(odds))
    conf_html = _confidence_html(edge_pct)
    bar_pct = min(100, max(15, int(edge_pct * 6)))

    subtitle = ""
    if extra_subtitle:
        subtitle = f'<div class="hero-subtitle">{extra_subtitle}</div>'
    game_time_html = ""
    if game_time:
        game_time_html = f'<span class="hero-time">{_ICON_CLOCK}{game_time}</span>'

    # Team logos from ESPN CDN (no-op for sports we don't have slugs for)
    logos_html = ""
    teams = _split_matchup(matchup)
    if teams and sport_key:
        away_url = _team_logo_url(teams[0], sport_key)
        home_url = _team_logo_url(teams[1], sport_key)
        if away_url and home_url:
            logos_html = (
                '<div class="hero-logos">'
                f'<img class="hero-logo-img" src="{away_url}" alt="" />'
                '<div class="hero-vs">@</div>'
                f'<img class="hero-logo-img" src="{home_url}" alt="" />'
                '</div>'
            )

    return f"""
<div class="hero-wrap">
  <!-- Matchup banner -->
  <div class="hero-matchup-block">
    <div class="hero-market-label">{market_label.upper()}</div>
    {logos_html}
    <div class="hero-matchup">{matchup}</div>
    {subtitle}
  </div>

  <!-- Center selection — dominant visual -->
  <div class="hero-selection-block">
    <div class="hero-selection-top">{selection_top}</div>
    <div class="hero-selection-bottom">{selection_bottom}</div>
  </div>

  <!-- Edge + odds row -->
  <div class="hero-edge-row">
    <div class="hero-odds-chip">{odds_str}</div>
    <div class="hero-edge-block">
      <div class="hero-edge-pct">+{edge_pct:.1f}%</div>
      {conf_html}
      <div class="hero-edge-bar"><div class="hero-edge-fill" style="width:{bar_pct}%"></div></div>
    </div>
    <div class="hero-units">{units}</div>
  </div>

  <!-- Meta -->
  <div class="hero-meta">
    <span class="hero-book">{_ICON_LOCK}{sportsbook.upper()}</span>
    {game_time_html}
  </div>
</div>"""


# ─────────────────────────────────────────────────────────────────────────────
# Card 1: MLB Moneyline
# ─────────────────────────────────────────────────────────────────────────────

def render_mlb_moneyline_card(picks: list[dict], card_date: date | None = None) -> Optional[Path]:
    """
    Render MLB moneyline picks card.
    picks keys: Team, Opponent/Matchup, BestOdds, Edge (fraction) or edge_pct, Sportsbook
    """
    if not picks:
        return None

    card_date = card_date or date.today()
    date_str = card_date.strftime("%B %d, %Y").upper()
    ts = card_date.strftime("%Y%m%d")
    out_path = Path("output/picks/baseball_mlb") / ts / "mlb_moneyline_card.png"

    # Normalize and pick top 5
    rows: list[dict] = []
    for p in picks[:5]:
        edge = _resolve_edge_pct(p)
        opponent = p.get("Opponent") or p.get("matchup") or ""
        matchup = p.get("Matchup") or p.get("matchup") or opponent
        if matchup and "vs" not in matchup.lower() and " @ " not in matchup:
            vs_line = f"vs {opponent}"
        else:
            if " @ " in matchup:
                parts = matchup.split(" @ ")
                team_name = p.get("Team", "")
                other = parts[0] if parts[1].lower() in team_name.lower() else parts[1]
                vs_line = f"vs {other}"
            else:
                vs_line = f"vs {opponent}" if opponent else matchup
        rows.append({
            "team": p.get("Team", ""),
            "vs_line": vs_line,
            "odds": p.get("BestOdds") or p.get("odds") or 0,
            "book": p.get("Sportsbook") or p.get("sportsbook") or "",
            "edge_pct": edge,
            "game_time": _fmt_game_time(p.get("CommenceTime") or p.get("commence_time")),
            "units": f"{float(p.get('stake', 1.0) or 1.0):.1f}u",
        })

    if not rows:
        return None

    max_edge_idx = max(range(len(rows)), key=lambda i: rows[i]["edge_pct"])
    record_html = _load_record_strip("mlb", "moneyline")
    body_parts = []
    for i, row in enumerate(rows):
        body_parts.append(_pick_row_html(
            market_label="Moneyline",
            team_name=row["team"],
            matchup_line=row["vs_line"],
            odds=row["odds"],
            sportsbook=row["book"],
            edge_pct=row["edge_pct"],
            is_top_play=(i == max_edge_idx),
            game_time=row["game_time"],
            units=row["units"],
        ))

    html = _card_html(
        sport_label="MLB",
        date_str=date_str,
        body_html="\n".join(body_parts),
        badge_color="#00e87a",
        badge_label="MLB",
        sport_key="baseball_mlb",
        market_banner="Moneyline Picks — AI Edge Detection",
        record_strip_html=record_html,
    )
    return _render_html_to_png(html, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Card 2: MLB Totals
# ─────────────────────────────────────────────────────────────────────────────

def render_mlb_totals_card(picks: list[dict], card_date: date | None = None) -> Optional[Path]:
    """
    Render MLB over/under totals card.
    picks keys: Team (e.g. "OVER 8.5"), Matchup, BestOdds, edge_pct/Edge, Sportsbook,
                optionally weather_context, Direction, MarketLine/BetLine/line
    """
    if not picks:
        return None

    card_date = card_date or date.today()
    date_str = card_date.strftime("%B %d, %Y").upper()
    ts = card_date.strftime("%Y%m%d")
    out_path = Path("output/picks/baseball_mlb") / ts / "mlb_totals_card.png"

    rows: list[dict] = []
    for p in picks[:5]:
        edge = _resolve_edge_pct(p)
        team_str = p.get("Team") or p.get("team") or ""
        direction = p.get("Direction") or p.get("direction") or ""
        line = p.get("MarketLine") or p.get("BetLine") or p.get("line") or ""
        # Parse direction+line from Team if not explicit
        if not direction:
            for keyword in ("OVER", "UNDER"):
                if keyword in team_str.upper():
                    direction = keyword
                    break
        if not line:
            parts = team_str.split()
            for part in parts:
                try:
                    float(part)
                    line = part
                    break
                except ValueError:
                    pass

        matchup = p.get("Matchup") or p.get("matchup") or p.get("Opponent") or ""
        weather = p.get("weather_context") or ""
        rows.append({
            "direction": direction.upper() if direction else "OVER",
            "line": str(line),
            "matchup": matchup,
            "weather": weather,
            "odds": p.get("BestOdds") or p.get("odds") or 0,
            "book": p.get("Sportsbook") or p.get("sportsbook") or "",
            "edge_pct": edge,
            "game_time": _fmt_game_time(p.get("CommenceTime") or p.get("commence_time")),
            "units": f"{float(p.get('stake', 1.0) or 1.0):.1f}u",
        })

    if not rows:
        return None

    record_html = _load_record_strip("mlb", "total")

    # Dedupe by matchup — keep highest-edge per game
    by_match: dict[str, dict] = {}
    for r in rows:
        key = (r["matchup"] or "").lower()
        if key not in by_match or r["edge_pct"] > by_match[key]["edge_pct"]:
            by_match[key] = r
    rows = sorted(by_match.values(), key=lambda r: -r["edge_pct"])

    # Hero layout when only 1 unique pick (no dead vertical space)
    if len(rows) == 1:
        row = rows[0]
        body_html = _hero_pick_html(
            sport_label="MLB",
            market_label="Game Total — Over / Under",
            matchup=row["matchup"],
            selection_top=row["direction"],
            selection_bottom=row["line"],
            odds=row["odds"],
            sportsbook=row["book"],
            edge_pct=row["edge_pct"],
            game_time=row["game_time"],
            units=row["units"],
            extra_subtitle=row["weather"] or None,
            sport_key="baseball_mlb",
        )
    else:
        max_edge_idx = max(range(len(rows)), key=lambda i: rows[i]["edge_pct"])
        body_parts = []
        for i, row in enumerate(rows):
            weather_html = ""
            if row["weather"]:
                weather_html = f'<div class="weather-badge">{row["weather"]}</div>'
            center_html = (
                f'<div class="direction-label">{row["direction"]}</div>'
                f'<div class="line-label">{row["line"]}</div>'
            )
            body_parts.append(_pick_row_html(
                market_label="Over / Under",
                team_name=row["matchup"],
                matchup_line="Game Total",
                odds=row["odds"],
                sportsbook=row["book"],
                edge_pct=row["edge_pct"],
                is_top_play=(i == max_edge_idx),
                center_html=center_html,
                extra_left_html=weather_html,
                game_time=row["game_time"],
                units=row["units"],
            ))
        body_html = "\n".join(body_parts)

    html = _card_html(
        sport_label="MLB",
        date_str=date_str,
        body_html=body_html,
        badge_color="#00e87a",
        badge_label="MLB",
        sport_key="baseball_mlb",
        market_banner="Over / Under Picks — AI Edge Detection",
        record_strip_html=record_html,
        form_strip_html=_load_recent_form_strip("baseball_mlb"),
    )
    return _render_html_to_png(html, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Card 3: MLB Pitcher Ks
# ─────────────────────────────────────────────────────────────────────────────

def render_mlb_pitcher_ks_card(picks: list[dict], card_date: date | None = None) -> Optional[Path]:
    """
    Render MLB pitcher strikeout props card.
    picks keys: player/Player, direction, line, odds, edge_pct, sportsbook, optionally projected
    """
    if not picks:
        return None

    card_date = card_date or date.today()
    date_str = card_date.strftime("%B %d, %Y").upper()
    ts = card_date.strftime("%Y%m%d")
    out_path = Path("output/picks/baseball_mlb") / ts / "mlb_pitcher_ks_card.png"

    rows: list[dict] = []
    for p in picks[:5]:
        edge = _resolve_edge_pct(p)
        player = p.get("player") or p.get("Player") or p.get("team") or p.get("Team") or ""
        team = p.get("team_abbrev") or p.get("team") or p.get("matchup") or ""
        direction = p.get("direction") or p.get("Direction") or "OVER"
        line = p.get("line") or p.get("Line") or p.get("BetLine") or ""
        projected = p.get("projected") or p.get("proj_k") or ""
        rows.append({
            "player": player,
            "team": team,
            "direction": direction.upper(),
            "line": str(line),
            "projected": projected,
            "odds": p.get("odds") or p.get("BestOdds") or 0,
            "book": p.get("sportsbook") or p.get("Sportsbook") or p.get("book") or "",
            "edge_pct": edge,
            "game_time": _fmt_game_time(p.get("CommenceTime") or p.get("commence_time")),
            "units": f"{float(p.get('stake', 1.0) or 1.0):.1f}u",
        })

    if not rows:
        return None

    max_edge_idx = max(range(len(rows)), key=lambda i: rows[i]["edge_pct"])
    record_html = _load_record_strip("mlb", "pitcher_ks")
    body_parts = []
    for i, row in enumerate(rows):
        proj_html = ""
        if row["projected"]:
            proj_html = f'<div class="proj-label">PROJ {row["projected"]} Ks</div>'

        center_html = (
            f'<div class="direction-label">{row["direction"]}</div>'
            f'<div class="line-label">{row["line"]} Ks</div>'
            + proj_html
        )

        body_parts.append(_pick_row_html(
            market_label="Pitcher Ks",
            team_name=row["player"],
            matchup_line=row["team"],
            odds=row["odds"],
            sportsbook=row["book"],
            edge_pct=row["edge_pct"],
            is_top_play=(i == max_edge_idx),
            center_html=center_html,
            game_time=row["game_time"],
            units=row["units"],
        ))

    html = _card_html(
        sport_label="MLB",
        date_str=date_str,
        body_html="\n".join(body_parts),
        badge_color="#00e87a",
        badge_label="MLB",
        sport_key="baseball_mlb",
        market_banner="Pitcher Strikeouts — AI Edge Detection",
        record_strip_html=record_html,
    )
    return _render_html_to_png(html, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Card 4: NBA Totals
# ─────────────────────────────────────────────────────────────────────────────

def render_nba_totals_card(picks: list[dict], card_date: date | None = None) -> Optional[Path]:
    """
    Render NBA over/under totals card.
    picks keys: team/matchup, market, direction, best_odds/odds, edge_pct, sportsbook, bet_line/line
    """
    if not picks:
        return None

    card_date = card_date or date.today()
    date_str = card_date.strftime("%B %d, %Y").upper()
    ts = card_date.strftime("%Y%m%d")
    out_path = Path("output/picks/basketball_nba") / ts / "nba_totals_card.png"

    rows: list[dict] = []
    for p in picks[:5]:
        edge = _resolve_edge_pct(p)
        matchup = p.get("matchup") or p.get("Matchup") or p.get("team") or p.get("Team") or ""
        direction = (p.get("direction") or p.get("Direction") or "OVER").upper()
        line = p.get("bet_line") or p.get("BetLine") or p.get("line") or p.get("MarketLine") or ""
        rows.append({
            "matchup": matchup,
            "direction": direction,
            "line": str(line),
            "odds": p.get("best_odds") or p.get("BestOdds") or p.get("odds") or 0,
            "book": p.get("sportsbook") or p.get("Sportsbook") or "",
            "edge_pct": edge,
            "game_time": _fmt_game_time(p.get("commence_time") or p.get("CommenceTime")),
            "units": f"{float(p.get('stake', 1.0) or 1.0):.1f}u",
        })

    if not rows:
        return None

    record_html = _load_record_strip("nba", "total")

    # Dedupe by matchup — keep the highest-edge pick per game so we don't
    # render the same game twice with different sportsbook lines
    by_match: dict[str, dict] = {}
    for r in rows:
        key = (r["matchup"] or "").lower()
        if key not in by_match or r["edge_pct"] > by_match[key]["edge_pct"]:
            by_match[key] = r
    rows = sorted(by_match.values(), key=lambda r: -r["edge_pct"])

    # Hero layout when 1-2 unique picks (no dead vertical space)
    if len(rows) <= 1:
        row = rows[0]
        body_html = _hero_pick_html(
            sport_label="NBA",
            market_label="Game Total — Over / Under",
            matchup=row["matchup"],
            selection_top=row["direction"],
            selection_bottom=row["line"],
            odds=row["odds"],
            sportsbook=row["book"],
            edge_pct=row["edge_pct"],
            game_time=row["game_time"],
            units=row["units"],
            extra_subtitle="NBA Playoffs",
            sport_key="basketball_nba",
        )
    else:
        max_edge_idx = max(range(len(rows)), key=lambda i: rows[i]["edge_pct"])
        body_parts = []
        for i, row in enumerate(rows):
            center_html = (
                f'<div class="direction-label">{row["direction"]}</div>'
                f'<div class="line-label">{row["line"]}</div>'
            )
            body_parts.append(_pick_row_html(
                market_label="Game Total",
                team_name=row["matchup"],
                matchup_line="NBA Playoffs",
                odds=row["odds"],
                sportsbook=row["book"],
                edge_pct=row["edge_pct"],
                is_top_play=(i == max_edge_idx),
                center_html=center_html,
                game_time=row["game_time"],
                units=row["units"],
            ))
        body_html = "\n".join(body_parts)

    html = _card_html(
        sport_label="NBA PLAYOFFS",
        date_str=date_str,
        body_html=body_html,
        badge_color="#3a86ff",
        badge_label="NBA PLAYOFFS",
        sport_key="basketball_nba",
        market_banner="Over / Under Picks — AI Edge Detection",
        record_strip_html=record_html,
        form_strip_html=_load_recent_form_strip("basketball_nba"),
    )
    return _render_html_to_png(html, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Card 5: Tennis
# ─────────────────────────────────────────────────────────────────────────────

_SURFACE_COLORS = {
    "clay":  "#e85d04",
    "hard":  "#3a86ff",
    "grass": "#00e87a",
}


def render_tennis_card(
    picks: list[dict],
    tournament: str,
    surface: str,
    card_date: date | None = None,
    out_dir: Path | None = None,
) -> Optional[Path]:
    """
    Render tennis moneyline picks card.
    picks keys: team, opponent/matchup, odds, edge_pct, sportsbook
    """
    if not picks:
        return None

    card_date = card_date or date.today()
    date_str = card_date.strftime("%B %d, %Y").upper()
    ts = card_date.strftime("%Y%m%d")

    if out_dir is None:
        sport_dir = f"tennis_atp_{tournament.lower().replace(' ', '_')}"
        out_dir = Path("output/picks") / sport_dir / ts
    out_path = out_dir / "tennis_card.png"

    surface_lower = (surface or "clay").lower()
    surface_color = _SURFACE_COLORS.get(surface_lower, "#00e87a")
    surface_name = surface_lower.upper()

    rows: list[dict] = []
    for p in picks[:5]:
        edge = _resolve_edge_pct(p)
        team = p.get("team") or p.get("Team") or ""
        matchup = p.get("matchup") or p.get("Matchup") or ""
        opponent = p.get("opponent") or p.get("Opponent") or ""
        if not opponent and matchup:
            if " vs " in matchup.lower():
                parts = matchup.lower().split(" vs ")
                for part in parts:
                    if team.lower() not in part:
                        opponent = part.strip().title()
                        break
            elif " @ " in matchup:
                parts = matchup.split(" @ ")
                for part in parts:
                    if team.lower() not in part.lower():
                        opponent = part.strip()
                        break
        vs_line = f"vs {opponent}" if opponent else matchup
        rows.append({
            "team": team,
            "vs_line": vs_line,
            "odds": p.get("odds") or p.get("BestOdds") or 0,
            "book": p.get("sportsbook") or p.get("Sportsbook") or "",
            "edge_pct": edge,
            "game_time": _fmt_game_time(p.get("commence_time") or p.get("CommenceTime")),
            "units": f"{float(p.get('stake', 1.0) or 1.0):.1f}u",
        })

    if not rows:
        return None

    max_edge_idx = max(range(len(rows)), key=lambda i: rows[i]["edge_pct"])
    record_html = _load_record_strip("tennis", "moneyline")
    body_parts = []
    for i, row in enumerate(rows):
        surface_html = (
            f'<div class="surface-tag">'
            f'<span class="surface-dot" style="background:{surface_color}"></span>'
            f'{surface_name}'
            f'</div>'
        )
        body_parts.append(_pick_row_html(
            market_label="Moneyline",
            team_name=row["team"],
            matchup_line=row["vs_line"],
            odds=row["odds"],
            sportsbook=row["book"],
            edge_pct=row["edge_pct"],
            is_top_play=(i == max_edge_idx),
            extra_left_html=surface_html,
            game_time=row["game_time"],
            units=row["units"],
        ))

    tournament_badge_label = tournament.upper()
    html = _card_html(
        sport_label=tournament_badge_label,
        date_str=date_str,
        body_html="\n".join(body_parts),
        badge_color="#ff6b35",
        badge_label=tournament_badge_label,
        sport_key="tennis",
        market_banner="Moneyline Picks — Elo Model Edge Detection",
        record_strip_html=record_html,
    )
    return _render_html_to_png(html, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Card 6: Soccer
# ─────────────────────────────────────────────────────────────────────────────

def _league_display_name(sport_key: str) -> str:
    """Convert soccer sport key to display league name."""
    _MAP = {
        "soccer_epl":                  "EPL",
        "soccer_spain_la_liga":        "La Liga",
        "soccer_italy_serie_a":        "Serie A",
        "soccer_germany_bundesliga":   "Bundesliga",
        "soccer_france_ligue_1":       "Ligue 1",
        "soccer_england_championship": "Championship",
        "soccer_fifa_world_cup":       "World Cup",
    }
    return _MAP.get(sport_key, sport_key.replace("soccer_", "").replace("_", " ").title())


def render_soccer_card(
    picks: list[dict],
    card_date: date | None = None,
    out_dir: Path | None = None,
) -> Optional[Path]:
    """
    Render soccer match winner picks card.
    picks keys: team, opponent/matchup, league/sport, odds, edge_pct, sportsbook
    """
    if not picks:
        return None

    card_date = card_date or date.today()
    date_str = card_date.strftime("%B %d, %Y").upper()
    ts = card_date.strftime("%Y%m%d")

    if out_dir is None:
        out_dir = Path("output/picks/soccer") / ts
    out_path = out_dir / "soccer_card.png"

    rows: list[dict] = []
    for p in picks[:5]:
        edge = _resolve_edge_pct(p)
        team = p.get("team") or p.get("Team") or ""
        matchup = p.get("matchup") or p.get("Matchup") or ""
        opponent = p.get("opponent") or p.get("Opponent") or ""
        if not opponent and matchup:
            if " @ " in matchup:
                parts = matchup.split(" @ ")
                for part in parts:
                    if team.lower() not in part.lower():
                        opponent = part.strip()
                        break
            elif " vs " in matchup.lower():
                parts = matchup.lower().split(" vs ")
                for part in parts:
                    if team.lower() not in part:
                        opponent = part.strip().title()
                        break
        vs_line = f"vs {opponent}" if opponent else matchup
        sport_key = p.get("sport") or p.get("league") or ""
        league_name = _league_display_name(sport_key)
        rows.append({
            "team": team,
            "vs_line": vs_line,
            "league": league_name,
            "odds": p.get("odds") or p.get("BestOdds") or 0,
            "book": p.get("sportsbook") or p.get("Sportsbook") or "",
            "edge_pct": edge,
            "game_time": _fmt_game_time(p.get("commence_time") or p.get("CommenceTime")),
            "units": f"{float(p.get('stake', 1.0) or 1.0):.1f}u",
        })

    if not rows:
        return None

    max_edge_idx = max(range(len(rows)), key=lambda i: rows[i]["edge_pct"])
    record_html = _load_record_strip("soccer", "moneyline")
    body_parts = []
    for i, row in enumerate(rows):
        league_html = f'<div class="league-pill">{row["league"]}</div>' if row["league"] else ""
        body_parts.append(_pick_row_html(
            market_label="Match Winner",
            team_name=row["team"],
            matchup_line=row["vs_line"],
            odds=row["odds"],
            sportsbook=row["book"],
            edge_pct=row["edge_pct"],
            is_top_play=(i == max_edge_idx),
            extra_left_html=league_html,
            game_time=row["game_time"],
            units=row["units"],
        ))

    html = _card_html(
        sport_label="SOCCER",
        date_str=date_str,
        body_html="\n".join(body_parts),
        badge_color="#00c9b1",
        badge_label="SOCCER",
        sport_key="soccer",
        market_banner="Match Winner Picks — Dixon-Coles Model",
        record_strip_html=record_html,
    )
    return _render_html_to_png(html, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Card 7: PGA
# ─────────────────────────────────────────────────────────────────────────────

def render_pga_card(
    picks: list[dict],
    tournament: str,
    card_date: date | None = None,
    out_dir: Path | None = None,
) -> Optional[Path]:
    """
    Render PGA outright picks leaderboard-style card.
    picks keys: player, odds, edge_pct, sportsbook, optionally sg_total or course_fit
    """
    if not picks:
        return None

    card_date = card_date or date.today()
    date_str = card_date.strftime("%B %d, %Y").upper()
    ts = card_date.strftime("%Y%m%d")

    if out_dir is None:
        sport_slug = tournament.lower().replace(" ", "_")
        out_dir = Path("output/picks") / f"golf_{sport_slug}" / ts
    out_path = out_dir / "pga_card.png"

    rows: list[dict] = []
    for i, p in enumerate(picks[:5]):
        edge = _resolve_edge_pct(p)
        player = p.get("player") or p.get("Player") or p.get("team") or ""
        sg_total = p.get("sg_total") or p.get("sg") or ""
        course_fit = p.get("course_fit") or ""
        sub_label = ""
        if sg_total:
            sub_label = f"SG Total: {sg_total:+.2f}" if isinstance(sg_total, float) else f"SG Total: {sg_total}"
        elif course_fit:
            sub_label = f"Course Fit: {course_fit}"
        rows.append({
            "rank": i + 1,
            "player": player,
            "sub_label": sub_label,
            "odds": p.get("odds") or p.get("BestOdds") or 0,
            "book": p.get("sportsbook") or p.get("Sportsbook") or "",
            "edge_pct": edge,
            "units": f"{float(p.get('stake', 1.0) or 1.0):.1f}u",
        })

    if not rows:
        return None

    max_edge_idx = max(range(len(rows)), key=lambda i: rows[i]["edge_pct"])
    record_html = _load_record_strip("pga", "outright")
    body_parts = []
    for i, row in enumerate(rows):
        rank_html = f'<div class="rank-num">{row["rank"]}.</div>'
        sub_html = f'<div class="matchup" style="margin-top:4px">{row["sub_label"]}</div>' if row["sub_label"] else ""

        bar_pct = _edge_bar_pct(row["edge_pct"])
        is_top = i == max_edge_idx
        top_badge = f'<div class="top-play-badge">{_ICON_LOCK}TAIL THIS</div>' if is_top else ""
        row_class = "pick-row top-play" if is_top else "pick-row"
        conf_html = _confidence_html(row["edge_pct"])

        body_parts.append(f"""
<div class="{row_class}" style="gap:16px">
  {top_badge}
  {rank_html}
  <div class="pick-left">
    <div class="market-label">Outright</div>
    <div class="team-name">{row["player"]}</div>
    {sub_html}
  </div>
  <div class="pick-odds">
    <div class="odds-number">{_fmt_odds(row["odds"])}</div>
    <div class="odds-book">{row["book"]}</div>
  </div>
  <div class="pick-edge">
    <div class="edge-value">+{row["edge_pct"]:.1f}%</div>
    {conf_html}
    <div class="edge-bar-track">
      <div class="edge-bar-fill" style="width:{bar_pct}%"></div>
    </div>
    <div class="units-badge">{row["units"]}</div>
  </div>
</div>""")

    tournament_label = tournament.upper()
    html = _card_html(
        sport_label=tournament_label,
        date_str=date_str,
        body_html="\n".join(body_parts),
        badge_color="#f5c518",
        badge_label=tournament_label,
        sport_key="golf",
        market_banner="Outright Value Picks — Strokes Gained Model",
        record_strip_html=record_html,
    )
    return _render_html_to_png(html, out_path)

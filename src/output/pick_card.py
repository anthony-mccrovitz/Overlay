"""
Social media pick card generator — Overlay AI.

1080 x 1350 (Instagram portrait 4:5).
Design: dark space, team logo circles, neon edge tier colors, zero clutter.
"""
from __future__ import annotations

import json
import math
import os
import io
from datetime import date
from pathlib import Path

OUTPUT_DIR    = Path("output/picks")
_LOGO_CACHE   = Path("data/cache/logos/mlb")

# ── Palette ───────────────────────────────────────────────────────────────────
_BG          = (  7,   8,  16)   # deep space
_BG_CARD     = ( 14,  16,  28)   # card surface
_BG_BEST     = ( 16,  20,  36)   # best bet card — slightly brighter
_DIVIDER     = ( 28,  32,  52)   # separator lines

_GOLD        = (255, 190,   0)   # Overlay gold
_GOLD_DIM    = (160, 120,   0)
_GREEN       = ( 57, 255, 120)   # HIGH edge neon
_AMBER       = (255, 165,  20)   # MED edge
_BLUE        = (100, 140, 255)   # LOW edge
_CYAN        = (  0, 210, 220)   # "AI" accent

_WHITE       = (252, 252, 255)
_GRAY_LT     = (155, 158, 180)
_GRAY_MID    = ( 85,  90, 115)
_GRAY_DK     = ( 26,  29,  48)

_SPORT_LABELS = {
    "baseball_mlb": "MLB", "basketball_nba": "NBA",
    "basketball_ncaab": "NCAAB", "americanfootball_nfl": "NFL",
    "mlb": "MLB", "nba": "NBA", "nfl": "NFL", "ncaab": "NCAAB",
}

# MLB team brand colors — used for logo glow rings + left accent bars
_MLB_COLORS: dict[str, tuple] = {
    "Arizona Diamondbacks":  (167,  25,  48),
    "Atlanta Braves":        (206,  17,  65),
    "Baltimore Orioles":     (223, 109,  29),
    "Boston Red Sox":        (189,  48,  57),
    "Chicago Cubs":          ( 14,  51, 134),
    "Chicago White Sox":     ( 39,  37,  31),
    "Cincinnati Reds":       (198,   1,  31),
    "Cleveland Guardians":   (  0,  56, 101),
    "Colorado Rockies":      ( 51,   0, 111),
    "Detroit Tigers":        ( 12,  35,  64),
    "Houston Astros":        (  0,  45,  98),
    "Kansas City Royals":    (  0,  70, 135),
    "Los Angeles Angels":    (186,   0,  33),
    "Los Angeles Dodgers":   (  0,  90, 156),
    "Miami Marlins":         (  0, 163, 224),
    "Milwaukee Brewers":     (  0,  40,  85),
    "Minnesota Twins":       (  0,  43, 127),
    "New York Mets":         (  0,  45, 114),
    "New York Yankees":      ( 12,  35,  64),
    "Athletics":             (  0,  56,  49),
    "Oakland Athletics":     (  0,  56,  49),
    "Philadelphia Phillies": (232,  24,  40),
    "Pittsburgh Pirates":    (253, 184,  39),
    "San Diego Padres":      ( 47,  36,  29),
    "San Francisco Giants":  (253,  90,  30),
    "Seattle Mariners":      (  0,  92,  92),
    "St. Louis Cardinals":   (196,  30,  58),
    "Tampa Bay Rays":        (  9,  44, 184),
    "Texas Rangers":         (  0,  50, 120),
    "Toronto Blue Jays":     ( 19,  74, 142),
    "Washington Nationals":  (171,   0,   3),
}

# ESPN CDN logo abbreviations
_ESPN_ABBR: dict[str, str] = {
    "Arizona Diamondbacks":  "ari",
    "Atlanta Braves":        "atl",
    "Baltimore Orioles":     "bal",
    "Boston Red Sox":        "bos",
    "Chicago Cubs":          "chc",
    "Chicago White Sox":     "chw",
    "Cincinnati Reds":       "cin",
    "Cleveland Guardians":   "cle",
    "Colorado Rockies":      "col",
    "Detroit Tigers":        "det",
    "Houston Astros":        "hou",
    "Kansas City Royals":    "kc",
    "Los Angeles Angels":    "laa",
    "Los Angeles Dodgers":   "lad",
    "Miami Marlins":         "mia",
    "Milwaukee Brewers":     "mil",
    "Minnesota Twins":       "min",
    "New York Mets":         "nym",
    "New York Yankees":      "nyy",
    "Athletics":             "oak",
    "Oakland Athletics":     "oak",
    "Philadelphia Phillies": "phi",
    "Pittsburgh Pirates":    "pit",
    "San Diego Padres":      "sd",
    "San Francisco Giants":  "sf",
    "Seattle Mariners":      "sea",
    "St. Louis Cardinals":   "stl",
    "Tampa Bay Rays":        "tb",
    "Texas Rangers":         "tex",
    "Toronto Blue Jays":     "tor",
    "Washington Nationals":  "wsh",
}

# Fonts
_FONT_COND = [("/System/Library/Fonts/HelveticaNeue.ttc", 9),
              ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)]
_FONT_BOLD = [("/System/Library/Fonts/HelveticaNeue.ttc", 1),
              ("/System/Library/Fonts/HelveticaNeue.ttc", 9),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)]
_FONT_REG  = [("/System/Library/Fonts/HelveticaNeue.ttc", 0),
              ("/System/Library/Fonts/SFNS.ttf", 0),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sport_label(s: str) -> str:
    return _SPORT_LABELS.get(s.lower(), s.upper())


def _american_odds_int(odds) -> int:
    try:
        x = float(odds)
    except (TypeError, ValueError):
        return 0
    return 0 if math.isnan(x) else int(round(x))


def _edge_color(edge: float, market: str = "moneyline") -> tuple:
    if market == "moneyline":
        if edge >= 0.08: return _GREEN
        if edge >= 0.04: return _AMBER
        return _BLUE
    else:
        if edge >= 1.5: return _GREEN
        if edge >= 0.8: return _AMBER
        return _BLUE


def _edge_tier(edge: float, market: str = "moneyline") -> str:
    if market == "moneyline":
        if edge >= 0.08: return "HIGH"
        if edge >= 0.04: return "MED"
        return "LOW"
    else:
        if edge >= 1.5: return "HIGH"
        if edge >= 0.8: return "MED"
        return "LOW"


def _load_font(paths, size: int):
    from PIL import ImageFont
    for path, idx in paths:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _fetch_team_logo(team_name: str, size: int = 80):
    """Return a PIL Image of the team logo, or None. Cached in data/cache/logos/mlb/."""
    from PIL import Image
    abbr = _ESPN_ABBR.get(team_name)
    if not abbr:
        return None

    _LOGO_CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = _LOGO_CACHE / f"{abbr}.png"

    if cache_file.exists():
        try:
            return Image.open(cache_file).convert("RGBA").resize((size, size), Image.LANCZOS)
        except Exception:
            pass

    try:
        import requests
        url = f"https://a.espncdn.com/i/teamlogos/mlb/500/scoreboard/{abbr}.png"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            cache_file.write_bytes(resp.content)
            return Image.open(io.BytesIO(resp.content)).convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        pass
    return None


def _draw_team_logo(img, cx: int, cy: int, size: int, team_name: str, ring_color: tuple):
    """Draw a circular team logo with a colored glow ring. Falls back to initial circle."""
    from PIL import Image, ImageDraw, ImageFilter

    draw = ImageDraw.Draw(img)
    logo = _fetch_team_logo(team_name, size)

    # Glow ring: draw slightly blurred colored ring behind the logo
    ring_r = size // 2 + 5
    glow_size = (ring_r * 2 + 20, ring_r * 2 + 20)
    glow_layer = Image.new("RGBA", glow_size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.ellipse([10, 10, glow_size[0] - 10, glow_size[1] - 10],
               outline=ring_color + (200,), width=4)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(4))
    gx = cx - glow_size[0] // 2
    gy = cy - glow_size[1] // 2
    img.paste(glow_layer, (gx, gy), glow_layer)

    # Solid ring
    draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
                 outline=ring_color, width=2)

    if logo:
        # Circular mask
        mask = Image.new("L", (size, size), 0)
        md = ImageDraw.Draw(mask)
        md.ellipse([0, 0, size - 1, size - 1], fill=255)
        # Dark background circle
        bg_circle = Image.new("RGBA", (size, size), (20, 22, 38, 255))
        img.paste(bg_circle, (cx - size // 2, cy - size // 2), mask)
        img.paste(logo, (cx - size // 2, cy - size // 2), mask)
    else:
        # Fallback: colored circle with team initials
        r = size // 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ring_color)
        font = _load_font(_FONT_BOLD, max(size // 3, 12))
        initials = "".join(w[0] for w in team_name.split()[:2]).upper()
        tw = draw.textlength(initials, font=font)
        draw.text((cx - tw // 2, cy - font.size // 2), initials, fill=_WHITE, font=font)


def _rounded_rect(draw, xy, radius, fill=None, outline=None, width=2):
    x0, y0, x1, y1 = xy
    r = min(radius, (x1 - x0) // 2, (y1 - y0) // 2)
    if fill:
        draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
        draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
        for ex, ey in [(x0, y0), (x1-2*r, y0), (x0, y1-2*r), (x1-2*r, y1-2*r)]:
            draw.ellipse([ex, ey, ex+2*r, ey+2*r], fill=fill)
    if outline:
        draw.arc([x0,     y0,     x0+2*r, y0+2*r], 180, 270, fill=outline, width=width)
        draw.arc([x1-2*r, y0,     x1,     y0+2*r], 270, 360, fill=outline, width=width)
        draw.arc([x0,     y1-2*r, x0+2*r, y1    ],  90, 180, fill=outline, width=width)
        draw.arc([x1-2*r, y1-2*r, x1,     y1    ],   0,  90, fill=outline, width=width)
        draw.line([x0+r, y0, x1-r, y0], fill=outline, width=width)
        draw.line([x0+r, y1, x1-r, y1], fill=outline, width=width)
        draw.line([x0, y0+r, x0, y1-r], fill=outline, width=width)
        draw.line([x1, y0+r, x1, y1-r], fill=outline, width=width)


def _pill(draw, x: int, y: int, text: str, font, fg: tuple, bg: tuple | None = None) -> int:
    """Draw a pill tag. Returns the right edge x coordinate."""
    tw = int(draw.textlength(text, font=font))
    px, py = 14, 6
    w = tw + px * 2
    h = font.size + py * 2
    if bg:
        _rounded_rect(draw, (x, y, x + w, y + h), radius=h // 2, fill=bg)
    draw.text((x + px, y + py), text, fill=fg, font=font)
    return x + w


def _scan_lines(img, opacity: int = 18):
    """Subtle horizontal scan lines for futuristic texture."""
    try:
        import numpy as np
        from PIL import Image as _Image
        arr = np.array(img).astype(np.int16)
        for y in range(0, img.height, 4):
            arr[y] = np.clip(arr[y] - opacity, 0, 255)
        img.paste(_Image.fromarray(arr.astype(np.uint8), "RGB"))
    except ImportError:
        pass


def _glow_line(draw, x0: int, y: int, x1: int, color: tuple, spread: int = 3):
    """Draw a glowing horizontal line (multiple alpha layers)."""
    for i in range(spread, 0, -1):
        alpha = int(80 * (i / spread))
        faded = tuple(int(c * alpha / 255) for c in color)
        draw.line([x0, y - i, x1, y - i], fill=faded, width=1)
        draw.line([x0, y + i, x1, y + i], fill=faded, width=1)
    draw.line([x0, y, x1, y], fill=color, width=2)


# ── Main card generator ───────────────────────────────────────────────────────

def generate_pick_card_image(
    picks: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
    record: str | None = None,
) -> Path | None:
    """Generate Instagram pick card. Tries HTML/Playwright first, falls back to PIL."""
    # Try the HTML renderer first — much better quality
    try:
        from src.output.card_html import render_pick_card_html
        path = render_pick_card_html(picks, sport=sport, card_date=card_date)
        if path and path.exists():
            return path
    except Exception as _html_err:
        print(f"  [card] HTML renderer unavailable ({_html_err}), using PIL fallback")

    # PIL fallback
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return None

    d         = card_date or date.today()
    sport_lbl = _sport_label(sport)
    display   = picks[:5]
    n         = len(display)

    W        = 1080
    PAD      = 44
    HDR_H    = 170    # header
    PICK_H   = 186    # per pick row
    GAP      = 10
    FOOT_H   = 80
    H        = HDR_H + n * (PICK_H + GAP) - GAP + FOOT_H + 24
    H        = max(H, 600)

    img  = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    # Subtle vertical gradient — slightly lighter at top
    try:
        import numpy as np
        arr = np.zeros((H, W, 3), dtype=np.uint8)
        for y in range(H):
            t = y / max(H - 1, 1)
            top = (10, 12, 22)
            bot = (5, 6, 14)
            arr[y] = [int(top[c] + (bot[c] - top[c]) * t) for c in range(3)]
        img.paste(Image.fromarray(arr, "RGB"))
    except ImportError:
        pass

    # Scan lines texture
    _scan_lines(img, opacity=12)
    draw = ImageDraw.Draw(img)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    f_brand    = _load_font(_FONT_COND, 80)
    f_brand_sm = _load_font(_FONT_BOLD, 60)
    f_ai       = _load_font(_FONT_BOLD, 48)
    f_sub_hdr  = _load_font(_FONT_REG,  22)
    f_team     = _load_font(_FONT_COND, 56)
    f_team_sm  = _load_font(_FONT_COND, 40)
    f_odds     = _load_font(_FONT_BOLD, 66)
    f_odds_sm  = _load_font(_FONT_BOLD, 48)
    f_vs       = _load_font(_FONT_REG,  22)
    f_pill     = _load_font(_FONT_BOLD, 18)
    f_pill_sm  = _load_font(_FONT_REG,  16)
    f_footer   = _load_font(_FONT_BOLD, 22)
    f_footer_r = _load_font(_FONT_REG,  18)

    # ── Header ────────────────────────────────────────────────────────────────
    # Dark raised header panel
    draw.rectangle([0, 0, W, HDR_H], fill=(11, 13, 24))

    # Top neon gold line
    _glow_line(draw, 0, 0, W, _GOLD, spread=4)

    # "Overlay" in white + "Bets" in gold + " AI" in cyan
    bx = PAD
    by = 22
    draw.text((bx, by), "Overlay", fill=_WHITE, font=f_brand)
    cw = int(draw.textlength("Overlay", font=f_brand))
    draw.text((bx + cw + 6, by + 14), "Bets", fill=_GOLD, font=f_brand_sm)
    bw2 = int(draw.textlength("Bets", font=f_brand_sm))

    # " AI" with subtle glow
    ai_x = bx + cw + 6 + bw2 + 10
    ai_y = by + 18
    ai_txt = "AI"
    # Glow layer
    glow_layer = Image.new("RGBA", (120, 70), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.text((10, 8), ai_txt, fill=_CYAN + (180,), font=f_ai)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(6))
    img.paste(glow_layer, (ai_x - 10, ai_y - 8), glow_layer)
    draw.text((ai_x, ai_y), ai_txt, fill=_CYAN, font=f_ai)

    # Subtitle line
    sub_txt = f"A.I. Edge Detection  ·  @Overlay"
    draw.text((PAD + 2, by + 104), sub_txt, fill=_GRAY_MID, font=f_sub_hdr)

    # Date + sport — right aligned
    date_txt = d.strftime("%b %d, %Y").upper()
    dw = int(draw.textlength(date_txt, font=f_footer))
    draw.text((W - PAD - dw, 28), date_txt, fill=_WHITE, font=f_footer)

    sport_lbl_txt = sport_lbl
    slw = int(draw.textlength(sport_lbl_txt, font=f_pill))
    pill_x0 = W - PAD - slw - 24
    pill_y0 = 64
    _rounded_rect(draw, (pill_x0, pill_y0, W - PAD, pill_y0 + 34),
                  radius=17, fill=_GRAY_DK)
    draw.text((pill_x0 + 12, pill_y0 + 7), sport_lbl_txt, fill=_GOLD, font=f_pill)

    # Bottom divider glow line
    _glow_line(draw, 0, HDR_H - 2, W, _GOLD, spread=3)

    # ── Pick rows ─────────────────────────────────────────────────────────────
    y = HDR_H + 14

    for idx, pick in enumerate(display):
        market   = str(pick.get("Market", "moneyline") or "moneyline").lower()
        team     = str(pick.get("Team",     "") or "")
        opponent = str(pick.get("Opponent", "") or "")
        bet_line = str(pick.get("BetLine",  "") or "")
        edge     = float(pick.get("Edge", 0) or 0)
        odds     = _american_odds_int(pick.get("BestOdds", 0))

        ec        = _edge_color(edge, market)
        team_clr  = _MLB_COLORS.get(team, _MLB_COLORS.get(opponent, ec))

        cx0, cx1 = PAD, W - PAD
        cy0, cy1 = y, y + PICK_H
        cw_inner  = cx1 - cx0

        is_best = idx == 0

        # ── Card background ────────────────────────────────────────────────
        # Best bet: faint team-color wash behind the card
        if is_best:
            # Subtle colored bg wash
            wash = tuple(min(255, int(c * 0.18) + 10) for c in team_clr)
            _rounded_rect(draw, (cx0, cy0, cx1, cy1), radius=18, fill=wash)
            # Bright card surface on top (slightly transparent effect via layering)
            _rounded_rect(draw, (cx0 + 2, cy0 + 2, cx1 - 2, cy1 - 2), radius=17, fill=_BG_BEST)
            # Gold glow border
            glow_c = Image.new("RGBA", (cw_inner + 40, PICK_H + 40), (0, 0, 0, 0))
            gg = ImageDraw.Draw(glow_c)
            _rounded_rect(gg, (16, 16, cw_inner + 24, PICK_H + 24),
                          radius=20, outline=_GOLD + (100,), width=4)
            glow_c = glow_c.filter(ImageFilter.GaussianBlur(6))
            img.paste(glow_c, (cx0 - 20, cy0 - 20), glow_c)
            _rounded_rect(draw, (cx0, cy0, cx1, cy1), radius=18, outline=_GOLD, width=2)
        else:
            _rounded_rect(draw, (cx0, cy0, cx1, cy1), radius=18, fill=_BG_CARD,
                          outline=_DIVIDER, width=1)

        # Left accent bar — team color, glowing
        bar_w  = 7
        bar_y0 = cy0 + 20
        bar_y1 = cy1 - 20
        for gi in range(8, 0, -2):
            gc = tuple(min(255, int(c * gi / 8)) for c in team_clr)
            draw.rectangle([cx0, bar_y0, cx0 + bar_w + gi, bar_y1], fill=gc)
        draw.rectangle([cx0, bar_y0, cx0 + bar_w, bar_y1], fill=team_clr)

        # Team logo
        logo_cx = cx0 + 82
        logo_cy = cy0 + PICK_H // 2
        logo_sz = 74 if is_best else 68
        _draw_team_logo(img, logo_cx, logo_cy, logo_sz, team, team_clr)
        draw = ImageDraw.Draw(img)

        TX = cx0 + 140    # text left
        RX = cx1 - 24     # right anchor

        # ── Team name ─────────────────────────────────────────────────────
        if market == "spread" and bet_line:
            team_disp = f"{team}  {bet_line}"
        elif market == "total":
            team_disp = team[:30]
        else:
            team_disp = team

        # Auto-shrink to fit
        max_team_w = RX - TX - 160   # leave room for odds
        tf = f_team
        while int(draw.textlength(team_disp, font=tf)) > max_team_w and tf.size > 28:
            tf = _load_font(_FONT_COND, tf.size - 4)

        name_y = cy0 + 26
        draw.text((TX, name_y), team_disp, fill=_WHITE, font=tf)

        # Market label — only for non-moneyline (small, grey)
        if market == "spread":
            draw.text((TX, name_y + tf.size + 4), "RUN LINE", fill=_GRAY_MID, font=f_pill_sm)
        elif market == "total":
            draw.text((TX, name_y + tf.size + 4), "OVER/UNDER", fill=_GRAY_MID, font=f_pill_sm)

        # ── vs opponent — subtle ───────────────────────────────────────────
        vs_y = cy0 + 104
        if market in ("moneyline", "spread"):
            vs_txt = f"vs  {opponent[:36]}"
        else:
            vs_txt = opponent[:44]
        draw.text((TX, vs_y), vs_txt, fill=_GRAY_MID, font=f_vs)

        # ── Edge — clean single line ───────────────────────────────────────
        edge_y = cy0 + 138
        if market == "moneyline":
            edge_txt = f"+{edge*100:.1f}% edge"
        else:
            edge_txt = f"+{edge:.2f} run edge"
        draw.text((TX, edge_y), edge_txt, fill=ec, font=f_pill)

        # ── Odds — dominant right side ─────────────────────────────────────
        if odds:
            odds_str = f"{odds:+d}"
            # Scale font to fill vertical space
            of = f_odds if abs(odds) < 1000 else f_odds_sm
            ow = int(draw.textlength(odds_str, font=of))
            odds_y = cy0 + (PICK_H - of.size) // 2 - 4
            # Faint glow behind the number
            try:
                og = Image.new("RGBA", (ow + 40, of.size + 20), (0, 0, 0, 0))
                ogd = ImageDraw.Draw(og)
                ogd.text((20, 10), odds_str, fill=ec + (90,), font=of)
                og = og.filter(ImageFilter.GaussianBlur(8))
                img.paste(og, (RX - ow - 20, odds_y - 10), og)
            except Exception:
                pass
            draw = ImageDraw.Draw(img)
            draw.text((RX - ow, odds_y), odds_str, fill=ec, font=of)

        # ── Best bet: subtle "⚡ TOP PLAY" inline under team name ───────────
        if is_best:
            bp_txt = "⚡  TOP PLAY"
            bpw = int(draw.textlength(bp_txt, font=f_pill_sm))
            # Sit it right of the edge text on the same bottom row
            draw.text((TX + int(draw.textlength(edge_txt, font=f_pill)) + 18, edge_y),
                      bp_txt, fill=_GOLD, font=f_pill_sm)

        y += PICK_H + GAP

    # ── Footer ────────────────────────────────────────────────────────────────
    fy = H - FOOT_H + 8
    _glow_line(draw, PAD, fy - 2, W - PAD, _GOLD, spread=2)

    # Centered handle
    handle = "@Overlay"
    hw = int(draw.textlength(handle, font=f_footer))
    draw.text(((W - hw) // 2, fy + 10), handle, fill=_GOLD, font=f_footer)

    # Right: AI verify tag
    ver_txt = "A.I. Verified"
    vw = int(draw.textlength(ver_txt, font=f_footer_r))
    draw.text((W - PAD - vw, fy + 14), ver_txt, fill=_GRAY_MID, font=f_footer_r)

    # Left: sport + date
    foot_left = f"{sport_lbl}  ·  {d.strftime('%b %d, %Y').upper()}"
    draw.text((PAD, fy + 14), foot_left, fill=_GRAY_MID, font=f_footer_r)

    # ── Save ──────────────────────────────────────────────────────────────────
    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / "pick_card.png"
    img.save(path, quality=95)
    return path


# ── Text / markdown ───────────────────────────────────────────────────────────

def generate_pick_card_text(
    picks: list[dict],
    sport: str = "mlb",
    card_date: date | None = None,
    record: str | None = None,
) -> str:
    """Generate a markdown pick card for Discord / Twitter captions."""
    d = card_date or date.today()
    header = f"Overlay AI | {_sport_label(sport)} | {d.strftime('%B %d, %Y')}"
    lines = [header, "=" * len(header), ""]

    if not picks:
        lines.append("No value bets identified today.")
        return "\n".join(lines)

    for i, pick in enumerate(picks[:5], 1):
        market   = str(pick.get("Market", "moneyline") or "moneyline").lower()
        team     = str(pick.get("Team",     "") or "")
        opponent = str(pick.get("Opponent", "") or "")
        bet_line = str(pick.get("BetLine",  "") or "")
        edge     = float(pick.get("Edge", 0) or 0)
        odds     = _american_odds_int(pick.get("BestOdds", 0))
        book     = str(pick.get("Sportsbook", "") or "")
        kelly    = float(pick.get("kelly_pct", 0) or 0)

        tier  = _edge_tier(edge, market)
        label = "⚡ BEST BET" if i == 1 else f"Pick #{i}"

        if market == "moneyline":
            prob    = float(pick.get("ModelProb", 0) or 0)
            lines.append(f"{label} — MONEYLINE  [{tier}]")
            lines.append(f"  {team} ML  (vs {opponent})")
            lines.append(f"  Model {prob:.1%}  ·  Edge +{edge*100:.1f}%")
            if kelly > 0:
                lines.append(f"  Kelly: {kelly:.1f}%  ($50 → ${kelly*0.5:.2f}  |  $200 → ${kelly*2:.2f})")
        elif market == "spread":
            lines.append(f"{label} — RUN LINE  [{tier}]")
            lines.append(f"  {team} {bet_line}  (vs {opponent})")
            lines.append(f"  Edge {edge:+.2f}R")
        elif market == "total":
            lines.append(f"{label} — TOTAL  [{tier}]")
            lines.append(f"  {team}  ({opponent})")
            lines.append(f"  Edge {edge:+.1f}R")

        if odds:
            book_str = f" @ {book}" if book else ""
            lines.append(f"  Bet: {odds:+d}{book_str}")
        lines.append("")

    lines.append("Overlay AI — Edge Detection · @Overlay")
    lines.append("Free daily picks · Follow for more")

    save_dir = OUTPUT_DIR / sport / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "picks.md").write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)

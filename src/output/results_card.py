"""
Results reveal card generator — Overlay.

Professional-quality social media card showing WIN/LOSS outcomes.
Same dark design language as pick_card.py, with:
  - Drop shadows on cards
  - Gradient stamp zones
  - Hand-drawn checkmark / X marks (no emoji)
  - Clean score display

Usage:
    from src.output.results_card import generate_results_card
    path = generate_results_card(sport="baseball_mlb", card_date=date(2026, 4, 9))
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

OUTPUT_DIR = Path("output/picks")

# ── Palette ────────────────────────────────────────────────────────────────────
_BG_TOP     = ( 8,  10,  18)
_BG_BOT     = ( 4,   5,  12)
_CARD_BG    = (18,  20,  34)
_CARD_TOP   = (24,  26,  44)
_GOLD       = (255, 184,   0)
_WHITE      = (248, 248, 252)
_GRAY_LT    = (155, 158, 180)
_GRAY_MID   = ( 88,  92, 116)
_GRAY_DK    = ( 34,  36,  56)
_BLACK      = (  8,   8,  12)

# WIN zone palette
_WIN_ZONE   = ( 14,  52,  24)   # dark green fill for result zone
_WIN_GLOW   = ( 25,  85,  38)   # lighter green tint for top of gradient
_WIN_TEXT   = ( 72, 225, 100)   # bright green text
_WIN_BORDER = ( 50, 190,  75)   # border on the whole card

# LOSS zone palette
_LOSS_ZONE  = ( 54,  14,  14)   # dark red fill
_LOSS_GLOW  = ( 85,  22,  22)   # lighter red tint for top
_LOSS_TEXT  = (230,  55,  55)   # bright red text
_LOSS_BORDER= (200,  45,  45)   # border on the whole card

# SHADOW
_SHADOW     = (  2,   2,   6)   # near-black shadow

_MLB_COLORS: dict[str, tuple] = {
    "Arizona Diamondbacks":   (167,  25,  48),
    "Atlanta Braves":         (206,  17,  65),
    "Baltimore Orioles":      (223, 109,  29),
    "Boston Red Sox":         (189,  48,  57),
    "Chicago Cubs":           ( 14,  51, 134),
    "Chicago White Sox":      ( 39,  37,  31),
    "Cincinnati Reds":        (198,   1,  31),
    "Cleveland Guardians":    (  0,  56, 101),
    "Colorado Rockies":       ( 51,   0, 111),
    "Detroit Tigers":         ( 12,  35,  64),
    "Houston Astros":         (  0,  45,  98),
    "Kansas City Royals":     (  0,  70, 135),
    "Los Angeles Angels":     (186,   0,  33),
    "Los Angeles Dodgers":    (  0,  90, 156),
    "Miami Marlins":          (  0, 163, 224),
    "Milwaukee Brewers":      (  0,  40,  85),
    "Minnesota Twins":        (  0,  43, 127),
    "New York Mets":          (  0,  45, 114),
    "New York Yankees":       ( 12,  35,  64),
    "Athletics":              (  0,  56,  49),
    "Oakland Athletics":      (  0,  56,  49),
    "Philadelphia Phillies":  (232,  24,  40),
    "Pittsburgh Pirates":     (253, 184,  39),
    "San Diego Padres":       ( 47,  36,  29),
    "San Francisco Giants":   (253,  90,  30),
    "Seattle Mariners":       (  0,  92,  92),
    "St. Louis Cardinals":    (196,  30,  58),
    "Tampa Bay Rays":         (  9,  44, 184),
    "Texas Rangers":          (  0,  50, 120),
    "Toronto Blue Jays":      ( 19,  74, 142),
    "Washington Nationals":   (171,   0,   3),
}

_SPORT_LABELS = {
    "baseball_mlb":         "MLB",
    "basketball_nba":       "NBA",
    "basketball_ncaab":     "NCAAB",
    "americanfootball_nfl": "NFL",
    "mlb": "MLB", "nba": "NBA", "nfl": "NFL", "ncaab": "NCAAB",
}

_FONT_COND_PATHS = [
    ("/System/Library/Fonts/HelveticaNeue.ttc", 9),
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]
_FONT_BOLD_PATHS = [
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
    ("/System/Library/Fonts/HelveticaNeue.ttc", 9),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]
_FONT_REG_PATHS = [
    ("/System/Library/Fonts/HelveticaNeue.ttc", 0),
    ("/System/Library/Fonts/SFNS.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sport_label(sport: str) -> str:
    return _SPORT_LABELS.get(sport.lower(), sport.upper())


def _american_odds_int(odds) -> int:
    try:
        x = float(odds)
    except (TypeError, ValueError):
        return 0
    return 0 if math.isnan(x) else int(round(x))


def _load_font(paths_with_index, size: int):
    from PIL import ImageFont
    for path, idx in paths_with_index:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _gradient_bg(img, top: tuple, bot: tuple):
    """Full-image vertical gradient."""
    try:
        import numpy as np
        arr = np.zeros((img.height, img.width, 3), dtype=np.uint8)
        for y in range(img.height):
            t = y / max(img.height - 1, 1)
            arr[y] = [int(top[c] + (bot[c] - top[c]) * t) for c in range(3)]
        from PIL import Image as _I
        img.paste(_I.fromarray(arr, "RGB"))
    except ImportError:
        pass


def _fill_gradient_rect(img, x0: int, y0: int, x1: int, y1: int,
                        col_top: tuple, col_bot: tuple):
    """Fill a rectangle with a vertical gradient using numpy."""
    try:
        import numpy as np
        arr = np.array(img)
        for y in range(y0, y1):
            t = (y - y0) / max(y1 - y0 - 1, 1)
            r = int(col_top[0] + (col_bot[0] - col_top[0]) * t)
            g = int(col_top[1] + (col_bot[1] - col_top[1]) * t)
            b = int(col_top[2] + (col_bot[2] - col_top[2]) * t)
            arr[y, x0:x1] = [r, g, b]
        from PIL import Image as _I
        img.paste(_I.fromarray(arr, "RGB"))
        return True
    except Exception:
        return False


def _rounded_rect(draw, xy, radius, fill, outline=None, width=2):
    x0, y0, x1, y1 = xy
    r = min(radius, (x1 - x0) // 2, (y1 - y0) // 2)
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    for ex, ey in [(x0, y0), (x1 - 2*r, y0), (x0, y1 - 2*r), (x1 - 2*r, y1 - 2*r)]:
        draw.ellipse([ex, ey, ex + 2*r, ey + 2*r], fill=fill)
    if outline:
        draw.arc([x0,     y0,     x0+2*r, y0+2*r], 180, 270, fill=outline, width=width)
        draw.arc([x1-2*r, y0,     x1,     y0+2*r], 270, 360, fill=outline, width=width)
        draw.arc([x0,     y1-2*r, x0+2*r, y1    ],  90, 180, fill=outline, width=width)
        draw.arc([x1-2*r, y1-2*r, x1,     y1    ],   0,  90, fill=outline, width=width)
        draw.line([x0+r,  y0,  x1-r, y0 ], fill=outline, width=width)
        draw.line([x0+r,  y1,  x1-r, y1 ], fill=outline, width=width)
        draw.line([x0,  y0+r,  x0,  y1-r], fill=outline, width=width)
        draw.line([x1,  y0+r,  x1,  y1-r], fill=outline, width=width)


def _draw_shadow(draw, xy, radius: int = 16, offset: int = 5, spread: int = 3):
    """Draw a simple drop shadow (darker rect, slightly offset)."""
    x0, y0, x1, y1 = xy
    for i in range(spread, 0, -1):
        alpha_shade = tuple(min(c + i * 2, 20) for c in _SHADOW)
        _rounded_rect(draw,
                      (x0 + offset - i, y0 + offset - i,
                       x1 + offset + i, y1 + offset + i),
                      radius=radius + i, fill=alpha_shade)


def _draw_checkmark(draw, cx: float, cy: float, size: float,
                    color: tuple, width: int = 5):
    """Draw a clean ✓ checkmark using lines."""
    # Short left leg + long right leg
    lx = cx - size * 0.40
    ly = cy + size * 0.05
    mx = cx - size * 0.05
    my = cy + size * 0.42
    rx = cx + size * 0.46
    ry = cy - size * 0.38
    draw.line([(lx, ly), (mx, my)], fill=color, width=width)
    draw.line([(mx, my), (rx, ry)], fill=color, width=width)


def _draw_xmark(draw, cx: float, cy: float, size: float,
                color: tuple, width: int = 5):
    """Draw a clean ✗ X using two diagonal lines."""
    s = size * 0.38
    draw.line([(cx - s, cy - s), (cx + s, cy + s)], fill=color, width=width)
    draw.line([(cx + s, cy - s), (cx - s, cy + s)], fill=color, width=width)


def _parse_score(score_str: str) -> list[str]:
    """
    Parse "Cincinnati Reds 1, Miami Marlins 8" into ["CIN  1", "MIA  8"]
    """
    if not score_str:
        return []
    parts = [p.strip() for p in score_str.split(",")]
    out = []
    for part in parts[:2]:
        tokens = part.rsplit(" ", 1)
        if len(tokens) == 2:
            team_words = tokens[0].split()
            # Use last word of team name (e.g., "Reds", "Twins")
            short = team_words[-1][:8].upper()
            out.append(f"{short}  {tokens[1]}")
        else:
            out.append(part[:12])
    return out


def _load_picks(sport: str, date_str: str) -> list[dict]:
    base = OUTPUT_DIR / sport / date_str
    for fname in ("picks_card.json", "picks.json"):
        path = base / fname
        if path.exists():
            data = json.loads(path.read_text())
            picks = data if isinstance(data, list) else []
            return [p for p in picks
                    if str(p.get("Market", "")).lower() != "total"][:5]
    return []


def _load_grades(sport: str, date_str: str) -> list[dict]:
    path = OUTPUT_DIR / sport / date_str / "grades.json"
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("details", [])


def _match_grade(pick: dict, grades: list[dict]) -> dict | None:
    team = str(pick.get("Team", "")).lower().strip()
    for g in grades:
        if g.get("team", "").lower().strip() == team:
            return g
    return None


# ── Image generator ────────────────────────────────────────────────────────────

def generate_results_card(
    sport: str = "baseball_mlb",
    card_date: date | None = None,
) -> Path | None:
    """
    Generate a professional results reveal card.
    Reads picks_card.json + grades.json for the given date.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        print("  Pillow not installed — skipping results card.")
        return None

    d         = card_date or date.today()
    date_str  = d.strftime("%Y%m%d")
    sport_lbl = _sport_label(sport)

    picks  = _load_picks(sport, date_str)
    grades = _load_grades(sport, date_str)

    if not picks:
        print(f"  No picks found for {date_str} — skipping results card.")
        return None
    if not grades:
        print(f"  No grades found for {date_str} — skipping results card.")
        return None

    annotated = [(p, _match_grade(p, grades)) for p in picks]

    wins         = sum(1 for _, g in annotated if g and g.get("status") == "win")
    losses       = sum(1 for _, g in annotated if g and g.get("status") == "loss")
    graded       = wins + losses
    total_profit = sum((g.get("profit", 0) or 0) for _, g in annotated if g)
    roi          = (total_profit / (graded * 100) * 100) if graded > 0 else 0.0

    profit_sign = "+" if total_profit >= 0 else ""
    roi_sign    = "+" if roi >= 0 else ""

    # ── Fonts ──────────────────────────────────────────────────────────────────
    f_brand_lg    = _load_font(_FONT_COND_PATHS, 68)
    f_brand_sm    = _load_font(_FONT_BOLD_PATHS, 52)
    f_hdr         = _load_font(_FONT_BOLD_PATHS, 20)
    f_hdr_sm      = _load_font(_FONT_REG_PATHS,  17)
    f_record      = _load_font(_FONT_COND_PATHS, 72)   # BIG record "3-2"
    f_roi         = _load_font(_FONT_BOLD_PATHS, 22)
    f_team        = _load_font(_FONT_COND_PATHS, 50)
    f_team_sm     = _load_font(_FONT_COND_PATHS, 36)
    f_odds        = _load_font(_FONT_BOLD_PATHS, 42)
    f_sub         = _load_font(_FONT_REG_PATHS,  20)
    f_meta        = _load_font(_FONT_BOLD_PATHS, 16)
    f_result_word = _load_font(_FONT_COND_PATHS, 58)   # "WIN" / "LOSS"
    f_score_team  = _load_font(_FONT_BOLD_PATHS, 18)
    f_footer      = _load_font(_FONT_BOLD_PATHS, 19)

    # ── Layout ─────────────────────────────────────────────────────────────────
    PAD     = 36
    W       = 1080
    HDR_H   = 178    # taller header — record lives in its own band
    PICK_H  = 154
    GAP     = 10
    FOOT_H  = 60
    n       = len(annotated)
    H       = HDR_H + n * (PICK_H + GAP) + FOOT_H + 24

    img  = Image.new("RGB", (W, H), _BG_TOP)
    _gradient_bg(img, _BG_TOP, _BG_BOT)
    draw = ImageDraw.Draw(img)

    # ── Header — two bands ─────────────────────────────────────────────────────
    # Band 1: brand + date/handle (H=110)
    BAND1_H = 108
    draw.rectangle([0, 0, W, BAND1_H], fill=(10, 12, 22))
    draw.rectangle([0, 0, W, 5], fill=_GOLD)   # top gold strip

    # Brand left
    draw.text((PAD, 14), "Overlay", fill=_WHITE, font=f_brand_lg)
    cw = draw.textlength("Overlay", font=f_brand_lg)
    draw.text((PAD + cw + 6, 22), "Bets", fill=_GOLD, font=f_brand_sm)
    draw.text((PAD + 2, 90), "RESULTS  ·  A.I. Sports Picks", fill=_GRAY_MID, font=f_hdr_sm)

    # Date + handle right
    sport_date = f"{sport_lbl}  ·  {d.strftime('%b %d, %Y').upper()}"
    sdw = draw.textlength(sport_date, font=f_hdr)
    draw.text((W - PAD - sdw, 14), sport_date, fill=_WHITE, font=f_hdr)
    hw = draw.textlength("@getoverlay", font=f_hdr)
    draw.text((W - PAD - hw, 42), "@getoverlay", fill=_GOLD, font=f_hdr)

    # Band 2: record bar (below brand, above picks)
    BAND2_Y0 = BAND1_H
    BAND2_Y1 = HDR_H
    record_color = _WIN_TEXT if wins >= losses else _LOSS_TEXT
    roi_color    = _WIN_TEXT if total_profit >= 0 else _LOSS_TEXT

    # Dark tinted band for record
    draw.rectangle([0, BAND2_Y0, W, BAND2_Y1], fill=(6, 8, 16))

    # Big record "3-2"
    record_str = f"{wins}-{losses}"
    rw = draw.textlength(record_str, font=f_record)
    record_x = PAD
    record_y = BAND2_Y0 + 4
    draw.text((record_x, record_y), record_str, fill=record_color, font=f_record)

    # ROI + profit right of record
    roi_line1 = f"{roi_sign}{roi:.1f}% ROI"
    roi_line2 = f"{profit_sign}{total_profit / 100:.2f}u  ({wins}W-{losses}L)"
    rl1w = draw.textlength(roi_line1, font=f_roi)
    rl2w = draw.textlength(roi_line2, font=f_meta)
    sub_x = record_x + rw + 28
    sub_y = BAND2_Y0 + 10
    draw.text((sub_x, sub_y),      roi_line1, fill=roi_color,  font=f_roi)
    draw.text((sub_x, sub_y + 34), roi_line2, fill=_GRAY_LT,   font=f_meta)

    # Gold separator below header
    draw.rectangle([0, HDR_H - 3, W, HDR_H], fill=_GOLD)

    # ── Pick rows ──────────────────────────────────────────────────────────────
    y = HDR_H + 12

    STAMP_SPLIT = 0.61   # stamp zone starts at this fraction of card width

    for idx, (pick, grade) in enumerate(annotated):
        market   = str(pick.get("Market", "moneyline") or "moneyline").lower()
        team     = str(pick.get("Team",     "") or "")
        opponent = str(pick.get("Opponent", "") or "")
        bet_line = str(pick.get("BetLine",  "") or "")
        edge     = float(pick.get("Edge", 0) or 0)
        odds     = _american_odds_int(pick.get("BestOdds", 0))
        book     = str(pick.get("Sportsbook", "") or "")[:16]

        won    = bool(grade and grade.get("status") == "win")
        lost   = bool(grade and grade.get("status") == "loss")
        score  = str(grade.get("score", "") if grade else "")

        team_color = _MLB_COLORS.get(team, _MLB_COLORS.get(opponent, _GOLD))

        cx0, cx1 = PAD, W - PAD
        cy0, cy1 = y, y + PICK_H
        card_w   = cx1 - cx0

        stamp_x  = cx0 + int(card_w * STAMP_SPLIT)

        # ── Drop shadow (draw first, behind the card) ─────────────────────
        _draw_shadow(draw, (cx0, cy0, cx1, cy1), radius=16, offset=6, spread=4)

        # ── Card background ─────────────────────────────────────────────────
        # Left zone (pick info): solid dark card color
        card_fill   = _CARD_TOP if idx == 0 else _CARD_BG
        card_border = _WIN_BORDER if won else (_LOSS_BORDER if lost else
                       (_GOLD if idx == 0 else None))

        _rounded_rect(draw, (cx0, cy0, cx1, cy1), radius=16,
                      fill=card_fill,
                      outline=card_border, width=2)

        # ── Stamp zone gradient fill ─────────────────────────────────────────
        if grade:
            zone_top = _WIN_GLOW  if won else _LOSS_GLOW
            zone_bot = _WIN_ZONE  if won else _LOSS_ZONE
            # Fill stamp zone rectangle with vertical gradient
            # Clip to right portion of rounded card
            _fill_gradient_rect(img, stamp_x, cy0 + 2, cx1 - 2, cy1 - 2,
                                zone_top, zone_bot)
            # Re-draw to refresh ImageDraw after numpy paste
            draw = ImageDraw.Draw(img)

            # Redraw card border on top of the gradient fill
            if card_border:
                _rounded_rect(draw, (cx0, cy0, cx1, cy1), radius=16,
                              fill=None, outline=card_border, width=2)

        # Vertical divider between pick info and stamp zone
        div_color = (_WIN_BORDER if won else _LOSS_BORDER) if grade else _GRAY_DK
        draw.rectangle([stamp_x - 1, cy0 + 12, stamp_x + 1, cy1 - 12],
                       fill=div_color)

        # ── Left accent bar (team color) ─────────────────────────────────────
        bar_w = 10 if idx == 0 else 8
        draw.rectangle([cx0, cy0 + 18, cx0 + bar_w, cy1 - 18], fill=team_color)
        draw.ellipse([cx0, cy0 + 10, cx0 + bar_w * 2, cy0 + 10 + bar_w * 2],
                     fill=team_color)
        draw.ellipse([cx0, cy1 - 10 - bar_w * 2, cx0 + bar_w * 2, cy1 - 10],
                     fill=team_color)

        # ── Pick info (left zone) ─────────────────────────────────────────────
        IX  = cx0 + 82      # text left edge
        RX  = stamp_x - 20  # text right bound

        # Team + bet line
        if market == "spread" and bet_line:
            team_disp = f"{team[:18]}  {bet_line}"
        else:
            team_disp = team[:24]

        tf = f_team
        if draw.textlength(team_disp, font=f_team) > (RX - IX - 10):
            tf = f_team_sm

        team_y = cy0 + 20
        draw.text((IX, team_y), team_disp, fill=_WHITE, font=tf)

        # Odds
        if odds:
            odds_str = f"{odds:+d}"
            ow = draw.textlength(odds_str, font=f_odds)
            if RX - ow >= IX:
                odds_color = (_WIN_TEXT if won else _LOSS_TEXT) if grade else _GOLD
                draw.text((RX - ow, team_y + 4), odds_str,
                          fill=odds_color, font=f_odds)

        # Sub row
        sub_y = cy0 + 84
        opp_str = f"vs  {opponent[:26]}"
        draw.text((IX, sub_y), opp_str, fill=_GRAY_LT, font=f_sub)

        pill_y  = sub_y + 28
        pill_x  = IX
        if market == "spread":
            mkt_tag = "RUN LINE"
        elif market == "total":
            mkt_tag = "OVER/UNDER"
        else:
            mkt_tag = None

        if mkt_tag:
            pill_w = int(draw.textlength(mkt_tag, font=f_meta)) + 16
            _rounded_rect(draw, (pill_x, pill_y, pill_x + pill_w, pill_y + 24),
                          radius=4, fill=_GRAY_DK)
            pill_text_color = (_WIN_TEXT if won else _LOSS_TEXT) if grade else _GRAY_LT
            draw.text((pill_x + 8, pill_y + 4), mkt_tag,
                      fill=pill_text_color, font=f_meta)
            pill_x += pill_w + 8

        # Edge
        if market == "moneyline":
            edge_str = f"+{edge*100:.1f}%  edge"
        else:
            edge_str = f"+{edge:.2f}R  edge"
        ew = draw.textlength(edge_str, font=f_meta)
        if RX - ew >= IX:
            draw.text((RX - ew, sub_y), edge_str, fill=_GRAY_MID, font=f_meta)

        # Sportsbook
        if book:
            bw = draw.textlength(book, font=f_meta)
            if RX - bw >= IX:
                draw.text((RX - bw, pill_y + 4), book,
                          fill=_GRAY_MID, font=f_meta)

        # ── Result stamp (right zone) ─────────────────────────────────────────
        if grade:
            stamp_cx  = (stamp_x + cx1) // 2
            stamp_mid = (cy0 + cy1) // 2

            # Big WIN / LOSS word
            result_word  = "WIN" if won else "LOSS"
            result_color = _WIN_TEXT if won else _LOSS_TEXT
            rw2 = draw.textlength(result_word, font=f_result_word)
            draw.text((stamp_cx - rw2 / 2, stamp_mid - 60),
                      result_word, fill=result_color, font=f_result_word)

            # Checkmark or X (drawn as lines — no emoji rendering issues)
            icon_cx = stamp_cx
            icon_cy = stamp_mid + 12
            icon_size = 22
            if won:
                _draw_checkmark(draw, icon_cx, icon_cy, icon_size,
                                result_color, width=5)
            else:
                _draw_xmark(draw, icon_cx, icon_cy, icon_size,
                            result_color, width=5)

            # Score
            score_lines = _parse_score(score)
            for li, line in enumerate(score_lines[:2]):
                lw = draw.textlength(line, font=f_score_team)
                draw.text((stamp_cx - lw / 2, stamp_mid + 44 + li * 24),
                          line, fill=_WHITE, font=f_score_team)

        else:
            # Pending pick
            p_txt = "PENDING"
            pw = draw.textlength(p_txt, font=f_meta)
            stamp_cx = (stamp_x + cx1) // 2
            draw.text((stamp_cx - pw / 2, (cy0 + cy1) // 2 - 10),
                      p_txt, fill=_GRAY_MID, font=f_meta)

        y += PICK_H + GAP

    # ── Footer ─────────────────────────────────────────────────────────────────
    fy = H - FOOT_H + 8
    draw.rectangle([PAD, fy - 4, W - PAD, fy - 2], fill=_GOLD)

    day_str = f"{wins}-{losses}  ·  {profit_sign}{total_profit / 100:.2f} units"
    draw.text((PAD, fy + 8), day_str, fill=_GOLD, font=f_footer)

    cta = "Follow @getoverlay for free daily picks"
    cta_w = draw.textlength(cta, font=f_footer)
    draw.text(((W - cta_w) // 2, fy + 8), cta, fill=_GOLD, font=f_footer)

    ver = "AI model · verified"
    vw  = draw.textlength(ver, font=f_hdr_sm)
    draw.text((W - PAD - vw, fy + 10), ver, fill=_GRAY_MID, font=f_hdr_sm)

    # ── Save ───────────────────────────────────────────────────────────────────
    save_dir = OUTPUT_DIR / sport / date_str
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / "results_card.png"
    img.save(path, quality=95)
    print(f"  Results card saved: {path}  ({wins}-{losses}, {roi_sign}{roi:.1f}% ROI)")
    return path

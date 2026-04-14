"""
Masters Tournament pick card generator — ChefTonyBets.

Generates an Instagram-ready 1080×1400 card for golf tournament outright picks.
Format is distinct from the daily MLB card: Augusta green accent palette,
player rows with reasoning blurbs, no "vs opponent" format.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

OUTPUT_DIR    = Path("output/picks")
_TRACKER_FILE = Path("data/pnl/picks.json")

# ── Palette ───────────────────────────────────────────────────────────────────
_BG_TOP      = ( 6,  10,  16)   # near-black
_BG_BOT      = ( 4,   6,  10)   # deepest black
_CARD_BG     = (14,  18,  28)
_CARD_TOP    = (18,  24,  38)   # best bet elevated surface
_DIVIDER     = (28,  32,  48)

# Augusta palette
_AUGUSTA_GRN = (  0, 103,  71)  # Augusta National green
_GOLD        = (255, 184,   0)  # ChefTonyBets brand gold
_GREEN_SOFT  = ( 80, 200, 120)  # win-signal green
_AMBER       = (255, 165,  20)
_BLUE_SOFT   = (100, 130, 255)

_WHITE   = (248, 248, 252)
_GRAY_LT = (160, 163, 185)
_GRAY_MID = ( 90,  94, 120)
_GRAY_DK  = ( 32,  36,  54)
_BLACK   = (  8,   8,  12)

# Font paths (same as daily card)
_FONT_COND = [("/System/Library/Fonts/HelveticaNeue.ttc", 9),
              ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)]
_FONT_BOLD = [("/System/Library/Fonts/HelveticaNeue.ttc", 1),
              ("/System/Library/Fonts/HelveticaNeue.ttc", 9),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)]
_FONT_REG  = [("/System/Library/Fonts/HelveticaNeue.ttc", 0),
              ("/System/Library/Fonts/SFNS.ttf", 0),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)]


def _load_font(paths, size: int):
    from PIL import ImageFont
    for path, idx in paths:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _gradient_bg(img, top, bot):
    try:
        import numpy as np
        from PIL import Image as _Img
        arr = __import__("numpy").zeros((img.height, img.width, 3), dtype=__import__("numpy").uint8)
        for y in range(img.height):
            t = y / max(img.height - 1, 1)
            arr[y] = [int(top[c] + (bot[c] - top[c]) * t) for c in range(3)]
        img.paste(_Img.fromarray(arr, "RGB"))
    except ImportError:
        pass


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
        draw.line([x0+r, y0, x1-r, y0], fill=outline, width=width)
        draw.line([x0+r, y1, x1-r, y1], fill=outline, width=width)
        draw.line([x0, y0+r, x0, y1-r], fill=outline, width=width)
        draw.line([x1, y0+r, x1, y1-r], fill=outline, width=width)


def _load_tracker_stats() -> dict | None:
    if not _TRACKER_FILE.exists():
        return None
    try:
        data = json.loads(_TRACKER_FILE.read_text())
        settled = [p for p in data.get("picks", []) if p.get("result") in ("win", "loss")]
        if not settled:
            return None
        wins   = sum(1 for p in settled if p["result"] == "win")
        losses = len(settled) - wins
        staked = sum(float(p.get("stake", p.get("bet_size", 1.0))) for p in settled)
        profit = sum(float(p.get("profit") or 0.0) for p in settled)
        roi    = (profit / staked * 100) if staked > 0 else 0.0
        return {"wins": wins, "losses": losses, "profit": profit, "roi": roi}
    except Exception:
        return None


# ── Masters pick schema ───────────────────────────────────────────────────────
# Each pick dict:
# {
#   "player":   "Rory McIlroy",
#   "odds":     1200,          # American
#   "book":     "BetRivers",
#   "market":   "outright",    # or "top_5", "top_10", "make_cut", "h2h"
#   "rank":     1,             # 1 = best bet
#   "blurb":    "Grand Slam on the line. Most complete game in field.",
# }


def generate_masters_card_image(
    picks: list[dict],
    card_date: date | None = None,
    record: str | None = None,
) -> Path | None:
    """Generate a 1080-wide Masters Tournament Instagram pick card."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  Pillow not installed. Run: pip install pillow")
        return None

    d       = card_date or date.today()
    display = picks[:5]

    # ── Fonts ─────────────────────────────────────────────────────────────────
    f_brand_lg = _load_font(_FONT_COND, 68)
    f_brand_sm = _load_font(_FONT_BOLD, 52)
    f_hdr      = _load_font(_FONT_BOLD, 21)
    f_hdr_sm   = _load_font(_FONT_REG,  18)
    f_tourn    = _load_font(_FONT_COND, 30)   # "2026 MASTERS" label
    f_player   = _load_font(_FONT_COND, 50)   # player name
    f_odds     = _load_font(_FONT_BOLD, 54)   # odds
    f_blurb    = _load_font(_FONT_REG,  19)   # reasoning blurb
    f_meta     = _load_font(_FONT_BOLD, 17)
    f_meta_r   = _load_font(_FONT_REG,  17)
    f_badge    = _load_font(_FONT_BOLD, 20)
    f_footer   = _load_font(_FONT_BOLD, 20)

    PAD    = 40
    W      = 1080
    # Header layout (3 rows, no overlaps):
    #   Row 1  y=16–82   brand + date/handle
    #   Row 2  y=88–134  stats pills  (left: tagline, right: pills)
    #   Row 3  y=144–188 tournament badge (full-width centered)
    #   Gold line at HDR_H-4
    HDR_H  = 208
    PICK_H = 158
    GAP    = 10
    FOOT_H = 72
    H      = HDR_H + len(display) * (PICK_H + GAP) + FOOT_H + 30
    H      = max(H, 650)

    img  = Image.new("RGB", (W, H), _BG_TOP)
    _gradient_bg(img, _BG_TOP, _BG_BOT)
    draw = ImageDraw.Draw(img)

    # ── Header surface ────────────────────────────────────────────────────────
    draw.rectangle([0, 0, W, HDR_H - 4], fill=(10, 13, 22))
    draw.rectangle([0, 0, W, 5], fill=_GOLD)                       # top gold
    draw.rectangle([0, 5, W, 13], fill=_AUGUSTA_GRN)               # Augusta green stripe
    draw.rectangle([0, HDR_H - 4, W, HDR_H], fill=_GOLD)          # bottom gold

    # ── Row 1: Brand (left) + Date / Handle (right) ───────────────────────────
    draw.text((PAD, 18), "ChefTony", fill=_WHITE, font=f_brand_lg)
    cw = draw.textlength("ChefTony", font=f_brand_lg)
    draw.text((PAD + cw + 6, 26), "Bets", fill=_GOLD, font=f_brand_sm)

    date_txt = "APR 10–13, 2026"
    dw = draw.textlength(date_txt, font=f_hdr)
    draw.text((W - PAD - dw, 20), date_txt, fill=_WHITE, font=f_hdr)

    handle_w = draw.textlength("@ChefTonyBets", font=f_hdr)
    draw.text((W - PAD - handle_w, 52), "@ChefTonyBets", fill=_GOLD, font=f_hdr)

    # ── Row 2: Tagline (left) + Stats pills (right) ───────────────────────────
    PILL_Y0 = 90
    PILL_H  = 40
    tagline = "A.I. Sports Picks  ·  Cooking Up Parlays"
    draw.text((PAD, PILL_Y0 + 10), tagline, fill=_GRAY_MID, font=f_hdr_sm)

    pass  # no stats pills on Masters card

    # ── Row 3: Tournament badge — centered, full-width feel ───────────────────
    tourn_txt = "⛳  2026 MASTERS PICKS  —  AUGUSTA NATIONAL"
    tw = draw.textlength(tourn_txt, font=f_tourn)
    tx = (W - tw) // 2
    ty = 146
    badge_pad = 24
    _rounded_rect(draw,
                  (tx - badge_pad, ty - 7, tx + tw + badge_pad, ty + 42),
                  radius=10, fill=_AUGUSTA_GRN, outline=_GOLD, width=2)
    draw.text((tx, ty), tourn_txt, fill=_WHITE, font=f_tourn)

    # ── Pick rows ─────────────────────────────────────────────────────────────
    y = HDR_H + 12

    for idx, pick in enumerate(display):
        player = str(pick.get("player", "") or "")
        odds   = int(pick.get("odds", 0) or 0)
        book   = str(pick.get("book", "") or "")[:16]
        market = str(pick.get("market", "outright") or "outright").lower()
        blurb  = str(pick.get("blurb", "") or "")
        rank   = idx + 1

        cx0, cx1 = PAD, W - PAD
        cy0, cy1 = y, y + PICK_H

        # Card surface
        if idx == 0:
            _rounded_rect(draw, (cx0, cy0, cx1, cy1), radius=16,
                          fill=_CARD_TOP, outline=_GOLD, width=2)
        else:
            _rounded_rect(draw, (cx0, cy0, cx1, cy1), radius=16, fill=_CARD_BG)

        # Augusta green left accent bar
        bar_w = 10 if idx == 0 else 8
        draw.rectangle([cx0, cy0 + 16, cx0 + bar_w, cy1 - 16], fill=_AUGUSTA_GRN)
        draw.ellipse([cx0, cy0 + 8, cx0 + bar_w * 2, cy0 + 8 + bar_w * 2], fill=_AUGUSTA_GRN)
        draw.ellipse([cx0, cy1 - 8 - bar_w * 2, cx0 + bar_w * 2, cy1 - 8], fill=_AUGUSTA_GRN)

        # Rank badge
        bcx = cx0 + 46
        bcy = cy0 + PICK_H // 2
        rank_color = _GOLD if idx == 0 else _AUGUSTA_GRN
        r = 24
        draw.ellipse([bcx - r, bcy - r, bcx + r, bcy + r], fill=rank_color)
        draw.ellipse([bcx - r + 3, bcy - r + 3, bcx + r - 3, bcy + r - 3], fill=_BLACK)
        draw.ellipse([bcx - r + 5, bcy - r + 5, bcx + r - 5, bcy + r - 5], fill=rank_color)
        rtxt = str(rank)
        rtw = draw.textlength(rtxt, font=f_badge)
        draw.text((bcx - rtw / 2, bcy - f_badge.size / 2 - 1), rtxt, fill=_BLACK, font=f_badge)

        # "BEST BET" label (pick #1 only)
        if idx == 0:
            bb = "⚡ BEST BET"
            bbw = draw.textlength(bb, font=f_meta)
            draw.text((cx1 - bbw - 12, cy0 + 8), bb, fill=_GOLD, font=f_meta)

        IX = cx0 + 90    # text left edge (slightly wider badge clearance)
        RX = cx1 - 24    # right anchor

        # Market tag
        market_display = {
            "outright":  "OUTRIGHT WINNER",
            "top_5":     "TOP 5 FINISH",
            "top_10":    "TOP 10 FINISH",
            "top_20":    "TOP 20 FINISH",
            "make_cut":  "MAKE CUT",
            "h2h":       "H2H MATCHUP",
        }.get(market, market.upper())

        # Player name — vertically centered in upper 2/3 of card
        player_y = cy0 + 22
        pf = f_player
        if draw.textlength(player, font=f_player) > 540:
            pf = _load_font(_FONT_COND, 38)
        draw.text((IX, player_y), player, fill=_WHITE, font=pf)

        # Odds — right-aligned, vertically centered with player name
        if odds:
            sign = "+" if odds > 0 else ""
            odds_str = f"{sign}{odds}"
            ow = draw.textlength(odds_str, font=f_odds)
            draw.text((RX - ow, player_y - 2), odds_str, fill=_GOLD, font=f_odds)

        # Market pill + book on same row
        row2_y = player_y + 68
        mw = int(draw.textlength(market_display, font=f_meta)) + 18
        _rounded_rect(draw, (IX, row2_y, IX + mw, row2_y + 28), radius=5, fill=_GRAY_DK)
        draw.text((IX + 9, row2_y + 5), market_display, fill=_AUGUSTA_GRN, font=f_meta)

        # Book — right side, same row as pill
        if book:
            bw = draw.textlength(book, font=f_meta)
            draw.text((RX - bw, row2_y + 5), book, fill=_GRAY_LT, font=f_meta)

        # Blurb — muted text below pill
        if blurb:
            blurb_y = row2_y + 36
            max_blurb_w = cx1 - IX - PAD
            while draw.textlength(blurb, font=f_blurb) > max_blurb_w and len(blurb) > 20:
                blurb = blurb[:-4] + "..."
            draw.text((IX, blurb_y), blurb, fill=_GRAY_LT, font=f_blurb)

        y += PICK_H + GAP

    # ── Footer ────────────────────────────────────────────────────────────────
    fy = H - FOOT_H + 10
    draw.rectangle([PAD, fy - 6, W - PAD, fy - 4], fill=_GOLD)

    cta = "Follow @ChefTonyBets for free daily picks"
    ctaw = draw.textlength(cta, font=f_footer)
    draw.text(((W - ctaw) // 2, fy + 6), cta, fill=_GOLD, font=f_footer)

    # ── Save ──────────────────────────────────────────────────────────────────
    save_dir = OUTPUT_DIR / "golf_masters" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / "masters_card.png"
    img.save(path, quality=95)
    return path

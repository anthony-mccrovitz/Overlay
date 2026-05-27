#!/usr/bin/env python3
"""
Print ready-to-post social media captions for all sports.

Scans output/picks/*/YYYYMMDD/captions/*.txt (new per-platform format)
and output/picks/*/YYYYMMDD/caption_*.txt (legacy MLB format).

Prints in order: MLB → NBA → Tennis → Soccer → PGA, then any others.

Usage:
    python scripts/gen_caption.py                    # today
    python scripts/gen_caption.py --date 2026-05-19
    python scripts/gen_caption.py --sport mlb
    python scripts/gen_caption.py --sport tennis
    python scripts/gen_caption.py --platform instagram
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

PICKS_ROOT = Path("output/picks")

# Display order for sports (dirs that match these prefixes get sorted first)
SPORT_ORDER = ["baseball_mlb", "basketball_nba", "tennis", "soccer", "golf_pga", "golf"]

# Legacy MLB caption files (old format, still support them)
_LEGACY_CAPTION_FILES = [
    ("nrfi",    "caption_nrfi.txt",    "NRFI / YRFI"),
    ("picks",   "caption_picks.txt",   "MONEYLINE PICKS"),
    ("props",   "caption_props.txt",   "PROPS"),
    ("totals",  "caption_totals.txt",  "TOTALS"),
    ("runline", "caption_runline.txt", "RUN LINE"),
]

# Platform display labels
PLATFORM_LABELS = {
    "instagram":     "Instagram",
    "twitter":       "X / Twitter",
    "x_twitter":     "X / Twitter",
    "reddit":        "Reddit",
    "tiktok_script": "TikTok Script",
    "tiktok":        "TikTok Script",
}

# Platform display order
PLATFORM_ORDER = ["instagram", "x_twitter", "twitter", "reddit", "tiktok_script", "tiktok"]


def _sport_sort_key(sport_dir: str) -> int:
    for i, prefix in enumerate(SPORT_ORDER):
        if sport_dir.startswith(prefix):
            return i
    return len(SPORT_ORDER)


def find_all_sport_dirs(date_str: str) -> list[Path]:
    """Return all output/picks/<sport>/<YYYYMMDD> dirs that exist for the date."""
    if not PICKS_ROOT.exists():
        return []
    dirs = []
    for sport_dir in PICKS_ROOT.iterdir():
        if not sport_dir.is_dir():
            continue
        date_dir = sport_dir / date_str
        if date_dir.exists() and date_dir.is_dir():
            dirs.append(date_dir)
    # Sort by canonical sport order
    return sorted(dirs, key=lambda p: _sport_sort_key(p.parent.name))


def find_best_date_dir(sport_dir: Path, target_date: date) -> Path | None:
    """Return the date subdir for target_date, or the most recent one."""
    date_str = target_date.strftime("%Y%m%d")
    p = sport_dir / date_str
    if p.exists():
        return p
    available = sorted(
        [d for d in sport_dir.iterdir() if d.is_dir() and d.name.isdigit()],
        reverse=True,
    )
    return available[0] if available else None


def collect_new_format_captions(date_dir: Path) -> dict[str, str]:
    """Read captions/{platform}.txt files from date_dir/captions/."""
    cap_dir = date_dir / "captions"
    if not cap_dir.exists():
        return {}
    result = {}
    for txt in sorted(cap_dir.glob("*.txt")):
        platform = txt.stem
        content  = txt.read_text(encoding="utf-8").strip()
        if content:
            result[platform] = content
    return result


def collect_legacy_captions(date_dir: Path) -> dict[str, str]:
    """Read old caption_*.txt files from MLB legacy format."""
    result = {}
    for key, filename, label in _LEGACY_CAPTION_FILES:
        path = date_dir / filename
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                result[key] = content
    return result


def _sport_label(date_dir: Path) -> str:
    sport_slug = date_dir.parent.name
    LABELS = {
        "baseball_mlb":   "MLB",
        "basketball_nba": "NBA",
        "tennis_atp_french_open":    "Tennis — Roland-Garros (ATP)",
        "tennis_wta_french_open":    "Tennis — Roland-Garros (WTA)",
        "tennis_atp_wimbledon":      "Tennis — Wimbledon (ATP)",
        "tennis_wta_wimbledon":      "Tennis — Wimbledon (WTA)",
        "tennis_atp_us_open":        "Tennis — US Open (ATP)",
        "tennis_wta_us_open":        "Tennis — US Open (WTA)",
        "tennis_atp_australian_open": "Tennis — Australian Open (ATP)",
        "tennis_wta_australian_open": "Tennis — Australian Open (WTA)",
        "soccer":                    "Soccer (All Leagues)",
        "soccer_epl":                "Soccer — EPL",
        "soccer_spain_la_liga":      "Soccer — La Liga",
        "soccer_italy_serie_a":      "Soccer — Serie A",
        "soccer_germany_bundesliga": "Soccer — Bundesliga",
        "soccer_france_ligue_1":     "Soccer — Ligue 1",
        "golf_pga":                  "PGA Tour",
        "golf_pga_championship":     "PGA Championship",
    }
    if sport_slug in LABELS:
        return LABELS[sport_slug]
    if sport_slug.startswith("tennis"):
        return "Tennis — " + sport_slug.replace("tennis_", "").replace("_", " ").title()
    if sport_slug.startswith("soccer"):
        return "Soccer — " + sport_slug.replace("soccer_", "").replace("_", " ").title()
    if sport_slug.startswith("golf"):
        return "Golf — " + sport_slug.replace("golf_", "").replace("_", " ").title()
    return sport_slug.replace("_", " ").title()


def main() -> None:
    parser = argparse.ArgumentParser(description="Print ready-to-post captions for all sports")
    parser.add_argument("--date",     type=str, default=None,
                        help="Date YYYY-MM-DD or YYYYMMDD (default: today)")
    parser.add_argument("--sport",    type=str, default=None,
                        choices=["mlb", "nba", "tennis", "soccer", "pga", "golf"],
                        help="Filter to a single sport")
    parser.add_argument("--platform", type=str, default=None,
                        help="Filter to a single platform (instagram, x_twitter, reddit, tiktok_script)")
    args = parser.parse_args()

    if args.date:
        raw = args.date.replace("-", "")
        target_date = date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
    else:
        target_date = date.today()

    date_str = target_date.strftime("%Y%m%d")
    sport_filter = args.sport
    platform_filter = args.platform

    W = 72
    print(f"\n{'═'*W}")
    print(f"  CAPTIONS — {target_date.strftime('%B %d, %Y').upper()}")
    print(f"{'═'*W}")

    date_dirs = find_all_sport_dirs(date_str)

    # Apply sport filter
    if sport_filter:
        _filter_map = {
            "mlb":    "baseball_mlb",
            "nba":    "basketball_nba",
            "tennis": "tennis",
            "soccer": "soccer",
            "pga":    "golf",
            "golf":   "golf",
        }
        prefix = _filter_map.get(sport_filter, sport_filter)
        date_dirs = [d for d in date_dirs if d.parent.name.startswith(prefix)]

    if not date_dirs:
        print(f"\n  No picks found for {date_str}.")
        if sport_filter:
            print(f"  (filtered to: {sport_filter})")
        print(f"  Run chef.py picks <sport> first.")
        print(f"\n{'═'*W}\n")
        return

    shown_any = False
    for date_dir in date_dirs:
        label     = _sport_label(date_dir)
        new_caps  = collect_new_format_captions(date_dir)
        old_caps  = collect_legacy_captions(date_dir)

        if not new_caps and not old_caps:
            continue

        print(f"\n{'─'*W}")
        print(f"  {label}")
        print(f"  Source: {date_dir}")
        print(f"{'─'*W}")

        # New format: output in platform order
        if new_caps:
            ordered_keys = [k for k in PLATFORM_ORDER if k in new_caps]
            remaining    = [k for k in new_caps if k not in PLATFORM_ORDER]
            for key in ordered_keys + remaining:
                if platform_filter and key not in (platform_filter, platform_filter.replace("-", "_")):
                    continue
                plabel  = PLATFORM_LABELS.get(key, key.replace("_", " ").title())
                content = new_caps[key]
                print(f"\n  ── {plabel} {'─' * max(0, W - len(plabel) - 5)}")
                print()
                for line in content.splitlines():
                    print(f"  {line}")
                shown_any = True

        # Legacy format
        if old_caps:
            for key, content in old_caps.items():
                if platform_filter:
                    continue  # legacy files aren't platform-specific
                for _, filename, cap_label in _LEGACY_CAPTION_FILES:
                    if filename.replace(".txt", "").replace("caption_", "") == key:
                        print(f"\n  ── {cap_label} {'─' * max(0, W - len(cap_label) - 5)}")
                        break
                else:
                    print(f"\n  ── {key.upper()} {'─' * max(0, W - len(key) - 5)}")
                print()
                for line in content.splitlines():
                    print(f"  {line}")
                shown_any = True

    if not shown_any:
        print(f"\n  No captions found. Run chef.py picks <sport> to generate them.")

    print(f"\n{'═'*W}\n")


if __name__ == "__main__":
    main()

"""Hourly rotating backup of data/pnl/picks.json.

Keeps the last 48 hourly snapshots under data/pnl/backups/.
Refuses to write if the source file has shrunk by >25% vs the most recent
backup — that's a smoke signal of accidental overwrite and the backup
should NOT replace good data with bad.

Run via cron: 0 * * * * python3 scripts/backup_picks.py
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "pnl" / "picks.json"
BACKUP_DIR = ROOT / "data" / "pnl" / "backups"
KEEP = 48  # 48 hourly = 2 days

def count_picks(path: Path) -> int:
    try:
        d = json.loads(path.read_text())
        return len(d.get("picks", d) if isinstance(d, (dict, list)) else [])
    except Exception:
        return -1

def main() -> int:
    if not SRC.exists():
        print(f"[backup] source missing: {SRC}", file=sys.stderr)
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    n_now = count_picks(SRC)
    if n_now < 0:
        print(f"[backup] source is unreadable JSON — NOT backing up", file=sys.stderr)
        return 1

    existing = sorted(BACKUP_DIR.glob("picks_*.json"))
    if existing:
        latest = existing[-1]
        n_prev = count_picks(latest)
        if n_prev > 100 and n_now < n_prev * 0.75:
            print(
                f"[backup] REFUSING: source has {n_now} picks, last backup had "
                f"{n_prev} ({n_now/n_prev:.0%}). Probable accidental overwrite. "
                f"Keep good backup intact.",
                file=sys.stderr,
            )
            return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    dst = BACKUP_DIR / f"picks_{ts}.json"
    shutil.copy2(SRC, dst)
    print(f"[backup] {n_now} picks → {dst.name}")

    # Rotate — keep only the last KEEP
    existing = sorted(BACKUP_DIR.glob("picks_*.json"))
    for old in existing[:-KEEP]:
        old.unlink()
    print(f"[backup] keeping {min(len(existing), KEEP)} snapshots")
    return 0

if __name__ == "__main__":
    sys.exit(main())

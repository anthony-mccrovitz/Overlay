"""World golf rankings from the OWGR public API — the live rating source.

WHY THIS EXISTS. The model's live skill feed was statdata.pgatour.com, and that
host no longer resolves at all. The fetch failed silently (returns {}), the
54-player static DB quietly took over, and nothing said so — the repo's
signature failure, in golf. Weekly fields run 147 players; 54 static ratings
cover ~20 of them.

OWGR covers every ranked professional (we pull the top 300, which blankets any
PGA Tour field's rated population), updates weekly, and needs no key. Average
ranking points are not strokes-gained, but they are strongly related: fitted on
the 51 players present in BOTH the static SG database and the OWGR list,

    skill = 0.588 * ln(avg_points) + 0.710      r² = 0.524

Half the variance, conservative at the elite end (Scheffler fits +2.35 against
a true +3.45) — an honest floor, used only where real SG data is absent.
Refit by running this module directly whenever the static DB changes.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

_URL = "https://apiweb.owgr.com/api/owgr/rankings/getRankings"
_CACHE = Path("data/cache/golf/owgr_rankings.json")
_TTL_S = 3 * 86400          # OWGR updates Mondays; 3 days keeps a week fresh
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# The fitted OWGR→SG mapping. Provenance above; a test pins these so a quiet
# "tune" without a refit fails the build.
OWGR_SKILL_COEF = 0.588
OWGR_SKILL_INTERCEPT = 0.710


def fetch_rankings(pages: int = 3, allow_network: bool = True) -> dict[str, float]:
    """{player full name: average ranking points} for the world top pages*100."""
    if _CACHE.exists() and time.time() - _CACHE.stat().st_mtime < _TTL_S:
        try:
            return json.loads(_CACHE.read_text())
        except (OSError, ValueError):
            pass
    if not allow_network:
        try:
            return json.loads(_CACHE.read_text())
        except (OSError, ValueError):
            return {}
    out: dict[str, float] = {}
    try:
        import requests
        for page in range(1, pages + 1):
            r = requests.get(_URL, params={"pageSize": 100, "pageNumber": page},
                             headers={"User-Agent": _UA}, timeout=20)
            r.raise_for_status()
            for row in r.json().get("rankingsList", []):
                name = ((row.get("player") or {}).get("fullName") or "").strip()
                pts = row.get("pointsAverage")
                if name and pts is not None and float(pts) > 0:
                    out[name] = float(pts)
    except Exception:
        try:
            return json.loads(_CACHE.read_text())
        except (OSError, ValueError):
            return {}
    if out:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(out))
    return out


def skill_from_points(avg_points: float) -> float:
    """OWGR average points → expected strokes-gained/round vs field."""
    if avg_points <= 0:
        return 0.0
    return OWGR_SKILL_COEF * math.log(avg_points) + OWGR_SKILL_INTERCEPT


if __name__ == "__main__":
    # Refit the mapping against the static SG database and print it.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import unicodedata

    import numpy as np

    from src.models.pga_championship import PLAYER_DB

    def _n(s):
        s = unicodedata.normalize("NFKD", str(s))
        s = "".join(c for c in s if not unicodedata.combining(c))
        return " ".join(s.lower().replace("'", "").replace(".", "").split())

    owgr = {_n(k): v for k, v in fetch_rankings().items()}
    X, Y = [], []
    for name, p in PLAYER_DB.items():
        a = owgr.get(_n(name))
        if a and "sg_total" in p:
            X.append(math.log(a))
            Y.append(p["sg_total"])
    X, Y = np.array(X), np.array(Y)
    A = np.vstack([X, np.ones_like(X)]).T
    (coef, intc), *_ = np.linalg.lstsq(A, Y, rcond=None)
    pred = coef * X + intc
    r2 = 1 - ((Y - pred) ** 2).sum() / ((Y - Y.mean()) ** 2).sum()
    print(f"skill = {coef:.4f} * ln(avg_pts) + {intc:.4f}   r2={r2:.3f}  n={len(X)}")
    print(f"currently shipped: {OWGR_SKILL_COEF} / {OWGR_SKILL_INTERCEPT}")

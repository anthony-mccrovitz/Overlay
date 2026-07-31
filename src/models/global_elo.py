"""Ratings over a fighter's WHOLE career, not just the UFC part.

WHY. The UFC-only Elo could not see two thirds of any fighter's record, and for
a debutant it could not see them at all. A UFC fighter averages ~6 UFC bouts
against ~20 professional bouts. Rating people on the visible third and calling
the rest "no data" was throwing away most of the evidence.

THE PROBLEM THIS CREATES. A win is not a win. Beating a regional opponent in
Oktagon says less about UFC-level ability than beating a UFC opponent, and a
fighter who is 16-3 against regional opposition is not a 16-3 UFC fighter. Elo
partly handles this on its own — you gain little for beating a low-rated
opponent — but only if the rating pools are connected, and they connect solely
through fighters who cross between them.

So we do NOT invent a promotion multiplier. We compute a plain global Elo and
expose the promotion MIX as its own feature (`top_share`), then let
walk-forward validation decide how much to discount. A fitted discount that
fails to improve held-out log-loss does not ship — same rule as the debut model.

DEDUPLICATION. Every bout appears twice, once on each fighter's page. Keyed on
(both slugs, date) so a bout counts once. Getting this wrong would double every
rating update and silently inflate the spread.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

_CACHE = Path("data/ufc/sherdog")

# Promotions where the opposition is roughly UFC-calibre. Used ONLY to build the
# `top_share` feature — never to weight a rating update directly, because that
# would bake in a judgement the data should be making.
TOP_TIER = {"UFC", "Bellator", "PFL", "ONE", "Strikeforce", "Pride", "WEC",
            "RIZIN", "DREAM", "EliteXC", "Invicta", "KSW"}

ELO_START = 1500.0
K_DECISION = 64.0
K_FINISH = 80.0


@dataclass
class GlobalState:
    elo: float = ELO_START
    n: int = 0
    top_n: int = 0                      # bouts in a top-tier promotion
    results: list[int] = field(default_factory=list)
    last: date | None = None


def load_global_bouts() -> list[dict]:
    """Every cached bout, deduplicated, oldest first.

    A bout is identified by its two fighters and its date. The same fight is
    written from both sides with opposite results, so we keep the row from the
    winner's page and drop the mirror.
    """
    seen: set[tuple] = set()
    out: list[dict] = []
    if not _CACHE.exists():
        return out
    for p in _CACHE.glob("*.json"):
        if p.name.startswith("."):
            continue
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        me = d.get("slug", "")
        for b in d.get("bouts", []):
            opp = b.get("opponent_slug") or ""
            when = b.get("when")
            res = b.get("result")
            if not opp or not when or res not in ("win", "loss"):
                continue          # draws and no-contests carry no ordering signal
            key = (tuple(sorted((me, opp))), when)
            if key in seen:
                continue
            seen.add(key)
            w, l = (me, opp) if res == "win" else (opp, me)
            out.append({"date": date.fromisoformat(when), "w": w, "l": l,
                        "promotion": b.get("promotion", "unknown"),
                        "method": b.get("method", "")})
    out.sort(key=lambda x: x["date"])
    return out


class GlobalLedger:
    """Point-in-time career ratings. Same read/write contract as the UFC ledger:
    `features_for` reads, `apply_bout` writes, and a caller must never invert
    them for the same fight."""

    def __init__(self) -> None:
        self.book: dict[str, GlobalState] = {}
        self.through: date | None = None

    def state(self, slug: str) -> GlobalState:
        return self.book.setdefault(slug, GlobalState())

    def known(self, slug: str) -> bool:
        s = self.book.get(slug)
        return s is not None and s.n > 0

    def features_for(self, slug: str, on: date) -> dict[str, float | None]:
        s = self.state(slug)
        if s.n == 0:
            return {"gelo": None, "pro_exp": None, "top_share": None,
                    "pro_form": None, "pro_layoff": None}
        return {
            "gelo": s.elo,
            "pro_exp": float(min(s.n, 40)),
            "top_share": s.top_n / s.n,
            "pro_form": sum(s.results[-5:]) / len(s.results[-5:]),
            "pro_layoff": (min((on - s.last).days, 900) / 365.25) if s.last else None,
        }

    def apply_bout(self, b: dict) -> None:
        w, l = b["w"], b["l"]
        sw, sl_ = self.state(w), self.state(l)
        exp_w = 1.0 / (1.0 + 10.0 ** ((sl_.elo - sw.elo) / 400.0))
        m = str(b.get("method", "")).lower()
        k = K_FINISH if ("ko" in m or "sub" in m) else K_DECISION
        sw.elo += k * (1.0 - exp_w)
        sl_.elo -= k * (1.0 - exp_w)
        top = b.get("promotion") in TOP_TIER
        for s, res in ((sw, 1), (sl_, 0)):
            s.n += 1
            if top:
                s.top_n += 1
            s.results.append(res)
            s.last = b["date"]
        if self.through is None or b["date"] > self.through:
            self.through = b["date"]


def build_global_ledger(through: date | None = None) -> GlobalLedger:
    led = GlobalLedger()
    for b in load_global_bouts():
        if through is not None and b["date"] > through:
            break
        led.apply_bout(b)
    return led


def name_to_slug() -> dict[tuple[str, str | None], str]:
    """Join key from the ufcstats world into the Sherdog graph.

    Keyed on (normalised name, ISO date of birth) and built ONLY from keys that
    map to exactly one slug — the same refusal rule as `sherdog.resolve`, for
    the same reason. Costs no requests: both sides are already on disk.
    """
    from src.models.ufc_features import normalize_name

    buckets: dict[tuple[str, str | None], list[str]] = {}
    if not _CACHE.exists():
        return {}
    for p in _CACHE.glob("*.json"):
        if p.name.startswith("."):
            continue
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        key = (normalize_name(d.get("name", "")), d.get("dob"))
        buckets.setdefault(key, []).append(d["slug"])
    return {k: v[0] for k, v in buckets.items() if len(v) == 1}


def roster_coverage(ufc_names: set[str], tott: dict) -> float:
    """Share of the ufcstats roster resolvable into the global graph.

    The gate on whether global features may be used at all. At 3% coverage a
    walk-forward comparison measures missing data, not the features, and would
    report whatever the imputation happens to do.
    """
    from src.models.ufc_features import normalize_name

    m = name_to_slug()
    tt = {normalize_name(k): v for k, v in tott.items()}
    if not ufc_names:
        return 0.0
    hit = 0
    for n in ufc_names:
        nn = normalize_name(n)
        dob = (tt.get(nn) or {}).get("dob")
        if (nn, dob.isoformat() if dob else None) in m:
            hit += 1
    return hit / len(ufc_names)


# Below this, global features are not offered to the model at all. Chosen so the
# comparison is about the features rather than about how many rows got imputed;
# it is a judgement, and it is printed alongside every result so it can be argued
# with rather than assumed.
MIN_ROSTER_COVERAGE = 0.55


def coverage() -> dict:
    """How much of the graph we actually hold. Reported next to any number that
    depends on it, because a thin crawl and a rich one produce very different
    ratings and only one of them deserves confidence."""
    bouts = load_global_bouts()
    fighters = {x for b in bouts for x in (b["w"], b["l"])}
    promos: dict[str, int] = {}
    for b in bouts:
        promos[b["promotion"]] = promos.get(b["promotion"], 0) + 1
    top = sum(c for p, c in promos.items() if p in TOP_TIER)
    return {"bouts": len(bouts), "fighters": len(fighters),
            "promotions": len(promos), "top_tier_bouts": top,
            "first": bouts[0]["date"].isoformat() if bouts else None,
            "last": bouts[-1]["date"].isoformat() if bouts else None}

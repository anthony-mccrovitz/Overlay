"""Full professional MMA records from Sherdog — every promotion, not just the UFC.

WHY. Our fight history came from ufcstats, which records UFC bouts only. A
fighter making their UFC debut therefore had no record at all, and three of the
ten fights on the 2026-08-01 card came back unreadable. They are not unknown
fighters:

    Vlasto Cepo        16-3  (19 bouts)  Oktagon MMA
    Alexander Poppeck  22-7  (30 bouts)  Oktagon MMA
    Jovan Leka         13-2  (15 bouts)  Brave CF / Contender Series / ARMMADA

Sherdog carries all of it. robots.txt is `Allow: /` for every agent with no
crawl-delay; we use 2s between requests anyway and cache permanently, because
being permitted to hammer someone's server is not a reason to.

THE HARD PART IS IDENTITY, NOT FETCHING. Searching "Michael Oliveira" returns
four fighters, and the first hit is a 0-2 regional fighter who is plainly not
the man on a UFC card. ufcstats alone contains eight duplicate names (two Mike
Davises, two Michael McDonalds). So `resolve()` matches on name AND date of
birth, and returns None when it cannot be sure. A wrong match here would produce
a confident number attached to the wrong person — the exact failure this repo
keeps paying for.

Once resolved, the fight graph keys on Sherdog SLUGS, never on names: every
opponent on a fighter's page is linked by slug, so the graph is built from
stable IDs and the name problem exists only at the entry point.

Cache:  data/ufc/sherdog/<slug>.json   (parsed, not raw HTML)
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

_BASE = "https://www.sherdog.com"
_CACHE = Path("data/ufc/sherdog")
_STAMP = _CACHE / ".last_request"

# 2 seconds between requests. robots.txt sets no crawl-delay; this is politeness,
# and it is enforced across processes via a timestamp file so a parallel run
# cannot multiply the rate.
_MIN_INTERVAL = 2.0

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_RESULT_RE = re.compile(r'<span class="final_result ([a-z]+)">')
_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"


class SherdogError(RuntimeError):
    pass


@dataclass(frozen=True)
class Bout:
    result: str          # win | loss | draw | nc
    opponent: str        # display name
    opponent_slug: str   # stable ID — the graph is built on this
    event: str
    promotion: str
    when: date | None
    method: str
    rnd: int | None

    @property
    def is_finish(self) -> bool:
        m = self.method.lower()
        return "ko" in m or "tko" in m or "submission" in m


@dataclass
class Fighter:
    slug: str
    name: str
    dob: date | None = None
    height_in: float | None = None
    nationality: str = ""
    association: str = ""
    bouts: list[Bout] = field(default_factory=list)

    @property
    def record(self) -> tuple[int, int, int]:
        w = sum(1 for b in self.bouts if b.result == "win")
        l = sum(1 for b in self.bouts if b.result == "loss")
        d = len(self.bouts) - w - l
        return w, l, d


# ── polite fetching ──────────────────────────────────────────────────────────
def _throttle() -> None:
    """Sleep so consecutive requests are at least _MIN_INTERVAL apart.

    The timestamp lives on disk rather than in memory so two processes (a card
    read and a backfill, say) cannot each think they are the only caller.
    """
    _CACHE.mkdir(parents=True, exist_ok=True)
    try:
        last = float(_STAMP.read_text().strip())
    except (OSError, ValueError):
        last = 0.0
    wait = _MIN_INTERVAL - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    _STAMP.write_text(str(time.time()))


def _get(path: str, params: dict | None = None) -> str:
    import requests
    _throttle()
    r = requests.get(f"{_BASE}{path}", params=params or {},
                     headers={"User-Agent": _UA}, timeout=30)
    r.raise_for_status()
    return r.text


# ── parsing ──────────────────────────────────────────────────────────────────
def _strip(s: str) -> str:
    import html as _html
    return _html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def _parse_date(s: str) -> date | None:
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in ("%b / %d / %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _promotion(event: str) -> str:
    """Everything before the first ' - ' is the promotion in Sherdog's naming.

    'UFC 323 - Dvalishvili vs. Yan 2' -> 'UFC 323'; normalised further so that
    'UFC 323', 'UFC Fight Night 255' and 'UFC on ESPN 36' all collapse to 'UFC'.
    Promotion strength is a fitted parameter later, and it can only be fitted if
    the label is stable.
    """
    head = event.split(" - ", 1)[0].strip()
    for prefix in ("UFC", "Bellator", "PFL", "ONE", "KSW", "Oktagon", "Brave",
                   "Cage Warriors", "LFA", "RIZIN", "M-1", "Invicta", "ACA", "ACB",
                   "Strikeforce", "WEC", "Pride", "DREAM", "Shooto", "EliteXC",
                   "Contender Series", "Road to UFC", "ARMMADA", "FNC", "CFFC"):
        if head.upper().startswith(prefix.upper()):
            return prefix
    # Strip the card number so "ROC 9" and "ROC 18" are one promotion. Without
    # this every event becomes its own promotion and the strength adjustment
    # has a single observation per level, which is no adjustment at all.
    head = re.sub(r"\s+\d+[A-Za-z]?$", "", head).strip()
    return head or "unknown"


def parse_fighter(html_text: str, slug: str) -> Fighter:
    """Turn a fighter page into a Fighter. Never raises on missing fields —
    a fighter with no date of birth is a fighter we know less about, not an
    error, and `resolve` is where that shortfall becomes a refusal."""
    name_m = re.search(r'<span class="fn">([^<]+)</span>', html_text)
    if not name_m:
        name_m = re.search(r"<title>([^<|]+)", html_text)
    dob_m = re.search(r'itemprop="birthDate">([^<]+)<', html_text)
    ht_m = re.search(r"(\d)'(\d+)\"", html_text)
    nat_m = re.search(r'itemprop="nationality">([^<]+)<', html_text)
    assoc_m = re.search(r'class="association"[^>]*>(.*?)</', html_text, re.S)

    bouts: list[Bout] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S):
        res = _RESULT_RE.search(row)
        if not res:
            continue
        opp = re.search(r'href="/fighter/([^"]+)"[^>]*>([^<]+)<', row)
        # Event name appears two ways on the same site: wrapped in an
        # itemprop="award" span, or as bare anchor text. Matching only the first
        # silently blanked 36% of bouts — including every ARMMADA and HFL card,
        # which is exactly the regional history this whole exercise is for.
        ev = re.search(r'href="/events/[^"]*"[^>]*>(.*?)</a>', row, re.S)
        when = re.search(rf'class="sub_line">\s*((?:{_MONTHS})[^<]*)<', row)
        meth = re.search(r'class="winby"><b>([^<]+)</b>', row)
        # Round and time are the last two cells. Indexing from the front breaks
        # whenever the method cell gains a play-by-play link.
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        rnd = None
        for c in reversed(cells):
            digits = _strip(c)
            if digits.isdigit():
                rnd = int(digits)
                break
        event = _strip(ev.group(1)) if ev else ""
        bouts.append(Bout(
            result=res.group(1).lower(),
            opponent=_strip(opp.group(2)) if opp else "",
            opponent_slug=opp.group(1) if opp else "",
            event=event,
            promotion=_promotion(event),
            when=_parse_date(when.group(1)) if when else None,
            method=_strip(meth.group(1)) if meth else "",
            rnd=rnd,
        ))
    bouts.sort(key=lambda b: (b.when or date(1900, 1, 1)))
    return Fighter(
        slug=slug,
        name=_strip(name_m.group(1)) if name_m else slug.rsplit("-", 1)[0].replace("-", " "),
        dob=_parse_date(dob_m.group(1)) if dob_m else None,
        height_in=(float(ht_m.group(1)) * 12 + float(ht_m.group(2))) if ht_m else None,
        nationality=_strip(nat_m.group(1)) if nat_m else "",
        association=_strip(assoc_m.group(1))[:60] if assoc_m else "",
        bouts=bouts,
    )


# ── cache ────────────────────────────────────────────────────────────────────
def _cache_path(slug: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", slug)
    return _CACHE / f"{safe}.json"


def _to_json(f: Fighter) -> dict:
    return {"slug": f.slug, "name": f.name,
            "dob": f.dob.isoformat() if f.dob else None,
            "height_in": f.height_in, "nationality": f.nationality,
            "association": f.association,
            "bouts": [{"result": b.result, "opponent": b.opponent,
                       "opponent_slug": b.opponent_slug, "event": b.event,
                       "promotion": b.promotion,
                       "when": b.when.isoformat() if b.when else None,
                       "method": b.method, "rnd": b.rnd} for b in f.bouts]}


def _from_json(d: dict) -> Fighter:
    return Fighter(
        slug=d["slug"], name=d["name"],
        dob=date.fromisoformat(d["dob"]) if d.get("dob") else None,
        height_in=d.get("height_in"), nationality=d.get("nationality", ""),
        association=d.get("association", ""),
        bouts=[Bout(result=b["result"], opponent=b["opponent"],
                    opponent_slug=b["opponent_slug"], event=b["event"],
                    promotion=b.get("promotion", "unknown"),
                    when=date.fromisoformat(b["when"]) if b.get("when") else None,
                    method=b.get("method", ""), rnd=b.get("rnd"))
               for b in d.get("bouts", [])])


def load_cached(slug: str) -> Fighter | None:
    try:
        return _from_json(json.loads(_cache_path(slug).read_text()))
    except (OSError, ValueError, KeyError):
        return None


def fetch_fighter(slug: str, *, refresh: bool = False) -> Fighter | None:
    """Fighter by slug, from cache unless `refresh`. None on failure.

    Cached permanently: a fight that happened does not change. Re-fetch only
    when a fighter appears on a new card, which is what `refresh` is for.
    """
    if not refresh:
        cached = load_cached(slug)
        if cached is not None:
            return cached
    try:
        html_text = _get(f"/fighter/{slug}")
    except Exception:
        return None
    f = parse_fighter(html_text, slug)
    _CACHE.mkdir(parents=True, exist_ok=True)
    _cache_path(slug).write_text(json.dumps(_to_json(f), indent=1, sort_keys=True))
    return f


# ── identity resolution ──────────────────────────────────────────────────────
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    for ch in ("'", "’", "ʼ", "`", ".", "-"):
        s = s.replace(ch, "")
    return " ".join(s.lower().split())


def search(name: str) -> list[tuple[str, str]]:
    """(slug, display name) candidates for a name. Sherdog's fightfinder always
    appends a few unrelated 'featured' fighters, so callers must match rather
    than take the first row."""
    try:
        html_text = _get("/stats/fightfinder",
                         {"SearchTxt": name, "association": ""})
    except Exception:
        return []
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for slug, disp in re.findall(r'href="/fighter/([^"]+)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,50})',
                                 html_text):
        if slug in seen:
            continue
        seen.add(slug)
        out.append((slug, _strip(disp)))
    return out


def resolve(name: str, *, dob: date | None = None,
            min_bouts: int = 1) -> Fighter | None:
    """Find the fighter, or return None. Never guesses.

    Rules, in order:
      1. Candidates must match on normalised name. Sherdog pads results with
         unrelated fighters, so a positional match is not a match.
      2. If a date of birth is supplied, it must agree within a day. This is the
         check that separates the four Michael Oliveiras.
      3. If more than one candidate survives, return None. An ambiguous identity
         is a refusal, not a coin flip — picking wrong attaches a confident
         number to the wrong person.
    """
    target = _norm(name)
    hits = search(name)
    cands = [(s, d) for s, d in hits if _norm(d) == target]

    resolved: list[Fighter] = []
    for slug, _disp in cands[:6]:
        f = fetch_fighter(slug)
        if f is None or len(f.bouts) < min_bouts:
            continue
        if dob is not None:
            if f.dob is None or abs((f.dob - dob).days) > 1:
                continue
        resolved.append(f)

    if len(resolved) == 1:
        return resolved[0]
    if len(resolved) > 1 and dob is not None:
        exact = [f for f in resolved if f.dob == dob]
        if len(exact) == 1:
            return exact[0]
    if resolved:
        return None        # several plausible people — refuse

    # Tier 2: the name we hold differs from the name Sherdog files them under.
    # Real and common — the odds feed says "Vlasto Cepo", Sherdog says
    # "Vlastislav Cepo". Only attempted when we have a DATE OF BIRTH, which is
    # a far stronger key than a nickname-vs-legal-name string, and only accepted
    # when exactly one candidate matches it exactly AND shares a surname. Both
    # conditions together, because either alone would eventually pair the wrong
    # people.
    if dob is None:
        return None
    surname = target.split()[-1] if target.split() else ""
    if len(surname) < 3:
        return None
    matched: list[Fighter] = []
    for slug, disp in hits[:8]:
        if surname not in _norm(disp).split():
            continue
        f = fetch_fighter(slug)
        if f is None or len(f.bouts) < min_bouts or f.dob != dob:
            continue
        matched.append(f)
    return matched[0] if len(matched) == 1 else None

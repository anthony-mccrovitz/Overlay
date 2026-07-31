"""Read a whole fight card: every bout, the model's call, and how sure it is.

WHY A CARD VIEW. The pick pipeline only ever surfaced fights it wanted to BET,
which meant a 12-fight card produced two lines and the other ten silently
vanished. Those ten are most of what anyone actually wants to know. This prints
every bout on the card, including the ones with no bettable edge and the ones
the model cannot read at all — because "we have no idea" is information, and
dropping the row is how it stops being information.

A card is grouped by start time. One calendar date routinely carries several
promotions (2026-08-01 has UFC at 22:00Z, Oktagon at 14:00Z, and two more), and
mixing them into one list was already a documented source of confusion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from src.models.ufc_features import Read, UFCFightModel, build_ledger


@dataclass(frozen=True)
class Bout:
    fighter_a: str
    fighter_b: str
    starts: datetime
    read: Read
    market_p_a: float | None = None      # devigged market probability for A
    book: str = ""
    # Full professional records, shown for fighters the UFC-only model cannot
    # read. This is a FACT about the fighter, not a model output, so it is not
    # subject to the global-Elo coverage gate — that gate exists to stop a
    # thinly-populated rating graph from being fitted into a probability, and
    # "22-7 in Oktagon" is neither fitted nor a probability.
    pro_record_a: str = ""
    pro_record_b: str = ""
    pro_note: str = ""

    @property
    def disagrees_with_market(self) -> bool:
        """Model and market on opposite sides of the fight."""
        if self.market_p_a is None:
            return False
        return (self.read.p_a >= 0.5) != (self.market_p_a >= 0.5)


def _devig_pair(odds_a: float, odds_b: float) -> tuple[float, float] | None:
    """Two-way multiplicative devig. Returns (p_a, p_b) summing to 1."""
    def imp(o: float) -> float:
        return (-o / (-o + 100.0)) if o < 0 else (100.0 / (o + 100.0))
    try:
        ia, ib = imp(float(odds_a)), imp(float(odds_b))
    except (TypeError, ValueError):
        return None
    tot = ia + ib
    if tot <= 0:
        return None
    return ia / tot, ib / tot


def _market_prob(event: dict) -> tuple[float | None, str]:
    """Consensus devigged probability for the HOME/first-listed fighter.

    Median across books in PROBABILITY space, never in American odds: +101 and
    −101 are adjacent prices but 202 apart numerically, so a median of the raw
    numbers is meaningless. Same rule as the CLV benchmark.
    """
    home = event.get("home_team")
    probs: list[float] = []
    books: list[str] = []
    for bm in event.get("bookmakers", []) or []:
        for mkt in bm.get("markets", []) or []:
            if mkt.get("key") != "h2h":
                continue
            outs = mkt.get("outcomes", []) or []
            if len(outs) != 2:
                continue
            a = next((o for o in outs if o.get("name") == home), None)
            b = next((o for o in outs if o.get("name") != home), None)
            if not a or not b:
                continue
            pair = _devig_pair(a.get("price"), b.get("price"))
            if pair:
                probs.append(pair[0])
                books.append(bm.get("title", ""))
    if not probs:
        return None, ""
    probs.sort()
    mid = probs[len(probs) // 2] if len(probs) % 2 else \
        (probs[len(probs) // 2 - 1] + probs[len(probs) // 2]) / 2
    return mid, f"{len(books)} books"


def read_card(events: list[dict], on: date | None = None,
              pro_records: bool = True) -> list[Bout]:
    """Price every event given. `events` is Odds API shape (h2h markets).

    The ledger is replayed once for the whole card, not per fight — rebuilding
    ~8,500 bouts of history eleven times is pure waste, and doing it once also
    guarantees every fight on the card is read against identical state.
    """
    model = UFCFightModel()
    led, _ = build_ledger()
    out: list[Bout] = []
    for ev in events:
        a = (ev.get("home_team") or "").strip()
        b = (ev.get("away_team") or "").strip()
        if not a or not b:
            continue
        try:
            starts = datetime.fromisoformat(
                str(ev.get("commence_time", "")).replace("Z", "+00:00"))
        except ValueError:
            starts = datetime.now(timezone.utc)
        fight_day = on or starts.date()
        read = model.predict(led, a, b, fight_day)
        mp, book = _market_prob(ev)

        # Only look up records for fighters the UFC data cannot see. A handful
        # of requests per card, cached permanently — and it turns "no read" into
        # something a human can actually use.
        ra = rb = ""
        note = ""
        if read.basis != "model" and pro_records:
            if not led.known(a):
                ra = _pro_record(a, led)
            if not led.known(b):
                rb = _pro_record(b, led)
            if ra or rb:
                note = ("Full professional record, all promotions. Not run "
                        "through the model — regional opposition is weaker than "
                        "UFC opposition, and by how much is not yet measured.")
        out.append(Bout(a, b, starts, read, mp, book, ra, rb, note))
    out.sort(key=lambda x: (x.starts, x.fighter_a))
    return out


def _pro_record(name: str, led) -> str:
    """'22-7 (30 bouts) — Oktagon, KSW' or '' when we cannot be sure who this is.

    Resolution uses the date of birth we already hold from ufcstats, because
    name alone is not an identity: four fighters are called Michael Oliveira and
    the first search hit is 0-2. An ambiguous lookup returns nothing rather than
    somebody else's career.
    """
    try:
        from src.data.sherdog import resolve
        from src.models.ufc_features import normalize_name
    except ImportError:
        return ""
    dob = (led.tott.get(normalize_name(name)) or {}).get("dob")
    try:
        f = resolve(name, dob=dob)
    except Exception:
        return ""
    if f is None or not f.bouts:
        return ""
    w, l, d = f.record
    promos: dict[str, int] = {}
    for bt in f.bouts:
        promos[bt.promotion] = promos.get(bt.promotion, 0) + 1
    top = ", ".join(p for p, _ in sorted(promos.items(), key=lambda kv: -kv[1])[:2])
    rec = f"{w}-{l}" + (f"-{d}" if d else "")
    return f"{rec} ({len(f.bouts)} bouts) — {top}"


def group_by_block(bouts: list[Bout]) -> dict[str, list[Bout]]:
    """Split a day's fights into cards by start time.

    Fights on one card share a start time in the Odds API feed; separate
    promotions running the same day sit hours apart. Grouping on the hour is
    crude but matches how the feed actually behaves, and a wrong grouping is
    visible immediately rather than silently mixing two promotions' fights.
    """
    blocks: dict[str, list[Bout]] = {}
    for b in bouts:
        key = b.starts.strftime("%Y-%m-%d %H:%MZ")
        blocks.setdefault(key, []).append(b)
    return dict(sorted(blocks.items()))

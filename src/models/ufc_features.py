"""Point-in-time features for UFC fight prediction, and the model that reads them.

WHY THIS EXISTS. The previous UFC model returned 50–53% on every fight — ten
predictions that were the same coin flip printed ten times. The cause was not
missing fighters. Ratings were fine (Klein 1572 vs Musayev 1499 = 60% by Elo).
The simulator destroyed the signal: every fighter carried `phi=350`, the Glicko
"never seen this fighter" deviation, regardless of having 2 bouts or 24, and
`simulate_fight` injected that as noise with sd 1.24 which it then multiplied by
4 in logit space. A ~5-sigma perturbation on a 0.4 signal. 60.4% went to 53.0%.

WHAT REPLACED IT. An 18-feature logistic regression over career-to-date form,
trained walk-forward. Held-out performance (2023+, n=1,150):

    accuracy 63.7%   AUC 0.696   log-loss 0.6337  (coin flip = 0.6931)

and stable across five independently-tested years (58.6%–66.8%). The single
strongest predictor is AGE, not rating — consistent with the MMA literature,
where decline past ~32 is steep and shows up before it shows up in the record.

WHAT THIS IS NOT. 63.7% is roughly what the closing market achieves unaided, so
this does NOT imply a betting edge, and the `ufc/moneyline` lane stays retired.
It is a defensible read on a fight, which is what it is used for.

POINT-IN-TIME DISCIPLINE. Every feature for a fight on date D is built only from
bouts that finished before D. State updates happen AFTER a row is emitted, never
before. That ordering is the entire guarantee against leakage, and
`tests/test_ufc_point_in_time.py` asserts it directly by replaying the stream and
checking that no fighter's accumulator has moved ahead of the row it fed.

Refresh data:  python3 -m src.data.ufc_data
Retrain:       python3 scripts/train_ufc.py
"""
from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

_DIR = Path("data/ufc")
_MODEL = Path("data/models/ufc/fight_model.json")

# Elo constants. Chosen by grid search on held-out log-loss, not by convention:
# the usual 28/40 scored 0.6822 and 64/80 scored 0.6795. Higher K disperses a
# short-career population faster, and UFC fighters average well under 10 bouts.
K_DECISION = 64.0
K_FINISH = 80.0
ELO_START = 1500.0

# A UFC debutant beats a rostered opponent 43.4% of the time (n=1,291, 2010+),
# and that rate is flat in the opponent's experience (42–46% across every
# bucket). Measured here, not assumed — it is what we report when a fighter has
# no UFC record at all, instead of silently defaulting them to average.
DEBUT_WIN_RATE = 0.434

# Order matters: it is the order of `coefficients` in the model artifact.
FEATURES = [
    "elo",      # chronological Elo, K tuned above
    "exp",      # UFC bouts, capped at 25 (returns diminish, tail is noise)
    "age",      # years at fight date — the strongest single feature
    "reach",    # inches
    "height",   # inches
    "slpm",     # significant strikes landed per minute
    "sapm",     # significant strikes absorbed per minute
    "sacc",     # significant strike accuracy
    "sdef",     # significant strike defence (1 - opponent accuracy)
    "td15",     # takedowns landed per 15 minutes
    "tdacc",    # takedown accuracy
    "tddef",    # takedown defence
    "sub15",    # submission attempts per 15 minutes
    "ctrl",     # share of fight time in control
    "kd15",     # knockdowns per 15 minutes
    "finish",   # share of wins by finish
    "form",     # win rate over last 5 bouts
    "layoff",   # years since last bout, capped at 900 days
]


# ── parsing helpers ──────────────────────────────────────────────────────────
def _pdate(s: str) -> date | None:
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _landed_att(s: str) -> tuple[float, float]:
    """'19 of 39' -> (19.0, 39.0). Blank or malformed -> (0, 0)."""
    m = re.match(r"\s*(\d+)\s+of\s+(\d+)", str(s))
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def _ctrl_secs(s: str) -> float:
    m = re.match(r"\s*(\d+):(\d+)", str(s))
    return float(m.group(1)) * 60 + float(m.group(2)) if m else 0.0


def _height_in(s: str) -> float | None:
    m = re.match(r"\s*(\d+)'\s*(\d+)", str(s))
    return float(m.group(1)) * 12 + float(m.group(2)) if m else None


def _reach_in(s: str) -> float | None:
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(s).replace('"', ""))
    return float(m.group(1)) if m else None


def is_finish(method: str) -> bool:
    m = str(method).lower()
    return "ko" in m or "sub" in m


def normalize_name(name: str) -> str:
    """Fold a fighter name to a comparison key.

    THE BUG THIS FIXES. The odds feed writes "L'udovit Klein" with a typographic
    apostrophe; ufcstats writes "Ludovit Klein". Exact matching missed it, and
    the model reported an 11-bout veteran as making his UFC debut — a confident
    wrong answer produced by a lookup failure. That is the same shape as every
    expensive bug in this repo: the check could not run, and the output did not
    say so.

    Strips accents, drops apostrophes/periods/hyphens, collapses whitespace,
    casefolds. Deliberately does NOT do fuzzy or last-name matching: this repo
    already ate a bug where last-name matching handed "Michael Chandler" the
    ratings of "Michael Page". A miss must stay a miss.
    """
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    for ch in ("'", "’", "ʼ", "`", ".", "-"):
        s = s.replace(ch, "")
    return " ".join(s.lower().split())


# ── data loading ─────────────────────────────────────────────────────────────
def load_bouts() -> tuple[list[dict], dict, dict]:
    """Return (bouts oldest→newest, per-fight stats, fighter tale-of-the-tape).

    Bouts without a resolvable date or a decisive outcome are dropped: a draw or
    no-contest carries no ordering signal, and an undated bout cannot be placed
    in the point-in-time stream at all.
    """
    events: dict[str, date] = {}
    ev_path = _DIR / "event_details.csv"
    if ev_path.exists():
        for r in csv.DictReader(ev_path.open()):
            d = _pdate(r.get("DATE", ""))
            if d:
                events[(r.get("EVENT") or "").strip()] = d

    tott: dict[str, dict] = {}
    tt_path = _DIR / "fighter_tott.csv"
    if tt_path.exists():
        for r in csv.DictReader(tt_path.open()):
            name = (r.get("FIGHTER") or "").strip()
            if not name:
                continue
            raw_reach = str(r.get("REACH", "--"))
            tott[name] = {
                "dob": _pdate(r.get("DOB", "")),
                "reach": _reach_in(raw_reach) if "-" not in raw_reach else None,
                "height": _height_in(r.get("HEIGHT", "")),
                "stance": (r.get("STANCE") or "").strip(),
            }

    stats: dict[tuple, dict] = {}
    st_path = _DIR / "fight_stats.csv"
    if st_path.exists():
        for r in csv.DictReader(st_path.open()):
            key = ((r.get("EVENT") or "").strip(), (r.get("BOUT") or "").strip(),
                   (r.get("FIGHTER") or "").strip())
            s = stats.setdefault(key, {"kd": 0.0, "sl": 0.0, "sa": 0.0, "tdl": 0.0,
                                       "tda": 0.0, "sub": 0.0, "ctrl": 0.0})
            s["kd"] += float(str(r.get("KD", 0) or 0).strip() or 0)
            a, b = _landed_att(r.get("SIG.STR.")); s["sl"] += a; s["sa"] += b
            a, b = _landed_att(r.get("TD")); s["tdl"] += a; s["tda"] += b
            s["sub"] += float(str(r.get("SUB.ATT", 0) or 0).strip() or 0)
            s["ctrl"] += _ctrl_secs(r.get("CTRL"))

    bouts: list[dict] = []
    fr_path = _DIR / "fight_results.csv"
    if fr_path.exists():
        for r in csv.DictReader(fr_path.open()):
            bout = (r.get("BOUT") or "").strip()
            if " vs. " not in bout:
                continue
            a, b = (x.strip() for x in bout.split(" vs. ", 1))
            oc = (r.get("OUTCOME") or "").strip()
            if oc == "W/L":
                w, l = a, b
            elif oc == "L/W":
                w, l = b, a
            else:
                continue
            ev = (r.get("EVENT") or "").strip()
            d = events.get(ev)
            if not d:
                continue
            try:
                rnd = float(str(r.get("ROUND", 1)).strip() or 1)
            except ValueError:
                rnd = 1.0
            m = re.match(r"\s*(\d+):(\d+)", str(r.get("TIME", "0:00")))
            secs = (rnd - 1) * 300 + (float(m.group(1)) * 60 + float(m.group(2)) if m else 0)
            bouts.append({"date": d, "event": ev, "bout": bout, "w": w, "l": l,
                          "method": (r.get("METHOD") or "").strip(),
                          "wc": (r.get("WEIGHTCLASS") or "").strip(),
                          "secs": max(secs, 60.0)})
    bouts.sort(key=lambda x: x["date"])
    return bouts, stats, tott


# ── the accumulator ──────────────────────────────────────────────────────────
@dataclass
class FighterState:
    """Career-to-date totals for one fighter. Mutated only by `apply_bout`."""
    elo: float = ELO_START
    n: int = 0
    secs: float = 0.0
    sl: float = 0.0     # sig strikes landed (own)
    sa: float = 0.0     # sig strikes attempted (own)
    osl: float = 0.0    # sig strikes landed BY opponents
    osa: float = 0.0    # sig strikes attempted BY opponents
    tdl: float = 0.0
    tda: float = 0.0
    otdl: float = 0.0
    otda: float = 0.0
    sub: float = 0.0
    ctrl: float = 0.0
    kd: float = 0.0
    finishes: int = 0
    last: date | None = None
    results: list[int] = field(default_factory=list)


class Ledger:
    """The point-in-time fighter book. Replay bouts in order; query between them.

    The contract that makes this safe: `features_for` reads state, `apply_bout`
    writes it, and a caller must never call them in the other order for the same
    fight. Everything downstream — training rows and live predictions alike —
    goes through the same two methods, so there is no train/serve skew to drift.
    """

    def __init__(self, stats: dict, tott: dict) -> None:
        self.stats = stats
        # Physicals are keyed by normalised name so a diacritic cannot cost a
        # fighter their reach and date of birth.
        self.tott = {normalize_name(k): v for k, v in tott.items()}
        self.book: dict[str, FighterState] = {}
        # Date of the most recent bout folded in. Reported alongside every
        # "no record" verdict so a stale cache reads as staleness, not as a
        # statement about the fighter.
        self.through: date | None = None

    def state(self, fighter: str) -> FighterState:
        return self.book.setdefault(normalize_name(fighter), FighterState())

    def known(self, fighter: str) -> bool:
        """Has this fighter any UFC record at all? A fighter with no record is
        not an average fighter, and reporting them as one is exactly the failure
        this repo keeps finding: 'couldn't check' rendering as 'all clear'."""
        s = self.book.get(normalize_name(fighter))
        return s is not None and s.n > 0

    def features_for(self, fighter: str, on: date) -> dict[str, float | None]:
        """Career-to-date features as of `on`. None where genuinely unknown."""
        s = self.state(fighter)
        t = self.tott.get(normalize_name(fighter), {})
        mins = max(s.secs / 60.0, 1.0)
        dob = t.get("dob")
        return {
            "elo": s.elo,
            "exp": float(min(s.n, 25)),
            "age": ((on - dob).days / 365.25) if dob else None,
            "reach": t.get("reach"),
            "height": t.get("height"),
            "slpm": s.sl / mins,
            "sapm": s.osl / mins,
            "sacc": (s.sl / s.sa) if s.sa else None,
            "sdef": (1 - s.osl / s.osa) if s.osa else None,
            "td15": s.tdl / mins * 15,
            "tdacc": (s.tdl / s.tda) if s.tda else None,
            "tddef": (1 - s.otdl / s.otda) if s.otda else None,
            "sub15": s.sub / mins * 15,
            "ctrl": s.ctrl / max(s.secs, 1.0),
            "kd15": s.kd / mins * 15,
            "finish": s.finishes / max(s.n, 1),
            "form": (sum(s.results[-5:]) / len(s.results[-5:])) if s.results else None,
            "layoff": (min((on - s.last).days, 900) / 365.25) if s.last else None,
        }

    def diff_vector(self, a: str, b: str, on: date) -> list[float | None]:
        """Feature differences a − b. None propagates: an unknown on either side
        makes that feature unknown, never zero. Imputation is the model's job and
        it happens once, visibly, at predict time."""
        fa, fb = self.features_for(a, on), self.features_for(b, on)
        out: list[float | None] = []
        for k in FEATURES:
            x, y = fa.get(k), fb.get(k)
            out.append((x - y) if (x is not None and y is not None) else None)
        return out

    def apply_bout(self, bout: dict) -> None:
        """Fold one settled bout into both fighters' state."""
        w, l = bout["w"], bout["l"]
        sw, sl_ = self.state(w), self.state(l)
        exp_w = 1.0 / (1.0 + 10.0 ** ((sl_.elo - sw.elo) / 400.0))
        k = K_FINISH if is_finish(bout["method"]) else K_DECISION
        sw.elo += k * (1.0 - exp_w)
        sl_.elo -= k * (1.0 - exp_w)

        secs = bout["secs"]
        for f, opp in ((w, l), (l, w)):
            s = self.state(f)
            s.n += 1
            s.secs += secs
            s.last = bout["date"]
            own = self.stats.get((bout["event"], bout["bout"], f))
            oth = self.stats.get((bout["event"], bout["bout"], opp))
            if own:
                s.sl += own["sl"]; s.sa += own["sa"]
                s.tdl += own["tdl"]; s.tda += own["tda"]
                s.sub += own["sub"]; s.ctrl += own["ctrl"]; s.kd += own["kd"]
            if oth:
                s.osl += oth["sl"]; s.osa += oth["sa"]
                s.otdl += oth["tdl"]; s.otda += oth["tda"]
        sw.results.append(1)
        sl_.results.append(0)
        if is_finish(bout["method"]):
            sw.finishes += 1
        if self.through is None or bout["date"] > self.through:
            self.through = bout["date"]


def build_ledger(through: date | None = None) -> tuple[Ledger, list[dict]]:
    """Replay every bout up to `through` (default: all). Returns the ledger and
    the bouts NOT applied, so a caller can score them as unseen."""
    bouts, stats, tott = load_bouts()
    led = Ledger(stats, tott)
    remaining: list[dict] = []
    for b in bouts:
        if through is not None and b["date"] > through:
            remaining.append(b)
            continue
        led.apply_bout(b)
    return led, remaining


# ── the fitted model ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Read:
    """One fight, as the model sees it."""
    fighter_a: str
    fighter_b: str
    p_a: float
    favourite: str
    confidence: float          # p of the favoured side
    basis: str                 # "model" | "debut_prior" | "no_data"
    drivers: list[str]         # plain-language reasons, strongest first
    note: str = ""

    @property
    def is_coinflip(self) -> bool:
        return self.confidence < 0.55


class UFCFightModel:
    """Reads `data/models/ufc/fight_model.json` and prices a matchup.

    The artifact is JSON, not a pickle, deliberately: the coefficients are the
    model, and they should be readable by a human who wants to know why the
    thing said what it said.
    """

    def __init__(self, artifact: Path | None = None) -> None:
        path = artifact or _MODEL
        self.ok = False
        self.meta: dict = {}
        try:
            blob = json.loads(path.read_text())
            self.coef = blob["coefficients"]
            self.mean = blob["feature_mean"]
            self.sd = blob["feature_sd"]
            self.median = blob["feature_median"]
            self.meta = blob.get("metadata", {})
            self.ok = all(k in self.coef for k in FEATURES)
        except (OSError, ValueError, KeyError):
            self.coef = self.mean = self.sd = self.median = {}

    def predict(self, ledger: Ledger, a: str, b: str, on: date) -> Read:
        """Probability that `a` beats `b` on `on`.

        Three honest outcomes, never blended:
          model        both fighters have UFC history — the regression runs
          debut_prior  one is making a UFC debut — the measured 43.4% applies
          no_data      both debuting, or no artifact — we say so
        """
        ka, kb = ledger.known(a), ledger.known(b)

        if not self.ok:
            return Read(a, b, 0.5, a, 0.5, "no_data", [],
                        "No trained artifact — run scripts/train_ufc.py.")

        # "No UFC record" is not the same claim as "debuting". Many of these
        # fighters have long careers in PFL, Bellator or Oktagon — this model
        # simply cannot see them, and saying "debut" would assert something
        # false about a fighter like Dakota Ditcheva.
        cutoff = f" (data through {ledger.through})" if ledger.through else ""

        if not ka and not kb:
            return Read(a, b, 0.5, a, 0.5, "no_data", [],
                        f"Neither fighter has a UFC record{cutoff}. Both may be "
                        "debuting, or both may fight in another promotion. "
                        "Either way this model cannot see them — no read.")

        if not ka or not kb:
            unrated, rated = (a, b) if not ka else (b, a)
            p_unrated = DEBUT_WIN_RATE
            p_a = p_unrated if unrated == a else 1 - p_unrated
            fav = a if p_a >= 0.5 else b
            n_vet = ledger.state(rated).n
            return Read(a, b, p_a, fav, max(p_a, 1 - p_a), "debut_prior",
                        [f"{unrated} has no UFC record{cutoff}",
                         f"{rated} has {n_vet} UFC bout{'s' if n_vet != 1 else ''}"],
                        f"Base rate only: a fighter with no UFC record wins "
                        f"{DEBUT_WIN_RATE:.1%} against a rostered opponent "
                        f"(n=1,291 since 2010, flat in the opponent's "
                        f"experience). This is NOT a read on these two fighters "
                        f"— if {unrated} is an established name elsewhere, the "
                        f"market knows things this number does not.")

        diffs = ledger.diff_vector(a, b, on)
        z = 0.0
        contrib: list[tuple[str, float]] = []
        for name, raw in zip(FEATURES, diffs):
            v = raw if raw is not None else self.median.get(name, 0.0)
            sd = self.sd.get(name, 1.0) or 1.0
            term = self.coef[name] * (v - self.mean.get(name, 0.0)) / sd
            z += term
            if raw is not None:
                contrib.append((name, term))
        p_a = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

        fav = a if p_a >= 0.5 else b
        sign = 1.0 if p_a >= 0.5 else -1.0
        contrib.sort(key=lambda kv: -kv[1] * sign)
        drivers = [_explain(n, t * sign, fav) for n, t in contrib[:3] if abs(t) > 0.02]
        return Read(a, b, p_a, fav, max(p_a, 1 - p_a), "model", drivers)


_LABEL = {
    "elo": "record against the level of opposition faced",
    "exp": "UFC experience",
    "age": "age",
    "reach": "reach",
    "height": "height",
    "slpm": "striking volume landed",
    "sapm": "damage absorbed",
    "sacc": "striking accuracy",
    "sdef": "striking defence",
    "td15": "takedown volume",
    "tdacc": "takedown accuracy",
    "tddef": "takedown defence",
    "sub15": "submission threat",
    "ctrl": "control time",
    "kd15": "knockdown rate",
    "finish": "finishing rate",
    "form": "recent form",
    "layoff": "time since last fight",
}


def _explain(name: str, signed: float, favourite: str) -> str:
    return f"{_LABEL.get(name, name)} favours {favourite}"

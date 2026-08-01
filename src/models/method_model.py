"""How a fight ENDS — KO/TKO, submission, or decision — from career history.

WHY THIS EXISTS. The old method simulator (ufc_model.simulate_fight) returned
27% KO / 21% sub / 52% decision for six different fights on the 2026-08-01
card, byte-identical, because 49% of its style profiles are the 0.50 default
and comparing 0.50 to 0.50 yields the league base rate every time. It printed
that as a confident distribution. This replaces it with a fitted model over the
268,190-bout Sherdog graph, where the method of every bout is recorded.

WHAT IT MODELS. P(ko_tko), P(submission), P(decision) for a bout — not who
wins. Who wins is `ufc_features.UFCFightModel`, and the two are deliberately
kept apart: they answer different questions from different evidence, and a
joint "wins by KO" number would assert an independence neither model has been
validated for. Read them side by side ("Medić 55% to win; 46% chance this goes
the distance"), not multiplied together.

ORIENTATION-INVARIANT BY CONSTRUCTION. "This fight ends by KO" is true or false
regardless of which fighter is listed first, so every feature is symmetric in
(a, b) — sums, never differences. The win model has the opposite problem and
solves it by alphabetical ordering; here symmetry is free and removes a whole
class of label leakage (a difference-based feature could encode WHO wins, which
is not what this predicts).

SHRINKAGE, NOT RAW RATES. A fighter with 3 bouts and 2 KOs has not got a 67% KO
rate — he has 3 bouts. Every rate is pulled toward the league base rate by
`PRIOR_BOUTS` pseudo-observations, so a thin record contributes something close
to "no information" instead of a loud wrong number. This is the same reasoning
as the market-anchored tennis model and the debut model's flat prior.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

_ARTIFACT = Path("data/models/ufc/method_model.json")

# The three outcomes a bout can have. Everything else (no contest, DQ, draw) is
# dropped from training rather than forced into a class it isn't.
CLASSES = ("ko_tko", "submission", "decision")

# Pseudo-observations of the league base rate mixed into every fighter's rates.
# 5 is deliberately gentle: it halves the weight of a 5-bout record and barely
# touches a 40-bout one.
PRIOR_BOUTS = 5.0


def classify_method(raw: str) -> str | None:
    """Sherdog's free-text method -> one of CLASSES, or None to drop the bout.

    Sherdog writes the same outcome many ways ('KO (Punch)', 'TKO (Punches)',
    'TKO (Submission to Punches)'), so this matches on the leading token and
    treats the parenthetical as colour. Two judgement calls worth stating:

      * 'TKO (Submission to Punches)' is a STRIKING finish. The loser tapped,
        but to strikes — grouping it with submissions would credit a grappler.
      * 'Technical Submission' is a submission; 'Technical Decision' a decision.

    Returns None for N/A, DQ, no-contest and draws: those are real outcomes but
    not methods of victory, and inventing a class for 1,375 'N/A' rows would
    put noise in every probability.
    """
    s = str(raw or "").strip().lower()
    if not s or s.startswith(("n/a", "na", "-")):
        return None
    if "no contest" in s or s.startswith("nc"):
        return None
    if "disqualif" in s or s.startswith("dq"):
        return None
    if "draw" in s:
        return None
    if s.startswith("decision") or "technical decision" in s:
        return "decision"
    # Order matters: check submission-to-punches BEFORE the submission prefix.
    if "submission to punches" in s or "submission to strikes" in s:
        return "ko_tko"
    if s.startswith("submission") or s.startswith("technical submission"):
        return "submission"
    if s.startswith(("ko", "tko", "knockout")):
        return "ko_tko"
    return None


@dataclass
class MethodState:
    """One fighter's finishing and durability record, as of some date."""
    n: int = 0
    win_ko: int = 0
    win_sub: int = 0
    win_dec: int = 0
    loss_ko: int = 0
    loss_sub: int = 0
    loss_dec: int = 0

    def rate(self, count: int, base: float) -> float:
        """Shrunk toward the league base rate — see module docstring."""
        return (count + PRIOR_BOUTS * base) / (self.n + PRIOR_BOUTS)


@dataclass
class MethodLedger:
    """Replays bouts in date order, answering questions about the state BEFORE.

    Same point-in-time contract as the Elo ledgers: `features_for` never sees a
    bout that has not been `apply_bout`ed, and reads never mutate state.
    """
    book: dict[str, MethodState] = field(default_factory=dict)
    # League base rates, themselves accumulated point-in-time so early fights
    # are not scored against rates learned from the future.
    tot: int = 0
    tot_ko: int = 0
    tot_sub: int = 0
    tot_dec: int = 0

    def known(self, slug: str) -> bool:
        return slug in self.book and self.book[slug].n > 0

    def state(self, slug: str) -> MethodState:
        return self.book.get(slug, MethodState())

    def base_rates(self) -> tuple[float, float, float]:
        """(ko, sub, dec) league-wide so far. Falls back to observed MMA-wide
        priors before enough history exists to measure them."""
        if self.tot < 200:
            return 0.36, 0.24, 0.40
        return (self.tot_ko / self.tot, self.tot_sub / self.tot,
                self.tot_dec / self.tot)

    def apply_bout(self, winner: str, loser: str, method: str) -> None:
        cls = classify_method(method)
        if cls is None:
            return
        w = self.book.setdefault(winner, MethodState())
        l = self.book.setdefault(loser, MethodState())
        w.n += 1
        l.n += 1
        if cls == "ko_tko":
            w.win_ko += 1
            l.loss_ko += 1
            self.tot_ko += 1
        elif cls == "submission":
            w.win_sub += 1
            l.loss_sub += 1
            self.tot_sub += 1
        else:
            w.win_dec += 1
            l.loss_dec += 1
            self.tot_dec += 1
        self.tot += 1

    def features_for(self, a: str, b: str) -> dict[str, float] | None:
        """Symmetric features for the pair, or None when neither has a record.

        One unrated fighter is tolerated (his shrunk rates are simply the base
        rates, i.e. no information); two unrated fighters carry no signal at all
        and must not be dressed up as a prediction.
        """
        sa, sb = self.state(a), self.state(b)
        if sa.n == 0 and sb.n == 0:
            return None
        bko, bsub, bdec = self.base_rates()

        a_ko,  b_ko  = sa.rate(sa.win_ko, bko),  sb.rate(sb.win_ko, bko)
        a_sub, b_sub = sa.rate(sa.win_sub, bsub), sb.rate(sb.win_sub, bsub)
        a_dec, b_dec = sa.rate(sa.win_dec, bdec), sb.rate(sb.win_dec, bdec)
        a_vko, b_vko = sa.rate(sa.loss_ko, bko), sb.rate(sb.loss_ko, bko)
        a_vsub, b_vsub = sa.rate(sa.loss_sub, bsub), sb.rate(sb.loss_sub, bsub)
        a_vdec, b_vdec = sa.rate(sa.loss_dec, bdec), sb.rate(sb.loss_dec, bdec)

        return {
            # Offence: either man can end it, so the threats ADD.
            "ko_offense":   a_ko + b_ko,
            "sub_offense":  a_sub + b_sub,
            # Defence: how often each has been finished that way before.
            "ko_vuln":      a_vko + b_vko,
            "sub_vuln":     a_vsub + b_vsub,
            # Distance: fights that reached the judges, from either side.
            "dec_tendency": a_dec + b_dec + a_vdec + b_vdec,
            # A KO needs a finisher AND someone finishable — the product is the
            # interaction a purely additive model cannot express.
            "ko_match":     (a_ko + b_ko) * (a_vko + b_vko),
            "sub_match":    (a_sub + b_sub) * (a_vsub + b_vsub),
            # Experience: veterans go to decision more (durable, and matched
            # against better-defended opponents).
            "experience":   math.log1p(sa.n) + math.log1p(sb.n),
            # Thin records should be visibly thin to the model, not silently
            # imputed — this is the shrinkage made explicit as a feature.
            "min_record":   math.log1p(min(sa.n, sb.n)),
        }


FEATURES = ("ko_offense", "sub_offense", "ko_vuln", "sub_vuln", "dec_tendency",
            "ko_match", "sub_match", "experience", "min_record")


def build_method_ledger(through: date | None = None) -> MethodLedger:
    """Replay the whole global bout graph up to `through` (exclusive)."""
    from src.models.global_elo import load_global_bouts
    led = MethodLedger()
    for bt in load_global_bouts():
        if through is not None and bt["date"] >= through:
            break
        led.apply_bout(bt["w"], bt["l"], bt.get("method", ""))
    return led


# ─────────────────────────── the model ───────────────────────────────────────

class MethodModel:
    """Reads data/models/ufc/method_model.json and prices how a fight ends.

    Absent artifact means "no read", never a guess: the trainer only writes the
    file when the fit beats the base rate on held-out years, and deletes it
    otherwise. That is the same contract as the debut and global-fallback
    models.
    """

    def __init__(self, artifact: Path | None = None) -> None:
        self.ok = False
        self.coef: dict[str, list[float]] = {}
        self.intercept: list[float] = []
        self.mean: dict[str, float] = {}
        self.sd: dict[str, float] = {}
        self.meta: dict = {}
        try:
            blob = json.loads((artifact or _ARTIFACT).read_text())
            self.coef = blob["coefficients"]
            self.intercept = blob["intercept"]
            self.mean = blob["feature_mean"]
            self.sd = blob["feature_sd"]
            self.meta = blob.get("metadata", {})
            self.ok = all(k in self.coef for k in FEATURES) and \
                len(self.intercept) == len(CLASSES)
        except (OSError, ValueError, KeyError):
            pass

    def predict_from_features(self, feats: dict[str, float]) -> dict[str, float]:
        """Softmax over the three classes."""
        z = list(self.intercept)
        for name in FEATURES:
            v = (feats.get(name, 0.0) - self.mean.get(name, 0.0)) / \
                (self.sd.get(name, 1.0) or 1.0)
            for k in range(len(CLASSES)):
                z[k] += self.coef[name][k] * v
        m = max(z)
        e = [math.exp(min(30.0, max(-30.0, x - m))) for x in z]
        tot = sum(e) or 1.0
        return {c: e[i] / tot for i, c in enumerate(CLASSES)}


@dataclass(frozen=True)
class MethodRead:
    ko_tko: float
    submission: float
    decision: float
    basis: str            # "model" | "no_data"
    note: str = ""

    @property
    def finish(self) -> float:
        """P(the fight ends inside the distance) — the bettable summary."""
        return self.ko_tko + self.submission

    @property
    def most_likely(self) -> tuple[str, float]:
        d = {"KO/TKO": self.ko_tko, "submission": self.submission,
             "decision": self.decision}
        k = max(d, key=d.get)
        return k, d[k]


_NO_READ = MethodRead(
    0.0, 0.0, 0.0, "no_data",
    "Neither fighter appears in the career bout graph, so there is no finishing "
    "or durability history to read. This is a refusal, not a 50/50.")


def read_method(ledger: MethodLedger, a_slug: str, b_slug: str,
                model: "MethodModel | None" = None) -> MethodRead:
    """How this fight ends, or an explicit refusal.

    Deliberately takes SLUGS, not names: identity resolution belongs to
    sherdog.resolve / global_elo.name_to_slug, which refuse ambiguity, and
    duplicating name matching here is exactly how four fighters called Michael
    Oliveira became one.
    """
    m = model or MethodModel()
    if not m.ok:
        return MethodRead(0.0, 0.0, 0.0, "no_data",
                          "No trained artifact — run scripts/train_method.py.")
    feats = ledger.features_for(a_slug, b_slug)
    if feats is None:
        return _NO_READ
    p = m.predict_from_features(feats)
    sa, sb = ledger.state(a_slug), ledger.state(b_slug)
    thin = min(sa.n, sb.n)
    note = ""
    if thin < 5:
        note = (f"Thin record on one side ({thin} bout(s) in the career graph), "
                f"so this leans on the league base rate more than on the men.")
    return MethodRead(p["ko_tko"], p["submission"], p["decision"], "model", note)

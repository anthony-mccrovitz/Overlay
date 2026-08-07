# Overlay

**A sports-betting research engine built around a single question: how do you tell a real edge from a lucky streak — and how do you stop yourself from betting the difference?**

Predicting sports outcomes is the easy half. The hard half is that a betting
model gives you a number every day, that number always looks like an edge, and
the feedback loop is slow and noisy enough that you can be wrong for months
without noticing. Overlay is 111,000 lines of Python whose real subject is not
prediction — it is **evidence**: measuring model output against the sharp closing
market, refusing to risk money until a lane clears an explicit statistical gate,
and making silent failure impossible to mistake for success.

Of the 59 sport×market lanes in the registry, **one takes real money.** That is
the system working as designed.

> Personal project, built and operated solo. Runs unattended on GitHub Actions.
> Numbers below are from live logged bets and reproducible via the commands shown.

---

## Where it stands

| | |
|---|---|
| Lanes modelled | 59 across 12 sports (MLB, NBA, NHL, WNBA, soccer, tennis, UFC, golf, motorsport) |
| Lanes cleared to bet | **1** — `mlb/total` |
| That lane | EV **+2.88%** vs the closing line on n=229, ROI **+8.9%**, **t = +3.34 (significant)** |
| Full logged record | 148–112 · **+31.9u** · ROI **+12.5%** (260 settled card picks) |
| Research corpus | 14,723 logged picks · 15,879 closing-line snapshots |
| Codebase | 375 Python files · 90 test modules · 22 scheduled CI workflows |

```bash
python3 chef.py scoreboard    # every lane and its distance from the gate
python3 chef.py record        # P&L by market and sport
```

**The headline ROI is not the claim.** 89% of that +12.5% comes from two lanes
that would fail today's gate — NBA totals (off-season, statistically
unmeasurable) and MLB moneyline (retired, EV +0.10%). The one lane that clears
the gate contributes about 13%. Reporting it that way is the point of the
project; a portfolio number you can't decompose is a number you can't trust.

---

## The three ideas worth reading the code for

### 1. Judge models on EV against the close, not on win rate

The industry-standard shorthand for "does this model have an edge" is
**closing-line value**: how often you beat the market's final price. Measured
across the 8 best-sampled lanes here, beat-close rate correlated **−0.153** with
realised ROI, while **mean EV vs the close correlated +0.494**.

A rate is blind to magnitude. A lane can beat the close 85% of the time on
tiny favourable moves and still lose money — `batter_total_bases` does exactly
that. So the promotion gate runs on expected value, and beat-rate is demoted to
a diagnostic that decides nothing.

Every promotion requires **all four**:

| Check | Threshold | Why it exists |
|---|---|---|
| EV vs the close | ≥ +1.0% | Estimated edges are biased upward. The estimate must clear a margin, not merely a sign. |
| Realised ROI | > 0 | Money, not theory. |
| Sample | n ≥ 30 | Data-sufficiency floor. |
| Independence | ≥ 15 distinct days | n counts snapshots. 46 bets from 4 slates is a small sample in disguise. |

And the gate is careful about what it claims: clearing it **authorises risk, it
does not assert proof**. Every gate line prints its t-statistic and the sample a
real verdict would need.

→ `src/analytics/ev_gate.py`, `src/config/model_standard.py`

### 2. Invariants enforced by tests, because conventions drift

Three separate incidents in this repo traced to the same root cause: a piece of
logic that *had* to have one answer got hand-copied into several modules and the
copies quietly diverged.

- A registry key function was re-implemented in **six** modules. They drifted,
  and fully-instrumented lanes reported as empty — the tennis lane held 246 CLV
  snapshots and displayed zero.
- The promotion gate itself accreted **three** copies. The dashboard printed
  "✅ READY" for a lane that `chef.py promote` was simultaneously refusing,
  because the inline copy had skipped the independence check — the exact check
  the lane failed.

The fix wasn't a code review guideline. Each invariant became an executable
test that fails the build when a new copy appears
(`tests/test_sport_key_single_source.py`, `tests/test_gate_single_source.py`),
and a build standard defines seven checks a live lane must pass, with
non-exemptible core checks and a guard that fails on stale exemptions — so
**a lane cannot go live by omission.**

→ `src/config/models.py`, `tests/test_model_standard.py`

### 3. "Couldn't check" must never render as "all clear"

The most expensive failures here were all silent. A grading pipeline broke on a
field rename and ran wrong for four weeks. A monitor ran RED for twelve
consecutive days and delivered zero alerts, because the alerting step itself was
broken and nothing tested the alerter.

That failure class — an unavailable check displaying as a passing one — is now
designed against directly:

- `chef.py monitor` exits non-zero on a detected gap **or on a check it could
  not run**.
- `chef.py heartbeat` sends a digest every day, green or red; a *missing* digest
  is itself the alarm.
- `alert-canary.yml` is a weekly self-test that the alert path still delivers,
  because an untested notifier is not a notifier.
- `chef.py moneypath` traces all twelve links from raw odds to a placed bet
  against live data, each stating what its silent failure would look like, and
  ends in one verdict: `BETTABLE` or `DO NOT BET`.

Guards themselves are mutation-tested: a guard that has never been observed
failing is not known to work.

→ `src/analytics/money_path.py`, `src/analytics/coverage.py`

---

## Architecture

```
chef.py                 unified CLI — 60 commands, every operation routes through it
predict.py              MLB model + pick generation

src/models/             ensembles (XGBoost / LightGBM / CatBoost), Elo, Dixon-Coles,
                        negative-binomial props, Monte Carlo tournament sims
src/features/           feature engineering: park factors, bullpen, weather, matchup, form
src/data/               ~50 ingestion adapters (odds APIs, Pinnacle fair lines, Polymarket,
                        Kalshi, ESPN, Sherdog, Statcast, KenPom) with quota management
src/analytics/          the evidence layer: CLV, EV gate, devigging, calibration,
                        coverage, the money path
src/betting/            Kelly sizing — on the SHRUNK edge, never the claimed one
src/config/             lane registry, build standard, promotion gate (single source)
src/tracking/           canonical pick schema + lock-protected ledger writes
tests/                  90 modules — the executable form of the invariants
api/ + overlay/         FastAPI service + Next.js subscription front end
.github/workflows/      22 scheduled jobs: picks, closing-line capture, grading,
                        CLV accrual, integrity monitor, alert canary, backups
```

**Stack:** Python 3.11 · pandas / NumPy / SciPy · scikit-learn · XGBoost,
LightGBM, CatBoost · pytest · FastAPI · Next.js + TypeScript + Tailwind ·
GitHub Actions.

Some design choices worth noting:

- **Kelly stakes are computed on the shrunk edge.** An edge-shrink factor is
  fitted per lane from claimed-vs-realised performance, because raw model edges
  are systematically optimistic and Kelly is brutally sensitive to that.
- **Calibration is guarded, not assumed.** Seven production calibrators were
  found degenerate — one flattened every MLB game to p = 0.5833 — and the
  guardrail that now quarantines them also had to be fixed for rejecting *good*
  calibrators by probing outside model support.
- **Ledger writes are the one place with a lock.** A reader race once emptied
  14.6k picks to 6. Every write now goes through locked helpers in
  `schema.py`, and a test makes writing around them impossible.
- **Prop CLV is treated as an artifact.** Prop models echo the book's line at
  r ≈ 0.97, so beat-close there measures line-following, not skill. Props are
  judged on ROI alone.

---

## Running it

```bash
pip install -r requirements.txt

python3 chef.py today         # what ran, the record, what to bet
python3 chef.py moneypath     # before staking: is the chain intact?
python3 chef.py picks mlb     # generate today's slate
python3 chef.py grade         # settle yesterday
python3 chef.py scoreboard    # every lane vs the promotion gate
python3 chef.py audit-models  # every lane vs the build standard
python3 chef.py test          # full suite
```

`chef.py --help` groups all 60 commands; six are marked ★ as the ones worth
knowing. `CLAUDE.md` holds the invariants and schema contract; `OPERATOR.md`
covers day-to-day operation.

---

## Honest limitations

- **One live lane is a thin result.** It is the honest one, but it means most of
  this codebase is infrastructure for a conclusion that is still mostly "not yet
  proven."
- **`mlb/total` runs on an identity calibrator** while its own calibrator sits
  quarantined as degenerate — a documented exemption with a written retirement
  condition, not a silent workaround.
- **A backtest here once tested a model on its own training data** and reported
  61.9% on a market that was honestly 52.2%. The lane survived on realised
  out-of-sample EV, not on the backtest. Three separate instances of
  "a test comparing two runs of the same code proves nothing" have been found
  and fixed; assume there is a fourth.
- **Sports betting is close to a zero-sum market against professionals.** The
  correct prior for any given lane is that it has no edge, and this system is
  built to keep confirming that prior until the data overrules it.

---

*Built by [Anthony McCrovitz](https://github.com/anthony-mccrovitz). Research and
engineering project — not betting advice.*

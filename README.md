# Overlay

A private sports-betting engine. Models a handful of sport×market lanes, prices
them against the sharp closing market, and only lets a lane take real money once
it has earned that on evidence.

This file is for a **human** — you, three weeks from now, wondering whether you
can bet today and what any of this is. `CLAUDE.md` is the agent-facing file
(invariants, schema, daily commands); it deliberately does not repeat this
orientation.

---

## Can I bet today?

```
python3 chef.py moneypath
```

Twelve links between raw odds and a placed bet, each checked against live data,
each stating what its **silent** failure would look like. It ends in one verdict:
`BETTABLE` or `DO NOT BET`. That is the whole question, answered in two seconds.

```
python3 chef.py today        # the daily driver: did it run, the record, what to bet
python3 chef.py scoreboard   # every lane and how close it is to earning real money
```

## What is actually proven

Be suspicious of this section if it disagrees with `chef.py scoreboard` — the
command reads live data, this file is written by hand.

| | |
|---|---|
| Lanes in the registry | 54 (**1 live**, 37 incubating, 16 retired) |
| The one live lane | `mlb/total` — EV +3.02% vs the close, ROI +8.9%, t=+3.38 (realised, from logged bets) |
| Card record | 286 settled, +34.5u, +12.1% ROI |

**One lane can take money.** Everything else logs, researches, or sits dormant.
That is not a defect; it is the gate working. Lanes go live on evidence, and
almost nothing has cleared the bar.

**The card record is not evidence the system works.** 89% of that +12.1% comes
from two lanes that would fail today's gate — `nba/total` (off-season,
statistically unmeasurable) and `mlb/moneyline` (retired, EV +0.10%). The one
lane that does clear the gate contributes about 13%. Read the record as history,
not as a forecast.

## How a lane earns real money

A lane is promoted only when **all** of these hold:

| Check | Threshold | Why |
|---|---|---|
| EV vs the close | ≥ +1.0% | Not zero. Estimated edges are biased upward, so the estimate must clear a margin, not merely a sign. |
| Realised ROI | > 0 | Money, not theory. |
| Sample | n ≥ 30 | Data-sufficiency floor. |
| Independence | ≥ 15 distinct days | n counts snapshots. 46 bets from 4 slates is a small sample wearing a disguise. |

Two things this gate deliberately does **not** do:

- **It does not run on beat-close rate.** Measured across the 8 best-sampled
  lanes, beat-close correlated **−0.153** with realised ROI while mean EV
  correlated **+0.494**. A hit rate is blind to magnitude: a lane can win 85% of
  small favourable moves and still lose money. Beat-close is still reported, as a
  diagnostic only.
- **It does not claim proof.** Clearing the gate authorises risk; it is not a
  significance test. Every gate line prints the t-statistic and the sample a real
  verdict would need.

## The daily loop

```
python3 chef.py today            # morning: what ran, what to bet
python3 chef.py moneypath        # before staking: is the chain intact?
python3 chef.py grade            # evening: settle yesterday
python3 chef.py record           # P&L by market and sport
```

Everything else is research and operations. `chef.py --help` groups the full
command set; the six entry points worth knowing are marked with ★.

## How you find out when something breaks

The expensive failures here have all been **silent**, so the alarms are built
around that. A monitor once ran RED for twelve consecutive days and delivered
zero notifications, because the alert step itself was broken and nothing tested
it.

- `chef.py monitor` — daily integrity check; exits non-zero on a gap **or on a
  check it could not run**. "Couldn't check" never renders as "all clear".
- `chef.py heartbeat` — a digest that arrives every day, green or red. A missing
  digest is itself the signal.
- `.github/workflows/alert-canary.yml` — weekly self-test that the alarm path
  still delivers, because an untested notifier is not a notifier.

## Layout

Roughly 91,000 lines across 255 Python files. You are not expected to hold that
in your head, and most of it cannot move money.

```
chef.py                 the CLI — every operation goes through it
predict.py              MLB model + pick generation
src/config/             the registry: which lanes exist, their status, the build standard
src/analytics/          CLV, EV gate, devig, coverage, the money path
src/betting/            Kelly sizing (on the SHRUNK edge, not the claimed one)
src/tracking/           canonical pick schema and the ledger
scripts/                capture, calibration, backfills, alerting
tests/                  71 files — the executable form of the invariants
data/pnl/picks.json     the canonical bet record
data/clv/               closing-line archives and CLV snapshots
docs/archive/           completed plans, kept for history — not current state
```

## Before changing anything

Read the **Invariants** section of `CLAUDE.md`. Each rule there exists because
breaking it already cost a rebuild, and each is enforced by a test rather than by
convention. The one that catches people most often: never re-implement
`src/config/models._key` — six modules once hand-rolled it, drifted to different
answers, and made fully-instrumented lanes report as empty.

```
python3 chef.py test        # the full suite
```

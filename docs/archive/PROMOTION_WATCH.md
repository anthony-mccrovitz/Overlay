> **ARCHIVED 2026-07-30 — superseded; the promotion gate was rewritten to run on EV vs the close, with an independence floor**
>
> Kept for history. This describes a past plan, not current state.
> For current state run `chef.py scoreboard` / `chef.py moneypath`, or read README.md.

# Promotion Watch — out-of-sample gates in progress

The `chef.py edge` gate flags candidates; promotion requires the edge to HOLD on
picks logged AFTER the flag date (out-of-sample). This file records each
candidate's baseline at flag time so the out-of-sample comparison has a clean,
un-fudgeable cutoff.

## mlb · batter_total_bases — flagged 2026-07-12

Baseline (everything scored up to and including 2026-07-12):

| metric                    | value        |
|---------------------------|--------------|
| n scored                  | 401          |
| avg line-CLV vs best      | +0.22 pt     |
| avg line-CLV vs Pinnacle  | +0.19 pt     |
| p(>0), Bonferroni α=0.0071| 0.0000       |
| verdict                   | EDGE CANDIDATE |

**Decision rule:** after ≥100 NEW scored picks dated 2026-07-13 or later, run

```
python3 chef.py edge
```

and compare the fresh slice. Promote via `python3 chef.py promote mlb
batter_total_bases` only if the out-of-sample avg line-CLV vs Pinnacle stays
positive. If it collapses toward zero, the in-sample number was selection noise —
do not promote, extend the watch another 100.

## Strategy-level watches (300-bet no-vig rule, `chef.py clv`)

| strategy         | status 2026-07-12                  | next checkpoint |
|------------------|------------------------------------|-----------------|
| devig_ev         | 1 pick logged, 0 scored            | ~2026-08-01: read stale-opener bands for the early signal; verdict at n=300 |
| devig_ev_totals  | registered 2026-07-12, accruing    | same |
| model            | SHADOW — flat (−0.13% best / ~0.0 sharp) | re-read after novig accrues ~300 |
| fav_longshot     | RETIRED (−2.48% @ n=344) — removed from daily run | none (settled) |

Weakest model markets — next to face the same rule once they reach n=200 scored:
NRFI (−2.4% CLV, 22% beat, n=165) and f5_total (32% beat, n=207, currently
"noise" at the gate).

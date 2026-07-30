> **ARCHIVED-IN-PLACE 2026-07-30.** Written 2026-06-21; its "Where we are"
> section asserted the system "can't silently break — the integrity monitor goes
> RED on any in-season market gone dark". That claim was false for twelve
> consecutive days in July: the monitor DID go red and delivered zero alerts,
> because the alert step itself was broken and nothing tested it. It is true
> again now, but a roadmap that asserts a guarantee it cannot check is how the
> gap stayed invisible.
>
> Current state: `chef.py scoreboard` / `chef.py moneypath`, or README.md.
> Kept for the plan history below.

# Roadmap — Overlay

Updated 2026-06-21, after the multi-market model build (PRs #23–#30).

## Where we are
The system is a **complete, autonomous, self-auditing measurement instrument**:
- Runs entirely on GitHub Actions (no laptop). Can't silently break — the
  integrity monitor goes RED on any in-season market gone dark, and workflows
  surface failed steps instead of fake-green.
- Prices **every game-line market + player props + outrights** across MLB, NBA,
  NHL, WNBA, World Cup, soccer leagues, tennis, golf, MMA — each prop type its
  own CLV-tracked market.
- Two-signal validation per market: **CLV** (`edge`) + **outcome calibration**
  (`validate`). Nothing is bet until both agree and persist out-of-sample.

**The build phase is done. The measurement phase runs itself.**

## The one job now: accumulate signal
Watch weekly:
```
chef.py edge       # which (sport, market) has real CLV vs noise
chef.py validate   # which models are calibrated vs overconfident
chef.py monitor    # is every in-season market still producing
```
A market promotes shadow → real money only when it shows **statistically
significant positive CLV that persists out-of-sample** AND `validate` calls it
calibrated. Current leads: `mlb · spread`, `mlb · total` (the only calibrated
markets) — still below the sample floor.

## Phase 1 — prove the leads (next ~4–8 weeks, no new code)
- Let MLB spread/total accumulate to n ≥ 200 scored with the cleaner post-fix
  capture. If CLV stays positive out-of-sample → first promotion candidate.
- Confirm props CLV-score now that closings capture (verify `pitcher_strikeouts`
  etc. leave 0-scored — first real settle ~daily).

## Phase 2 — fix the overconfident models (data-driven)
`validate` flags these as inflated; retune rather than trust their EV:
1. **Calibrate the prop models** — fit per-stat variance from realized WNBA/MLB
   outcomes (current coefficients borrowed from NBA). Add a Platt/temperature
   layer like the soccer 1X2 model.
2. **Soccer scorer lineup-awareness** — biggest single improvement: ingest a
   team-sheet/expected-XI feed so benched stars aren't overestimated and rotation
   games aren't mispriced.
3. **WC spread margin-shape** — calibrate the margin distribution beyond 1X2
   (currently raw Poisson over-predicts blowout covers).
4. **Tennis** — replace the 50% serve default for sparse-Elo players with a
   ranking-based prior so minor-event picks aren't noise.

## Phase 3 — the second edge (parallel track)
The **Kalshi ↔ Polymarket arbitrage** stack (~80% built: clients, entity
resolver, arb math). A structurally different edge from beating closing lines.
Blocked items: fee-correct fill modeling, resolution-criteria matching, and the
US-person Polymarket constraint. Worth finishing once the sports leads resolve.

## Phase 4 — productize (only after a proven edge)
A market with proven, persistent positive CLV is the product thesis. Then: Kelly
sizing on that market only, a real bankroll, subscription surfacing of that
specific edge. **Not before** — selling unproven picks is the trap this whole
instrument exists to avoid.

## Standing principles
- Shadow-first: every new market/model logs `card_pick=False` until validated.
- Two signals: CLV (market) + calibration (outcome). EV alone is never trusted.
- Loud failure: the monitor + RED runs mean a gap shows the next morning.
- More data, not more bets: when in doubt, keep collecting.

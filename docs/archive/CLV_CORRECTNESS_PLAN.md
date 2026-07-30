> **ARCHIVED 2026-07-30 — completed; the vig-consistent CLV ladder shipped, and the gate has since moved to EV entirely**
>
> Kept for history. This describes a past plan, not current state.
> For current state run `chef.py scoreboard` / `chef.py moneypath`, or read README.md.

# CLV Correctness Plan — vig-consistent CLV for every market + experiment verdicts

**Status (2026-07-10): IMPLEMENTED — all 159 tests pass. Uncommitted on `main` working tree
(needs a branch + PR). Historical raw-CLV backfill persisted 2026-07-10.**

This is the plan that got built across the `feat/devig-ev-shadow-strategy` sessions. The code
comments in `clv_tracker.py` reference these items by number ("item 1 of the CLV plan", etc.) —
this document is the plan they refer to.

---

## The core problem this fixes

The legacy `clv_pct` compared a **devigged close** against a **vigged entry**
(raw implied prob of the price we took). Fair-close minus vigged-entry deflates every
price-CLV by roughly the entry vig share (**~1.5–2.5%**), so a genuinely break-even
strategy reads negative and a mildly winning one reads flat. Every market's headline
CLV was biased pessimistic.

### The fix: a vig-consistency ladder

Every price-market snapshot now carries up to three CLV variants; all readers
(`chef.py` `_clv_gate`, strategy report, entry-hour/entry-edge reports via
`_best_prob_clv`) prefer them in this order:

| field | comparison | availability |
|---|---|---|
| `clv_novig_pct` | fair close vs **fair entry** (both devigged, best-price pairs) — gold standard | forward-only from 2026-07-10 (needs the entry board, `entry_fair.py`) |
| `clv_raw_pct` | raw close vs raw entry (both vigged, best price both times → vig ≈ cancels) | **all history** — backfilled by `scripts/backfill_raw_clv.py` |
| `clv_pct` (legacy) | fair close vs vigged entry — biased ~−2% | kept only for snapshots predating the fix |

Sharp (Pinnacle) mirrors exist for each: `clv_novig_sharp_pct`, `clv_raw_sharp_pct`,
`clv_sharp_pct`. Line markets (spread/total/prop/f5) get `price_clv_raw_pct` /
`price_clv_novig_pct` when open line == close line; NRFI gets `clv_raw_pct`.

Key files:
- `src/analytics/entry_fair.py` — devigs the ENTRY from the same cached odds board the pick
  came from (`data/cache/odds/*_latest.json`, zero API cost). Attaches `opening_fair_prob`,
  `opening_fair_sharp`, `entry_ev_vs_fair_pct`, `entry_overround`, `entry_board_age_min`.
  Boards older than 12h are refused.
- `scripts/backfill_raw_clv.py` — idempotent, no API. Ran `--write` 2026-07-10:
  1,490 price + 1,234 sharp-price + 2,236 line snapshots stamped.

## The four plan items

1. **Stale-opener validation** (`get_clv_by_entry_edge` / `print_clv_by_entry_edge`).
   `entry_ev_vs_fair_pct` is stamped at bet time = your entry price vs Pinnacle's no-vig fair.
   Bands (≤0 / 0–2 / 2–5 / >5%) vs realized CLV. If higher entry-EV bands realize higher CLV,
   "we knew we got a good price" is verified **at entry**, before any close exists.
   *Status: implemented; accrues from 2026-07-10 picks forward (table empty until then).*

2. **Catalyst tags** (`_derive_catalyst` at snapshot time; `get_clv_by_catalyst`).
   Why should the line move toward us? Tags: `weather`, `model_agreement`, `stale_opener`
   (devig_ev picks), `park`, `lineup`. Splits CLV catalyst vs no-catalyst
   (bare model-vs-market disagreement = "coin-flip CLV"). *Status: implemented, forward-only.*

3. **Promotion rule — the 300-bet verdict** (`_strategy_verdict`, printed under
   `CLV BY STRATEGY` in `chef.py clv`):
   - **PROMOTE** — avg vig-consistent CLV > 0 AND beat-close ≥ 50% at n≥300
   - **RETIRE** — avg < −0.5% at n≥300
   - **SHADOW** — everything else (insufficient n, flat, or outlier-driven mean)

4. **Time-of-bet attribution** (`get_clv_by_entry_hour`), 3-hour UTC buckets — is the edge
   actually *timing*? Bet earlier/harder in windows that earn CLV.

## Verdicts as of 2026-07-10

```
model         4022/7703 scored — avg −0.13%, beat 46.8% │ sharp +0.009  → SHADOW (flat)
fav_longshot   344/431  scored — avg −2.48%, beat 42.2% │ sharp −2.53   → RETIRE
devig_ev         0/1    scored — first pick logged 2026-07-10           → SHADOW (need 300)
```

- **The `devig_ev` experiment is LIVE, not lost** — `chef.py strategies` runs daily in
  `.github/workflows/morning.yml`, and its picks are tagged `stale_opener` catalysts. It needs
  ~300 scored picks (weeks) before item 3 can rule. Item 1's table is the early read: if the
  0–2% / 2–5% entry-EV bands show positive realized CLV before n=300, the signal is real.
- **fav_longshot is settled: RETIRE.** −2.5% CLV at n=344. It served its purpose as the
  zero-model benchmark.
- **model (all untagged picks)** is flat vs best price but ~0 vs Pinnacle — exactly what the
  vig-bias fix predicted (legacy metric made it look worse than it is).
- Entry-hour: 18–21 UTC shows +1.23% but n=44 — revisit at n≥100 per the printed caveat.

## Remaining steps

- [x] Backfill raw CLV onto history (`--write` done 2026-07-10; cloud `chef.py clv --refresh`
      re-stamps raw fields on every recompute, so snapshots.json doesn't need committing)
- [x] Commit this work (this PR): `chef.py`, `src/analytics/clv_tracker.py`,
      `src/analytics/entry_fair.py`, `scripts/backfill_raw_clv.py`, this doc
- [x] Wire `print_clv_by_catalyst` into `chef.py clv` (item 2's report was getter-only)
- [ ] Let `devig_ev` + entry-EV bands accrue; check `chef.py clv` weekly
- [ ] At n≥300 for devig_ev, apply the item-3 verdict; only PROMOTE on CLV that persists
      out-of-sample (see docs/SHADOW_PICKS_PLAN.md §8)
- [ ] Deprecate legacy `clv_pct` readers once novig coverage dominates

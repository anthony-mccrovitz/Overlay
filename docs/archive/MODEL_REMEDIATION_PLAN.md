> **ARCHIVED 2026-07-30 — completed; remediation landed and its guards are now enforced by tests**
>
> Kept for history. This describes a past plan, not current state.
> For current state run `chef.py scoreboard` / `chef.py moneypath`, or read README.md.

# Model Remediation Plan — Getting to a Verified Edge

**Created:** 2026-07-15
**Owner:** Anthony
**Governing principle:** *No model ships an edge it cannot prove out-of-sample, and
no market becomes a card pick until it earns positive CLV in the shadow book first.*

---
## STATUS 2026-07-15 — infrastructure phase COMPLETE (all tests green, 299 pass)

| Item | State |
|---|---|
| **X1 Calibration gate** | ✅ DONE — `src/analytics/calibration_gate.py`; wired into `normalize_pick` (pending-only, idempotent, card-demoting); refreshed nightly in `grade.py`; 13 tests. Verified: tennis/WNBA/props phantom edges → 0; `mlb::total` (k=1.0) survives. |
| **X3 Determinism** | ✅ DONE — Elo snapshot cache in `soccer_model_v2.seed_from_eloratings`; `src/util/determinism.py` seed in `run_soccer.py`; 5 tests. Fixes the Argentina-45.7% phantom root cause. |
| **X2 Registry reconcile** | ✅ DONE — NHL totals demoted (36% win, CLV −2.2%); labels corrected; gate now centrally de-cards any phantom-edge pending pick. |
| **Purge bad WC picks** | ✅ DONE — 16 non-deterministic Argentina@England shadow picks removed. |
| **X4 CLV coverage** | ✅ VERIFIED (mostly a misdiagnosis — see below); line CLV works (spreads 238/346, totals 97/516) + regression tests. F5 back-score deferred (operational). |
| **Key correction** | The calibration gate revealed MLB moneyline & NRFI have +CLV but ~0 realized outcome edge (k≈0). **`mlb::total` is the ONLY outcome-verified market (k=1.0).** |

**Not done (by design — data/time-gated, not codeable now):** per-model *refits* for
Tier A/B (the gate neutralizes their phantom edges in the meantime); promotion of any
new market to card status (requires ≥200 shadow bets + positive CLV to accrue); F5
historical back-score. These are the ongoing part of the plan, not one-session work.
---

---

## The master diagnosis

Across the whole book, **claimed edge is inversely correlated with realized performance.**
The models quoting the biggest edges are the worst performers; the models quoting modest
edges are the only ones beating the closing line.

| Model | Claimed edge | Win% | Sample | Signal |
|---|---|---|---|---|
| Tennis Wimbledon totals | +43.5% | 38% | 55 | miscalibrated |
| WNBA spreads | +26.7% | 43% | 51 | miscalibrated |
| Tennis WTA Wim totals | +26.8% | 47% | 36 | miscalibrated |
| Tennis FO moneyline (v1) | +18.5% | 19% | 52 | miscalibrated |
| WNBA moneyline | +17.1% | 53% | 134 | overconfident |
| MLB pitcher Ks | +15.7% | 39% | 199 | broken |
| MLB F5 total | +14.5% | 46% | 409 (CLV −1.42%) | overconfident |
| WNBA totals | +14.9% | 38% | 58 | miscalibrated |
| WC anytime scorer | −8.4% | 11% | 35 | broken engine |
| **MLB totals** | **+1.9%** | **54%** | 210 (CLV +0.13%) | **HONEST — works** |
| **MLB moneyline** | (modest) | 51% | 1037 (CLV **+1.81%**) | **HONEST — works** |
| **MLB NRFI** | +8.5% | 47% | 391 (CLV **+3.36%**) | **HONEST — works** |

**Conclusion:** the fix is not 20 rewrites. It is one calibration discipline applied
everywhere, plus a handful of genuinely broken engines to repair, plus killing the
overconfident models until they earn their way back through the shadow book.

---

## Cross-cutting fixes (do these FIRST — they fix whole classes at once)

### X1. Edge-calibration gate (highest leverage)
**Problem:** models emit raw model_prob vs market_prob and call the gap "edge" with no
out-of-sample calibration check. A model that is systematically overconfident manufactures
edges that don't exist (every +20-40% row above).
**Fix:**
- Build `src/analytics/calibration_gate.py`: for each (sport, market), compute reliability
  curve + ECE on graded history; derive a shrink factor `k ∈ [0,1]`.
- Every pick's stored `edge_pct` = raw_edge × k. Where ECE is unknown (new market),
  k defaults to a hard cap (e.g. edges clamped to ≤ 6-8%) until ≥100 graded outcomes exist.
- Reject/flag any pick whose *post-shrink* edge is still > a sanity ceiling per market.
**Definition of done:** no market can print an average claimed edge > its historically
justified level; the +43% tennis-total class becomes structurally impossible.

### X2. CLV promotion gate (what makes a pick a "card pick")
**Problem:** markets go straight to card picks with no proof they beat the close.
**Fix:** formalize `docs/PROMOTION_WATCH.md` into code — a market is `card_pick`-eligible
only after **N ≥ 200 shadow bets with positive avg CLV** (leading indicator) AND calibrated
Brier. Everything else logs as `card_pick=False`, strategy-tagged, CLV-tracked.
**Definition of done:** the only card picks are markets with demonstrated positive CLV
(today: MLB moneyline, MLB NRFI, MLB totals — nothing else).

### X3. Determinism / reproducibility
**Problem:** the WC model retrains non-deterministically — printed Argentina 45.7% one run,
England 41.6% the next on identical input. Any model that can't reproduce its own number
can't be trusted or debugged.
**Fix:** global seed (`numpy`, `random`, model libs) + freeze/serialize fitted params;
pick generation LOADS a versioned fitted model, never refits live. Add a test that runs
`find_edges` twice on a fixture and asserts identical output.
**Definition of done:** every generator is bit-for-bit reproducible; CI guards it.

### X4. CLV join coverage  — STATUS 2026-07-15: mostly a MISDIAGNOSIS
**What we assumed:** CLV is moneyline-only-joined; totals/spreads blank.
**What's actually true (verified):** `capture_closing.py` already archives
`h2h,spreads,totals` for every sport (+ F5, NRFI, props, soccer scorer/alt markets),
and `compute_clv` already fetches, scores, and dashboards line CLV. Populated in
picks.json today: **spreads 238/346, totals 97/516** — line CLV works.
**The one real gap found:** `f5_total` = 0/419. Not a scoring bug — `_score_total`
scores real archived F5 lines correctly (now pinned by tests/test_line_clv_scoring.py).
It's a *historical back-score* gap: F5 closings were only archived from ~June, F5
picks predate that, and F5 is a shadow market so the card-only backfill skips it.
**Remaining work (operational, low priority):** a scoped historical back-score of F5
through the clv_tracker snapshot path. Deliberately NOT run against the live pipeline
unattended. Going forward it accrues automatically via the nightly capture+compute.
**Definition of done:** line CLV verified working + regression-tested (DONE); F5
back-score is a deferred operational task, gated behind higher-value model repairs.

---

## Per-model remediation, by tier

### TIER A — Broken / actively harmful. Pull from any card use NOW; fix or shelve.

**A1. Tennis totals model** (`tennis_model.py`) — +43.5% / +26.8% claimed, ~38-47% win.
Range compression → every game looks like a huge over/under edge. Recentre projected
totals on realized outcomes; recalibrate spread of the total distribution; clamp edges.
*Until fixed: shadow only.*

**A2. Tennis moneyline v1 → validate v2.** v1 French Open: +18.5% edge, 19% win (−28.6u
shadow). v2 (dual-tour Elo + market anchor, PR #63) already replaced it — **validate v2 on
out-of-sample outcomes before any card use.** Confirm v1 fully decommissioned.

**A3. WNBA totals** (`wnba_model.py`) — known range compression (`project_wnba_totals_
miscalibration`). +14.9% edge, 38% win. Recalibrate on outcome data (not n=6); widen
predicted variance; clamp.

**A4. WNBA spreads** — +26.7% edge, 43% win, 0% on the 8 graded `basketball_wnba/spread`.
Same compression as totals. Recalibrate or shelve.

**A5. MLB pitcher strikeouts** (`mlb_pitcher_ks.py`) — +15.7% edge, 39% win. Partial fix
landed (real IP/start, PR #53) but graded record still poor. Re-audit projection vs
realized K distribution; verify the fix actually moved the calibration; likely still
over-dispersed. *Shadow until Brier proves out.*

**A6. World Cup moneyline engine** (`soccer_model_v2.py` + `wc_simulator.py`) — 2-param fit,
non-deterministic (see X3). 56% win/200 is variance, not proven. After X3, re-fit and
re-validate; purge the bad Argentina-45.7% shadow picks already logged.

**A7. WC anytime scorer** (`soccer_scorer.py` / `goalscorer_model.py`) — −8.4% edge, 11%
win. Depends on A6's expected-goals split, so it inherits the non-determinism. Fix after
A6; validate the 90-minute grading rule end-to-end before trusting numbers.

### TIER B — Overclaiming edge AND leaking to the close. Recalibrate + downsize.

**B1. MLB run line / spread** (`mlb_spreads.py`) — CLV **−5.55%** (worst on the board).
We're consistently getting worse run-line numbers than close. Re-examine line shopping +
model; likely no real edge here — candidate to demote entirely.

**B2. NHL totals** (`nhl_model.py`) — +11.7% edge, 36% win, CLV −2.21%. Overconfident +
losing to close. Recalibrate; shadow only.

**B3. MLB F5 totals** — +14.5% edge, 46% win, CLV −1.42%. Same overconfidence as full-game
totals but worse. Recentre; clamp edge.

**B4. NHL player props** (goals 35%, points/assists/SOG ~49-53%, all +13-14% edge).
Overconfident across the board. Recalibrate dispersion; shadow.

### TIER C — Unvalidated new sports. Keep shadow-only; do not expand.

**C1. Soccer minor leagues** — MLS 18%, Copa Libertadores 0%, La Liga 38%, Serie A 0% (all
tiny n). The Dixon-Coles fit tuned for WC/top sides doesn't transfer. Either fit league-
specific Elo/params or stop generating picks for them.

**C2. UFC/MMA** (`ufc_model.py`) — 18% win on 11. Unvalidated. Keep shadow; also finish the
Saturday 7/18 Fight Night card automation separately.

**C3. Golf & motorsport outrights** (`pga_championship.py`, `motorsport_engine.py`) — 0
graded (US Open outrights 0/21 win once graded). No validated grading path + futures never
resolve in-sample. Wire grading first, then judge.

### TIER D — The honest core. PROTECT. This is the product.

**D1. MLB moneyline** — CLV +1.81%, n=1037. Keep; this is real signal.
**D2. MLB NRFI** — CLV +3.36%, n=391. Best CLV on the board. Keep + lean in.
**D3. MLB totals** — +1.9% honest edge, 54%, calibrated (ECE 0.026). The grinder. Keep.
**D4. NBA totals** — 64% win/94 but CLV −0.32%. Watch closely: strong record, but negative
CLV means variance risk. Do NOT scale until CLV turns positive.
**Investigate: MLB batter HR props** — 73% win/402 is implausibly high; verify it's real
signal and not a grading artifact before trusting it.

---

## Sequencing

1. **Week 1 — Infra:** X3 (determinism) + X1 (calibration gate) + X4 (CLV joins). These
   unlock everything and stop new phantom edges at the source.
2. **Week 1 — Triage:** flip all Tier A/B/C models to `card_pick=False` (shadow) via the X2
   gate. Card book = Tier D only. This immediately stops betting the broken models.
3. **Weeks 2-4 — Repair Tier A** in order of sample size / harm: A3/A4 (WNBA), A1 (tennis
   totals), A6/A7 (WC), A5 (pitcher Ks), A2 (tennis v2 validation).
4. **Weeks 3-6 — Recalibrate Tier B**; decide B1 (run line) keep-or-kill.
5. **Ongoing — Promotion:** as each shadow market crosses ≥200 bets + positive CLV +
   calibrated Brier, promote to card via X2. That is the definition of "verified edge."

## What "verified edge" means (the finish line)
A market is *verified* when: (a) ≥200 graded shadow bets, (b) positive average CLV vs
Pinnacle close, (c) Brier calibrated (ECE < ~0.05). ROI confirmation follows at ~1,000
bets/market. Today only D1/D2/D3 clear (b). The plan's job is to grow that list honestly.

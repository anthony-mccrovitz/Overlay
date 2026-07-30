# Methodology

Every quantitative decision in this system, why it was made that way, and how
much confidence it deserves. Written 2026-07-30.

Each entry is labelled:

- **SETTLED** — the literature and our own data agree; changing it would need new evidence.
- **JUDGEMENT** — a defensible choice among several; a different number would be
  defensible too. These are the ones to argue with.
- **MEASURED HERE** — derived from this repo's own data, not from a paper.

Constants live in `src/config/model_standard.py` and `src/analytics/devig.py`.
If a number below disagrees with the code, **the code is right and this file has
drifted** — the same failure that made `docs/MODELS.md` describe retired lanes as
live.

---

## 1. Removing the vig — Shin for props, multiplicative for game lines

**Choice.** `multiplicative` (`p_i = π_i / Σπ`) on Pinnacle-priced game lines;
`shin` on player props. Implemented in `src/analytics/devig.py`, selected per
market so no call site re-encodes the rule.

**Why.** A bookmaker's prices sum to more than 100%; the excess is the margin,
and you have to remove it before a price means a probability. Multiplicative
splits that margin in proportion to raw probability, which assumes the book
loads margin evenly. It does not: books load proportionally more onto longshots
(favourite–longshot bias).

That assumption barely matters at Pinnacle's 1–3% overround and matters a lot at
the 8–15% a retail prop carries — there is simply more margin to misallocate.
Shin models the margin as the book's defence against insider money, which
*predicts* heavier margin on longshots, and is the usual recommendation for
high-vig markets. Power sits between the two.

**Status: SETTLED on direction, JUDGEMENT on method.** That props need a
bias-correcting devig is well supported. Shin over power is a defensible
preference, not a proof — our own test only pins that both shade the longshot
below multiplicative, deliberately *not* their relative order, because which
corrects harder depends on the odds and margin.

**What would change it.** Grading enough prop outcomes to compare calibration
under each method directly. We have not done that.

---

## 2. The closing benchmark — Pinnacle, else a declared median

**Choice.** For props: the modal line across books; Pinnacle's price where it
prices that prop (~36% of MLB props), otherwise the **median across books taken
in probability space**, tagged by source so sharp and consensus never blend.

**Why.** CLV only means something against an efficient close, and Pinnacle's is
the consensus reference — low margin, high limits, welcomes sharp action. Where
it is absent you need *a declared fallback*, because the alternative is what this
repo actually did: `if key not in out` — first-write-wins by JSON row order.

Measured before the fix: the "closing book" was theScore Bet 58% of the time and
FanDuel 32%; books disagreed on the same prop at the same line by a **median of
20¢, p90 218¢**; and re-scoring an identical archive under shuffled row order
changed **96% of closing prices**. Freddy Peralta closed +100, +110 or −109
depending on ordering.

Medians are taken in probability space because American odds jump
discontinuously across ±100 — +101 and −101 are adjacent prices but 202 apart
numerically.

**Status: SETTLED.** "Declare your reference book" is standard practice, and
determinism is not optional. `tests/test_clv_benchmark.py` fails if the benchmark
ever varies with row order again.

---

## 3. What CLV even means here — EV, not beat-rate

**Choice.** `clv_ev_pct = fair_close(the exact bet) / price_paid − 1`.

**Why.** The obvious metric is "how often did I beat the close", and it is
actively misleading. **Measured across our 8 best-sampled lanes:**

```
corr(beat_close%, realised ROI) = -0.153
corr(clv_ev_pct,  realised ROI) = +0.494
```

A hit rate is blind to magnitude. `mlb/batter_total_bases` beats the close 85.4%
of the time — the best rate in the book — and returns −2.9%. Win 85% of small
favourable moves, lose 15% large ones, finish underwater.

Mixing a **devigged close** against a **raw entry price** is correct here and is
not the fair-vs-raw asymmetry error it resembles: it is the standard +EV
computation (devig the reference, compare to the price you actually paid). It
also sidesteps a real data limit — prop snapshots record only the side we took,
so the entry cannot be devigged at all.

**Status: MEASURED HERE, and the strongest result in this document.** The
correlation is computed on 8 lanes, so treat the magnitude loosely and the sign
seriously.

---

## 4. Points are not value — the line-value mapping

**Choice.** Convert line movement to probability using a slope measured from
**cross-book disagreement inside the same event**, via within-event demeaned OLS
(`scripts/calibrate_line_value.py`).

**Why.** `mlb/total` reported "+0.19pt" of CLV. A point is not a unit of value:
it cannot be compared across sports, compared with a moneyline CLV in %, or
turned into money. When FanDuel posts 7.5 and DraftKings posts 8 at the same
instant on the same game, the gap between their devigged Over probabilities is
caused by the half-point and nothing else — no news, no steam, no time passing.
Demeaning within the event removes the teams, the park, the weather, the
starters.

**Measured result:**

| lane | per ½ point | r² |
|---|---|---|
| `mlb::f5_total` | 5.60 pp | 0.88 |
| `mlb::spread` | 4.63 pp | 0.98 |
| `mlb::total` | 3.94 pp | 0.80 |
| `wnba::total` | 0.45 pp | 0.35 |

The sanity checks pass on their own: F5 exceeds full-game (fewer innings, each
run matters more), and the same half-point is worth **9× more** in an MLB total
than a WNBA total. Lanes whose slope explains nothing (`pitcher_outs` r²=0.01)
are flagged unusable and left in raw points rather than converted through noise.

**Status: MEASURED HERE, SETTLED in method.** The identification strategy is
sound; the numbers will drift as markets change and should be re-run periodically.

---

## 5. Stake sizing — fractional Kelly on the shrunk edge

**Choice.** Fractional Kelly, sized on the edge **after** shrinking it by the
lane's measured reliability `k = realised_pp / claimed_pp`.

**Why.** Kelly is exquisitely sensitive to the edge estimate, and estimated edges
are biased upward. Baker & McHale derive a shrinkage factor precisely for this;
the practical consensus is quarter-to-half Kelly. The asymmetry is what matters:
**overbetting loses growth far faster than underbetting**, and past ~1.5× Kelly
the growth rate can go negative outright.

`mlb/total` sits at **k=0.67** — it claims 6.17pp and delivers 4.12pp. Sizing on
the claim rather than the delivery oversizes by about half, turning a nominal
quarter-Kelly into ~0.37 Kelly. The shrink is applied to the **edge**
(`prob − implied`), never to the probability, because "shrink toward the market"
is the whole idea.

**Status: SETTLED.** Fractional Kelly with shrinkage under parameter uncertainty
is well established. The *fraction* (quarter) is JUDGEMENT.

---

## 6. The promotion gate

| Check | Value | Status |
|---|---|---|
| EV vs close | ≥ **+1.0%** | JUDGEMENT |
| Realised ROI | > 0 | SETTLED |
| Sample | n ≥ **30** | JUDGEMENT |
| Independence | ≥ **15 distinct days** | MEASURED HERE |
| Edge shrink | k ≥ **0.25** | JUDGEMENT |
| Capture rate | ≥ **60%** | JUDGEMENT |

**The EV floor is not zero, deliberately.** `EV > 0` let `mlb/moneyline` through
at **+0.09%** on 1,132 bets — t=+0.24, needing ~75,000 bets to distinguish from
zero. A coin flip wearing a plus sign, clearing a gate meant to authorise real
stakes. 1.0% sits below the live lane (+3.02%) and above the noise floor every
break-even lane occupies. **There is nothing magic about the number, only about
it not being zero.**

**The independence floor is the newest and the most earned.** `usa_mls/moneyline`
cleared every other check — EV +13.00%, ROI +7.9%, t=+2.28 "significant" — on 46
rows drawn from **four days, 63% of them from one**, entered a median 3.7 days
before kickoff, with a mean driven by outliers (median +5.98%; dropping the top 3
rows collapses it to +5.01%). A t-test assuming 46 independent observations is
simply the wrong test. The live lane, for contrast, is 215 rows across 60 days.

**The gate does not require statistical significance, and that is deliberate.**
Proving a real edge takes thousands of bets; industry guidance puts ~2,000 behind
a 57% win rate at 95% confidence. Requiring it would mean betting nothing for
months. The bet taken instead: several independent signals agreeing is enough to
size at quarter-Kelly on a small bankroll, where a false positive costs little
and waiting costs real edge. **Every gate line prints the t-statistic and the
sample a real verdict would need**, so "clears the gate" can never be read as
"proven".

---

## 7. What we do NOT claim

- **CLV on props is weaker evidence than on game lines.** Prop markets are less
  efficient — lower limits, algorithmic lines, less sharp shaping — which cuts
  both ways: it is where the biggest true edges live *and* where the close is
  noisiest as a benchmark.
- **The card record is not evidence the system works.** 89% of the +12.1% comes
  from two lanes that would fail today's gate.
- **Backtests here are not purged/embargoed cross-validation.** `mlb_batter_props`
  builds features point-in-time (`prior = logs[:i]`) and splits by season, which
  is sound. Other lanes have not been audited to that standard.
- **One lane is live.** Everything else is research.

---

## Sources

- [Buchdahl on closing line value](https://www.pinnacleoddsdropper.com/blog/closing-line-value--clv-demystified-by-expert-joseph-buchdahl)
- [Devigging methods compared — power, Shin, additive, multiplicative](https://betherosports.com/blog/devigging-methods-explained)
- [Outlier: how to devig](https://help.outlier.bet/en/articles/8208129-how-to-devig-odds-comparing-the-methods)
- [Kelly betting under parameter uncertainty (Baker & McHale)](https://arxiv.org/pdf/1701.02814)
- [Why fractional Kelly — simulations of bet size under uncertainty](https://matthewdowney.github.io/uncertainty-kelly-criterion-optimal-bet-size.html)
- [Pyckio: Pinnacle closing odds and market efficiency](https://blog.pyckio.com/en/eg-pinnacle-closing-odds/)
- [Sports Insights: statistical significance and sample size](https://www.sportsinsights.com/sports-investing-statistical-significance/)
- [Backtesting without overfitting — walk-forward, purging, embargo](https://www.greatbets.co.uk/how-to-backtest-a-sports-betting-strategy-without-overfitting/)
- [Feature freshness and point-in-time discipline](https://tacnode.io/post/feature-freshness-explained)

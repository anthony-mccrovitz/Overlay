1# ChefTonyBets — Product Plan & Roadmap
**Last updated: April 16, 2026**

---

## The Vision
A fully automated sports betting edge detection platform that generates daily picks across MLB, NBA, and eventually all major sports — delivered to paying subscribers via Discord, email, and a web dashboard. Built on a real quantitative model with transparent graded results.

**Revenue target: $10,000/month**

---

## Where We Are Right Now

### What's Built ✅
- MLB moneyline, run line, totals edge detection model
- Pitcher props model (K strikeouts — working well)
- NRFI / YRFI model (80% hit rate over 10 picks — best signal)
- NBA game model (spreads, totals, moneylines)
- NBA player props model (7 markets)
- Daily pick cards: ML, RL, totals, props, NRFI (PNG via Playwright)
- Graded results cards (Instagram Story format)
- Arb finder (finds guaranteed-profit opportunities across books)
- Monte Carlo arb simulator ($1k bankroll → P50 +127% over 162-game season)
- $50→$500 challenge tracker (current: $30.74)
- Auto-grading pipeline (grade.py fetches MLB Stats API + ESPN)

### Current Model Performance
| Market | Record | Hit Rate | Notes |
|--------|--------|----------|-------|
| NRFI/YRFI | 8-2 | **80%** | Best signal — post every day |
| Run Lines | 26-18 | **59.1%** | Solid, above break-even |
| Moneylines | 23-21 | **52.3%** | Marginal, needs improvement |
| Totals (card) | 11-14 | **44%** | BROKEN — model outputting placeholders |
| K Props | ~60%+ | **Good** | Fried, Sproat, Montero all hit today |
| TB/Hit Props | 0-6+ | **BAD** | Kill these until batter model is built |
| NBA Edges | N/A | **Miscalibrated** | Showing 46%+ edges — not real |

---

## Critical Bugs to Fix (In Order)

### 1. 🔴 Totals Model Outputting Placeholders
**Problem:** `PredictedTotal: 0.5`, `ModelProb: 0.0` — the model isn't computing real run projections. It's picking UNDERs based on edge% with no actual projected total. This is why totals hit rate is 44% (below break-even).

**Fix:** Build real run projection using:
- Starting pitcher ERA (last 5 starts weighted)
- Team wRC+ vs LHP/RHP
- Ballpark run factor
- Weather (wind speed/direction)

### 2. 🔴 Hit/TB Props Are Junk
**Problem:** Model projects `1.7 total bases` for every single batter regardless of matchup — it's a hardcoded default. 0-6 on these picks today.

**Fix:** Either build a real batter vs pitcher model or stop posting hit props entirely until it's built. Don't post picks that aren't real.

### 3. 🟡 NBA Model Miscalibrated
**Problem:** Showing 46%+ edges when real sharp models see 3-8%. Something is wrong in the probability conversion.

**Fix:** Audit the devig math and edge calculation. Cap displayed edges at 15% as a sanity check while investigating.

### 4. 🟡 No Recency Weighting
**Problem:** Using full season averages for everything. A pitcher with a 2.50 ERA in April but 5.00 ERA in his last 3 starts is treated identically.

**Fix:** Weight last 5 starts at 60%, season average at 40% for all pitcher-dependent models.

### 5. 🟡 No Ballpark Factor
**Problem:** Coors Field, Fenway, and pitcher-friendly parks are treated identically. This creates systematic errors in totals.

**Fix:** Add park factor multiplier table to totals model.

### 6. 🟢 NRFI Has No Odds Tracked
**Problem:** NRFI picks show `odds: null` — can't compute real P&L or Kelly sizing.

**Fix:** Pull NRFI odds from Odds API (`player_first_inning_score_no` market) or FanDuel scrape.

---

## Product Tiers & Revenue Model

```
ChefTonyBets Platform
│
├── FREE — Content / Top of Funnel
│   ├── Daily NRFI card (X + IG)
│   ├── 1 best moneyline pick per day
│   └── Weekly record recap card
│
├── BASIC — $19/month  →  target 200 subs = $3,800/mo
│   ├── Full 5-card daily slate (all markets)
│   ├── Kelly sizing on every pick
│   ├── Graded results card next morning
│   └── Discord access
│
├── SHARP — $49/month  →  target 100 subs = $4,900/mo
│   ├── Everything in Basic
│   ├── Arb alerts (validated algo)
│   ├── NBA picks during season
│   ├── Model edge % + reasoning per pick
│   └── Picks delivered at 9am vs noon for free tier
│
└── PRO / ALGO — $149/month  →  target 10 subs = $1,490/mo
    ├── Raw model output (JSON feed / API)
    ├── All sports (Champions League, NFL, NHL)
    ├── Arb finder API access
    └── 1:1 monthly strategy call
```

**At target numbers: $3,800 + $4,900 + $1,490 = $10,190/month**

---

## Build Roadmap

### Phase 1 — Fix the Foundation (This Week)
- [ ] Fix totals model → real run projections (park factor + pitcher ERA)
- [ ] Fix props → add last-5-starts data, remove hit/TB props
- [ ] Recalibrate NBA edges → realistic 3-8% range
- [ ] Build weekly recap card (cumulative record by market, auto-generated)
- [ ] Track NRFI odds so we have real P&L data

### Phase 2 — Content Machine (Month 1)
- [ ] Post every single day — cards already auto-generate
- [ ] Add: challenge bankroll update 2x/week (story arc content)
- [ ] Add: "model of the week" post showing sharpest market
- [ ] Pin best NRFI graded card on X profile
- [ ] **Goal:** 500 followers X, 200 IG

### Phase 3 — Monetization Infrastructure (Month 2)
- [ ] Build landing page in Next.js app (already scaffolded)
  - Record by market (auto-pulls from grades)
  - Sample pick card
  - Subscribe button → Stripe
- [ ] Build Discord bot that posts picks automatically at 10am
- [ ] Launch Basic tier at $19/mo
- [ ] **Goal:** 10 paying subscribers (proof of concept)

### Phase 4 — Scale (Month 3-4)
- [ ] Build arb execution tracker (validate real profitability)
- [ ] Launch Sharp tier at $49/mo with arb alerts
- [ ] Automate X + IG posting via cron
- [ ] Add weather API to totals model
- [ ] **Goal:** 50 paying subscribers = $1,500-2,500/mo

### Phase 5 — Full Product (Month 5-6)
- [ ] Subscriber web dashboard (picks + grades + personal bankroll tracker)
- [ ] Email delivery of daily picks (SendGrid)
- [ ] Add Champions League (soccer_uefa_champs_league via Odds API)
- [ ] Add NFL model ahead of season
- [ ] **Goal:** 150+ subscribers = $4,000+/mo

### Phase 6 — $10k/Month (Month 8-10)
- [ ] 200 Basic + 100 Sharp + 10 Pro = $10,190/mo
- [ ] Validated arb product as upsell
- [ ] Affiliate partnerships with sportsbooks (legal in most states)
- [ ] YouTube/TikTok longer-form content driving top of funnel

---

## Daily Workflow

### Morning (~30 min)
```bash
python3 run_picks.py              # generate today's slate
# Post NRFI card to X + IG       ← first, highest engagement
# Post ML card
# Post totals card
# Post run line card
# Post props card (K props only)
```

### Evening after games (~45 min)
```bash
python3 grade.py                              # auto-grade everything
python3 scripts/gen_results_card.py           # overall results card
python3 scripts/gen_results_card.py --nrfi    # NRFI graded card (post this)
# Update bankroll.json if challenge bet placed
# Post NRFI graded card → best performing content
# Post overall W-L for the day
```

### Weekly (Sunday)
```bash
# Post week-in-review card (build this)
# Show cumulative W-L by market
# Tease sharpest model signal for next week
```

---

## Arb Tracking Plan (Saved for Later)
Build a live arb execution log to validate real-world profitability before selling as a product.

**What to track:** date, game, leg1 (team/odds/book/stake), leg2, guaranteed_profit_pct, executed (bool), actual_result (both sides filled?), account health per book.

**Why:** Simulation shows P50 +127% ROI with all books, P50 +51% tier-1 only. Need to validate these assumptions with real money before selling as a product. Also need to measure how fast books limit accounts (model assumes 0.8% per arb).

**Product angle if validated:** "Arb Alert" — $50/month guaranteed-profit notifications. Tier above Sharp.

---

## Key Metrics to Track
| Metric | Current | 30-day Target | $10k Target |
|--------|---------|---------------|-------------|
| NRFI hit rate | 80% (n=10) | 75%+ (n=40) | 70%+ (n=150) |
| RL hit rate | 59% | 60%+ | 58%+ |
| Totals hit rate | 44% | 52%+ (after fix) | 54%+ |
| X followers | — | 500 | 5,000 |
| Paying subscribers | 0 | 10 | 310 |
| MRR | $0 | $190 | $10,190 |
| Challenge bankroll | $30.74 | $60+ | $500 (hit target) |

---

## The One Thing
**The NRFI model at 80% is the proof of concept.** Everything else — the website, the Discord, the pricing — is just packaging. Get to 30+ graded NRFI picks at 70%+ and you have something no other picks account can show. Build every piece of content and every product decision around making that number trustworthy and visible.

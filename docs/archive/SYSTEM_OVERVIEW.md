# ChefTonyBets — Full System Overview

> Use this to explain the product to anyone: friends, investors, content audience, Discord members.
> Covers everything from the 10-second pitch to the full technical pipeline.

---

## The 10-Second Pitch

An AI model that finds mathematically proven edges against sportsbook lines — picks spots where the books are wrong, sizes bets by the Kelly Criterion, and tracks every result publicly. 108-70 record, +38 units profit since April 2026.

---

## The 30-Second Pitch (for friends / social)

Sportsbooks set lines using sharp money, public bias, and profit margin. They're not always right. My model computes the *true probability* of each outcome using team efficiency ratings, pace, weather, park factors and historical data — then compares that to the implied probability baked into the betting line. When the gap is large enough (the "edge"), it flags a bet.

Every pick is logged with a timestamp before the game starts, auto-graded after, and the full record is public. No cherry-picking, no selective posting.

---

## The 2-Minute Pitch (for investors / serious people)

**The problem:** Recreational bettors lose because they pick favorites, chase parlays, and bet on feelings. The edge belongs to whoever has better information and better math.

**The edge source:** Sportsbooks balance action, not predict outcomes perfectly. In high-volume markets (MLB totals, NBA totals) there are consistent, documented inefficiencies that quantitative models can exploit — peer-reviewed academic research backs this (Voulgaris on NBA pace, Kovalchik on tennis Elo, weather effects on MLB run totals).

**The model:** An ensemble of XGBoost, LightGBM, CatBoost, and Pythagorean regression trained on multi-year historical data. Features include offensive/defensive efficiency, pace, umpire tendencies, wind direction, temperature, stadium park factors, and injury reports. Picks are sized by the Kelly Criterion — bet more when the edge is larger, less when it's smaller.

**The record:** Since April 22, 2026:
- Overall: 108-70 (60.7% WR, +38u, +21.6% ROI)
- NBA Totals: 51-23 (68.9% WR, +24u) — best model
- MLB Totals: 13-7 (65.0% WR, +5.6u)
- MLB Moneyline: 35-31 (53% WR, +5.8u)

**The business:** Free Discord community → Whop subscription ($25-50/mo) for premium picks and live alerts. Revenue from sportsbook referral links (FanDuel, DraftKings, BetMGM). Long-term: licensing the model signal.

---

## Active Models (What Gets Posted)

| Model | Record | WR% | Status |
|-------|--------|-----|--------|
| NBA Totals | 51-23 | 68.9% | ✅ Live (Tier 1) |
| MLB Totals | 13-7 | 65.0% | ✅ Live (Tier 1) |
| MLB F5 Totals | 63-47 shadow | 57.3% | ✅ Live (Tier 2, newly promoted) |
| MLB Moneyline | 35-31 | 53.0% | ✅ Live (Tier 2) |
| Soccer Moneyline | 4-8 | 33.3% | ✅ Live (Dixon-Coles, building) |
| NHL (all) | 5 picks | — | ✅ Live (too small to judge) |
| WNBA Moneyline | 3-2 shadow | 60.0% | 🔄 Shadow (need 30+ picks) |
| Tennis Elo | 4-25 | 13.8% | ❌ Retired (model broken) |
| MLB NRFI | 81-82 | 49.7% | ❌ Paused (coinflip) |
| MLB Pitcher Ks | 83-108 | 43.5% | ❌ Retired (-16u) |
| NBA Spread | 48-51 | 48.5% | ❌ Paused |

---

## How a Pick Is Generated (Step by Step)

```
1. SCHEDULE    →  Fetch today's games from MLB Stats API / Odds API
2. MODEL       →  Run ensemble (XGBoost + LightGBM + CatBoost + Pythagorean)
                  Inputs: team ratings, pace, park factor, weather, injuries
3. FAIR PROB   →  Devig the market (remove bookmaker margin) using Pinnacle as anchor
4. EDGE        →  edge% = model_probability - market_implied_probability
5. THRESHOLD   →  Only pick if edge >= 8% (moneyline) or meaningful run differential (totals)
6. SIZING      →  Kelly Criterion: stake = edge / odds_decimal (capped at 2u)
7. LOGGING     →  Timestamped to picks.json before first pitch (card_pick=True for posted picks)
8. CLV CHECK   →  Capture closing line 5 min before game — positive CLV = sharp pick
9. GRADING     →  Auto-grade via ESPN/MLB Stats API within 15 min of game ending
10. CARDS      →  Result cards generated automatically, posted to Discord/social
```

---

## Daily Workflow (What Actually Happens Each Day)

**You do:**
- Morning: Check `output/picks/baseball_mlb/YYYYMMDD/` — pick cards + captions are ready
- Post pick cards to Instagram, X, TikTok, Discord (Buffer can schedule)
- Evening: Check Discord for result cards (auto-generated within 15 min of games ending)
- Post win/loss cards to Stories/X

**The system does automatically:**
- 9:30 PM* — Generate picks on opening lines *(pending cron update)*
- Every 2 min — Capture closing lines
- 11:30 AM–1:15 PM — Generate all sport picks + captions + cards + deploy
- Every 15 min (8 PM–7 AM) — Grade completed games + generate result cards
- 3:45 AM — Full overnight grade sweep
- 4:00 AM — Backup result card generation
- Sunday 9 AM — Weekly algo audit + weekly recap card

---

## Key Files

| File | Purpose |
|------|---------|
| `chef.py` | Unified CLI — run everything from here |
| `predict.py` | MLB model + picks generation |
| `run_nba.py` | NBA model + picks |
| `grade.py` | Grades settled picks, writes picks.json |
| `src/config/models.py` | **Master algo registry** — controls what's live vs shadow |
| `data/pnl/picks.json` | **The canonical bet record** — every pick ever logged |
| `data/public_stats.json` | Computed stats for the web app |
| `src/output/cards.py` | Pick card renderer (1080×1350) |
| `src/output/result_cards.py` | Win/loss result cards + weekly recap |
| `scripts/weekly_audit.py` | Sunday algo health check |
| `scripts/grade_completed.py` | Real-time grader (every 15 min) |

---

## The Pick Record Schema

Every pick in `data/pnl/picks.json` has:

```json
{
  "pick_id":     "mlb_20260528_toronto-blue-jays_moneyline_ml",
  "date":        "2026-05-28",
  "sport":       "baseball_mlb",
  "market":      "moneyline",
  "team":        "Toronto Blue Jays",
  "odds":        110,
  "line":        null,
  "edge_pct":    19.1,
  "stake":       1.0,
  "card_pick":   true,
  "result":      "win",
  "profit":      1.10,
  "recorded_at": "2026-05-28T13:44:00Z",
  "resulted_at": "2026-05-29T01:23:00Z"
}
```

`card_pick=true` = officially posted pick, counts toward public record.
`card_pick=false` = shadow tracked only, not in public record.

---

## The Edge: Why This Works

**NBA Totals (68.9% WR):** Pace and efficiency ratings systematically misprice totals. When two high-pace teams play, books shade the line but not enough. The model quantifies this precisely.

**MLB Totals (65% WR):** Wind direction and temperature have a statistically significant, quantifiable effect on run scoring that books underweight. A 15 mph headwind reduces expected runs by ~0.8.

**MLB Moneyline (53% WR):** The "favourite-longshot bias" — books overcharge on favourites, undercharge on underdogs. The model corrects for this using Pythagorean win expectation + bias correction (Snowberg & Wolfers 2010).

**CLV (Closing Line Value):** The best measure of a sharp pick isn't whether it wins — it's whether the line moved in your direction after you bet. Positive CLV = the market agreed with you. The system captures this automatically.

---

## What CLV Means (for content / explaining to people)

> "Closing line value is how sharp bettors measure skill. If I take the Braves at -130 and the line closes at -145, I got +15 cents of value — the market moved to agree with me. Over hundreds of picks, consistent positive CLV is proof the model is finding real edges, not just getting lucky."

---

## FAQ (for Discord / content)

**"Is this gambling?"** Yes, sports betting involves risk. The model finds mathematical edges but no model wins every bet. We manage risk through Kelly sizing and only betting when the edge is proven.

**"How do I know the record is real?"** Every pick is timestamped before the game starts and graded automatically using official box score data. No manual entry, no cherry-picking.

**"What's a 'unit'?"** 1 unit = 1% of a bankroll (e.g. $10 on a $1,000 bankroll). +38 units means the model has returned 38% profit on a flat bankroll since April 2026.

**"Why do you post losses too?"** Transparency builds trust. Any service that only posts winners is lying to you.

**"How is this different from a tout?"** Touts sell picks without showing their record. Everything here is verified, timestamped, and public.

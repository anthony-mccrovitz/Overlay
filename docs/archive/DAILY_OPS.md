# ChefTonyBets — Daily Operations Guide

## How the System Works

```
MLB Stats API ──┐
Odds API ───────┼──► predict.py ──► picks.json ──► grade.py ──► public_stats.json ──► Web App
NBA Stats API ──┘        │
                         └──► output/picks/{sport}/{date}/
                               ├── picks.json
                               ├── pick_card.png
                               ├── props.json
                               ├── nrfi.json
                               └── caption_*.txt
```

**Model pipeline (MLB):**
1. Fetch today's schedule + team stats from MLB Stats API (free, no key needed)
2. Run 4-model ensemble: XGBoost + LightGBM + CatBoost + Pythagorean
3. Fetch live odds from Odds API (12 approved books)
4. De-vig Pinnacle to get fair probability (sharp benchmark)
5. Compare model probability vs market implied probability → find edges
6. Line shop all 12 approved books → surface best available odds
7. Output pick card, props, NRFI plays, captions

---

## Your 12 Approved Books

| Book | Best For |
|------|----------|
| FanDuel | Moneylines, spreads |
| DraftKings | Totals, moneylines |
| BetMGM | Totals, props |
| BetRivers | Alternatives when DK limited |
| Hard Rock Bet | Run lines |
| Fliff | Boosts, moneylines |
| Caesars | Spreads |
| Bet365 | International lines |
| Bally Bet | Totals |
| theScore Bet | Moneylines |
| Fanatics | Promos |
| Novig | Sharp alternative |

**Pinnacle** = sharp benchmark only. Never bet there. Use it to validate picks.

---

## Daily Terminal Commands

## Optimal Daily Schedule

| Time (ET) | Action | Command |
|-----------|--------|---------|
| **9-10am** | Generate picks on opening lines | `chef.py morning` |
| **12-2pm** | Re-check odds — opening sharp money has moved lines | `chef.py picks mlb --refresh` |
| **5-6pm** | **LATE LINE — best CLV window.** Bet this. | `chef.py picks mlb --late` |
| **5-6pm** | Place real bets at the late-line prices | *(place bets manually)* |
| **11pm-midnight** | Grade yesterday's picks, post results | `chef.py evening` |

**Why late line matters:** Sharp money moves MLB lines from 10am to 6pm. If you bet at 9am, you're getting the soft opening line — the market then corrects against you (negative CLV). Bet at 5-6pm after the market has settled. Your model edge is the same but you're betting into a sharper price that's less likely to move further.

---

### Morning — Generate Picks

```bash
# MLB picks for today
python3 chef.py picks mlb

# NBA picks for today
python3 chef.py picks nba

# Late-line refresh (run at 5-6pm — best time to bet)
python3 chef.py picks mlb --late
python3 chef.py picks nba --late

# Force-refresh odds cache anytime
python3 chef.py picks mlb --refresh
```

Output files land in:
```
output/picks/baseball_mlb/YYYYMMDD/
output/picks/basketball_nba/YYYYMMDD/
```

### Evening — Grade Results

```bash
# Grade both MLB + NBA (defaults to yesterday)
python3 chef.py grade

# Grade specific sport
python3 chef.py grade --sport mlb
python3 chef.py grade --sport nba

# Grade specific date
python3 chef.py grade --date 20260423
```

### Check Record Anytime

```bash
# Full record breakdown (card picks only — your actual bets)
python3 chef.py record

# Shadow record — all model picks (not just ones you bet)
# Use this to see if the algo is finding edges you're not betting
python3 chef.py record --shadow

# Filter by market
python3 chef.py record --market moneyline
python3 chef.py record --market total
python3 chef.py record --market spread
python3 chef.py record --market nrfi
python3 chef.py record --market prop

# Filter by sport
python3 chef.py record --sport mlb
python3 chef.py record --sport nba
```

### CLV Dashboard — Is the Algo Real?

```bash
# Show Closing Line Value report
# Positive avg CLV = you're finding edges before the market corrects
# Negative CLV = getting worse lines than closing (noise or weak model)
python3 chef.py clv

# Recompute from all date-specific archives (after adding new closing files)
python3 chef.py clv --refresh
```

**Interpreting CLV:**
- `+2%` avg CLV over 50+ picks = real edge. Scale up.
- `-2%` avg CLV = model is behind the market. Investigate.
- Under 50 picks = early data. Wait for sample.

### Utilities

```bash
# Refresh public_stats.json (web app data)
python3 chef.py stats

# Run all tests (58 tests, should always be green)
python3 chef.py test
# or: python3 -m pytest tests/ -v

# Migrate picks.json after schema changes
python3 chef.py migrate
```

---

## Pick Selection Logic

### What makes a pick go on the card

A pick appears on today's card when ALL of these are true:
1. **Model edge** — model win probability exceeds market implied probability by the minimum threshold (default 4%)
2. **AGREE signal** — Pythagorean and XGBoost models point the same direction (higher confidence)
3. **Real odds available** — Odds API returned live lines (picks with `odds=0` are never logged)
4. **`card_pick=False` by default** — picks are NEVER auto-marked as card picks. Only manually confirmed bets become card picks in the record.

### Edge calculation

```
model_edge = model_win_prob - pinnacle_fair_prob
pinnacle_fair_prob = de_vig(pinnacle_home_odds, pinnacle_away_odds)
```

If Pinnacle isn't available for a game, falls back to market consensus across all books.

### Line shopping

For each model pick, the system:
1. Fetches all 12 approved books via Odds API
2. Finds the book offering the best price for that pick
3. Surfaces it on the card with alternatives listed

---

## Bankroll Strategy

**Current:** 2% flat stake = $5 per bet on $250 bankroll

| Bankroll | Stake Per Bet |
|---------|--------------|
| $250 | $5 |
| $500 | $10 |
| $1,000 | $20 |

**Profit calculation:**
- Win at +140: `$5 × 1.40 = +$7.00`
- Win at -112: `$5 × (100/112) = +$4.46`
- Loss: `-$5.00` always

**Kelly sizing** (shown on card but use cautiously):
- Full Kelly is too aggressive. System uses 25% Kelly as a cap.
- Stick with 2% flat until sample size > 200 bets.

---

## Data Files

| File | Purpose |
|------|---------|
| `data/pnl/picks.json` | Canonical bet record — source of truth |
| `data/public_stats.json` | Computed stats for web API |
| `web/public/data/public_stats.json` | Mirror for Vercel/Next.js |
| `data/clv/snapshots.json` | Closing line value tracking |
| `data/odds_history/` | Historical odds for CLV analysis |
| `.env` | API keys (ODDS_API_KEY, etc.) |

### picks.json schema

```json
{
  "pick_id": "mlb_20260423_user_cubs-ml",
  "date": "2026-04-23",
  "sport": "mlb",
  "market": "moneyline",
  "direction": "home",
  "team": "Chicago Cubs",
  "matchup": "Philadelphia Phillies @ Chicago Cubs",
  "odds": 106,
  "line": null,
  "sportsbook": "FanDuel",
  "model_prob": 0.571,
  "edge_pct": 9.5,
  "stake": 5.0,
  "card_pick": true,
  "result": "win",
  "profit": 5.30,
  "recorded_at": "2026-04-23T12:00:00",
  "resulted_at": "2026-04-23T22:00:00"
}
```

**Key rules:**
- `card_pick=true` only for bets you actually placed
- `edge_pct` is percentage points (9.5 = 9.5%, NOT 0.095)
- `stake` is dollars (5.0 = $5)
- `profit` is dollars, positive = win, negative = loss

---

## Known Limits

| Resource | Limit | Action When Hit |
|----------|-------|-----------------|
| Odds API | 500 req/month (free tier) | Model still runs, no line shopping |
| MLB Stats API | Unlimited | No action needed |
| NBA Stats API | Rate limited | Add delays if hitting 429 errors |

**When Odds API hits 0:** Model predictions still generate. No live odds = no line shopping. Update `.env` with new key or wait for monthly reset.

---

## Current Record

Run `python3 chef.py record` for live numbers.

As of 2026-04-23:
- **Overall:** 17W-13L (56.7% WR) +5.07u +4.4% ROI
- **MLB:** 14W-12L (53.8%) +3.99u
- **NBA:** 3W-1L (75.0%) +1.07u
- **Totals submodel:** 6W-1L (85.7%) — strongest market

---

## Social Content Output

After running picks, cards and captions are ready at:

```
output/picks/baseball_mlb/YYYYMMDD/
├── pick_card.png          # Main moneyline card (post to Instagram/X)
├── runline_card.png       # Run lines card
├── totals_card.png        # Totals card
├── props_card.png         # Player props card
├── nrfi_card.png          # NRFI/YRFI card
├── pick_of_day_card.png   # Single best bet card
├── slate_card.png         # Full slate overview
├── caption_picks.txt      # Instagram/X caption for picks
├── caption_props.txt      # Caption for props card
└── caption_nrfi.txt       # Caption for NRFI card
```

Reddit POTD format: one pick, -200 to +200 odds, 1-5 units, include model record and description.

---

## API Keys (.env)

```bash
ODDS_API_KEY=your_key_here        # the-odds-api.com — line shopping
OPENWEATHER_API_KEY=your_key_here # weather adjustments on totals
```

Get a free Odds API key at: https://the-odds-api.com (500 req/month free, $79/mo for unlimited)

---

## Troubleshooting

**"Warning: Invalid ODDS_API_KEY"**
→ Check `.env` has correct key. Run: `python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.environ.get('ODDS_API_KEY'))"`

**"0 requests remaining"**
→ Odds API quota exhausted. Update key in `.env` or wait for monthly reset.

**Picks not grading**
→ Check `data/pnl/picks.json` has `result: null` for the picks. Run `python3 chef.py grade --date YYYYMMDD`.

**Tests failing**
→ Run `python3 chef.py test` — all 97 should pass. If failing, check brand name and schema constants.

**Web app not showing new data**
→ Run `python3 chef.py stats` to regenerate `public_stats.json`, then redeploy.

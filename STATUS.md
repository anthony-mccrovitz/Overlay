# Overlay — Status
**Updated: June 7, 2026**

This is the one true status doc. If it conflicts with anything in `docs/archive/`, this wins.

---

## What's Live Right Now

### Models running daily (automated, cron 9 AM ET)
| Model | Record | Status |
|-------|--------|--------|
| MLB Totals | 87-54 (61.7%) +29.0u | ✅ Live — post these |
| NBA Totals | included in overall | ✅ Live |
| PGA Outright | track record building | ✅ Live (t2) |

### Models in shadow (tracking, not posting)
| Model | Record | Note |
|-------|--------|------|
| MLB Moneyline | 41-39 +4u | Shadowed May 30 — soft-book edge inflation |
| MLB F5 Totals | 63-47 shadow | Promoting after first 30 live picks |
| MLB Pitcher Ks | 83-108 -16u | Rebuild needed |
| NRFI | 81-82 -7u | Paused |
| Tennis Elo | 4-25 -8u | Shadow — keep tracking |
| Soccer Dixon-Coles | 4-8 -1.5u | Rebuilding |
| NASCAR / IndyCar / F1 | Elo shadow | Long runway |

### Overall season record (card picks only)
```
132W – 95L (58.2% WR) · +32.8u · +14.7% ROI
```

---

## What's Active Right Now

### June Challenge (started June 1)
- Bankroll: **$131.11** (started $200, down $68.89)
- Record: **1-4**
- Goal: $200 → $500 by June 30. Needs to turn around.
- Command: `python3 chef.py challenge`

### Franchise Tracker (started June 6)
- Shadow betting all 30 MLB teams: ML + RL fav (-1.5) + RL dog (+1.5)
- 84 bets logged, 80 settled. **Review date: June 30.**
- June 6 Day 1: 27W-29L (-3.5u). Dogs (+1.5) went 7-3 — most interesting signal.
- Command: `python3 chef.py franchise --leaderboard`

---

## Daily Commands

```bash
# Morning (run picks for today)
python3 chef.py morning

# Evening (grade yesterday)
python3 chef.py grade

# Record check
python3 chef.py record

# Voice brief (what to post + outreach scaffold)
python3 chef.py voice

# Franchise leaderboard
python3 chef.py franchise --leaderboard
```

---

## What's Next

| Priority | Item |
|----------|------|
| P1 | Turn around June Challenge — study the 4 losses, tighten pick criteria |
| P1 | Post consistently using voice brief (5 min/day, your words) |
| P1 | Build Twitter account from scratch — new account, new approach |
| P2 | Franchise tracker: watch dogs (+1.5) — early signal is real |
| P2 | MLB F5 Totals: 30 shadow picks in → evaluate for promotion |
| P3 | Email list — highest-value channel, zero platform risk |

---

## Architecture (short version)

```
chef.py morning  →  run_*.py  →  output/picks/{sport}/{date}/
                                  ├── picks.json
                                  ├── picks_card.png
                                  └── grades.json (after grade)

chef.py grade    →  grade.py  →  data/pnl/picks.json
                              →  data/public_stats.json
                              →  web/public/data/public_stats.json

chef.py voice    →  scripts/gen_voice_brief.py  →  output/briefs/voice_YYYYMMDD.md
```

**Source of truth for picks:** `data/pnl/picks.json`
**Source of truth for public record:** `data/public_stats.json`
**Schema:** `src/tracking/schema.py`

# ChefTonyBets — Daily Ops Checklist

## MORNING (9–10am ET)
### Algo (auto via cron)
- [ ] `predict.py --daily` runs at 9:00am → picks + cards generated
- [ ] `gen_caption.py` runs at 9:05am → captions ready

### Review & Post
- [ ] Check `output/picks/baseball_mlb/YYYYMMDD/` — verify picks look sane
- [ ] Post **NRFI card** (`nrfi_card.png`) to IG Story + X
- [ ] Post **MLB Picks card** (`pick_card.png`) to IG Feed + X
- [ ] Post **MLB Full Slate Story** (`mlb_story_card.png`) to IG Story
- [ ] Copy caption from `caption_nrfi.txt` / `caption_picks.txt`
- [ ] Log challenge bets on sportsbook (use Kelly sizing from daily ops)

### NBA (game days only)
- [ ] Run `python3 predict.py --sport nba --daily` if NBA games today
- [ ] Post **NBA Picks card** (`nba_pick_card.png`)
- [ ] Post **NBA Props card** (`nba_props_card.png`)
- [ ] Copy caption from `caption_picks.txt` in NBA folder

---

## EVENING (6–7pm ET)
- [ ] `predict.py --close` runs at 6:45pm → CLV snapshot captured
- [ ] Check line movement vs our opening pick (optional manual review)

---

## LATE NIGHT / NEXT MORNING (auto)
- [ ] `predict.py --grade` runs at 1:00am ET → results graded
- [ ] `public_stats.json` updated → web dashboard refreshes

---

## WEEKLY
- [ ] Check `logs/grade.log` — any grading errors?
- [ ] Check `data/pnl/picks.json` — record accurate?
- [ ] Post **Results card** showing week's record
- [ ] Update challenge bankroll post (honest — win or lose)
- [ ] Check CLV: `data/clv/snapshots.json` — are we beating closing lines?

---

## CONTENT CALENDAR
| Day | Content |
|-----|---------|
| Mon | MLB picks + NRFI + Full Slate story |
| Tue | MLB picks + NRFI + challenge update |
| Wed | MLB picks + NRFI + model explainer post |
| Thu | MLB picks + NRFI + CLV/record update |
| Fri | MLB picks + NRFI + weekend preview |
| Sat | MLB picks + NRFI + bankroll update |
| Sun | Weekly results recap + next week preview |

---

## CHALLENGE TRACKER
- Start: $50 | Target: $500
- Current bankroll: **$30.74**
- Record: **3-7-1**
- Rule: 1/3 Kelly sizing only. No flat bets. Max 4 bets/day.

---

## FILE LOCATIONS (quick ref)
```
Cards:    output/picks/baseball_mlb/YYYYMMDD/
          output/picks/basketball_nba/YYYYMMDD/
Captions: same folder as cards (caption_*.txt)
Logs:     logs/picks.log | logs/grade.log | logs/close.log
P&L:      data/pnl/picks.json
Challenge: data/challenge/bankroll.json
Stats:    data/public_stats.json
```

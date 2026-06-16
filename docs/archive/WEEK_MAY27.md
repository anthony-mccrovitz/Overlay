# Overlay — Week of May 27–June 1, 2026
*OddsJam playbook: authentic voice, real record, no AI slop.*

---

## Model P&L — Totals (as of May 27, 2026)

### Full Totals Breakdown by Sport

| Model | W-L | Win% | Profit | ROI |
|-------|-----|------|--------|-----|
| NBA total | 56-26 | 68.3% | +25.98u | +31.7% |
| NHL total | 5-2 | 71.4% | +1.57u | +22.4% |
| MLB total (full game) | 29-20 | 59.2% | +8.88u | +18.1% |
| MLB f5_total | 55-43 | 56.1% | **-2.09u** | **-2.1%** |
| Soccer totals | 1-8 | 14.3% | -3.55u | -39.3% |
| **ALL TOTALS** | **150-104** | **59.1%** | **+30.48u** | **+12.0%** |

### ⭐ Card Picks Only (officially posted picks)

> **65-27 (70.7%) +32.83u ROI +35.7%**

These are the model's highest-edge plays only — not every pick generated. This is the number to use publicly.

### What to know
- **NBA totals is the strongest model** (+31.7% ROI, 56-26). No NBA until June 4 (Knicks @ OKC Finals).
- **MLB F5 totals is net negative** (-2.09u) despite 56% win rate — vig kills it at that win rate. Post F5 card picks only, not the full model record.
- **Use card picks stat publicly**: 65-27 (70.7%) +32.83u. Always say "top-rated plays only, not every pick."
- **Overall system**: 946-943, -25.59u. Do not post this number. Be honest if directly asked.

---

## Week Content Plan — May 27–June 1

### Rules for every post this week
- Write every caption yourself. Use `gen_caption.py` for numbers only (edge %, odds, model prob).
- One post per platform per day. Quality over volume.
- Post losses the same format as wins — same night, no hiding.
- Reddit is off limits entirely this week (7-day suspension + r/sportsbook permanent ban).

---

### ✅ Tuesday May 27 — Establish

**Morning**
- [ ] Post `f5_card.png` to Instagram
  > *No NBA today so the model shifts to MLB. Best bet: Reds/Mets F5 UNDER 4.5 (-110 BetMGM). Model gives it 81.8% — market is at 51% implied. Andrew Abbott's been elite in the first 5 innings all season. F5 card picks: 65-27 (70.7%). Link in bio.*
- [ ] Post same pick to Twitter
  > *MLB F5 today: Reds/Mets UNDER 4.5 (-110 BetMGM)*
  > *Model: 81.8% | Market: 51% implied | Edge: +32%*
  > *Andrew Abbott in the first 5 innings is a different pitcher than Abbott in the 6th.*
  > *Card picks: 65-27 (70.7%) this season. Every pick logged before first pitch.*
  > *overlay-gray.vercel.app*

**Today (non-negotiable)**
- [ ] **Film and post TikTok #1** — 60 seconds, your face, phone camera
  - Hook: *"I'm a CS student at Purdue. I built an actual ML model for sports betting. It's been running publicly since March. Let me show you what 147 picks of real data looks like."*
  - Screen-record overlay-gray.vercel.app scrolling through equity curve + picks table
  - End: *"$29/month at the link in bio."*
- [ ] Fix Twitter header — swap World Series banner for screenshot of Overlay site
- [ ] Fix Twitter bio — change `52.4% WR` to `Totals model card picks: 65-27 (70.7%)`

**Evening**
- [ ] Tweet result: *"WIN/LOSS. Reds/Mets F5 UNDER. [score after 5 innings]. Card picks now [X]-[Y]."*

---

### Wednesday May 28 — Post + Tease

**Morning**
- [ ] `python3 chef.py picks mlb`
- [ ] Post `f5_card.png` to Instagram + Twitter (write your own 2-line caption)
- [ ] Add one line: *"Announcing something Sunday — 30-day public challenge. Details dropping this week."*

**Evening**
- [ ] Tweet result of today's pick

---

### Thursday May 29 — Post + Drop Challenge Rules

**Morning**
- [ ] `python3 chef.py picks mlb`
- [ ] Post `f5_card.png`

**Midday — standalone challenge announcement post**

Post on Twitter AND Instagram:
> *June Challenge — starting June 1.*
>
> *Here's how it works:*
> *— $200 starting bankroll*
> *— $20/bet (flat unit, no Kelly)*
> *— Totals model card picks only*
> *— Every bet slip posted before the game starts*
> *— Every result posted same night*
>
> *Goal: finish June profitable.*
>
> *Card picks are 65-27 (70.7%) on the season. June is the live test.*
> *Following along is free. overlay-gray.vercel.app*

**Evening**
- [ ] Tweet today's result

---

### Friday May 30 — Post + Show the Bankroll

**Morning**
- [ ] `python3 chef.py picks mlb`
- [ ] Post `f5_card.png`

**Midday**
- [ ] Screenshot your actual sportsbook app showing $200 balance. Post it.
  > *$200 loaded. Challenge starts Sunday. Every bet public.*
- [ ] **TikTok #2**: *"I'm putting $200 on my AI model for 30 days. Every bet public. Here's the model's record going in."* Show the Overlay equity curve.

**Evening**
- [ ] Tweet today's result

---

### Saturday May 31 — Post + Week Recap

**Morning**
- [ ] `python3 chef.py picks mlb`
- [ ] Post `f5_card.png`

**Midday — weekly recap post**

Run `python3 chef.py record` and post the honest week numbers:
> *Week recap — [X-Y] this week on totals.*
> *Best pick: [pick + result]*
> *Miss: [honest loss if any]*
> *Card picks season record: [X]-[Y] ([%])*
> *Challenge starts tomorrow. $200. All public.*

**Evening**
- [ ] Tweet today's result
- [ ] *"Last day before the challenge. First bet posts tomorrow morning."*

---

### Sunday June 1 — Evaluation + Challenge Day 1 🚀

**Morning — post first challenge bet**
- [ ] `python3 chef.py picks mlb`
- [ ] Screenshot bet slip **before the game** — post it
  > *Challenge Day 1. Bet #1: [pick]. $20 on [book]. Here we go.*

**Evening — sit-down evaluation (do this before posting results)**

Run:
```
python3 chef.py record
python3 chef.py record --sport mlb
```

Answer these 4 questions honestly and write them down:
1. What did the model go W-L this week?
2. Is the Overlay site showing live accurate data?
3. Can someone subscribe and pay at overlay-gray.vercel.app right now?
4. What was hardest to post this week — and why?

- [ ] Post Day 1 result when game settles
- [ ] Tweet week summary: followers gained, any DMs, what you're fixing next week

---

## June Challenge Rules (reference)

| Rule | Detail |
|------|--------|
| Starting bankroll | $200 |
| Bet size | $20/unit (flat, no Kelly) |
| Which picks | Totals model card picks only |
| Proof | Bet slip screenshot posted before game starts |
| Results | Posted same night |
| Primary book | FanDuel, BetMGM for best line |
| Goal | Finish June profitable |

**Content arc for June:**
- June 1: Day 1 bet slip
- June 4: NBA Finals — Knicks @ OKC OVER 215.5 (+16% edge) — featured play
- ~June 7: First week recap
- ~June 14: Midpoint check-in
- June 30: Final results — every bet, final P&L

---

## What NOT to do this week

| Stop | Why |
|------|-----|
| Posting to r/sportsbook | Permanent ban — do not touch |
| Creating alt Reddit accounts | Extends suspension, risks permanent ban |
| Auto-posting from gen_caption.py | Got you banned. Numbers only, write words yourself |
| Hashtag spam | Signals bot, hurts reach |
| Posting the overall system record (-25.59u) | That's not the model you're selling |
| Mixing F5 record with NBA totals record | Different models, different sports — keep separate |

---

*Generated May 27, 2026 | Run `python3 chef.py record --market total` to refresh P&L*

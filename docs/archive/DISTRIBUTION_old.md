# ChefTonyBets / Overlay — Daily Distribution Playbook

**Time budget: 30-60 min/day**
**Goal: Build audience → prove track record → convert to subscribers**

---

## Morning Routine (15-20 min, after `python3 morning.py`)

### Step 1: Post the Pick Card (5 min)
```
output/picks/baseball_mlb/YYYYMMDD/pick_card.png
```
- Platform: **Instagram feed post**
- Caption template:
  ```
  🎯 MLB Picks — [DATE]

  [PICK 1] [ODDS] (+X% edge)
  [PICK 2] [ODDS] (+X% edge)
  [PICK 3] [ODDS] (+X% edge)
  [PICK 4] [ODDS] (+X% edge)
  [PICK 5] [ODDS] (+X% edge)

  Season: [W]-[L] | +[PROFIT]u | [ROI]% ROI

  All picks AI-model backed. Link in bio for free slate card.

  #mlbbets #sportsbetting #mlb #freepicks
  ```
- Always include season record in caption — that's the trust signal.

### Step 2: Post the Slate Card to Stories (2 min)
```
output/picks/baseball_mlb/YYYYMMDD/slate_card.png
```
- Instagram Stories + X (Twitter)
- No caption needed — the card explains itself
- Add poll sticker: "Which game do YOU like today?" → drives engagement

### Step 3: Tweet the Top Pick (3 min)
```
Template:
🔥 Best Bet Today: [TEAM] ML [ODDS] @ [BOOK]

Model: [X]% | Market: [X]% | Edge: +[X]%

My model is finding value here because [one-sentence reason from edge drivers].

Season: [W]-[L], +[ROI]% ROI

Full slate 👇 [link to slate card image or landing page]
```

---

## Evening Routine (5-10 min, after games end + `python3 grade.py`)

### Step 4: Post Nightly Recap to Stories (5 min)
```
output/picks/recaps/YYYYMMDD.png  (once recap card feature is built)
```

Until recap card is automated, screenshot `track.py status` output or type manually:

```
Stories caption:
Last Night:
✅ [TEAM] [ODDS] — WIN +[PROFIT]u
✅ [TEAM] [ODDS] — WIN +[PROFIT]u
❌ [TEAM] [ODDS] — LOSS -1.0u
❌ [TEAM] [ODDS] — LOSS -1.0u

[W]-[L] | [ROI]% ROI season

Picks are free daily. Link in bio 🔗
```

**Why this matters:** People see the losses too. That's what makes you different from
scammy pick sellers who only show wins. Transparent track record = trust = conversions.

---

## Weekly (Tuesday or Wednesday, 20-30 min)

### Step 5: Reddit r/sportsbook Track Record Post
Post once per week when your record looks good. Format:

```
Title: "My ML model's MLB picks — Week [N] recap and methodology"

Body:
Week [N] results: [W]-[L], [PROFIT]u profit, [ROI]% ROI
Season to date: [W]-[L], [ROI]% ROI

[Brief model explanation: "I built an ensemble of Pythagorean expectation + XGBoost
on 65 features including real-time pitcher matchups, park factors, and line movement.
Finding edges where my model's win probability differs from market implied probability."]

[Link to pick card image if allowed, or just the record]
```

Rules:
- r/sportsbook allows track record posts. Picks-for-sale posts get removed.
- Position as "sharing my results" not "buy my picks"
- Respond to every comment — engagement = visibility

### Step 6: Twitter Thread (3x/week, 10 min each)
Pick one game from yesterday where your model was right OR wrong and explain it.

```
Template:
Thread: What my model saw on [TEAM] vs [TEAM] yesterday 🧵

1/ My model had [TEAM] at [X]%, market implied [Y]%. Edge: +[Z]%.
Result: [WIN/LOSS] [SCORE]

2/ Why the model liked [TEAM]:
- Pythagorean: [X]% vs opponent's [Y]%
- SP matchup: [pitcher] [ERA] vs [pitcher] [ERA]
- Last 10 games: [X]-[Y]

3/ What the market was missing:
[1-2 sentence explanation]

4/ CLV (Closing Line Value): opened [ODDS], closed [ODDS].
[Beat/missed] the close by [N] points → [positive/negative] CLV signal.

5/ Follow for daily picks. Full slate posted every morning.
[Link to Instagram or landing page]
```

---

## Channel Priority (ranked by ROI on your time)

| Channel | Effort | Follower Growth | Conversion | Priority |
|---------|--------|----------------|------------|----------|
| Instagram feed (pick card) | 5 min/day | High | High (bio link) | #1 |
| Instagram stories (slate + recap) | 5 min/day | Medium | Medium | #2 |
| Twitter/X (top pick + threads) | 10-15 min/day | Medium | Medium | #3 |
| Reddit (weekly track record) | 20-30 min/week | High (bursts) | Low | #4 |
| TikTok ("how I use AI to bet") | 30 min/week | Very high | Low | #5 (later) |

---

## What NOT to do

- **Don't post only wins.** Post every result. Transparency is the whole product.
- **Don't sell picks in Reddit posts.** You get banned and it looks scammy.
- **Don't buy followers.** The only number that matters is conversion to email/paid.
- **Don't post without the season record visible.** Every post should show W-L-ROI.
- **Don't ghost after a bad day.** Post the recap even when it's 0W-5L. That's what builds trust.

---

## Content Calendar (4-week view)

**Week 1 (now):** Daily pick cards + manual recaps. Establish posting rhythm.
**Week 2:** Add NRFI card as second daily post. Start Reddit weekly thread.
**Week 3:** Launch landing page. Bio link = email capture. Start Twitter threads.
**Week 4:** First 30+ bets settled. Post "30-day track record" breakdown post.
  This is your first real conversion play — show the receipts.

---

## The Conversion Funnel

```
Instagram post (free pick card)
    ↓
  Bio link → edgefinder.ai landing page
    ↓
  Email capture
    ↓
  Email: "Here's today's full slate (free)"
    ↓
  Email: "Here's last week's record: 18W-12L +12.4u"
    ↓
  Email: "Upgrade for $25/mo → today's picks + NRFI + Kelly sizing"
    ↓
  Stripe checkout
```

The track record email is the closer. Don't rush to Stripe. Build 30 days of
transparent results first. Then the conversion rate on that email will be high.

---

## Metrics to Track (weekly)

- Instagram: follower count, story views, link in bio clicks
- Landing page: email signups (once built)
- Track record: W-L, ROI, CLV vs closing line
- Twitter: impressions on pick threads
- Reddit: upvotes and comments on weekly post

---

## Quick Reference: Daily Commands

```bash
# Morning (8am)
python3 morning.py

# Post pick_card.png to Instagram + stories (slate_card.png)
open output/picks/baseball_mlb/$(date +%Y%m%d)/pick_card.png
open output/picks/baseball_mlb/$(date +%Y%m%d)/slate_card.png

# Evening (after games end)
python3 grade.py

# Check record for caption
python3 track.py card
```

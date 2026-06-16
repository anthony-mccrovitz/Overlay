# Distribution Strategy
**Updated: June 7, 2026**
**Handle: @getoverlay (all platforms)**

## Why the old approach failed

Templated AI captions pasted directly. Hashtag blocks. Scheduled Reddit drops with the same format every day. Instagram and Reddit both banned the accounts. New accounts running the same strategy get banned just as fast — the content pattern is what triggers it, not the account age.

The fix: human voice, AI scaffolded not AI-written. Platform-appropriate behavior. One record, everywhere.

---

## The brand

**Name:** Overlay
**Handle:** `@getoverlay` — same on every platform, no exceptions
**Tagline:** "Every pick timestamped before game time."
**What it means:** Your face, your voice, the model behind you. People follow the person. Overlay is the product they subscribe to.

**"Timestamped before game time"** — this is the differentiator nobody else can claim. Every pick goes into `data/pnl/picks.json` with a timestamp before the game starts. That's the receipts. That's what you say when someone asks how they know you didn't post it after.

---

## Cards (locked in)

Two cards, both generated daily by the pipeline:

**Calibration card** (`calibration_card.png`) — single pick, big bold format. `@GETOVERLAY` bottom center. Use this on Twitter, TikTok thumbnail, Instagram.

**Pick card** (`pick_card.png`) — full slate view, Overlay logo, team logos, `@getoverlay · overlay-gray.vercel.app` footer. Use this for the full slate post, Reddit, YouTube thumbnail.

Colors locked: dark navy background, blue accent (`#6366f1`/`#818CF8`), green for positive edge. Don't change this.

**Run `python3 chef.py picks mlb` to regenerate both cards with current branding.**

---

## Platform stack

### 1. Twitter/X — post here first, every day
New account: `@getoverlay`
One tweet per morning. Your words, built from the voice brief scaffold.
4 lines max. No hashtags in body. No emoji spam.

```
MLB UNDER 7.5 tonight — Mets @ Padres.

Both starters under 3.0 ERA last 5, wind blowing in, both bullpens fresh.
Model: 52% · Market: 50% · Edge: +1.4%

Totals: 87-54 (62%). Every pick logged before first pitch.
→ overlay-gray.vercel.app
```

Evening: tweet yesterday's result. One line. Always.
```
Yesterday: WIN. MLB UNDER 8.5, logged 10:47 AM. Model 59%, final 4-2.
Totals: 88-54 (62%). Season continues.
```

---

### 2. TikTok — highest discovery, record daily
New account: `@getoverlay`

30-60 seconds, face on camera, no script. Pick up phone, record, post.
- "Here's my pick tonight and why the model likes it"
- Show the calibration card on screen
- One stat, one reason, no hype language

**Cross-post the same video to YouTube Shorts and Instagram Reels.**
Key: download the original file before posting to TikTok (TikTok watermarks the video). Post the clean file to all three:
- TikTok → post directly
- YouTube Shorts → upload original
- Instagram Reels → upload original

One recording → three platforms. This is the force multiplier.

---

### 3. YouTube — weekly breakdown, long game
New channel: Overlay (face thumbnail)

One video per week, Sunday. 10-15 minutes.
Format: "Here's every pick I made this week, why I took each one, what hit, what missed."
Also: model explainer videos ("How I built an ML model that's 87-54 on totals").

The weekly recap is the highest-trust content you can make. Showing losses openly is more powerful than 10 wins.

YouTube Shorts (daily): the TikTok cross-post above. Same video, no extra work.

---

### 4. Beehiiv (email) — build this in parallel, own your audience
Set up at beehiiv.com — 10 minutes, free tier.

One email per day. Send it yourself by copying from the voice brief.
- Today's top pick + one paragraph of reasoning in your voice
- The record
- Link to overlay-gray.vercel.app

**Why email first:** If Twitter or TikTok bans your account, the email list survives. Every subscriber you add is yours forever. This is the only channel with no platform risk.

Link in every bio. Mention it in every TikTok. One CTA: "Free daily picks — link in bio."

---

### 5. Reddit — participate, don't post (yet)
New account: `@getoverlay`

**For 30 days: comments only. No posts.** Build karma first.

Daily habit:
- Find the r/sportsbook megathread or the game thread for your top pick
- Reply with one fact — not the pick, a stat. "Mets starter under 3.0 ERA last 5 starts."
- No link. No "DM me." Just the fact.

After 30 days of karma: post a picks thread. By then the account has credibility.

---

### 6. Instagram — June Challenge arc only
New account: `@getoverlay`

One post per day: bankroll update.
- "Day 7. $131 on the line."
- "Day 8 — WIN. $157 now."
- No hashtags. No pick spam.

That's a story. Stories build followers. Daily pick cards are spam.

---

### 7. Whop — set up now, charge July 1
Create a page at whop.com.

Free tier to start. List the record: "ML model. 87-54 on totals. Every pick logged before game time."

July 1: open paid tier at $29/month. Founding member rate.

Pricing ladder:
- $29/month — founding member (limited spots)
- $49/month — regular
- $99/month — premium (includes model breakdown + franchise tracker alerts)

Your verifiable timestamped record is what makes this work on Whop. Most services there can't prove anything.

---

### 8. Discord — later, paid only
Don't open Discord until you have 30+ paying customers. An empty server kills trust.

When you open it: free tier gets the email newsletter. Paid tier gets Discord (real-time picks, model alerts, Q&A). That's the upgrade path.

---

## TOS — what's safe, what isn't

| Platform | Safe | Never say |
|----------|------|-----------|
| Twitter/X | Picks, record, model stats, odds | "Guaranteed," "can't miss" |
| TikTok | Organic picks content, face video, model breakdowns | "Guaranteed," paid ads (banned for gambling) |
| YouTube | Everything — breakdowns, model explainers, recaps | Gambling ads without disclosure |
| Reddit | Organic participation, picks with methodology | Spam patterns, same template repeatedly |
| Instagram | Personal content, bankroll arc, results | Guaranteed wins, deceptive stats |
| Beehiiv | Everything | Nothing — email has no TOS issue |
| Whop | Built for this | "Guaranteed" picks |

The rule everywhere: "Model has 59%, market pricing 50%" is fine. "Can't miss tonight" is not.

---

## Complete daily system

### Morning (45 min total)

```bash
python3 chef.py voice    # → output/briefs/voice_YYYYMMDD.md
```

**Step 1 — Twitter (5 min)**
Open the brief → edit the tweet scaffold (change 2-3 words, make it yours) → post.
Attach the calibration card PNG.

**Step 2 — TikTok/Shorts/Reels (10 min)**
Record 30-60 seconds on your phone:
- Show the pick, explain the reasoning in plain english
- One stat from the model notes
- "Timestamped before game time, record in bio"
Save the original → post to TikTok, YouTube Shorts, Instagram Reels (3 platforms, 1 video).

**Step 3 — Beehiiv email (5 min)**
Copy the tweet text + add 1-2 sentences of context → send.

**Step 4 — Outreach (15 min)**
From the brief's outreach block:
- Search Twitter for the matchup → reply to 3 conversations with a fact, no link
- Find the r/sportsbook megathread → one reply with a stat
- DM anyone who engages: "Want today's slate for free? [Beehiiv link]"

**Step 5 — Reddit (5 min)**
One comment in the game thread. A fact. No link.

---

### Evening (5 min)

Tweet yesterday's W/L result. One line.

---

### Weekly — Sunday (45 min)

**YouTube video (30 min record/upload):**
"Week in review — every pick, every result, what the model saw."
Post the calibration cards from the week as B-roll.

**Beehiiv newsletter (15 min):**
Week in review + next week's angles. What sports are coming up. What the franchise tracker is showing.

---

## The user acquisition funnel

```
Twitter/TikTok post (1 video/tweet per day)
    ↓
Outreach — reply to conversations, DM anyone who engages
    ↓
DM: "Want today's picks for free?" → Beehiiv signup
    ↓
Free email list — daily picks, build trust with the record
    ↓
After 2 weeks: "Paid tier launching July 1 — founding rate $29/month"
    ↓
Whop page → recurring revenue
    ↓
$29 × 100 people = $2,900/month
```

**The step everyone skips:** the DM. You can't convert from a post alone. Someone likes your tweet → you DM them. That's where subscribers come from.

Target: 3 DM conversations per day → 1 new email subscriber per day → 30 subscribers by end of June → 5-10 paid by July.

---

## Commands

```bash
python3 chef.py morning        # generate picks + cards + voice brief
python3 chef.py voice          # just the brief (if picks already ran)
python3 chef.py record         # current record for bio updates
python3 chef.py franchise --leaderboard   # franchise tracker
```

Voice brief output: `output/briefs/voice_YYYYMMDD.md`
Cards: `output/picks/baseball_mlb/YYYYMMDD/calibration_card.png`

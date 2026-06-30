# Operator's Manual — the only page you need

You have 80+ `chef.py` commands. **You use three of them.** Everything else is
either automatic (runs on cron/CI — you never type it) or occasional (you look
it up the once-a-month you need it). This page exists so you never have to hold
it all in your head.

---

## ☀️ Every morning — ONE command

```
python3 chef.py today
```

One screen: did the pipeline run, your record, and **what to actually bet today.**
🟢 = nothing needs you. 🔴 = it tells you exactly what to do. That's it. That's
your daily driver.

> An empty card is normal and correct — it means no market cleared its edge gate
> today. Posting nothing beats posting bad bets.

---

## 🤖 What runs itself (never type these)

| Runs automatically | When | You get pinged if… |
|---|---|---|
| Generate picks, grade, CLV capture | every day (GitHub Actions) | — |
| **Full test suite** (156 tests) | every push + daily 8:30 ET | a test goes red → **GitHub emails you** |
| Closing-line capture + scoring | continuously near game time | — |
| Web app deploy | on push | — |

**Silence means everything is fine.** You do not check these. They check
themselves and email you only when something breaks. That is the whole point of
the test/audit/validate work — so you can stop watching.

---

## 🔧 Occasional — look them up when you need them (≈monthly)

- `chef.py validate` — **are my models telling the truth?** Shows stated vs
  actual hit-rate per market. `✓ calibrated` = trust it. `⚠ OVERCONFIDENT` =
  don't trust its edge (it's correctly kept in shadow until fixed).
- `chef.py edge` — has any shadow market earned promotion to the live card?
- `chef.py promote <sport> <market>` — flip a market live (only when `edge` says so).
- `chef.py audit` — find any settled bet missing its closing line/CLV.
- `chef.py record` — full P&L breakdown by market + sport.

---

## 🧠 The mental model

You are **not** managing 81,000 lines of code. The machine is. Your job:

1. Glance at `chef.py today` each morning.
2. Trust the CI emails (red = look, silence = fine).
3. Once in a while, run `validate` to see which models are real.

**A model is valid only when it's BOTH `✓ calibrated` (validate) AND beats the
closing line (CLV).** The live card only ever contains markets that clear both —
so even a hidden bug in a shadow market can't cost you. The system is built to
protect you from what you don't have time to watch.

Everything else is noise you're allowed to ignore.

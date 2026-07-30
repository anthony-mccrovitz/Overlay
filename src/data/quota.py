"""One Odds API quota preflight, shared by every script that spends credits.

WHY IT IS SHARED. An exhausted quota is the nastiest failure this pipeline has,
because nothing about it looks like a failure: /v4/sports is free and keeps
answering 200 with a full sports list, so only the PAID calls 401. Each caller
then degrades differently — capture_closing turned the empty result into "this
game has no odds" and exited 0 (green, archived nothing), while odds_snapshot
died on a raw 401 traceback with no hint about the cause.

On 2026-07-30 a single exhausted key produced seven red runs across three
workflows overnight, each reporting a different-looking symptom.

So the check lives in ONE place with ONE message. This is the same discipline
`models._key` needed after six modules hand-rolled it and drifted: a rule that
every caller re-implements is a rule that eventually means six different things.

Credits cannot be recovered and neither can closing lines — a run that CANNOT
capture must be loud, not quiet.
"""
from __future__ import annotations

import os

# Below this, warn: a run that starts here may exhaust the budget mid-slate and
# lose the back half of the day's closing lines.
LOW_WATER = 250


def preflight_quota(log=print, *, allow_without_key: bool = False) -> tuple[bool, str]:
    """(ok, message). ok=False means: do not spend credits, exit non-zero.

    A network failure reaching the check returns ok=True: an unreachable
    preflight should not stop a run that might otherwise work. An exhausted or
    rejected key returns ok=False, because continuing there is guaranteed to
    archive nothing while looking like it tried.
    """
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        msg = "ODDS_API_KEY is not set — cannot fetch odds."
        if not allow_without_key:
            log(f"  FATAL: {msg}")
            return False, msg
        return True, msg

    try:
        import requests
        r = requests.get("https://api.the-odds-api.com/v4/sports",
                         params={"apiKey": key}, timeout=15)
    except Exception as e:                       # network flake: let it try
        msg = f"preflight quota check failed ({type(e).__name__}) — attempting anyway"
        log(f"  WARN: {msg}")
        return True, msg

    if r.status_code in (401, 429):
        msg = (f"Odds API rejected the key (HTTP {r.status_code}). Quota exhausted "
               f"or key invalid: {r.text[:120]}")
        log(f"  FATAL: {msg}")
        return False, msg

    try:
        remaining = int(r.headers.get("x-requests-remaining", "-1"))
    except (TypeError, ValueError):
        remaining = -1

    if remaining == 0:
        msg = ("Odds API quota EXHAUSTED (0 remaining). Closing lines are NOT "
               "being captured and this window's CLV is being lost permanently. "
               "Top up the plan or cut request volume.")
        log(f"  FATAL: {msg}")
        return False, msg
    if 0 < remaining <= LOW_WATER:
        msg = f"only {remaining} Odds API requests remaining"
        log(f"  WARN: {msg} — this run may exhaust the budget mid-slate.")
        return True, msg
    return True, f"{remaining} requests remaining" if remaining >= 0 else "quota unknown"

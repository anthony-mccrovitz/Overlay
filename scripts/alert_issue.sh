#!/usr/bin/env bash
# Deliver a pipeline alarm to the repo owner as a GitHub issue.
#
# WHY THIS IS ITS OWN SCRIPT: the alert used to be inlined in monitor.yml, and it
# was broken for 12+ consecutive days without anyone noticing. The integrity
# monitor correctly went RED every single day from 2026-07-18 onward, and every
# single one of those alarms died here instead of reaching a human. Two causes,
# both fixed below:
#
#   1. `gh issue list --search \"$title in:title\"` — the backslash-quotes are
#      literal inside a YAML block scalar, so gh received `\"Pipeline` and
#      `in:title\"` as separate bare args and exited 1 with "unknown arguments".
#      Fixed by matching on LABEL + exact title via jq, so no search syntax (and
#      no emoji in a query string) is involved at all.
#   2. The step ran under `bash -e`, so that failed assignment killed the script
#      before either the comment branch or the create branch could run. Fixed by
#      never letting a probe abort the script, and by checking outcomes explicitly.
#
# Extracting it also makes the weekly canary meaningful: alert-canary.yml runs
# THIS script, so a delivery regression fails the canary. A notifier that is
# never exercised is not a notifier.
#
# Usage:  alert_issue.sh <title> <body-file>
# Env:    ALERT_ASSIGNEE (default anthony-mccrovitz), ALERT_LABEL (default alert)
# Output: the issue number on stdout.
# Exit:   0 only if the alarm is verifiably sitting in an open issue.

set -uo pipefail

title="${1:?usage: alert_issue.sh <title> <body-file>}"
body_file="${2:?usage: alert_issue.sh <title> <body-file>}"
who="${ALERT_ASSIGNEE:-anthony-mccrovitz}"
label="${ALERT_LABEL:-alert}"
stamp="$(date -u +%Y-%m-%dT%H:%MZ)"
# Wording only. The heartbeat reuses this exact delivery path (see heartbeat.yml)
# so that the channel carrying the daily digest is the same one carrying real
# alarms — if delivery breaks, the digest stops too, and you notice within a day.
intro="${ALERT_INTRO:-the pipeline alarm went RED}"
# Wording for a repeat delivery onto an existing thread. Separate from `intro`
# because "still RED" is right for a persisting alarm and wrong for a heartbeat,
# which is a fresh report each day rather than a recurrence of a problem.
recur="${ALERT_RECUR:-still RED}"
footer="${ALERT_FOOTER:-Fix the cause, then close this issue — the next RED run reopens one.}"

if [ ! -f "$body_file" ]; then
  echo "alert_issue: body file '$body_file' does not exist" >&2
  exit 1
fi
body="$(cat "$body_file")"
[ -n "$body" ] || body="(the alarm produced no output — that is itself worth investigating)"

# Find an already-open alarm with this exact title. Label-scoped list + exact
# jq match: no search-query parsing, so titles may contain emoji, quotes, "in:",
# or anything else without breaking the lookup. `|| true` keeps a transient API
# failure from aborting the script before we get a chance to create the issue.
# Pick the OLDEST matching open issue (`min`, not `[0]`) so repeated alarms always
# converge on one canonical thread instead of ping-ponging between duplicates.
find_existing() {
  gh issue list --state open --label "$label" --limit 100 --json number,title 2>/dev/null \
    | jq -r --arg t "$title" '[.[] | select(.title == $t) | .number] | min // empty' \
      2>/dev/null || true
}

existing="$(find_existing)"
# Retry once after a beat. The issues LIST endpoint is eventually consistent, so
# a just-filed issue can be invisible for a second or two — without this, two
# runs in quick succession each conclude "nothing open" and file duplicates.
if [ -z "$existing" ]; then
  sleep 3
  existing="$(find_existing)"
fi

# Confirm the candidate is genuinely still open before commenting into it. The
# open-issues LIST lags reality by a few seconds, so an alarm resolved moments
# ago can still show up here; commenting on a closed issue would file the alarm
# somewhere nobody is looking. `issue view` is immediately consistent, so this
# demotes a stale hit back to "none found" and we create a fresh issue instead.
if [ -n "$existing" ]; then
  st="$(gh issue view "$existing" --json state -q .state 2>/dev/null || true)"
  [ "$st" = "OPEN" ] || existing=""
fi

if [ -n "$existing" ] && [ "${ALERT_ONCE:-0}" = "1" ]; then
  # ONE issue per outage, no re-ping. For a workflow that runs every 15 minutes
  # (capture-closing), commenting on each failure would post a dozen notifications
  # a day and teach you to filter the label — which is how the original twelve
  # silent days happened, just from the opposite direction. The daily monitor
  # still re-pings while the cause persists, so nothing goes quiet; it simply
  # doesn't alarm from two places at once.
  echo "$existing"
  exit 0
fi

if [ -n "$existing" ]; then
  # Re-ping rather than spawn a duplicate: an alarm that stays red for a week
  # should be one issue with seven comments, not seven issues.
  printf '@%s — %s at %s:\n\n```\n%s\n```\n' "$who" "$recur" "$stamp" "$body" \
    | gh issue comment "$existing" --body-file - >/dev/null
  rc=$?
  gh issue edit "$existing" --add-assignee "$who" >/dev/null 2>&1 || true
  if [ $rc -ne 0 ]; then
    echo "alert_issue: FAILED to comment on existing issue #$existing" >&2
    exit 1
  fi
  num="$existing"
else
  # Assign AND @mention: "assigned to you" and "mentioned" notifications are on
  # by default for every GitHub account and fire regardless of watch settings,
  # so this reaches you without you having to remember to check anything.
  # Take the number from `gh issue create` itself (it prints the new issue's
  # URL), NOT from a follow-up list query. The issues LIST endpoint is eventually
  # consistent: a create-then-list round trip really does come back empty for a
  # moment, which made the first version of this script report "delivery could
  # not be verified" for an issue it had just successfully filed.
  url="$(printf '@%s — %s at %s.\n\n```\n%s\n```\n\n%s\n' \
           "$who" "$intro" "$stamp" "$body" "$footer" \
         | gh issue create --title "$title" --assignee "$who" --label "$label" \
             --body-file - 2>/dev/null || true)"
  num="${url##*/}"
  if ! printf '%s' "$num" | grep -Eq '^[0-9]+$'; then
    echo "alert_issue: FAILED to create issue titled '$title' (got '$url')" >&2
    exit 1
  fi
fi

# Verify rather than assume. The whole failure mode being fixed here is a
# delivery path that reported success while delivering nothing, so the script
# only exits 0 once it can independently SEE an open issue. `issue view` is a
# direct object fetch, so unlike `issue list` it is immediately consistent.
if [ -z "$num" ]; then
  echo "alert_issue: delivery could not be verified — no issue number" >&2
  exit 1
fi
state="$(gh issue view "$num" --json state -q .state 2>/dev/null || true)"
if [ "$state" != "OPEN" ]; then
  echo "alert_issue: issue #$num reads back as '${state:-unreachable}', expected OPEN" >&2
  exit 1
fi
echo "$num"

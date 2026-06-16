#!/bin/bash
# Daily crontab self-check.
# Flags any non-comment cron line that runs a relative-path script (e.g.
# "scripts/foo.py") without first chdir'ing to the project root.
#
# Background: cron runs jobs from $HOME, not the project dir. A bare
# "/usr/local/bin/python3 scripts/foo.py" silently fails because the
# relative path doesn't resolve. The required pattern is:
#   cd /Users/anthonymccrovitz/march-madness && python3 scripts/foo.py
# OR an absolute path:
#   python3 /Users/anthonymccrovitz/march-madness/scripts/foo.py
#
# Writes to stdout (captured into logs/crontab_check.log by cron). Exits 1
# if any issues found so the log line is easy to grep.

PROJ="/Users/anthonymccrovitz/march-madness"
TS=$(date "+%Y-%m-%d %H:%M:%S")
ISSUES=0

# Pull current crontab
CRON=$(crontab -l 2>/dev/null)

while IFS= read -r line; do
    # Skip empty lines and comments
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue

    # Look for relative path patterns: " scripts/" or " bash scripts/"
    # that are NOT preceded by "cd $PROJ &&" AND are NOT an absolute path
    if echo "$line" | grep -qE '(^|[^/])(scripts|chef\.py|run_[a-z]+\.py|predict\.py)' ; then
        # Has a project-relative reference. Verify it's either chdir'd or absolute.
        if ! echo "$line" | grep -qE "cd $PROJ"; then
            if ! echo "$line" | grep -qE "$PROJ/(scripts|chef\.py|run_)" ; then
                echo "[$TS] ❌ BAD CRON LINE (relative path, no cd): $line"
                ISSUES=$((ISSUES+1))
            fi
        fi
    fi
done <<< "$CRON"

if [ "$ISSUES" -eq 0 ]; then
    echo "[$TS] ✓ crontab clean — all lines use cd-prefix or absolute paths"
    exit 0
fi

echo "[$TS] FOUND $ISSUES BROKEN CRON LINE(S) — fix by adding 'cd $PROJ &&' prefix"
exit 1

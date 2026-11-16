#!/bin/bash
# quiet.sh - run a long or chatty command (Blender, hython, renders, map and overlay runs) and print only what matters.
# Every later step of an agent reads its whole context again, so a long log costs on every step after it.
# Usage:  bash tools/quiet.sh <label> <command> [args...]
# Prints: exit code, the path of the full log, lines that look like results or problems, and the last 15 lines.
# The full log stays in review/logs/<label>_<time>.log - read it only where the summary points to a problem.
label="${1:-run}"; shift
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
logdir="$here/review/logs"; mkdir -p "$logdir"
log="$logdir/${label//[^A-Za-z0-9_.-]/_}_$(date +%Y%m%d_%H%M%S).log"
"$@" > "$log" 2>&1; code=$?
echo "EXIT $code  LOG $log  ($(wc -l < "$log") lines)"
grep -E -i '(^[A-Z][A-Z_]{2,}[: ]|error|exception|traceback|warn|fail|fatal|not found|missing)' "$log" \
  | grep -v -E -i '^(Fra:|Read prefs|Blender quit)' | awk '!seen[$0]++' | head -n 40
echo "--- last 15 lines"
tail -n 300 "$log" | grep -v -E '^(Fra:|Read prefs)' | tail -n 15
exit $code

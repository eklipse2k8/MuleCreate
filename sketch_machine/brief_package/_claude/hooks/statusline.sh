#!/bin/bash
# statusLine (v4 #9): Claude Code passes the plan usage on stdin (rate_limits.five_hour / seven_day .used_percentage);
# this script writes it to review/gate/usage.txt (weekly=<n> 5h=<n> time=<iso>), at most once a minute, so the main
# chat needs no usage watcher of its own. Prints one short status line. No model turn, no tokens.
HOOKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
while IFS='=' read -r k v; do v="${v%$'\r'}"; case "$k" in WORK) WORK="$v";; LEVEL) LEVEL="$v";; esac; done < "$HOOKDIR/gate.conf"
[[ -f "$HOOKDIR/gate.local.conf" ]] && while IFS='=' read -r k v; do v="${v%$'\r'}"; [[ $k == LEVEL ]] && LEVEL="$v"; done < "$HOOKDIR/gate.local.conf"
input="$(cat)"
pct() {   # used_percentage inside the object named $1
  local re="\"$1\": ?\\{[^}]*\"used_percentage\": ?([0-9.]+)"
  [[ $input =~ $re ]] && printf '%s' "${BASH_REMATCH[1]}"
}
h5="$(pct five_hour)"; wk="$(pct seven_day)"
G="$WORK/review/gate"
if [[ -n $WORK && -d $G && ( -n $h5 || -n $wk ) ]]; then
  printf -v now '%(%s)T' -1
  uf="$G/usage.txt"; age=999; [[ -f $uf ]] && age=$(( now - $(date -r "$uf" +%s) ))
  if (( age >= 60 )); then
    printf -v iso '%(%Y-%m-%dT%H:%M:%S)T' -1
    printf 'weekly=%s 5h=%s time=%s source=statusline\n' "${wk:-0}" "${h5:-0}" "$iso" > "$uf.tmp" && mv -f "$uf.tmp" "$uf"
  fi
fi
printf 'Mule %s · 5h %s%% · week %s%%' "${LEVEL:-final}" "${h5:-?}" "${wk:-?}"
exit 0

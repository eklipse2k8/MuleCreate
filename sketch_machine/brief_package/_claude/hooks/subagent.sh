#!/bin/bash
# SubagentStart / SubagentStop (arg: start|stop): count running subagents and map agent_id -> role. Base: test 006.
# The gate logs every allowed Agent start in agents.log (col 6: epoch seconds, col 7: start type).
# v4 #1: an agent started with its agent type (agent_type = role) takes the oldest unmapped line of that role;
# one started by ROLE line (agent_type general-purpose) the oldest unmapped ROLE-line start - both within 3 minutes.
source "$(dirname "$0")/common.sh"
c=$active; if [[ $1 == start ]]; then c=$((c+1)); else c=$((c-1)); (( c < 0 )) && c=0; fi
echo "$c" > "$G/active_subagents"
pick=""
if [[ $1 == start && $agent != main ]]; then
  known=0
  [[ -f "$G/agent_roles.tsv" ]] && grep -q -F "$agent"$'\t' "$G/agent_roles.tsv" && known=1   # a resumed agent (v4 #8) keeps its line
  if (( ! known )); then
    declare -A used=()
    if [[ -f "$G/agent_roles.tsv" ]]; then
      while IFS=$'\t' read -r _id _r _u _it lno; do lno="${lno%$'\r'}"; [[ -n $lno ]] && used[$lno]=1; done < "$G/agent_roles.tsv"
    fi
    typed=0; [[ $atype =~ $re_roles ]] && typed=1
    k=0; r="unknown"; (( typed )) && r="$atype"; u="-"; it="-"
    if [[ -f "$G/agents.log" ]]; then
      while IFS=$'\t' read -r _t lr lu lit _d ep tp; do
        k=$((k+1)); ep="${ep%$'\r'}"; tp="${tp%$'\r'}"; [[ -z $tp ]] && tp=gp
        [[ -n ${used[$k]} ]] && continue
        [[ $ep =~ ^[0-9]+$ ]] || continue
        (( now - ep > 180 )) && continue
        if (( typed )); then [[ $tp == "$atype" ]] || continue; else [[ $tp == gp ]] || continue; fi
        r="$lr"; u="$lu"; it="$lit"; pick=$k; break
      done < "$G/agents.log"
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' "$agent" "$r" "$u" "$it" "$pick" >> "$G/agent_roles.tsv"
    # v4 #7: a viewer's start mark for the file check at its end
    [[ $r == viewer ]] && : > "$G/viewer_${agent}.start"
  fi
fi
printf '%s\tSUBAGENT-%s\t%s\t%s\n' "$ts" "$1" "$agent" "$atype" >> "$G/tools.log"
# v4 #7: a viewer that changed project files -> VETO line for the main chat
if [[ $1 == stop && -f "$G/viewer_${agent}.start" ]]; then
  ch="$(/usr/bin/find "$WORK" -type f -newer "$G/viewer_${agent}.start" \( -name '*.hip*' -o -name '*.blend' -o -name '*.hda' -o -name '*.usd*' -o -path "$WORK/export/*" \) -not -path "$WORK/review/*" 2>/dev/null | head -n 20 | tr '\n' ';')"
  if [[ -n $ch ]]; then
    printf '%s\tviewer %s changed project files: %s\n' "$ts" "$agent" "$ch" >> "$G/viewer_veto.log"
    printf '%s\tVETO\t%s\tviewer\t%s\n' "$ts" "$agent" "$ch" >> "$G/tools.log"
  fi
  mv -f "$G/viewer_${agent}.start" "$G/viewer_${agent}.checked"
fi
# v4 #17 token account: the stopping agent's own transcript, each message counted once -> review/gate/agent_tokens.tsv
if [[ $1 == stop && $agent != main ]]; then
  atp=""; re='"agent_transcript_path": ?"(([^"\]|\.)*)"'; [[ $input =~ $re ]] && atp="${BASH_REMATCH[1]}"
  if [[ -z $atp ]]; then
    tp=""; re='"transcript_path": ?"(([^"\]|\.)*)"'; [[ $input =~ $re ]] && tp="${BASH_REMATCH[1]}"
    [[ -n $tp ]] && atp="${tp%.jsonl}/subagents/agent-${agent}.jsonl"
  fi
  atp="${atp//\\//}"
  if [[ -f $atp ]]; then
    tok="$(awk 'index($0, "\"usage\"") {
        id = ""; if (match($0, /"id": ?"msg_[^"]+"/)) id = substr($0, RSTART, RLENGTH)
        if (id != "" && seen[id]++) next
        n = split("input_tokens cache_creation_input_tokens cache_read_input_tokens output_tokens", k, " ")
        for (i = 1; i <= n; i++) if (match($0, "\"" k[i] "\": ?[0-9]+")) { s = substr($0, RSTART, RLENGTH); sub(/.*: ?/, "", s); t[i] += s }
      } END { printf "%d\t%d\t%d\t%d", t[1], t[2], t[3], t[4] }' "$atp")"
    r="-"; u="-"; it="-"
    [[ -f "$G/agent_roles.tsv" ]] && while IFS=$'\t' read -r id rr uu ii _x; do [[ $id == "$agent" ]] && { r="$rr"; u="$uu"; it="$ii"; }; done < "$G/agent_roles.tsv"
    mins="-"; st0="$(grep -F $'\tSUBAGENT-start\t'"$agent" "$G/tools.log" 2>/dev/null | head -n 1 | cut -c1-19)"
    [[ -n $st0 ]] && s0="$(date -d "$st0" +%s 2>/dev/null)" && mins=$(( (now - s0) / 60 ))
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$ts" "$agent" "$r" "$u" "$it" "$tok" "$mins" >> "$G/agent_tokens.tsv"
  fi
fi
# a stopping agent releases the live sessions it held
if [[ $1 == stop && $agent != main ]]; then
  for lk in "$G"/lock_*; do
    [[ -f $lk ]] || continue
    IFS=$'\t' read -r owner _s < "$lk"
    [[ $owner == "$agent" ]] && rm -f "$lk"
  done
fi
# shared files (rule 13): SHARED_FILES in gate.conf are read-only; a builder that asked for some with
# "SHARED:" in its prompt (the gate wrote shared_requests.tsv with its agents.log line) holds them alone.
shared=""; while IFS='=' read -r k v; do [[ $k == SHARED_FILES ]] && shared="${v%$'\r'}"; done < "$HOOKDIR/gate.conf"
if [[ -n $shared ]]; then
  lockof() { local f="$1"; f="${f//\//_}"; f="${f//\\/_}"; echo "$G/filelock_${f//./_}"; }
  setro()  { [[ -f "$WORK/$1" ]] && attrib "$2" "$(cygpath -w "$WORK/$1")" >/dev/null 2>&1; }
  if [[ $1 == start && $agent != main && -n $pick && -f "$G/shared_requests.tsv" ]]; then
    while IFS=$'\t' read -r lno files; do
      files="${files%$'\r'}"
      [[ $lno == "$pick" ]] || continue
      IFS=';' read -ra req <<< "$files"
      for f in "${req[@]}"; do [[ -n $f ]] || continue; printf '%s\t%s\n' "$agent" "$now" > "$(lockof "$f")"; setro "$f" -R; done
    done < "$G/shared_requests.tsv"
  fi
  if [[ $1 == stop && $agent != main ]]; then
    for lk in "$G"/filelock_*; do
      [[ -f $lk ]] || continue
      IFS=$'\t' read -r owner _s < "$lk"; [[ $owner == "$agent" ]] && rm -f "$lk"
    done
  fi
  # every shared file without a live holder is read-only
  IFS=';' read -ra all <<< "$shared"
  for f in "${all[@]}"; do
    [[ -n $f ]] || continue
    lk="$(lockof "$f")"; held=0
    if [[ -f $lk ]]; then
      IFS=$'\t' read -r owner since < "$lk"; since="${since%$'\r'}"; held=1
      grep -q -F $'\tSUBAGENT-stop\t'"$owner" "$G/tools.log" 2>/dev/null && held=0
      [[ $since =~ ^[0-9]+$ ]] && (( now - since > 3600 )) && held=0
      (( held )) || rm -f "$lk"
    fi
    (( held )) || setro "$f" +R
  done
fi
exit 0

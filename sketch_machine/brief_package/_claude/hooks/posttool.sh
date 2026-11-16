#!/bin/bash
# PostToolUse: log every tool call (time, agent, role, tool, build flag); every N calls of each agent re-inject the RULES.
# v4 #11: main chat context above HANDOVER_AT -> one reminder per 100 k to write review/conductor_handover.md.
# v4 #9: main chat starts an agent while review/gate/usage.txt is missing or older than 20 min (status line not running) -> reminder (at most every 10 min).
source "$(dirname "$0")/common.sh"
printf '%s\t%s\t%s\t%s\t%s\n' "$ts" "$agent" "$role" "$tool" "$is_build" >> "$G/tools.log"
# v4 #17 traces: duration and fingerprint of an expensive call (start mark written by pretool_build.sh)
if [[ -n $tuid && -f "$G/t_${tuid}" ]]; then
  read -r t0 fp < "$G/t_${tuid}"; rm -f "$G/t_${tuid}"; fp="${fp%$''}"
  dur=$(( now - t0 )); u="$(unit_of "$agent")"; [[ $agent == main ]] && u="-"
  mark=""; (( dur >= 60 )) && [[ -f "$G/commands.log" ]] && awk -F'	' -v f="$fp" '$6 == f && $5 >= 60 { x = 1 } END { exit !x }' "$G/commands.log" && mark="REPEAT"
  txt="${cmd}${code}"; txt="${txt//$'	'/ }"; txt="${txt:0:160}"
  printf '%s	%s	%s	%s	%s	%s	%s	%s
' "$ts" "$agent" "$role" "$u" "$dur" "$fp" "$mark" "$txt" >> "$G/commands.log"
fi
cf="$G/count_${agent}"; n=0; [[ -f "$cf" ]] && n="$(<"$cf")"; [[ $n =~ ^[0-9]+$ ]] || n=0; n=$((n+1)); echo "$n" > "$cf"
rules_due=0
# v5.1: the main chat keeps the full rules through CLAUDE.md (also after a compaction); only agents get the headline reminder
if [[ $agent != main ]] && { (( n % ${REMIND_EVERY:-30} == 0 )) || [[ -f "$G/rules_due_${agent}" ]]; }; then rules_due=1; fi
msg=""
# v5.1: a builder whose context passes BUILDER_HINT_AT gets one hint to hand over at a clean point (no block; rule 17)
if [[ $agent != main && $role == builder && ${BUILDER_HINT_AT:-0} -gt 0 && ! -f "$G/builder_hint_${agent}" ]]; then
  tp=""; re='"transcript_path": ?"(([^"\]|\.)*)"'; [[ $input =~ $re ]] && tp="${BASH_REMATCH[1]}"; tp="${tp//\\//}"
  sp="${tp%.jsonl}/subagents/agent-${agent}.jsonl"
  if [[ -f $sp ]]; then
    line="$(tail -c 2000000 "$sp" | grep -F '"usage"' | tail -n 1)"; i=0; cc=0; cr=0
    re='"input_tokens": ?([0-9]+)'; [[ $line =~ $re ]] && i="${BASH_REMATCH[1]}"
    re='"cache_creation_input_tokens": ?([0-9]+)'; [[ $line =~ $re ]] && cc="${BASH_REMATCH[1]}"
    re='"cache_read_input_tokens": ?([0-9]+)'; [[ $line =~ $re ]] && cr="${BASH_REMATCH[1]}"
    ctx=$((i + cc + cr))
    if (( ctx >= BUILDER_HINT_AT )); then
      : > "$G/builder_hint_${agent}"
      msg="GATE: your context is about $((ctx / 1000)) k tokens. Every further step reads all of it again: finish the current step, reach a clean point, write state note and report, and hand the rest over to the next run (rule 17)."
    fi
  fi
fi
if [[ $agent == main ]]; then
  tp=""; re='"transcript_path": ?"(([^"\]|\.)*)"'; [[ $input =~ $re ]] && tp="${BASH_REMATCH[1]}"; tp="${tp//\\//}"
  if [[ -n $tp && -f $tp ]]; then
    line="$(tail -c 3000000 "$tp" | grep -F '"type":"assistant"' | grep -F '"usage"' | grep -v -F '"isSidechain":true' | tail -n 1)"
    i=0; cc=0; cr=0
    re='"input_tokens": ?([0-9]+)'; [[ $line =~ $re ]] && i="${BASH_REMATCH[1]}"
    re='"cache_creation_input_tokens": ?([0-9]+)'; [[ $line =~ $re ]] && cc="${BASH_REMATCH[1]}"
    re='"cache_read_input_tokens": ?([0-9]+)'; [[ $line =~ $re ]] && cr="${BASH_REMATCH[1]}"
    ctx=$((i + cc + cr)); mk="$G/handover_mark"; last=-1; [[ -f $mk ]] && last="$(<"$mk")"; [[ $last =~ ^-?[0-9]+$ ]] || last=-1
    if (( ctx >= HANDOVER_AT )); then
      b=$(( (ctx - HANDOVER_AT) / 100000 ))
      if (( b > last )); then
        echo "$b" > "$mk"; echo "$((ctx / 1000))" > "$G/handover_due"   # v4 #19: the gate holds new agents until the hand-over is newer
        msg="GATE: your context is about $((ctx / 1000)) k tokens (above $((HANDOVER_AT / 1000)) k). Write the hand-over into review/conductor_handover.md now (state, open lanes, next steps) and go on: this chat compacts on its own and continues from it."
      fi
    elif (( last != -1 )); then echo "-1" > "$mk"; rm -f "$G/handover_due"
    fi
  fi
  if [[ $tool == Agent || $tool == Task ]]; then
    uf="$G/usage.txt"; st="$G/usage_reminded"; age=99999; [[ -f $uf ]] && age=$(( (now - $(date -r "$uf" +%s)) / 60 ))
    last=0; [[ -f $st ]] && last="$(date -r "$st" +%s)"
    if (( age > 20 && now - last > 600 )); then
      : > "$st"
      msg="${msg:+$msg }GATE: review/gate/usage.txt is missing or older than 20 minutes. The status line normally writes it; refresh it once by hand now (usage tool, then Write: one line weekly=<n> 5h=<n> time=<iso>). Set up no recurring job."
    fi
  fi
fi
if [[ -n $msg ]]; then
  (( rules_due )) && : > "$G/rules_due_${agent}"   # the rules follow with the next call
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s"}}' "$msg"
elif (( rules_due )) && [[ -f "$G/reminder.json" ]]; then
  cat "$G/reminder.json"; rm -f "$G/rules_due_${agent}"
fi
exit 0

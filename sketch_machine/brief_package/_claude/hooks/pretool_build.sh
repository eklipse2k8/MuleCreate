#!/bin/bash
# PreToolUse guard (rules 1-2), for the main chat and every subagent. Base: test 006; v4 changes marked "v4 #<n>".
#   - nobody changes the hooks, their settings, the agent types, the rules, the roles, the brief or the gate logs;
#   - nobody writes into review/*.md from the shell (v4 #10);
#   - each check report is written only by its own role (main chat: only "ABORTED" builder reports);
#   - main chat: no build tools, only read-only live tools (v4 #6), no scripts, SendMessage only to resume an ABORTED agent once (v4 #8);
#   - referee, engineer, stand-in: no build tools, no scripts; viewer: live tools to show, never a file (v4 #7);
#   - helper: no build tools once building has started.
source "$(dirname "$0")/common.sh"
deny() {
  printf '%s\tDENIED\t%s\t%s\t%s\t%s\n' "$ts" "$agent" "$role" "$tool" "$1" >> "$G/tools.log"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"GATE: %s"}}' "$2"
  exit 0
}
is_file_tool=0; [[ $tool == Write || $tool == Edit || $tool == NotebookEdit ]] && is_file_tool=1
is_shell=0; [[ $tool == Bash || $tool == PowerShell ]] && is_shell=1

# 0. hard deadline set by the artist (STOP_AT in gate.conf, epoch seconds): after it only .md notes may be written
stop_at=""; while IFS='=' read -r k v; do [[ $k == STOP_AT ]] && stop_at="${v%$'\r'}"; done < "$HOOKDIR/gate.conf"
if [[ $stop_at =~ ^[0-9]+$ ]] && (( now >= stop_at )); then
  re_md='\.md$'
  if (( is_shell || is_build || is_script_run )) || [[ $tool == SendMessage ]] || { (( is_file_tool )) && ! [[ $fpath =~ $re_md ]]; }; then
    deny deadline "the artist ended the test at its deadline. Do no more work: write your report or a short final state (.md) and end."
  fi
fi

# 1. protected files - v4 #9: the main chat's usage watcher may write review/gate/usage.txt (Write tool, one line weekly=<n> 5h=<n> ...)
re_usage='review[/\\]+gate[/\\]+usage\.txt$'
if (( is_file_tool )) && [[ $fpath =~ $re_prot_path ]]; then
  re_uc='"content": ?"weekly=[0-9.]+ +5h=[0-9.]+'
  if [[ $role == main && $tool == Write && $fpath =~ $re_usage ]]; then
    [[ $input =~ $re_uc ]] || deny usage "review/gate/usage.txt takes exactly one line: weekly=<percent> 5h=<percent> time=<iso>."
  else
    deny protected "this file belongs to the brief or to the gate and is not changed during a run. If it really must change, ask the artist."
  fi
fi
if (( is_shell && is_write_cmd )) && [[ $cmd =~ $re_prot_cmd ]]; then
  deny protected "this command would change the hooks, their settings, the agent types, the rules, the roles or the gate logs. Read files with the Read tool; changes only by the artist (settings by a message line SET: <key>=<value>)."
fi
# 1b. read-only protection of shared files is never lifted by an agent (rule 14) - not from the shell, not from a script
re_ro='(attrib(\.exe)?[\\" ]+[-+][rR]|attrib(\.exe)?[\\" ]+-|IsReadOnly|Set-ItemProperty[^"]*ReadOnly|os\.chmod|S_IWRITE|S_IWUSR|FILE_ATTRIBUTE_READONLY|SetFileAttributes)'
if (( is_shell )) && [[ $cmd =~ $re_ro ]]; then
  deny readonly "the write protection of shared files is set by the hooks only. Ask for the file with a line SHARED: <file> in the builder task."
fi
if [[ $tool == Write || $tool == Edit ]] && [[ $input =~ $re_ro ]]; then
  deny readonly "scripts may not change file attributes or permissions (write protection of shared files is set by the hooks only)."
fi
# 1c. shared text files are only added to (Edit), never rewritten whole - except by the engineer who tidies bauwissen
re_shared_txt='review[/\\]+(bauwissen|assumed)\.md$'
if [[ $tool == Write && $role != main && $role != engineer ]] && [[ $fpath =~ $re_shared_txt ]]; then
  deny sharedtext "add your lines to this shared file with Edit; never rewrite it whole (other agents add to it at the same time)."
fi
# 1d. v4 #10: no shell writes into review/*.md, for every role (redirection, tee, cmdlets, sed -i, cp/mv/rm, .NET writes)
if (( is_shell )); then
  shopt -s nocasematch
  P='[^[:space:]|;&>]*review[/\\]+[^[:space:]|;&]*\.md'
  re10='(>>?[[:space:]]*'"$P"'|tee([[:space:]]+-[A-Za-z-]+)*[[:space:]]+'"$P"'|(Set-Content|Add-Content|Out-File|Clear-Content|Remove-Item|Move-Item|Copy-Item|New-Item|Rename-Item)[^|;]*review[/\\]+[^[:space:]|;]*\.md|(sed[[:space:]]+-i|(^|[[:space:];&|(])(cp|mv|rm|del|truncate|dd)[[:space:]])[^|;&]*review[/\\]+[^[:space:]|;&]*\.md|(WriteAll|AppendAll)[A-Za-z]*[^;|]*review[/\\]+[^[:space:]|;]*\.md)'
  if [[ $cmd =~ $re10 ]]; then
    shopt -u nocasematch
    deny shellwrite "notes and reports in review/ are written with the Write or Edit tool, never from the shell (a shell command once emptied a plan). Read with Read, change with Edit."
  fi
  shopt -u nocasematch
fi

# 2. check reports belong to their role
re_rep='review[/\\]+(iter|units)[/\\]+([^/\\]+)_(builder|referee|qc|qc_r2|engineer)(_[0-9]+)?\.md$'
re_round='review[/\\]+round_qc(_r2)?\.md$'
re_targets='review[/\\]+units[/\\]+([^/\\]+)_targets\.md$'
if (( is_file_tool )) && [[ $fpath =~ $re_round ]] && [[ $role != qc ]]; then
  deny report "the round QC report is written only by ROLE: qc UNIT: ROUND."
fi
# v4 #14: picture targets only by a QC, and never by the QC that judges the unit (and the reverse)
if (( is_file_tool )) && [[ $fpath =~ $re_targets ]]; then
  [[ $role == qc ]] || deny report "picture targets are written only by a QC started with STAGE: targets."
  grep -q -F -x "$agent" "$G/qc_checkers.tsv" 2>/dev/null && deny report "you wrote a QC check report; the targets come from a different QC agent."
  printf '%s\n' "$agent" >> "$G/qc_targets_authors.tsv"
fi
if (( is_file_tool )) && [[ $fpath =~ $re_rep ]]; then
  kind="${BASH_REMATCH[3]}"; [[ $kind == qc_r2 ]] && kind=qc
  ppath="${fpath//\\\\//}"   # JSON-escaped backslashes -> forward slashes
  if [[ $role == main ]]; then
    if [[ $kind == builder && $tool == Write && $content_start =~ ^[[:space:]]*ABORTED && ! -f $ppath ]]; then :; else
      deny report "the main chat does not write check reports. Only a dead builder's report that does not exist yet may be written by the main chat, and it must start with ABORTED: <why>."; fi
  elif [[ $role == unknown ]]; then
    deny report "the hooks could not tell which role you are, so you cannot write a check report. Say so in your reply; the main chat must start you again with your agent type."
  elif [[ $role != "$kind" ]]; then
    deny report "a $role does not write a $kind report."
  elif [[ $kind == qc ]]; then
    grep -q -F -x "$agent" "$G/qc_targets_authors.tsv" 2>/dev/null && deny report "you wrote the picture targets of this unit; a different QC agent judges them (v4, targets and judging are split)."
    printf '%s\n' "$agent" >> "$G/qc_checkers.tsv"
  fi
  # a run report in review/iter belongs to the agent that wrote it first; no other agent overwrites it
  key="${ppath,,}"; key="${key//\\//}"
  if [[ $key == *review/iter/* ]]; then
    key="review/iter/${key##*review/iter/}"; ra="$G/report_authors.tsv"; owner=""   # owner = the last recorded writer of this file
    [[ -f $ra ]] && owner="$(awk -F'\t' -v k="$key" '$1 == k { a = $2 } END { print a }' "$ra")"
    # a file that is gone (moved away on a resume) is free again
    if [[ ! -f $ppath || -z $owner ]]; then [[ $owner == "$agent" ]] || printf '%s\t%s\n' "$key" "$agent" >> "$ra"
    elif [[ $owner != "$agent" ]]; then
      deny report "${key#review/iter/} was written by another run and is never overwritten. Put your full report into your final message and tell the main chat that the file name was taken."; fi
  fi
fi
if [[ $role == main ]] && (( is_shell && is_write_cmd )); then
  re='review[/\\]+iter|_(referee|qc|engineer)[^ ]*\.md'
  [[ $cmd =~ $re ]] && deny report "the main chat does not write check reports, not even from the shell."
fi

# 3. SendMessage - v4 #8: only the main chat, only to an agent whose report starts with ABORTED:, only once
if [[ $tool == SendMessage ]]; then
  [[ $role == main ]] || deny sendmessage "agents do not message other agents or the main chat; put it into your report."
  to=""; re='"to": ?"([^"]+)"'; [[ $input =~ $re ]] && to="${BASH_REMATCH[1]}"
  # another session of the app (local_<id>, e.g. the development chat that maintains these hooks) is not an agent of this run: allowed, logged
  if [[ $to == local_* ]]; then printf '%s\t%s\n' "$ts" "$to" >> "$G/session_messages.log"; exit 0; fi
  r=""; u=""; it=""
  if [[ -n $to && -f "$G/agent_roles.tsv" ]]; then
    while IFS=$'\t' read -r id lr lu lit _rest; do [[ $id == "$to" ]] && { r="$lr"; u="$lu"; it="$lit"; break; }; done < "$G/agent_roles.tsv"
  fi
  [[ -n $r ]] || deny sendmessage "agents are fresh: SendMessage only resumes an agent whose report starts with ABORTED: (by its agent id). '$to' is not an agent the hooks know. Start a new agent instead."
  case "$r" in builder|referee) rep="$WORK/review/iter/${it}_${r}.md";; qc) rep="$WORK/review/iter/${it}_qc.md";; *) rep="";; esac
  first=""; [[ -n $rep && -f $rep ]] && IFS= read -r first < "$rep"
  re_ab='^[[:space:]]*ABORTED'
  [[ $first =~ $re_ab ]] || deny sendmessage "only an agent whose report starts with ABORTED: may be resumed. $r $it has no such report; start a fresh agent."
  grep -q -F -x "$to" "$G/resumed.tsv" 2>/dev/null && deny sendmessage "$r $it was resumed once already. Start a fresh agent with the state note."
  printf '%s\n' "$to" >> "$G/resumed.tsv"
  # the ABORTED report is kept under a new name; while the resumed agent works, its iteration counts as running again
  n=1; dst="${rep%.md}_aborted.md"; while [[ -e $dst ]]; do n=$((n+1)); dst="${rep%.md}_aborted$n.md"; done
  mv "$rep" "$dst"
  printf '%s\tRESUME\t%s\t%s\t%s\n' "$ts" "$to" "$r" "$it" >> "$G/tools.log"
  exit 0
fi

# 4. one agent per live session (rule 14): each Houdini / Blender MCP server is one live scene.
#    The first subagent that runs code there holds it until it stops; others are refused for that server.
re_live='^mcp__((houdini|blender)[A-Za-z0-9_-]*)__(run_python|execute_blender_code)'
if [[ $role != main && $tool =~ $re_live ]]; then
  srv="${BASH_REMATCH[1]}"; lock="$G/lock_${srv}"
  if [[ -f $lock ]]; then
    IFS=$'\t' read -r owner since < "$lock"; since="${since%$'\r'}"
    alive=1
    grep -q -F $'\tSUBAGENT-stop\t'"$owner" "$G/tools.log" 2>/dev/null && alive=0
    [[ $since =~ ^[0-9]+$ ]] && (( now - since > 3600 )) && alive=0
    if [[ $owner != "$agent" ]] && (( alive )); then
      deny livesession "the live session $srv is in use by another agent ($owner) - one agent per live scene. Work headless on your own files (blender -b, hython on your own .hip), use another session if there is one, or wait for it."
    fi
  fi
  [[ -f $lock && $owner == "$agent" ]] || printf '%s\t%s\n' "$agent" "$now" > "$lock"
fi

# 5. building by role
case "$role" in
  main)
    (( is_build )) && deny build "rule 1 - the main chat does not build or render ($tool). Start a fresh agent with ROLE: builder (build) or ROLE: helper (analysis before building) and UNIT: <id>; to show something, ROLE: viewer."
    # v4 #6: read-only live tools pass, every other live tool is refused
    if [[ $tool =~ $re_live_any ]] && ! [[ $tool =~ $re_live_ro ]]; then
      deny livewrite "rule 1 - the main chat only looks: inspect, geo, problems, screenshot (Houdini) and get_*/search_* (Blender). To open a scene or set a camera start ROLE: viewer; to change anything ROLE: builder."
    fi
    (( is_code_write )) && deny codewrite "rule 1 - the main chat does not write scripts or scene files; that is the builder's work."
    (( is_script_run )) && deny scriptrun "rule 1 - the main chat does not run scripts; that is the builder's work."
    ;;
  referee|engineer|standin|unknown)
    (( is_build || is_script_run )) && deny build "a $role does not build or change the scene. Use existing pictures and files. (unknown = the hooks could not tell your role: say so in your reply.)"
    [[ $tool =~ $re_live_write ]] && deny build "a $role does not save, write VEX or render in a live session."
    ;;
  viewer)
    # v4 #7: the viewer opens, sets cameras and states in a live session; it never writes a file
    (( is_file_tool )) && deny viewer "the viewer writes no file. Reply in one line what is shown where."
    [[ $tool =~ $re_live_write ]] && deny viewer "the viewer never saves, writes VEX or renders to a file."
    if (( is_shell )) && (( is_write_cmd || is_script_run || is_build )); then deny viewer "the viewer runs no scripts and writes nothing from the shell."; fi
    ;;
  helper)
    re_vis='vis_map'
    if (( is_build || is_script_run )) && builder_started && ! [[ $cmd =~ $re_vis ]]; then
      deny build "once building has started, building and rendering belong to ROLE: builder (its own sheets) or ROLE: qc (its checks), not to a helper (a helper may still run tools/vis_map)."
    fi
    ;;
esac
# v4 #17 traces: an expensive call (build tool or script) gets a fingerprint of its text and a start time; posttool
# logs it with its duration in review/gate/commands.log. The same text that already ran for 60 s or more is announced.
if (( is_build || is_script_run )); then
  fp="$(printf '%s' "${cmd}${code}" | cksum)"; fp="${fp%% *}"
  [[ -n $tuid ]] && printf '%s	%s
' "$now" "$fp" > "$G/t_${tuid}"
  if [[ -f "$G/commands.log" ]]; then
    prev="$(awk -F'	' -v f="$fp" '$6 == f && $5 >= 60 { l = $1 " by " $3 " " $2 " (unit " $4 ", " $5 " s)" } END { print l }' "$G/commands.log")"
    [[ -n $prev ]] && printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"GATE: this exact command already ran: %s. If its inputs did not change, use that result instead of running it again; if they did, say in your report why it ran again."}}' "$prev"
  fi
fi
exit 0

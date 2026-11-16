#!/bin/bash
# Test cases for the v4 hooks: simulated hook inputs (JSON on stdin), PASS/FAIL per case.
# Run in Git Bash:  bash run_tests.sh      Every run builds fresh fixtures under tests/_runs/<time>/ (nothing is deleted).
T="$(cd "$(dirname "$0")" && pwd)"; PKG="$(cd "$T/.." && pwd)"; SRC="$(cd "$PKG/.." && pwd)"   # SRC = fassung_v4 (rules, levels, roles)
PS=/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe
RUN="$T/_runs/$(date +%Y%m%d_%H%M%S)"; mkdir -p "$RUN"
pass=0; fail=0; FAILS=""
ok()  { pass=$((pass+1)); echo "PASS  $1"; }
bad() { fail=$((fail+1)); FAILS+="$1"$'\n'; echo "FAIL  $1  -> ${2:0:300}"; }
n=0
# fresh fixture: B = brief folder (with .claude/hooks), W = work folder
fx() {
  n=$((n+1)); F="$RUN/c$n"; B="$F/brief"; W="$F/work"; H="$B/.claude/hooks"
  mkdir -p "$H" "$B/roles" "$W/review/gate" "$W/review/iter" "$W/review/units" "$W/review/strategy" "$W/review/vis" "$W/export" "$W/houdini"
  cp "$SRC/rules.md" "$SRC/levels.md" "$B/"; cp "$SRC"/roles/*.md "$B/roles/"
  cp "$PKG"/hooks/*.ps1 "$PKG"/hooks/*.sh "$H/"
  WM="$(cygpath -m "$W")"
  printf 'WORK=%s\nREMIND_EVERY=30\nMAX_BUILDERS=%s\nLEVEL=%s\n%s\n' "$WM" "${MB:-1}" "${LV:-final}" "${EXTRA:-}" > "$H/gate.conf"
  G="$W/review/gate"
  printf -- '- goal: x\n- level: x\n- units: x\n- approach: x\n- blockout: x\n- tolerance: x\n- collision: x\n- visibility: x\n- sheet: x\n- away: x\n- marks: x\n' > "$W/review/readings.md"
}
gate()  { printf '%s' "$2" | "$PS" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$(cygpath -w "$H/gate.ps1")" "$1" 2>&1; }
pre()   { printf '%s' "$1" | bash "$H/pretool_build.sh" 2>&1; }
sub()   { printf '%s' "$2" | bash "$H/subagent.sh" "$1" 2>&1; }
post()  { printf '%s' "$1" | bash "$H/posttool.sh" 2>&1; }
agentj() { printf '{"hook_event_name":"PreToolUse","tool_name":"Agent","tool_input":{"subagent_type":"%s","description":"t","prompt":"%s"}}' "$1" "$2"; }
toolj()  { # agent_id agent_type tool input-json
  local a=""; [[ -n $1 ]] && a="\"agent_id\":\"$1\",\"agent_type\":\"$2\","
  printf '{%s"hook_event_name":"PreToolUse","tool_name":"%s","tool_input":%s}' "$a" "$3" "$4"; }
logl()  { printf '%s\t%s\t%s\t%s\tdesc\t%s\t%s\n' "${5:-2026-11-09T08:00:00}" "$1" "$2" "$3" "${4:-1000}" "${6:-gp}" >> "$G/agents.log"; }
isdeny()  { [[ $1 == *'"permissionDecision":"deny"'* && $1 != *"GATE ERROR"* ]]; }
isallow() { [[ $1 == *'"permissionDecision":"allow"'* ]]; }
expd() { if isdeny "$2"; then ok "$1"; echo "      ${2:90:110}" >> "$RUN/reasons.txt"; else bad "$1" "$2"; fi; }
expa() { if isallow "$2"; then ok "$1"; else bad "$1" "$2"; fi; }   # gate.ps1 allow
expn() { if isdeny "$2"; then bad "$1" "$2"; else ok "$1"; fi; }    # bash hooks: no output = pass

echo "== old locks (006, unchanged)"
fx
expd "OLD main chat may not run_python" "$(pre "$(toolj '' '' mcp__houdini_code__run_python '{"code":"x"}')")"
expd "OLD main chat may not write a script" "$(pre "$(toolj '' '' Write '{"file_path":"C:/w/tools/x.py","content":"x"}')")"
expd "OLD main chat may not write a referee report" "$(pre "$(toolj '' '' Write "{\"file_path\":\"$WM/review/iter/001_referee.md\",\"content\":\"x\"}")")"
expn "OLD main chat may write a missing ABORTED builder report" "$(pre "$(toolj '' '' Write "{\"file_path\":\"$WM/review/iter/001_builder.md\",\"content\":\"ABORTED: limit\"}")")"
expd "OLD fork is refused" "$(gate pretool "$(agentj fork 'ROLE: helper')")"
expd "OLD agent without role is refused" "$(gate pretool "$(agentj general-purpose 'do something')")"
expd "OLD hooks are protected" "$(pre "$(toolj a1 builder Write "{\"file_path\":\"$(cygpath -m "$H")/gate.conf\",\"content\":\"x\"}")")"

fx; logl builder U1 001
touch "$W/review/iter/001_builder.md"
expd "OLD final: next builder of U1 refused while referee due" "$(gate pretool "$(agentj builder 'UNIT: U1')")"
o="$(gate stop '{}')"; [[ $o == *'"decision":"block"'* && $o == *Referee* ]] && ok "OLD final: Stop blocked while referee due" || bad "OLD final: Stop blocked while referee due" "$o"
o="$(gate pretool "$(agentj referee 'UNIT: U1')")"; isallow "$o" && [[ $o == *'001_referee.md'* ]] && ok "OLD referee start gets its report path" || bad "OLD referee start gets its report path" "$o"

fx; MB=2 fx; logl builder U1 001
expd "OLD one builder per unit (U1 still running)" "$(gate pretool "$(agentj builder 'UNIT: U1')")"
expa "OLD second lane U2 allowed with MAX_BUILDERS=2" "$(gate pretool "$(agentj builder 'UNIT: U2')")"

EXTRA='SHARED_FILES=houdini/rig.hip' fx
expd "OLD SHARED: unknown file refused" "$(gate pretool "$(agentj builder 'UNIT: U1\nSHARED: other.hip')")"
printf 'aXX\t%s\n' "$(date +%s)" > "$G/filelock_houdini_rig_hip"
expd "OLD SHARED: file held by a running agent refused" "$(gate pretool "$(agentj builder 'UNIT: U1\nSHARED: rig.hip')")"
EXTRA='STOP_AT=1000' fx
expd "OLD STOP_AT passed: no agent start" "$(gate pretool "$(agentj helper 'x')")"

echo "== v4 #1 roles as agent types"
fx
expn "#1 referee by agent_type (no tsv line) may read" "$(pre "$(toolj r1 referee Bash '{"command":"cat a.md"}')")"
expn "#1 referee by agent_type writes its report" "$(pre "$(toolj r1 referee Write "{\"file_path\":\"$WM/review/iter/001_referee.md\",\"content\":\"VERDICT: PASS\"}")")"
expd "#1 referee by agent_type may not run_python" "$(pre "$(toolj r1 referee mcp__houdini_code__run_python '{"code":"x"}')")"
expd "#1 builder may not write a referee report" "$(pre "$(toolj b1 builder Write "{\"file_path\":\"$WM/review/iter/001_referee.md\",\"content\":\"x\"}")")"
o1="$(gate pretool "$(agentj helper 'look')")"; o2="$(gate pretool "$(agentj viewer 'show')")"
if isallow "$o1" && isallow "$o2"; then ok "#1 two typed starts in one message both allowed"; else bad "#1 two typed starts in one message both allowed" "$o1 $o2"; fi
sub start '{"agent_id":"av1","agent_type":"viewer"}' >/dev/null; sub start '{"agent_id":"ah1","agent_type":"helper"}' >/dev/null
r="$(cut -f1,2 "$G/agent_roles.tsv" | tr '\t\n' ': ')"
[[ $r == *'av1:viewer'* && $r == *'ah1:helper'* ]] && ok "#1 both get the right role (start order reversed)" || bad "#1 both get the right role" "$r"
o1="$(gate pretool "$(agentj general-purpose 'ROLE: helper')")"; o2="$(gate pretool "$(agentj general-purpose 'ROLE: helper')")"
isallow "$o1" && isdeny "$o2" && ok "#1 fallback ROLE line: still one start per message" || bad "#1 fallback ROLE line: one start per message" "$o2"
expd "#1 ROLE line contradicting the agent type refused" "$(gate pretool "$(agentj referee 'ROLE: builder\nUNIT: U1')")"

echo "== v4 #2 LEVEL"
LV=scout fx; logl builder U1 001; touch "$W/review/iter/001_builder.md"
o="$(gate stop '{}')"; [[ $o != *'"decision":"block"'* ]] && ok "#2 scout: no referee due after a builder run" || bad "#2 scout: no referee due after a builder run" "$o"
expa "#2 scout: next builder of U1 allowed without referee" "$(gate pretool "$(agentj builder 'UNIT: U1')")"
touch "$W/review/iter/002_builder.md"; touch "$W/review/units/U1_report.md"
o="$(gate stop '{}')"; [[ $o == *'"decision":"block"'* && $o == *Referee* ]] && ok "#2 scout: referee due at unit end" || bad "#2 scout: referee due at unit end" "$o"
o="$(gate pretool "$(agentj referee 'UNIT: U1')")"; [[ $o == *'001,002'* && $o == *'002_referee.md'* ]] && ok "#2 scout: one referee covers all runs of the unit" || bad "#2 scout: one referee covers all runs" "$o"
LV=study fx
o="$(gate pretool "$(agentj helper 'x')")"; [[ $o == *'LEVEL: study'* && $o == *'Picture targets'* ]] && ok "#2 level row of levels.md in the agent prompt" || bad "#2 level row in the agent prompt" "${o:0:200}"

echo "== v4 #3 SET:"
fx
o="$(gate context '{"hook_event_name":"UserPromptSubmit","prompt":"ok\nSET: level=study\nSET: max_builders=3"}')"
c="$(cat "$H/gate.local.conf" 2>/dev/null)"; [[ $c == *LEVEL=study* && $c == *MAX_BUILDERS=3* ]] && ok "#3 artist message SET: level=study -> gate.local.conf" || bad "#3 SET writes gate.local.conf" "$c"
# Hafen test 2026-11-12: the status line said "SET by the artist's message: System.Object[]" (array wrapped twice)
[[ $o == *"SET level=study applied. SET max_builders=3 applied."* && $o != *System.Object* ]] && ok "#3 SET result shown as text in the context" || bad "#3 SET result shown as text" "$(grep -a 'SET by' <<<"$o")"
o="$(gate context '{"hook_event_name":"UserPromptSubmit","prompt":"just a message"}')"
[[ $o != *"SET by the artist"* && $o != *System.Object* ]] && ok "#3 no SET line without SET:" || bad "#3 no SET line without SET:" "$(grep -a 'SET by' <<<"$o")"
# Hafen test 2026-11-12: usage-watcher prompts and subagent hand-backs were logged as the artist's words
gate context '{"hook_event_name":"UserPromptSubmit","prompt":"[usage-watcher] read the usage, write usage.txt"}' >/dev/null
gate context '{"hook_event_name":"UserPromptSubmit","prompt":"Usage watcher (conductor duty): call get_usage"}' >/dev/null
gate context '{"hook_event_name":"UserPromptSubmit","prompt":"<agent-message from=\"a1\">\nreport\n</agent-message>"}' >/dev/null
al="$(cat "$W/review/gate/artist.log" 2>/dev/null)"
[[ $al == *"just a message"* && $al != *usage* && $al != *Usage* && $al != *agent-message* ]] && ok "#3 artist.log keeps only the artist's messages" || bad "#3 artist.log only the artist" "$al"
gate context '{"hook_event_name":"UserPromptSubmit","prompt":"<task-notification>\nSET: level=scout\n</task-notification>"}' >/dev/null
[[ "$(cat "$H/gate.local.conf")" == *LEVEL=study* ]] && ok "#3 SET inside a task notification ignored" || bad "#3 SET in notification ignored" "$(cat "$H/gate.local.conf")"
o="$(gate pretool "$(agentj helper 'x')")"; [[ $o == *'LEVEL: study'* ]] && ok "#3 the SET level reaches the gate" || bad "#3 SET level reaches the gate" "${o:0:200}"
expd "#3 model writes gate.local.conf (Write) -> refused" "$(pre "$(toolj '' '' Write "{\"file_path\":\"$(cygpath -m "$H")/gate.local.conf\",\"content\":\"LEVEL=scout\"}")")"
expd "#3 model writes gate.local.conf (shell) -> refused" "$(pre "$(toolj '' '' Bash '{"command":"echo LEVEL=scout > gate.local.conf"}')")"
gate context '{"hook_event_name":"UserPromptSubmit","prompt":"SET: pause=night"}' >/dev/null
expd "#3 SET: pause=night stops builder starts" "$(gate pretool "$(agentj builder 'UNIT: U1')")"
gate context '{"hook_event_name":"UserPromptSubmit","prompt":"SET: pause=off"}' >/dev/null
expa "#3 SET: pause=off lets builders start" "$(gate pretool "$(agentj builder 'UNIT: U1')")"

echo "== v4 #4 keys per level"
LV=study fx; sed -i '/visibility/d' "$W/review/readings.md"
o="$(gate pretool "$(agentj builder 'UNIT: U1')")"; isdeny "$o" && [[ $o == *visibility* ]] && ok "#4 study without visibility -> refused" || bad "#4 study without visibility" "$o"
LV=scout fx; printf -- '- goal: x\n- level: scout\n- units: x\n- approach: x\n' > "$W/review/readings.md"
expa "#4 scout with goal, level, units, approach -> allowed" "$(gate pretool "$(agentj builder 'UNIT: U1')")"
LV=final fx; sed -i '/goal/d' "$W/review/readings.md"
expd "#4 final without goal -> refused" "$(gate pretool "$(agentj builder 'UNIT: U1')")"

echo "== v4 #5 STAGE: details"
fx; logl builder U2 001; touch "$W/review/iter/001_builder.md"; logl referee U2 001; touch "$W/review/iter/001_referee.md"
expd "#5 details without visibility map -> refused" "$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"
touch -d '2026-11-09 08:00' "$W/review/vis/U2_vis.md"; touch -d '2026-11-09 09:00' "$W/export/U2_body_v002.usd"
expd "#5 map older than the last export -> refused" "$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"
touch "$W/review/vis/U2_vis.md"
mkdir -p "$W/export/review/stage_v003_layers"; touch -d '+1 hour' "$W/export/review/stage_v003_layers/hide_U2.usda"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"; [[ $o != *"older than a changed export"* ]] && ok "#5 shared review file naming the unit does not age the map" || bad "#5 shared review file ages the map" "$o"
touch "$W/review/iter/002_builder.md"; logl referee U2 002; touch "$W/review/iter/002_referee.md"
mkdir -p "$W/export/U2"; touch -d '+1 hour' "$W/export/U2/hinge_v003.usd"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"; [[ $o == *"older than a changed export"* ]] && ok "#5 new export in export/U2/ -> refused" || bad "#5 export in unit folder" "$o"
rm -rf "$W/export/U2" "$W/export/review"
printf 'part | purpose | carrier | reference | binding level | tier\n--- | --- | --- | --- | --- | ---\n' > "$W/review/strategy/U2.md"
echo "0" > "$G/strategy_U2.lines"; printf 'hinge | turn | rib | photo 3 | basis\n' >> "$W/review/strategy/U2.md"
expd "#5 new part line without tier -> refused" "$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"
sed -i 's/| basis$/| basis | A/' "$W/review/strategy/U2.md"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"; isdeny "$o" && [[ $o == *components.md* ]] && ok "#7c details without the unit's components -> refused" || bad "#7c no components" "$o"
printf '| name | unit | kind | rank | views | readable size |\n|---|---|---|---|---|---|\n| crane | U2 | component | 1 | side: silhouette; hook: works | 0.4 m |\n| bins | U2 | component | 3 | - | - |\n| yard | U2 | area | 2 | eye: mix | - |\n' > "$W/review/components.md"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"; isdeny "$o" && [[ $o == *"not made yet for: crane"* && $o != *bins* && $o != *yard* ]] && ok "#7c rank-1 component without views -> refused (rank 3 and areas exempt)" || bad "#7c views missing" "$o"
printf '{\n "name": "crane_side",\n "rank": 1\n}\n' > "$W/review/vis/U2_crane_views.json"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"; [[ $o == *"not made yet for: crane"* ]] && ok "#7c a view name is not the component name" || bad "#7c view name matched" "$o"
printf '{\n "name": "crane",\n "rank": 1\n}\n' > "$W/review/vis/U2_crane_views.json"
expa "#5 current map, components with views and tier on every new line -> allowed" "$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"
sed -i 's/| bins | U2 | component | 3 |/| bins | U2 | component | 2 |/' "$W/review/components.md"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"; isdeny "$o" && [[ $o == *"not made yet for: bins"* ]] && ok "#7c final: rank 2 needs views too" || bad "#7c final rank 2" "$o"
sed -i 's/^LEVEL=final/LEVEL=study/' "$H/gate.conf"
expa "#7c study: rank 2 needs no views" "$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"
touch -d '+1 hour' "$W/export/U2_body_v002.usd"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"; [[ $o != *"older than a changed export"* ]] && ok "#18 re-export with the same content keeps the map current" || bad "#18 same content" "$o"
echo "new form" > "$W/export/U2_body_v002.usd"; touch -d '+2 hour' "$W/export/U2_body_v002.usd"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: details')")"; isdeny "$o" && [[ $o == *"older than a changed export"* ]] && ok "#18 changed content ages the map" || bad "#18 changed content" "$o"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: map')")"; isdeny "$o" && [[ $o == *"helper task"* ]] && ok "#18 a builder run only for the map -> refused (helper task)" || bad "#18 map run by builder" "$o"

echo "== unit QC after a package run (finished unit)"
LV=study MB=2 fx; touch "$W/review/units/U4_targets.md"
logl builder U4 001 1000; touch "$W/review/iter/001_builder.md"; logl referee U4 001 1001; touch "$W/review/iter/001_referee.md"
logl qc U4 001 1002; touch "$W/review/iter/001_qc.md"; touch "$W/review/units/U4_report.md"
logl builder U4-belt 002 1003; touch "$W/review/iter/002_builder.md"; logl referee U4-belt 002 1004; touch "$W/review/iter/002_referee.md"
o="$(gate stop '{}')"; [[ $o == *'no QC ran after its last build'* ]] && ok "#pkg QC of the unit due after a package run" || bad "#pkg QC due after a package run" "$o"
o="$(gate pretool "$(agentj qc 'UNIT: U4')")"; isallow "$o" && [[ $o == *002_qc.md* ]] && ok "#pkg unit QC starts on the package state (002)" || bad "#pkg unit QC starts on the package state" "$o"
touch "$W/review/iter/002_qc.md"
o="$(gate stop '{}')"; [[ $o != *'no QC ran after its last build'* ]] && ok "#pkg obligation cleared after the unit QC" || bad "#pkg obligation cleared" "$o"

echo "== parallel starts get their own numbers"
MB=3 fx
gate pretool "$(agentj builder 'UNIT: U5')" > "$F/p1.txt" & gate pretool "$(agentj builder 'UNIT: U7')" > "$F/p2.txt" & gate pretool "$(agentj builder 'UNIT: U4')" > "$F/p3.txt" & wait
its="$(cut -f4 "$G/agents.log" | sort | tr '\n' ' ')"; [[ $its == '001 002 003 ' ]] && ok "#num three builders started at once -> 001 002 003" || bad "#num parallel numbers" "$its / $(cat "$F"/p*.txt | cut -c1-200)"

echo "== a run report is never overwritten by another agent"
fx; qf="$WM/review/iter/005_qc.md"
expn "#own first QC writes 005_qc.md" "$(pre "$(toolj a1 qc Write "{\"file_path\":\"$qf\",\"content\":\"VERDICT: PASS\"}")")"
touch "$W/review/iter/005_qc.md"
expn "#own the same QC may edit its report" "$(pre "$(toolj a1 qc Edit "{\"file_path\":\"$qf\",\"old_string\":\"a\",\"new_string\":\"b\"}")")"
expd "#own a second QC may not overwrite it" "$(pre "$(toolj a2 qc Write "{\"file_path\":\"$qf\",\"content\":\"VERDICT: PASS\"}")")"
rm "$W/review/iter/005_qc.md"
expn "#own a file moved away (resume) is free again" "$(pre "$(toolj a2 qc Write "{\"file_path\":\"$qf\",\"content\":\"VERDICT: PASS\"}")")"

echo "== messages to other app sessions"
fx
expn "#msg main chat may message another session (local_)" "$(pre '{"hook_event_name":"PreToolUse","tool_name":"SendMessage","tool_input":{"to":"local_abc","message":"x"}}')"
expd "#msg main chat may not message an unknown agent" "$(pre '{"hook_event_name":"PreToolUse","tool_name":"SendMessage","tool_input":{"to":"a123","message":"x"}}')"

echo "== v4 #6 read-only live tools"
fx
expn "#6 main inspect passes" "$(pre "$(toolj '' '' mcp__houdini_code__inspect '{}')")"
expn "#6 main blender get_objects_summary passes" "$(pre "$(toolj '' '' mcp__blender__get_objects_summary '{}')")"
expd "#6 main run_python refused" "$(pre "$(toolj '' '' mcp__houdini_code__run_python '{"code":"x"}')")"
expd "#6 main houdini save refused" "$(pre "$(toolj '' '' mcp__houdini_code__save '{}')")"
expd "#6 main blender render refused" "$(pre "$(toolj '' '' mcp__blender__render_viewport_to_path '{}')")"

echo "== v4 #7 viewer"
fx; touch "$W/houdini/a.hip"; touch -d '2026-11-09 07:00' "$W/houdini/a.hip"
sub start '{"agent_id":"av2","agent_type":"viewer"}' >/dev/null
expn "#7 viewer may run live code (open, camera)" "$(pre "$(toolj av2 viewer mcp__houdini_code__run_python '{"code":"hou.hipFile.load(x)"}')")"
expd "#7 viewer may not write a file" "$(pre "$(toolj av2 viewer Write '{"file_path":"C:/w/x.md","content":"x"}')")"
expd "#7 viewer may not save" "$(pre "$(toolj av2 viewer mcp__houdini_code__save '{}')")"
sleep 1; touch "$W/houdini/a.hip"
sub stop '{"agent_id":"av2","agent_type":"viewer"}' >/dev/null
[[ -f $G/viewer_veto.log && "$(cat "$G/viewer_veto.log")" == *a.hip* ]] && ok "#7 viewer saved a hip -> VETO line" || bad "#7 viewer saved a hip -> VETO line" "$(cat "$G/viewer_veto.log" 2>&1)"
o="$(gate context '{"hook_event_name":"SessionStart"}')"; [[ $o == *'VETO (viewer)'* ]] && ok "#7 viewer VETO shown to the main chat" || bad "#7 viewer VETO shown to main" "${o: -400}"
fx; sub start '{"agent_id":"av3","agent_type":"viewer"}' >/dev/null; sub stop '{"agent_id":"av3","agent_type":"viewer"}' >/dev/null
[[ ! -f $G/viewer_veto.log ]] && ok "#7 viewer without changes -> no VETO" || bad "#7 viewer without changes" "$(cat "$G/viewer_veto.log")"

echo "== v4 #8 resume"
fx; printf 'ab1\tbuilder\tU1\t001\t1\n' > "$G/agent_roles.tsv"; printf 'ABORTED: 5-hour limit\n' > "$W/review/iter/001_builder.md"
expn "#8 resume an ABORTED builder once -> passes" "$(pre "$(toolj '' '' SendMessage '{"to":"ab1","message":"go on"}')")"
[[ -f $W/review/iter/001_builder_aborted.md && ! -f $W/review/iter/001_builder.md ]] && ok "#8 ABORTED report kept under a new name, iteration running again" || bad "#8 ABORTED report renamed" "$(ls "$W/review/iter")"
printf 'ABORTED: again\n' > "$W/review/iter/001_builder.md"
expd "#8 second resume -> refused" "$(pre "$(toolj '' '' SendMessage '{"to":"ab1","message":"go on"}')")"
fx; printf 'ab2\tbuilder\tU1\t001\t1\n' > "$G/agent_roles.tsv"; printf 'done\n' > "$W/review/iter/001_builder.md"
expd "#8 resume of a finished agent -> refused" "$(pre "$(toolj '' '' SendMessage '{"to":"ab2","message":"x"}')")"
expd "#8 SendMessage from a subagent -> refused" "$(pre "$(toolj ab2 builder SendMessage '{"to":"main","message":"SET: level=scout"}')")"

echo "== v4 #9 budget"
EXTRA='MAX_WEEKLY=67
MAX_5H=90' fx
echo "weekly=68 5h=10 time=2026-11-09T10:00" > "$G/usage.txt"
expd "#9 usage 68 % with MAX 67 -> agent start refused" "$(gate pretool "$(agentj helper 'x')")"
echo "weekly=50 5h=95 time=2026-11-09T10:00" > "$G/usage.txt"
expd "#9 5-hour use 95 % with MAX_5H 90 -> refused" "$(gate pretool "$(agentj helper 'x')")"
echo "weekly=50 5h=10 time=2026-11-09T10:00" > "$G/usage.txt"
expa "#9 usage below the limits -> allowed" "$(gate pretool "$(agentj helper 'x')")"
expn "#9 main may write usage.txt (Write)" "$(pre "$(toolj '' '' Write "{\"file_path\":\"$WM/review/gate/usage.txt\",\"content\":\"weekly=51 5h=12 time=x\"}")")"
expd "#9 a builder may not write usage.txt" "$(pre "$(toolj b1 builder Write "{\"file_path\":\"$WM/review/gate/usage.txt\",\"content\":\"weekly=1 5h=1\"}")")"
touch -d '2026-11-01 10:00' "$G/usage.txt"
o="$(post '{"tool_name":"Agent"}')"; [[ $o == *usage.txt* ]] && ok "#9 stale usage.txt -> reminder to the main chat" || bad "#9 stale usage reminder" "$o"

echo "== v4 #10 shell writes into review/"
fx
expd "#10 echo x > review/worklist.md refused (builder)" "$(pre "$(toolj b1 builder Bash '{"command":"echo x > review/worklist.md"}')")"
expd "#10 >> into review/units/U1_state.md refused (main)" "$(pre "$(toolj '' '' Bash '{"command":"echo x >> C:/w/review/units/U1_state.md"}')")"
expd "#10 Set-Content review\\\\worklist.md refused" "$(pre "$(toolj b1 builder PowerShell '{"command":"Set-Content -Path review\\\\worklist.md -Value x"}')")"
expd "#10 tee -a review/assumed.md refused" "$(pre "$(toolj b1 builder Bash '{"command":"echo x | tee -a review/assumed.md"}')")"
expd "#10 Out-File review/x.md refused" "$(pre "$(toolj b1 builder PowerShell '{"command":"x | Out-File review/x.md"}')")"
expn "#10 reading review/ with redirect elsewhere passes" "$(pre "$(toolj b1 builder Bash '{"command":"grep U1 review/worklist.md > C:/tmp/out.txt"}')")"

echo "== v4 #11 conductor context"
fx; TR="$F/t.jsonl"
printf '{"type":"assistant","isSidechain":false,"message":{"usage":{"input_tokens":4,"cache_creation_input_tokens":20000,"cache_read_input_tokens":500000,"output_tokens":5}}}\n' > "$TR"
pj="{\"tool_name\":\"Read\",\"transcript_path\":\"$(cygpath -m "$TR")\"}"
o1="$(post "$pj")"; o2="$(post "$pj")"
[[ $o1 == *conductor_handover.md* && $o2 != *conductor_handover* ]] && ok "#11 transcript at 520 k -> exactly one reminder" || bad "#11 one reminder at 520 k" "$o1 | $o2"
printf '{"type":"assistant","message":{"usage":{"input_tokens":4,"cache_creation_input_tokens":0,"cache_read_input_tokens":630000}}}\n' >> "$TR"
o="$(post "$pj")"; [[ $o == *conductor_handover.md* ]] && ok "#11 next reminder after another 100 k" || bad "#11 reminder after +100 k" "$o"
o="$(post "{\"agent_id\":\"b1\",\"tool_name\":\"Read\",\"transcript_path\":\"$(cygpath -m "$TR")\"}")"; [[ $o != *handover* ]] && ok "#11 no reminder for a subagent" || bad "#11 subagent no reminder" "$o"
echo "== v4 #19 hand-over enforced at HANDOVER_AT"
[[ -f "$G/handover_due" ]] && ok "#19 above HANDOVER_AT the mark handover_due is written" || bad "#19 mark" "$(ls "$G")"
o="$(gate pretool "$(agentj builder 'UNIT: U1')")"; isdeny "$o" && [[ $o == *HANDOVER_AT* ]] && ok "#19 no new agent before the hand-over" || bad "#19 agent before hand-over" "$o"
echo "state" > "$W/review/conductor_handover.md"; touch -d '+1 min' "$W/review/conductor_handover.md"
expa "#19 hand-over written -> agents start again" "$(gate pretool "$(agentj builder 'UNIT: U1')")"
printf '{"type":"assistant","message":{"usage":{"input_tokens":4,"cache_creation_input_tokens":0,"cache_read_input_tokens":740000}}}\n' >> "$TR"
post "$pj" >/dev/null; touch -d '+2 min' "$G/handover_due"
o="$(gate pretool "$(agentj builder 'UNIT: U1')")"; isdeny "$o" && [[ $o == *HANDOVER_AT* ]] && ok "#19 another 100 k -> a fresh hand-over is due" || bad "#19 next 100 k" "$o"
printf '{"type":"assistant","message":{"usage":{"input_tokens":4,"cache_creation_input_tokens":0,"cache_read_input_tokens":90000}}}\n' >> "$TR"
post "$pj" >/dev/null
[[ ! -f "$G/handover_due" ]] && ok "#19 after a compaction (small context) the mark is gone" || bad "#19 mark after compaction" "$(cat "$G/handover_due")"
o="$(gate pretool "$(agentj referee 'UNIT: U1')")"; [[ $o != *HANDOVER_AT* ]] && ok "#19 no hold below HANDOVER_AT" || bad "#19 hold below" "$o"

echo "== v4 #12 referee extract"
fx; logl builder U1 001 1000 2026-11-09T09:00:00; touch "$W/review/iter/001_builder.md"
printf '2026-11-09T08:00:00\tmain\tmain\tRead\t0\n2026-11-09T09:10:00\tb1\tbuilder\tmcp__houdini_code__run_python\t1\n2099-01-01T00:00:00\tx\tx\tRead\t0\n' > "$G/tools.log"
o="$(gate pretool "$(agentj referee 'UNIT: U1')")"; ex="$(cat "$G/extract_001.log" 2>/dev/null)"
[[ $ex == *09:10:00* && $ex != *08:00:00* && $ex != *2099* && $o == *extract_001.log* ]] && ok "#12 extract has only the builder window's lines" || bad "#12 extract window" "$ex"

echo "== v4 #13 bauwissen by section"
fx; printf '# bauwissen\nintro\n## U2 canopy\ncanopy tip\n## U3 tail\ntail tip\n## pitfalls\nnever x\n' > "$W/review/bauwissen.md"
o="$(gate pretool "$(agentj builder 'UNIT: U2\nSTAGE: blockout')")"
[[ $o == *'canopy tip'* && $o == *'never x'* && $o != *'tail tip'* ]] && ok "#13 task for U2 -> only matching sections plus pitfalls" || bad "#13 sections" "${o: -600}"

echo "== v4 #14 QC targets"
LV=study fx; logl builder U1 001; touch "$W/review/iter/001_builder.md"; logl referee U1 001; touch "$W/review/iter/001_referee.md"
expd "#14 study: unit QC without targets -> refused" "$(gate pretool "$(agentj qc 'UNIT: U1')")"
expa "#14 STAGE: targets QC at unit start -> allowed" "$(gate pretool "$(agentj qc 'UNIT: U1\nSTAGE: targets')")"
expn "#14 targets QC writes the targets" "$(pre "$(toolj q1 qc Write "{\"file_path\":\"$WM/review/units/U1_targets.md\",\"content\":\"x\"}")")"
expd "#14 same agent id writes the check -> refused" "$(pre "$(toolj q1 qc Write "{\"file_path\":\"$WM/review/iter/001_qc.md\",\"content\":\"x\"}")")"
expn "#14 another QC writes the check" "$(pre "$(toolj q2 qc Write "{\"file_path\":\"$WM/review/iter/001_qc.md\",\"content\":\"x\"}")")"
expd "#14 main may not write targets" "$(pre "$(toolj '' '' Write "{\"file_path\":\"$WM/review/units/U1_targets.md\",\"content\":\"x\"}")")"
touch "$W/review/units/U1_targets.md"
expa "#14 unit QC with targets -> allowed" "$(gate pretool "$(agentj qc 'UNIT: U1')")"
LV=scout fx
expd "#14 scout: no targets QC" "$(gate pretool "$(agentj qc 'UNIT: U1\nSTAGE: targets')")"
fx; expd "OLD round QC report only by qc" "$(pre "$(toolj b1 builder Write "{\"file_path\":\"$WM/review/round_qc.md\",\"content\":\"x\"}")")"

echo "== v4 #15 language"
fx; gate context '{"hook_event_name":"UserPromptSubmit","prompt":"Hallo, bitte weiter"}' >/dev/null
o="$(gate context '{"hook_event_name":"SessionStart"}')"; [[ $o == *"artist's language"* && $o == *Hallo* ]] && ok "#15 start hook: talk in the artist's language" || bad "#15 language line" "${o: -300}"

echo "== v4 #9 status line writes usage.txt (no watcher in the main chat)"
EXTRA="MAX_5H=40" fx
sl() { printf '%s' "$1" | bash "$H/statusline.sh" 2>&1; }
o="$(sl '{"rate_limits":{"five_hour":{"used_percentage":42.5,"resets_at":1},"seven_day":{"used_percentage":61,"resets_at":2}}}')"
c="$(cat "$G/usage.txt" 2>/dev/null)"; [[ $c == "weekly=61 5h=42.5 time="* && $o == *"5h 42.5%"* ]] && ok "#9 status line writes weekly and 5h" || bad "#9 status line" "$c / $o"
sl '{"rate_limits":{"five_hour":{"used_percentage":1},"seven_day":{"used_percentage":1}}}' >/dev/null
c="$(cat "$G/usage.txt")"; [[ $c == "weekly=61 "* ]] && ok "#9 status line writes at most once a minute" || bad "#9 status line throttle" "$c"
o="$(gate pretool "$(agentj builder 'UNIT: U1')")"; isdeny "$o" && [[ $o == *[Bb]udget* ]] && ok "#9 budget stop from the status line's numbers" || bad "#9 budget from status line" "$o"
o="$(sl '{"model":{"id":"x"}}')"; [[ $o == *"5h ?%"* ]] && ok "#9 no rate_limits: status line prints, writes nothing new" || bad "#9 no rate_limits" "$o"

echo "== v4 #17 traces of expensive calls, tokens per agent"
fx; printf 'ab1\tbuilder\tU3\t004\t1\n' >> "$G/agent_roles.tsv"
bj() { printf '{"agent_id":"ab1","agent_type":"builder","hook_event_name":"%s","tool_name":"Bash","tool_use_id":"%s","tool_input":{"command":"%s"}}' "$1" "$2" "$3"; }
o="$(pre "$(bj PreToolUse tu1 'hython sim_terrain.py')")"; [[ -f "$G/t_tu1" && $o != *"already ran"* ]] && ok "#17 expensive call gets a start mark, no notice the first time" || bad "#17 start mark" "$o"
read -r t0 fp < "$G/t_tu1"; printf '%s\t%s\n' "$((t0 - 95))" "$fp" > "$G/t_tu1"
post "$(bj PostToolUse tu1 'hython sim_terrain.py')" >/dev/null
l="$(tail -n 1 "$G/commands.log" 2>/dev/null)"; u="$(cut -f4 <<< "$l")"; d="$(cut -f5 <<< "$l")"; m="$(cut -f7 <<< "$l")"; x="$(cut -f8 <<< "$l")"
[[ $u == U3 && $d -ge 95 && -z $m && $x == *sim_terrain* ]] && ok "#17 commands.log: unit, duration, text" || bad "#17 commands.log line" "$l"
o="$(pre "$(bj PreToolUse tu2 'hython sim_terrain.py')")"; [[ $o == *"already ran"* && $o == *"unit U3, 9"?" s"* ]] && ok "#17 the same expensive call again -> notice" || bad "#17 repeat notice" "$o"
read -r t0 fp < "$G/t_tu2"; printf '%s\t%s\n' "$((t0 - 70))" "$fp" > "$G/t_tu2"; post "$(bj PostToolUse tu2 'hython sim_terrain.py')" >/dev/null
[[ "$(tail -n 1 "$G/commands.log" | cut -f7)" == REPEAT ]] && ok "#17 a repeat that ran 60 s or more is marked REPEAT" || bad "#17 REPEAT mark" "$(tail -n 1 "$G/commands.log")"
o="$(pre "$(bj PreToolUse tu3 'hython other_step.py')")"; [[ $o != *"already ran"* ]] && ok "#17 another call -> no notice" || bad "#17 other call" "$o"
o="$(pre "$(bj PreToolUse tu4 'ls -la')")"; [[ ! -f "$G/t_tu4" ]] && ok "#17 a cheap call gets no trace" || bad "#17 cheap call traced" "$o"
mkdir -p "$RUN/tr"; T="$RUN/tr/agent-ab1.jsonl"
printf '%s\n' '{"type":"assistant","message":{"id":"msg_1","usage":{"input_tokens":10,"cache_creation_input_tokens":100,"cache_read_input_tokens":1000,"output_tokens":5}}}' \
  '{"type":"assistant","message":{"id":"msg_1","usage":{"input_tokens":10,"cache_creation_input_tokens":100,"cache_read_input_tokens":1000,"output_tokens":5}}}' \
  '{"type":"assistant","message":{"id":"msg_2","usage":{"input_tokens":1,"cache_creation_input_tokens":0,"cache_read_input_tokens":2000,"output_tokens":7}}}' > "$T"
printf '%s\tSUBAGENT-start\tab1\tbuilder\n' "$(date -d '-30 min' +%Y-%m-%dT%H:%M:%S)" >> "$G/tools.log"
sub stop "{\"agent_id\":\"ab1\",\"agent_type\":\"builder\",\"agent_transcript_path\":\"$(cygpath -m "$T")\"}" >/dev/null
l="$(tail -n 1 "$G/agent_tokens.tsv" 2>/dev/null)"; IFS=$'\t' read -r _t a r u it i cw cr out mins <<< "$l"
[[ $a == ab1 && $r == builder && $u == U3 && $i == 11 && $cw == 100 && $cr == 3000 && $out == 12 && $mins -ge 29 ]] && ok "#17 tokens per agent, each message once, minutes" || bad "#17 agent_tokens.tsv" "$l"
logl builder U3 004 "" "" "" ; touch "$W/review/iter/004_builder.md"
o="$(gate pretool "$(agentj referee 'UNIT: U3')")"; [[ $o == *"Effort: 2 expensive calls"* && $o == *REPEATED* ]] && ok "#17 the referee's extract names effort and repeats" || bad "#17 referee extract" "${o:0:600}"

echo
echo "RESULT: $pass passed, $fail failed  (fixtures: $RUN)"
[[ -n $FAILS ]] && printf 'FAILED:\n%s' "$FAILS"
exit $fail

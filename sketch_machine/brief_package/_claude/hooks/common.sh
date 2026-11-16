# shared by the fast bash hooks (bash builtins only). Base: test 006; v4 changes marked "v4 #<n>".
HOOKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIEFNAME="$(cd "$HOOKDIR/../.." && pwd)"; BRIEFNAME="${BRIEFNAME##*/}"
HANDOVER_AT=500000
while IFS='=' read -r k v; do v="${v%$'\r'}"; case "$k" in WORK) WORK="$v";; REMIND_EVERY) REMIND_EVERY="$v";; HANDOVER_AT) [[ $v =~ ^[0-9]+$ ]] && HANDOVER_AT="$v";; esac; done < "$HOOKDIR/gate.conf"
G="$WORK/review/gate"; mkdir -p "$G" "$WORK/review/iter"
input="$(cat)"
tool=""; re='"tool_name": ?"([^"]+)"'; [[ $input =~ $re ]] && tool="${BASH_REMATCH[1]}"
# Claude Code sets agent_id (and agent_type) only when a hook fires inside a subagent
agent="main"; re='"agent_id": ?"([^"]+)"'; [[ $input =~ $re ]] && agent="${BASH_REMATCH[1]}"
atype=""; re='"agent_type": ?"([^"]*)"'; [[ $input =~ $re ]] && atype="${BASH_REMATCH[1]}"
re_roles='^(builder|referee|qc|engineer|helper|standin|viewer)$'
role="main"
if [[ $agent != main ]]; then
  role="unknown"
  # v4 #1: an agent started with its agent type (.claude/agents/<role>.md) carries the role itself
  if [[ $atype =~ $re_roles ]]; then role="$atype"
  elif [[ -f "$G/agent_roles.tsv" ]]; then
    while IFS=$'\t' read -r id r _rest; do [[ $id == "$agent" ]] && { role="$r"; break; }; done < "$G/agent_roles.tsv"
  fi
fi
printf -v ts '%(%Y-%m-%dT%H:%M:%S)T' -1
printf -v now '%(%s)T' -1
# JSON string values (escaped characters kept as they are)
fpath=""; re='"file_path": ?"(([^"\\]|\\.)*)"'; [[ $input =~ $re ]] && fpath="${BASH_REMATCH[1]}"
cmd="";   re='"command": ?"(([^"\\]|\\.)*)"';   [[ $input =~ $re ]] && cmd="${BASH_REMATCH[1]}"
code="";  re='"code": ?"(([^"\\]|\\.)*)"';      [[ $input =~ $re ]] && code="${BASH_REMATCH[1]}"
tuid="";  re='"tool_use_id": ?"([^"]+)"';         [[ $input =~ $re ]] && tuid="${BASH_REMATCH[1]}"
unit_of() { local id r u; [[ -f "$G/agent_roles.tsv" ]] && while IFS=$'	' read -r id r u _x; do [[ $id == "$1" ]] && { printf '%s' "$u"; return; }; done < "$G/agent_roles.tsv"; printf '%s' "-"; }
content_start=""; re='"content": ?"([^"\\]{0,20})'; [[ $input =~ $re ]] && content_start="${BASH_REMATCH[1]}"
is_build=0
case "$tool" in
  mcp__houdini_code*__run_python|mcp__blender*__execute_blender_code*) is_build=1;;
  Bash|PowerShell)
    re='(hython|hbatch|hcmd|husk|blender\.exe|blender[\\"]* +(-b|--background|-P|--python)|import bpy|import hou)'; [[ $cmd =~ $re ]] && is_build=1;;
esac
# running a script file from the shell (python x.py, x.bat, -File x.ps1, bash x.sh)
is_script_run=0
re='(python[0-9.]*(\.exe)?[\\"]* +[^ ]*\.py|\.(bat|cmd)([\\" ]|$)|-File +[^ ]*\.ps1|\.ps1([\\" ]|$)|(bash|sh)(\.exe)?[\\"]* +[^ ]*\.sh)'
[[ $tool == Bash || $tool == PowerShell ]] && [[ $cmd =~ $re ]] && is_script_run=1
is_code_write=0
re='\.(py|pyw|vfl|vex|h|hda|hdanc|otl|hip|hiplc|hipnc|blend|usd|usda|usdc|bat|cmd|ps1|psm1|sh)$'
[[ $tool == Write || $tool == Edit || $tool == NotebookEdit ]] && [[ $fpath =~ $re ]] && is_code_write=1
# shell command that writes (approximate)
is_write_cmd=0
re='(>|tee |sed +-i|cp |mv |rm |rmdir|del |ren |Set-Content|Out-File|Add-Content|New-Item|Remove-Item|Copy-Item|Move-Item|Rename-Item|Clear-Content|WriteAll|chmod |truncate|touch )'
[[ $cmd =~ $re ]] && is_write_cmd=1
# files nobody may change during a run: hook settings and scripts (incl. gate.local.conf), agent types, rules, roles, the brief itself, the gate logs
re_prot_path='(\.claude[/\\]+(settings[^/\\]*\.json|hooks|agents)|'"$BRIEFNAME"'[/\\]+(rules\.md|levels\.md|CLAUDE\.md|core\.md|conductor\.md|brief\.md|brief\.json|context\.md|project\.md|roles[/\\])|review[/\\]+gate[/\\])'
re_prot_cmd='(\.claude[/\\]+(settings|hooks|agents)|settings(\.local)?\.json|rules\.md|levels\.md|CLAUDE\.md|roles[/\\]|gate\.conf|gate\.local\.conf|gate\.ps1|review[/\\]+gate|disableAllHooks)'
# v4 #6: live tools (Houdini / Blender MCP) and the read-only ones the main chat may use
re_live_any='^mcp__(houdini|blender)'
re_live_ro='^mcp__houdini[A-Za-z0-9_-]*__(inspect|geo|problems|screenshot)$|^mcp__blender[A-Za-z0-9_-]*__(get_[A-Za-z0-9_]+|search_[A-Za-z0-9_]+)$'
re_live_write='^mcp__houdini[A-Za-z0-9_-]*__(save|vex)$|^mcp__blender[A-Za-z0-9_-]*__render_[A-Za-z0-9_]+$'
active=0; [[ -f "$G/active_subagents" ]] && active="$(<"$G/active_subagents")"; [[ $active =~ ^[0-9]+$ ]] || active=0
builder_started() { [[ -f "$G/agents.log" ]] || return 1; while IFS=$'\t' read -r _t r _rest; do [[ $r == builder ]] && return 0; done < "$G/agents.log"; return 1; }

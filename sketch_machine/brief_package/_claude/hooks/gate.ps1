# Gate for Mule brief runs (v4): keeps the RULES in context and enforces builder -> referee -> (qc, engineer).
# Base: test 006 (2026-11-09 00:17). v4 changes are marked "v4 #<n>" (hooks_spec.md).
# Modes: context (SessionStart, UserPromptSubmit) | pretool (PreToolUse on Agent) | stop (Stop)
param([string]$Mode = 'context')
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding  = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

# fail closed: any error in this script blocks the guarded call and says so (never a silent pass)
function Plain-Json([string]$s) { (($s -replace '\\', '/' -replace '"', "'" -replace "[`r`n`t]", ' ').ToCharArray() | ForEach-Object { if ([int]$_ -gt 126) { '?' } else { $_ } }) -join '' }
trap {
  $err = Plain-Json ("$_ at line " + $_.InvocationInfo.ScriptLineNumber)
  if ($Mode -eq 'pretool') {
    [Console]::Out.Write('{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"GATE ERROR - the gate hook failed, so this agent start is blocked: ' + $err + '. Tell the artist."}}')
  } elseif ($Mode -eq 'context') {
    try { [Console]::Out.Write((Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot '..\..\rules.md'))) } catch {}
    [Console]::Out.Write("`nGATE STATUS: ERROR in the gate hook ($err). Tell the artist; until it is fixed keep the rules by hand.")
  } else {
    [Console]::Out.Write('{"systemMessage":"GATE ERROR in the Stop hook: ' + $err + '"}')
  }
  exit 0
}

$Brief = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$RoleNames = @('builder', 'referee', 'qc', 'engineer', 'helper', 'standin', 'viewer')

# configuration: gate.conf (artist) overlaid by gate.local.conf (written only by this hook from "SET:" lines of the artist, v4 #3)
function Read-Conf {
  $h = @{}
  foreach ($f in @('gate.conf', 'gate.local.conf')) {
    $p = Join-Path $PSScriptRoot $f
    if (Test-Path $p) { foreach ($l in [IO.File]::ReadAllLines($p)) { if ($l -match '^\s*([A-Za-z0-9_]+)\s*=(.*)$') { $h[$Matches[1].ToUpper()] = $Matches[2].Trim() } } }
  }
  $h
}
function Load-Conf {
  $script:C = Read-Conf
  $script:Work = [string]$C['WORK']
  # shared files (rule 14): read-only unless one builder holds them
  $script:SharedFiles = @(if ($C['SHARED_FILES']) { $C['SHARED_FILES'] -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ } })
  # parallel builder lanes, set by the artist only; default 1 = serial
  $script:MaxBuilders = 1; $x = 0
  if ($C['MAX_BUILDERS'] -and [int]::TryParse($C['MAX_BUILDERS'], [ref]$x) -and $x -ge 1) { $script:MaxBuilders = $x }
  # v4 #2: level of this round; no LEVEL = final (the behaviour of 006)
  $script:Level = 'final'
  if ($C['LEVEL'] -and @('scout', 'study', 'final') -contains $C['LEVEL'].ToLower()) { $script:Level = $C['LEVEL'].ToLower() }
}
Load-Conf
$Gate  = Join-Path $Work 'review\gate'
$Iter  = Join-Path $Work 'review\iter'
$Units = Join-Path $Work 'review\units'
foreach ($d in @($Gate, $Iter, $Units)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force $d | Out-Null } }
$AgentsLog = Join-Path $Gate 'agents.log'
$Rules = Get-Content -Raw -Encoding UTF8 (Join-Path $Brief 'rules.md')

function Esc-Json([string]$s) {
  # ConvertTo-Json in PS 5.1 leaves non-ASCII as is; escape it so any reader decodes it safely
  $sb = New-Object System.Text.StringBuilder
  foreach ($ch in $s.ToCharArray()) { if ([int]$ch -gt 126) { [void]$sb.AppendFormat('\u{0:x4}', [int]$ch) } else { [void]$sb.Append($ch) } }
  $sb.ToString()
}
function Out-Json($obj) { [Console]::Out.Write((Esc-Json ($obj | ConvertTo-Json -Depth 20 -Compress))) }
function Read-Input { $raw = [Console]::In.ReadToEnd(); if ($raw.Trim()) { $raw | ConvertFrom-Json } else { $null } }
function Now-Ep { [DateTimeOffset]::Now.ToUnixTimeSeconds() }

function Get-Log {
  $rows = @()
  if (Test-Path $AgentsLog) {
    $i = 0
    foreach ($l in Get-Content -Encoding UTF8 $AgentsLog) {
      $p = $l -split "`t"
      if ($p.Count -ge 4) { $rows += [pscustomobject]@{ idx = $i; time = $p[0]; role = $p[1]; unit = $p[2]; iter = $p[3] }; $i++ }
    }
  }
  ,$rows
}
# agents.log: time, role, unit, iteration, description, epoch, start type (v4 #1: role name = started by agent type, gp = by ROLE line)
function Add-Log($role, $unit, $itn, $desc, $stype) {
  $line = "{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}" -f (Get-Date -Format 's'), $role, $unit, $itn, ($desc -replace "[`t`r`n]", ' '), (Now-Ep), $stype
  [IO.File]::AppendAllText($AgentsLog, $line + "`r`n", $Utf8)
}
function BuilderReport($n) { Join-Path $Iter ('{0}_builder.md' -f $n) }
function Base-Unit([string]$u) { $u -replace '-.*$', '' }

# v4 #2: the column of the current level in levels.md, as lines "- <row>: <cell>"
function Level-Row($lv) {
  $lf = Join-Path $Brief 'levels.md'
  if (-not (Test-Path $lf)) { return "LEVEL: $lv (levels.md missing)" }
  $tab = @([IO.File]::ReadAllLines($lf) | Where-Object { $_ -match '^\s*\|' })
  if ($tab.Count -lt 3) { return "LEVEL: $lv" }
  $hdr = $tab[0] -split '\|'
  $col = -1; for ($i = 0; $i -lt $hdr.Count; $i++) { if ($hdr[$i] -match ('(?i)\b' + $lv + '\b')) { $col = $i; break } }
  $out = @("LEVEL: $lv - " + (($hdr[$col] -replace '\*', '').Trim()) + " (levels.md; build and check to this level, not deeper; nothing of the next level is owed):")
  foreach ($r in $tab[2..($tab.Count - 1)]) {
    $c = $r -split '\|'
    if ($c.Count -gt $col -and $col -ge 0) { $out += ('- ' + (($c[1] -replace '\*', '').Trim()) + ': ' + $c[$col].Trim()) }
  }
  $out -join "`n"
}

function Get-State {
  $log = Get-Log
  $builders = @($log | Where-Object role -eq 'builder')
  $running  = @($builders | Where-Object { -not (Test-Path (BuilderReport $_.iter)) })
  $finished = @($builders | Where-Object { Test-Path (BuilderReport $_.iter) })
  # an iteration whose report starts with ABORTED needs no referee
  $aborted  = @($finished | Where-Object { (Get-Content -Encoding UTF8 (BuilderReport $_.iter) -TotalCount 1) -match '^\s*ABORTED' } | ForEach-Object iter)
  # a referee line covers one iteration, or at scout several of one unit ("003,005"); its report is named by the last
  $refEntries = @($log | Where-Object role -eq 'referee' | ForEach-Object { $its = @($_.iter -split ','); [pscustomobject]@{ iters = $its; report = (Join-Path $Iter ('{0}_referee.md' -f $its[-1])) } })
  $refereed = @($refEntries | ForEach-Object { $_.iters })
  $needRef  = @($finished | Where-Object { $refereed -notcontains $_.iter -and $aborted -notcontains $_.iter })
  # v4 #2: at scout one referee per unit over all its runs, due when the unit report exists
  if ($Level -eq 'scout') { $needRef = @($needRef | Where-Object { Test-Path (Join-Path $Units ("{0}_report.md" -f (Base-Unit $_.unit))) }) }
  $active = 0; $af = Join-Path $Gate 'active_subagents'; if (Test-Path $af) { [int]::TryParse((Get-Content $af -TotalCount 1), [ref]$active) | Out-Null }
  # a referee counts as done only when its report exists
  $refRunning = @($refEntries | Where-Object { -not (Test-Path $_.report) } | ForEach-Object { $_.iters } | Select-Object -Unique)
  $open = @()
  foreach ($b in $needRef) { $open += "Referee missing for builder iteration $($b.iter) (unit $($b.unit)): start an agent with ROLE: referee." }
  # a referee that was started but left no report (crashed) counts as missing once no agent is running
  $missingRef = @()
  if ($active -eq 0) {
    foreach ($e in @($refEntries | Where-Object { -not (Test-Path $_.report) })) {
      $missingRef += @($builders | Where-Object { $e.iters -contains $_.iter })
      $open += "The referee of iteration $($e.iters -join ',') left no report ($([IO.Path]::GetFileName($e.report))): start ROLE: referee again." }
  }
  $missingRef = @($missingRef | Sort-Object idx -Unique)
  foreach ($r in @(Get-ChildItem -Path $Units -Filter '*_report.md' -ErrorAction SilentlyContinue)) {
    $u = $r.Name -replace '_report\.md$', ''
    # the unit and its packages (<unit>-<package>) together
    $lastB = @($builders | Where-Object { $_.unit -eq $u -or $_.unit -like "$u-*" } | Select-Object -Last 1)
    $after = if ($lastB.Count) { $lastB[0].idx } else { -1 }
    $lastRunning = $lastB.Count -and -not (Test-Path (BuilderReport $lastB[0].iter))
    # once a unit has a report, every later build of it needs a fresh QC before the turn ends
    if ($lastB.Count -and -not $lastRunning -and -not @($log | Where-Object { $_.role -eq 'qc' -and $_.unit -eq $u -and $_.iter -ne 'TARGETS' -and $_.idx -gt $after }).Count) {
      $open += "Unit $u is reported as finished but no QC ran after its last build: start ROLE: qc UNIT: $u." }
    # v4 #2: engineer after every unit only at final
    if ($Level -eq 'final' -and -not @($log | Where-Object { $_.role -eq 'engineer' -and $_.unit -eq $u }).Count) {
      $open += "Unit $u is reported as finished but the engineer has not run for it: start ROLE: engineer UNIT: $u." }
  }
  # v4 #2: at study the engineer runs once per round, after the round QC
  $rq = Join-Path $Work 'review\round_qc.md'
  if ($Level -eq 'study' -and (Test-Path $rq) -and -not @($log | Where-Object { $_.role -eq 'engineer' -and $_.unit -eq 'ROUND' }).Count) {
    $open += "The round QC is written but the engineer has not run for this round: start ROLE: engineer UNIT: ROUND." }
  $veto = $null
  $lastFin = @($finished | Select-Object -Last 1)
  if ($lastFin.Count) {
    $rf = Join-Path $Iter ('{0}_referee.md' -f $lastFin[0].iter)
    if (Test-Path $rf) {
      $vline = @(Get-Content -Encoding UTF8 $rf -TotalCount 8 | Where-Object { $_ -match 'VERDICT' } | Select-Object -First 1)
      if ($vline.Count -and $vline[0] -match 'VETO') { $veto = "Iteration $($lastFin[0].iter): $($vline[0].Trim())" }
    }
  }
  [pscustomobject]@{ log = $log; builders = $builders; running = $running; finished = $finished; needRef = $needRef; missingRef = $missingRef; refRunning = $refRunning; open = $open; veto = $veto }
}

function Last-ArtistTime {
  $al = Join-Path $Gate 'artist.log'; $t = [datetime]::MinValue
  if (Test-Path $al) {
    foreach ($l in [IO.File]::ReadAllLines($al)) { if ($l -match '^===== (\S+)') { $x = [datetime]::MinValue; if ([datetime]::TryParse($Matches[1], [ref]$x)) { $t = $x } } }
  }
  $t
}

# v4 #4: the mandatory keys of the level (levels.md, first round)
function Level-Keys($lv) {
  if ($lv -eq 'scout') { @('goal', 'level', 'units', 'approach') }
  else { @('goal', 'level', 'units', 'approach', 'blockout', 'tolerance', 'collision', 'visibility', 'sheet', 'away', 'marks') }
}
function Missing-Readings($lv) {
  $rf = Join-Path $Work 'review\readings.md'
  $txt = if (Test-Path $rf) { Get-Content -Raw -Encoding UTF8 $rf } else { '' }
  @(Level-Keys $lv | Where-Object { $txt -notmatch ('(?im)^\s*[-*|]?\s*[`*]*' + $_ + '[`*]*\s*:\s*\S') })
}

# v4 #9: plan usage written by the status line (hooks/statusline.sh), else once by hand: "weekly=<n> 5h=<n> time=<iso>"
function Budget {
  $uf = Join-Path $Gate 'usage.txt'
  $b = [pscustomobject]@{ exists = $false; weekly = $null; h5 = $null; age = $null; stale = $true }
  if (-not (Test-Path $uf)) { return $b }
  $b.exists = $true
  $t = [IO.File]::ReadAllText($uf)
  $d = 0.0
  if ($t -match '(?i)weekly\s*=\s*([0-9.]+)' -and [double]::TryParse($Matches[1], [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$d)) { $b.weekly = $d }
  if ($t -match '(?i)\b5h\s*=\s*([0-9.]+)' -and [double]::TryParse($Matches[1], [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$d)) { $b.h5 = $d }
  $b.age = ((Get-Date) - (Get-Item $uf).LastWriteTime).TotalMinutes
  $b.stale = $b.age -gt 20
  $b
}
function Budget-Stop {
  $b = Budget
  $mw = 0.0; $m5 = 0.0
  $why = $null
  if ($b.weekly -ne $null -and $C['MAX_WEEKLY'] -and [double]::TryParse($C['MAX_WEEKLY'], [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$mw) -and $b.weekly -ge $mw) { $why = "weekly use $($b.weekly) % >= MAX_WEEKLY $mw %" }
  if (-not $why -and $b.h5 -ne $null -and $C['MAX_5H'] -and [double]::TryParse($C['MAX_5H'], [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$m5) -and $b.h5 -ge $m5) { $why = "5-hour use $($b.h5) % >= MAX_5H $m5 %" }
  $why
}
function Deadline-Passed { $se = 0; ($C['STOP_AT'] -and [long]::TryParse($C['STOP_AT'], [ref]$se) -and (Now-Ep) -ge $se) }

function Status-Text($st) {
  $t = @('GATE STATUS (from the hooks):')
  $t += "- LEVEL: $Level; MAX_BUILDERS: $MaxBuilders" + $(if ($C['PAUSE']) { "; PAUSED: $($C['PAUSE'])" } else { '' }) + ' (gate.conf / SET: lines of the artist).'
  if ($st.running.Count) { $t += ($st.running | ForEach-Object { "- Builder iteration $($_.iter) (unit $($_.unit)) is running or has no report yet." }) }
  if ($st.open.Count) { $t += ($st.open | ForEach-Object { "- OPEN: $_" }) }
  if ($st.veto) { $t += "- VETO to fix: $($st.veto)" }
  # v4 #7: changes made by a viewer since the artist's last message
  $vv = Join-Path $Gate 'viewer_veto.log'
  if (Test-Path $vv) {
    $since = Last-ArtistTime
    foreach ($l in [IO.File]::ReadAllLines($vv)) { $x = [datetime]::MinValue; if ([datetime]::TryParse(($l -split "`t")[0], [ref]$x) -and $x -ge $since) { $t += "- VETO (viewer): $(($l -split "`t", 2)[1])" } }
  }
  # v4 #9: budget
  $b = Budget; $bs = Budget-Stop
  if ($bs) { $t += "- BUDGET STOP: $bs - no new agent starts. Write the state and tell the artist." }
  elseif (-not $b.exists) { $t += '- Budget: review/gate/usage.txt is missing. The status line writes it after the first answer; if it stays missing, write it once by hand (usage tool, Write tool, one line weekly=<n> 5h=<n> time=<iso>). No recurring job.' }
  elseif ($b.stale) { $t += ("- Budget: review/gate/usage.txt is {0:N0} minutes old - the status line did not refresh it; before the next agent start write it once by hand (usage tool, Write tool)." -f $b.age) }
  if (-not $st.running.Count -and -not $st.open.Count -and -not $st.veto) { $t += '- nothing open.' }
  $t += '- Artist feedback: first add it as lines to review/worklist.md; it never replaces the RULES.'
  # v4 #15: language
  $lang = "- Talk to the artist in the artist's language (the language of the artist's messages in review/gate/artist.log)"
  $al = Join-Path $Gate 'artist.log'
  if (Test-Path $al) {
    $last = @(([IO.File]::ReadAllText($al) -split '(?m)^===== ') | Where-Object { $_.Trim() } | Select-Object -Last 1)
    if ($last.Count) { $body = (($last[0] -split "`r?`n", 2)[1] + '') -replace '\s+', ' '; $body = $body.Trim(); if ($body.Length -gt 60) { $body = $body.Substring(0, 60) }; if ($body) { $lang += "; last message begins: '$body'" } }
  }
  $t += ($lang + '.')
  $t -join "`n"
}

# v4 #3: "SET: <key>=<value>" lines of a real artist message go into gate.local.conf (locked for every agent)
function Apply-Set([string]$prompt) {
  $msgs = @()
  $ms = [regex]::Matches($prompt, '(?im)^[ \t>*-]*SET:[ \t]*([A-Za-z_0-9]+)[ \t]*=[ \t]*([^\r\n]*?)[ \t]*$')
  if (-not $ms.Count) { return }
  $lp = Join-Path $PSScriptRoot 'gate.local.conf'
  $loc = [ordered]@{}
  if (Test-Path $lp) { foreach ($l in [IO.File]::ReadAllLines($lp)) { if ($l -match '^\s*([A-Za-z0-9_]+)\s*=(.*)$') { $loc[$Matches[1].ToUpper()] = $Matches[2].Trim() } } }
  foreach ($m in $ms) {
    $k = $m.Groups[1].Value.ToLower(); $v = $m.Groups[2].Value.Trim().Trim('`', '"', "'"); $n = 0
    switch ($k) {
      'level'        { if (@('scout', 'study', 'final') -contains $v.ToLower()) { $loc['LEVEL'] = $v.ToLower(); $msgs += "SET level=$($v.ToLower()) applied." } else { $msgs += "SET level=$v refused: use scout, study or final." } }
      'max_builders' { if ([int]::TryParse($v, [ref]$n) -and $n -ge 1 -and $n -le 12) { $loc['MAX_BUILDERS'] = "$n"; $msgs += "SET max_builders=$n applied." } else { $msgs += "SET max_builders=$v refused: a number 1-12." } }
      'max_weekly'   { if ([int]::TryParse($v, [ref]$n) -and $n -ge 1 -and $n -le 100) { $loc['MAX_WEEKLY'] = "$n"; $msgs += "SET max_weekly=$n applied." } else { $msgs += "SET max_weekly=$v refused: a percentage 1-100." } }
      'pause'        { if ($v -match '^(?i)(off|none|no|0|)$') { $loc['PAUSE'] = ''; $msgs += 'SET pause=off applied: builders may start again.' } else { $loc['PAUSE'] = ($v -replace '[\r\n=]', ' '); $msgs += "SET pause applied: $v" } }
      default        { $msgs += "SET $k refused: only level, max_builders, pause, max_weekly can be set from a message." }
    }
  }
  $txt = ($loc.Keys | ForEach-Object { "$_=$($loc[$_])" }) -join "`r`n"
  [IO.File]::WriteAllText($lp, "# written by gate.ps1 from SET: lines of the artist's messages - never by an agent`r`n" + $txt + "`r`n", $Utf8)
  [IO.File]::AppendAllText((Join-Path $Gate 'set.log'), ("{0}`t{1}`r`n" -f (Get-Date -Format 's'), ($msgs -join ' ')), $Utf8)
  $msgs  # flat: the caller collects with @(); a wrapped ,$msgs arrived there as one element and printed as System.Object[]
}

# v4 #12: the lines of tools.log in a time window (ISO times compare as strings)
function Tools-Extract([string]$from, [string]$to, [string]$out) {
  $tl = Join-Path $Gate 'tools.log'
  $lines = @()
  if (Test-Path $tl) { $lines = @([IO.File]::ReadAllLines($tl) | Where-Object { $_.Length -ge 19 -and $_.Substring(0, 19) -ge $from -and $_.Substring(0, 19) -le $to }) }
  [IO.File]::WriteAllText($out, (($lines -join "`r`n") + "`r`n"), $Utf8)
  $builds = @($lines | Where-Object { ($_ -split "`t")[-1] -eq '1' })
  $mainBuilds = @($builds | Where-Object { ($_ -split "`t")[2] -eq 'main' })
  $denied = @($lines | Where-Object { ($_ -split "`t")[1] -eq 'DENIED' })
  $txt = "Extract of review/gate/tools.log for the window $from .. $to ($($lines.Count) lines): $out - build calls $($builds.Count), by main $($mainBuilds.Count), refused calls $($denied.Count)."
  # v4 #17: effort of the window - expensive calls with duration, repeats of a call that already ran for 60 s or more
  $cl = Join-Path $Gate 'commands.log'
  if (Test-Path $cl) {
    $cm = @([IO.File]::ReadAllLines($cl) | Where-Object { $_.Length -ge 19 -and $_.Substring(0, 19) -ge $from -and $_.Substring(0, 19) -le $to })
    if ($cm.Count) {
      $sec = 0; foreach ($c in $cm) { $d = 0; [void][int]::TryParse(($c -split "`t")[4], [ref]$d); $sec += $d }
      $rp = @($cm | Where-Object { ($_ -split "`t")[6] -eq 'REPEAT' })
      $txt += " Effort: $($cm.Count) expensive calls, $([math]::Round($sec / 60)) min (review/gate/commands.log)"
      if ($rp.Count) { $txt += "; REPEATED with the same text after a run of 60 s or more: " + (@($rp | Select-Object -First 3 | ForEach-Object { $f = $_ -split "`t"; "$($f[0]) $($f[4]) s: $($f[7])" }) -join ' | ') + " - ask in your report whether the inputs had changed (rule 17)" }
      $txt += '.'
    }
  }
  $txt
}

# v4 #18: content signature of export files: path, size and SHA-256 of the first and last 4 MB
function Export-Sig($files, [string]$root) {
  $sha = [Security.Cryptography.SHA256]::Create()
  (@($files | Sort-Object FullName | ForEach-Object {
    $fs = [IO.File]::OpenRead($_.FullName)
    try {
      $n = [int][math]::Min(4MB, $fs.Length); $buf = New-Object byte[] ([math]::Max(1, $n * 2)); $r = $fs.Read($buf, 0, $n)
      if ($fs.Length -gt $n) { [void]$fs.Seek(-$n, 'End'); $r += $fs.Read($buf, $n, $n) }
      $h = [BitConverter]::ToString($sha.ComputeHash($buf, 0, $r)) -replace '-', ''
    } finally { $fs.Dispose() }
    '{0}|{1}|{2}' -f $_.FullName.Substring($root.Length), $_.Length, $h
  })) -join "`n"
}

# v4 #17: tokens per unit from review/gate/agent_tokens.tsv (cols: time agent role unit iter in cache_write cache_read out minutes)
function Unit-Effort([string]$u) {
  $tf = Join-Path $Gate 'agent_tokens.tsv'
  if (-not (Test-Path $tf)) { return '' }
  $rows = @([IO.File]::ReadAllLines($tf) | ForEach-Object { , ($_ -split "`t") } | Where-Object { $_.Count -ge 9 -and ($_[3] -eq $u -or $_[3] -like "$u-*") })
  if (-not $rows.Count) { return '' }
  $by = @{}; foreach ($r in $rows) { $k = $r[2]; if (-not $by[$k]) { $by[$k] = @(0, 0.0, 0.0) }; $by[$k][0]++; $by[$k][1] += [double]$r[7]; $by[$k][2] += [double]$r[8] }
  "Effort of unit $u (review/gate/agent_tokens.tsv): " + ((@($by.Keys | Sort-Object | ForEach-Object { "{0} {1} runs, {2:N1} M cache read, {3:N0} k output" -f $_, $by[$_][0], ($by[$_][1] / 1e6), ($by[$_][2] / 1e3) })) -join '; ') + '.'
}

# v4 #13: only the sections of bauwissen.md whose keywords match the task, plus pitfalls
function Bauwissen-For([string]$role, [string]$task) {
  $bw = Join-Path $Work 'review\bauwissen.md'
  if (-not (Test-Path $bw)) { return '' }
  $b = Get-Content -Raw -Encoding UTF8 $bw
  $cut = { param($s) if ($s.Length -gt 14000) { $s.Substring(0, 14000) + "`n[... cut: bauwissen.md is longer than about two pages - the engineer must tidy it]" } else { $s } }
  if ($role -eq 'engineer') { return "`nBAUWISSEN (review/bauwissen.md, whole - you tidy it):`n" + (& $cut $b) }
  $lines = $b -split "`r?`n"
  if (-not @($lines | Where-Object { $_ -match '^#{1,4}\s+\S' }).Count) { return "`nBAUWISSEN (review/bauwissen.md - use it before you invent anything new):`n" + (& $cut $b) }
  $stop = @('the', 'and', 'for', 'with', 'from', 'into', 'that', 'this', 'not', 'are', 'all', 'use', 'keywords')
  $secs = @(); $cur = [pscustomobject]@{ head = ''; body = New-Object System.Collections.ArrayList }
  foreach ($l in $lines) {
    if ($l -match '^#{1,4}\s+\S') { $secs += $cur; $cur = [pscustomobject]@{ head = $l; body = New-Object System.Collections.ArrayList } }
    [void]$cur.body.Add($l)
  }
  $secs += $cur
  $keep = @(); $left = @()
  foreach ($s in $secs) {
    if (-not $s.head) { if (($s.body -join '').Trim()) { $keep += ($s.body -join "`n") }; continue }
    $kwText = $s.head + ' ' + (@($s.body | Where-Object { $_ -match '(?i)^\s*[*_]*keywords?[*_]*\s*:' }) -join ' ')
    $kws = @(($kwText -replace '(?i)keywords?\s*:', ' ') -split '[^A-Za-z0-9_\-]+' | Where-Object { $_.Length -ge 2 -and $stop -notcontains $_.ToLower() -and $_ -notmatch '^-+$' } | Select-Object -Unique)
    $hit = $s.head -match '(?i)pitfall'
    if (-not $hit) { foreach ($k in $kws) { if ($k.Length -ge 3 -or $k -match '\d') { if ($task -match ('(?i)(?<![A-Za-z0-9])' + [regex]::Escape($k) + '(?![A-Za-z0-9])')) { $hit = $true; break } } } }
    if ($hit) { $keep += ($s.body -join "`n") } else { $left += ($s.head -replace '^#+\s*', '').Trim() }
  }
  $txt = "`nBAUWISSEN (sections of review/bauwissen.md that match your task, plus pitfalls - use them before you invent anything new):`n" + (& $cut ($keep -join "`n"))
  if ($left.Count) { $txt += "`n[sections left out: " + ($left -join ' | ') + " - read review/bauwissen.md if you need one]" }
  $txt
}

switch ($Mode) {
  'context' {
    $in = Read-Input
    $setMsgs = @()
    # keep the artist's own words for the referee, the next builder, the stand-in and the language: only a real
    # artist message (UserPromptSubmit in the main chat) - not a notification, a subagent's hand-back (agent-message)
    # or a recurring job of the main chat (usage watcher, prompt starts with [usage-watcher]; Hafen test 2026-11-12:
    # these were logged as the artist's words)
    $p = if ($in -and $in.prompt) { [string]$in.prompt } else { '' }
    $isArtist = $p -and [string]$in.hook_event_name -eq 'UserPromptSubmit' -and -not $in.agent_id -and
      $p -notmatch '^\s*<(task-notification|system-reminder|agent-message|teammate-message)' -and
      $p -notmatch '^\s*(\[usage-watcher\]|Usage watcher\b)'
    if ($isArtist) {
      $entry = "===== {0}`r`n{1}`r`n" -f (Get-Date -Format 's'), $p
      [IO.File]::AppendAllText((Join-Path $Gate 'artist.log'), $entry, $Utf8)
      # v4 #3: SET: lines only from the artist's own message, never from a quoted message of another agent
      if ($p -notmatch '<(task-notification|system-reminder|agent-message|teammate-message)') {
        $setMsgs = @(Apply-Set $p)
        if ($setMsgs.Count) { Load-Conf }
      }
    }
    $st = Get-State
    $text = $Rules + "`n" + (Status-Text $st)
    if ($setMsgs.Count) { $text += "`n- SET by the artist's message: " + ($setMsgs -join ' ') }
    # static reminder for the fast bash hook (every N tool calls)
    $rem = @{ hookSpecificOutput = @{ hookEventName = 'PostToolUse'; additionalContext = ("REMINDER - keep to these rules now:`n" + $Rules) } }
    [IO.File]::WriteAllText((Join-Path $Gate 'reminder.json'), (Esc-Json ($rem | ConvertTo-Json -Depth 5 -Compress)))
    [Console]::Out.Write($text)
  }

  'pretool' {
    $in = Read-Input
    $ti = $in.tool_input
    $prompt = [string]$ti.prompt
    $deny = {
      param($why)
      Out-Json @{ hookSpecificOutput = @{ hookEventName = 'PreToolUse'; permissionDecision = 'deny'; permissionDecisionReason = "GATE: $why" } }
      exit 0
    }
    $stype = ([string]$ti.subagent_type).ToLower()
    if ($stype -eq 'fork') { & $deny 'A fork inherits the whole main context; every agent here must be fresh. Start it with its agent type (builder, referee, qc, engineer, helper, standin, viewer).' }
    # v4 #1: the role comes from the agent type (.claude/agents/<role>.md); fallback: the ROLE line
    $lineRole = if ($prompt -match '(?im)^\s*\**ROLE:\s*\**\s*(builder|referee|qc|engineer|helper|stand-?in|viewer)\b') { $Matches[1].ToLower() -replace '-', '' } else { $null }
    $typed = $RoleNames -contains $stype
    if ($typed) {
      $role = $stype
      if ($lineRole -and $lineRole -ne $role) { & $deny "The agent type is $role but the prompt says ROLE: $lineRole. Use one role: the agent type of that role." }
    } else { $role = $lineRole }
    $unit = if ($prompt -match '(?im)\bUNIT:\s*\**\s*([A-Za-z0-9_\-]+)') { $Matches[1] } else { $null }
    # hard deadline set by the artist (STOP_AT = epoch seconds): no agent starts after it
    if (Deadline-Passed) { & $deny 'The artist ended the test at its deadline. Start no agent. Write a short final state into review/worklist.md and the state notes, then stop.' }
    # v4 #9: budget
    $bs = Budget-Stop
    if ($bs) { & $deny "Budget stop ($bs, review/gate/usage.txt). Start no agent. Write the state into review/worklist.md and the state notes, tell the artist, then stop." }
    # v4 #19: main chat context above HANDOVER_AT (posttool writes review/gate/handover_due, again every 100 k):
    # no new agent until review/conductor_handover.md is newer than that mark. Running agents and the end of a turn are never blocked.
    $hd = Join-Path $Gate 'handover_due'; $ho = Join-Path $Work 'review\conductor_handover.md'
    if (-not $in.agent_id -and (Test-Path $hd) -and (-not (Test-Path $ho) -or (Get-Item $ho).LastWriteTime -lt (Get-Item $hd).LastWriteTime)) {
      $k = ([IO.File]::ReadAllText($hd)).Trim()
      & $deny "Your context is about $k k tokens, above HANDOVER_AT. Before the next agent: write the hand-over into review/conductor_handover.md (state per unit, open lanes and checks, next steps, changes to tools/), then ask the artist for a fresh chat that continues from it. Running agents go on; after the hand-over new agents may start again." }
    if (-not $role) { & $deny 'Start every agent with its agent type (builder, referee, qc, engineer, helper, standin, viewer) or a first line "ROLE: <role>"; except helper, standin and viewer also a line "UNIT: <id>" (rules 1-2).' }
    if (@('helper', 'standin', 'viewer') -notcontains $role -and -not $unit) { & $deny "ROLE: $role needs a line UNIT: <id>." }
    # agents started in one message run their hooks at the same time: one start at a time, so that each gets its own
    # iteration number (read state, count, write the log line). The lock is held until this process ends.
    $startLock = $null
    for ($try = 0; $try -lt 300 -and -not $startLock; $try++) {
      try { $startLock = [IO.File]::Open((Join-Path $Gate 'start.lock'), 'OpenOrCreate', 'ReadWrite', 'None') } catch { Start-Sleep -Milliseconds 50 }
    }
    $st = Get-State
    # the hooks map agent ids to roles by start order: lines started by ROLE line are told apart only by order,
    # lines started by agent type by their type (v4 #1). Pending = logged in the last 3 minutes and not yet mapped.
    $mapped = @{}
    $rt = Join-Path $Gate 'agent_roles.tsv'
    if (Test-Path $rt) { foreach ($l in Get-Content -Encoding UTF8 $rt) { $p = $l -split "`t"; if ($p.Count -ge 5 -and $p[4]) { $mapped[$p[4].Trim()] = 1 } } }
    $sreq = @{}
    $srt = Join-Path $Gate 'shared_requests.tsv'
    if (Test-Path $srt) { foreach ($l in Get-Content -Encoding UTF8 $srt) { $p = $l -split "`t"; if ($p.Count -ge 2) { $sreq[$p[0].Trim()] = 1 } } }
    $wantsShared = $prompt -match '(?im)^\s*\**SHARED:'
    $nowEp = Now-Ep; $k = 0
    if (Test-Path $AgentsLog) {
      foreach ($l in Get-Content -Encoding UTF8 $AgentsLog) {
        $k++; $p = $l -split "`t"; $ep = 0
        if ($p.Count -ge 6 -and [long]::TryParse($p[5].Trim(), [ref]$ep) -and ($nowEp - $ep) -le 180 -and -not $mapped.ContainsKey([string]$k)) {
          $ptype = if ($p.Count -ge 7 -and $p[6].Trim()) { $p[6].Trim() } else { 'gp' }
          if (-not $typed -and $ptype -eq 'gp') {
            & $deny "The previous agent ($($p[1]) $($p[2])) has not started yet. Agents started with a ROLE line go one per message (or start them with their agent type); try again once it runs (at most 3 minutes)." }
          if ($typed -and $ptype -eq $role -and ($wantsShared -or $sreq.ContainsKey([string]$k))) {
            & $deny "Another $role ($($p[2])) started in the same message and one of the two holds shared files (SHARED:). The hooks cannot tell two agents of one type apart, so start this one in the next message." }
        }
      }
    }
    $itNo = '-'; $gateText = ''; $refExtract = ''
    $stageName = if ($prompt -match '(?im)^\s*\**STAGE:\s*\**\s*([A-Za-z0-9_\-]+)') { $Matches[1].ToLower() } else { '' }
    switch ($role) {
      'builder' {
        # pause set by the artist (PAUSE=<reason>, or SET: pause=<reason>): no new builder starts; checks of finished runs go on
        if ($C['PAUSE']) { & $deny ("Paused by the artist: " + $C['PAUSE'] + ". Start no builder. Finish the referee/QC of runs that ended, write the state, then wait for the artist.") }
        # packages: UNIT <unit>-<package> (e.g. U45-hda, U45-kit) are parallel parts of one unit
        $isPkg = $unit -match '^([A-Za-z0-9_]+)-(.+)$'
        $baseUnit = if ($isPkg) { $Matches[1] } else { $unit }
        $isIntegrate = $stageName -like 'integrat*'
        if ($isIntegrate -and -not $isPkg) {
          $pkgIters = @($st.builders | Where-Object { $_.unit -like "$baseUnit-*" } | ForEach-Object iter)
          $pkgRun = @($st.running | Where-Object { $_.unit -like "$baseUnit-*" })
          $pkgRef = @(@($st.needRef) + @($st.missingRef) | Where-Object { $_.unit -like "$baseUnit-*" })
          $pkgRefRun = @($st.refRunning | Where-Object { $pkgIters -contains $_ })
          if ($pkgRun.Count -or $pkgRef.Count -or $pkgRefRun.Count) {
            & $deny ("STAGE: integrate for unit $baseUnit waits for its packages: " + ((@($pkgRun | ForEach-Object { "$($_.unit) $($_.iter) building" }) + @($pkgRef | ForEach-Object { "$($_.unit) $($_.iter) needs its referee" }) + @($pkgRefRun | ForEach-Object { "referee of $_ running" })) -join ', ') + ".") }
        }
        if (-not $st.builders.Count) {
          $miss = @(Missing-Readings $Level)
          if ($miss.Count) { & $deny ("The first builder starts only when the mandatory keys of level $Level are answered (levels.md, conductor.md). Missing lines in review/readings.md: " + ($miss -join ', ') + ". Ask the artist, or quote the brief section that settles it.") }
        }
        # v4 #5: STAGE: details needs a current visibility map and a tier on every new part line
        $stratFile = Join-Path $Work "review\strategy\$baseUnit.md"
        $stratMark = Join-Path $Gate "strategy_$baseUnit.lines"
        if ($stageName -match '^(map|vis)') { & $deny "A run that only runs the visibility map is a helper task (ROLE: helper, no referee, no QC). A builder runs tools/vis_map at the end of the run that changed the geometry (rule 7)." }
        if ($stageName -like 'detail*') {
          $vis = Join-Path $Work "review\vis\$($baseUnit)_vis.md"
          if (-not (Test-Path $vis)) { & $deny "STAGE: details for unit $baseUnit needs the visibility map review/vis/$($baseUnit)_vis.md (rule 7). Start ROLE: helper to run tools/vis_map for $baseUnit first." }
          $exDir = Join-Path $Work 'export'
          if (Test-Path $exDir) {
            $ure = '(?i)(^|[\\/_.\- ])' + [regex]::Escape($baseUnit) + '([\\/_.\- ]|$)'
            # only the unit's own exports count: export/<unit>/... or export/<unit>_*.usd; shared files deeper down (export/review/.../hide_<unit>.usda) do not
            $exAll = @(Get-ChildItem -Path $exDir -Recurse -File -ErrorAction SilentlyContinue | Where-Object { ($_.FullName.Substring($exDir.Length).TrimStart('\', '/') -split '[\\/]')[0] -match $ure } | Sort-Object LastWriteTime)
            $lastEx = @($exAll | Select-Object -Last 1)
            # v4 #18: the map ages by content, not by date - the gate keeps a signature of the exports it last saw
            # with a current map (review/gate/vis_<unit>.sig); a re-export with the same content keeps the map current
            $sigF = Join-Path $Gate ("vis_{0}.sig" -f $baseUnit); $sigNow = Export-Sig $exAll $exDir
            $mapOld = $lastEx.Count -and (Get-Item $vis).LastWriteTime -lt $lastEx[0].LastWriteTime
            if (-not $mapOld) { [IO.File]::WriteAllText($sigF, $sigNow, $Utf8) }
            elseif ((Test-Path $sigF) -and [IO.File]::ReadAllText($sigF) -eq $sigNow) { $mapOld = $false }
            if ($mapOld) {
              & $deny "The visibility map of $baseUnit ($((Get-Item $vis).LastWriteTime.ToString('s'))) is older than a changed export of the unit, $($lastEx[0].Name) ($($lastEx[0].LastWriteTime.ToString('s'))). The builder that changes the geometry runs tools/vis_map at the end of its own run (rule 7); if that was missed, ROLE: helper runs it before STAGE: details." }
          }
          # rule 7: components of the unit listed, and their views made for every rank the level asks (study: 1, final: 1-2)
          if ($Level -ne 'scout') {
            $cf = Join-Path $Work 'review\components.md'; $rows = @(); $sep = '[|' + [char]0xB7 + ']'   # columns split by | or a middle dot
            if (Test-Path $cf) {
              foreach ($l in [IO.File]::ReadAllLines($cf)) {
                if ($l -match '^\s*\|?\s*:?-{3,}' -or $l -match ('(?i)^\s*\|?\s*name\s*' + $sep)) { continue }
                $c = @(($l.Trim().Trim('|')) -split $sep | ForEach-Object { $_.Trim() })
                if ($c.Count -ge 4 -and $c[1] -eq $baseUnit) { $rows += , $c }
              }
            }
            if (-not $rows.Count) { & $deny "STAGE: details for unit $baseUnit needs its components, runs and areas in review/components.md (rule 7), one line each: name | unit | kind (component/run/area) | rank | views (name: why) | readable size. A unit with none writes one line of kind area, rank 3. The artist confirms them by exception, with one picture per view." }
            $maxRank = $(if ($Level -eq 'final') { 2 } else { 1 })
            $vd = Join-Path $Work 'review\vis'
            $made = (@(Get-ChildItem -Path $vd -Filter '*_views.json' -File -ErrorAction SilentlyContinue | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join "`n")
            $noViews = @($rows | Where-Object { $_[2] -notmatch '(?i)area' -and $_[3] -match '(\d)' -and [int]$Matches[1] -le $maxRank -and $made -notmatch ('"name":\s*"' + [regex]::Escape($_[0]) + '"') } | ForEach-Object { $_[0] })
            if ($noViews.Count) { & $deny ("STAGE: details for unit $baseUnit - component views not made yet for: " + ($noViews -join ', ') + ". Start ROLE: helper to run tools/vis_map with the key component for each (rule 7; it writes review/vis/<config unit>_views.json and the readable size).") }
          }
          if (Test-Path $stratFile) {
            $sl = @([IO.File]::ReadAllLines($stratFile))
            $from = 0; if (Test-Path $stratMark) { [int]::TryParse(([IO.File]::ReadAllText($stratMark)).Trim(), [ref]$from) | Out-Null }
            if ($from -gt $sl.Count) { $from = 0 }
            $bad = @()
            for ($i = $from; $i -lt $sl.Count; $i++) {
              $l = $sl[$i]
              if ($l -notmatch '\|') { continue }
              if ($l -match '^\s*\|?\s*:?-{3,}') { continue }
              if ($l -match '(?i)^\s*\|?\s*part\s*\|\s*purpose') { continue }
              $cells = @(($l.Trim().Trim('|')) -split '\|' | ForEach-Object { $_.Trim() })
              if ($cells.Count -lt 6 -or $cells[5] -notmatch '^[ABCSD](?![A-Za-z])') { $bad += ('line ' + ($i + 1) + ': ' + $(if ($l.Length -gt 60) { $l.Substring(0, 60) } else { $l })) }
            }
            if ($bad.Count) { & $deny ("STAGE: details for unit $baseUnit - new part lines in review/strategy/$baseUnit.md need the column tier (part | purpose | carrier | reference | binding level | tier, tier A/B/C/S/D from the map): " + (($bad | Select-Object -First 5) -join '; ')) }
          }
        }
        # lanes (rule 14): one builder per unit, at most $MaxBuilders at once; checks of a unit block only that unit
        $iterUnit = @{}; foreach ($x in $st.builders) { $iterUnit[$x.iter] = $x.unit }
        $refRunMine = @($st.refRunning | Where-Object { $iterUnit[$_] -eq $unit })
        if ($refRunMine.Count) { & $deny "The referee of iteration $($refRunMine[0]) (unit $unit) has not written its report yet. Wait for it before the next builder of this unit." }
        $runMine = @($st.running | Where-Object unit -eq $unit)
        if ($runMine.Count) { $r = $runMine[0]; & $deny "Builder iteration $($r.iter) of unit $unit has no report yet ($(BuilderReport $r.iter)). One builder per unit: wait for it. If it failed, write that file with 'ABORTED: <why>'." }
        if ($st.running.Count -ge $MaxBuilders) { & $deny ("$($st.running.Count) builder(s) running (" + (($st.running | ForEach-Object { "$($_.iter) $($_.unit)" }) -join ', ') + "); at most $MaxBuilders at once (gate.conf, set by the artist). Wait for one of them.") }
        $openMine = @($st.open | Where-Object { $_ -match ('(?i)\bunit ' + [regex]::Escape($unit) + '(?![\w-])') -or $_ -notmatch '(?i)\bunit\b' })
        if ($openMine.Count) { & $deny ("Open obligations first: " + ($openMine -join ' ')) }
        # open units = started, not reported and not paused; at most $MaxBuilders of them at once (packages count as part of their unit)
        $openUnits = @($st.builders | ForEach-Object { Base-Unit $_.unit } | Select-Object -Unique | Where-Object { -not (Test-Path (Join-Path $Units "$($_)_report.md")) -and -not (Test-Path (Join-Path $Units "$($_)_paused.md")) })
        if ($openUnits -notcontains $baseUnit -and $openUnits.Count -ge $MaxBuilders) {
          & $deny ("Starting unit $unit would make more than $MaxBuilders open units (" + ($openUnits -join ', ') + "). Close one first: write review/units/<unit>_report.md (four groups), then QC and engineer, or write review/units/<unit>_paused.md with the reason.") }
        $itNo = '{0:d3}' -f ($st.builders.Count + 1)
        $gateText = "GATE: you are builder iteration $itNo of unit $unit. Write your report to $(BuilderReport $itNo) - the next builder of this unit is blocked until that file exists."
        if ($MaxBuilders -gt 1) { $gateText += " Other units or packages may be built at the same time by other builders: touch only your own files; use a live Houdini or Blender session only if the hooks let you (one agent per session; headless blender -b / hython on your own files are always fine)." }
        if ($isPkg) { $gateText += "`nYou build PACKAGE $unit of unit $($baseUnit): deliver exactly what its contract in review/strategy/$($baseUnit).md says (inputs, outputs, sizes, ports), in your own files, versioned (e.g. _v003). Do not touch the unit's scene; the integrate run of $baseUnit brings it in." }
        if ($isIntegrate) { $gateText += "`nYou are the INTEGRATE run of unit $($baseUnit): bring in the latest versions of its packages (see their state notes), check them against their contracts and on pictures." }
        # shared files: requested with a line "SHARED: a; b" - each must be in SHARED_FILES and not held by another running agent
        $sharedReq = @()
        if ($SharedFiles.Count) {
          if ($prompt -match '(?im)^\s*\**SHARED:\s*\**\s*(.+)$') {
            foreach ($w in ($Matches[1] -split '[;,]' | ForEach-Object { $_.Trim().Trim('`') } | Where-Object { $_ })) {
              $hit = @($SharedFiles | Where-Object { $_ -eq $w -or [IO.Path]::GetFileName($_) -eq $w })
              if (-not $hit.Count) { & $deny "SHARED: '$w' is not a shared file. Shared files (gate.conf): $($SharedFiles -join ', '). Your own files need no SHARED line." }
              $sharedReq += $hit[0]
            }
          }
          $tlog = Join-Path $Gate 'tools.log'; $tl = if (Test-Path $tlog) { [IO.File]::ReadAllText($tlog) } else { '' }
          foreach ($f in $sharedReq) {
            $lk = Join-Path $Gate ('filelock_' + (($f -replace '[\\/]', '_') -replace '\.', '_'))
            if (Test-Path $lk) {
              $parts = (Get-Content $lk -TotalCount 1) -split "`t"; $owner = $parts[0]; $since = 0; [long]::TryParse(($parts[1] + '').Trim(), [ref]$since) | Out-Null
              $alive = (-not $tl.Contains("`tSUBAGENT-stop`t$owner")) -and (((Now-Ep) - $since) -le 3600)
              if ($alive) { & $deny "Shared file $f is held by another running agent ($owner). Wait until it ends, or plan the run without it." }
            }
          }
          if ($sharedReq.Count) { $gateText += "`nYou hold these shared files alone for this run: $($sharedReq -join ', '). Save them as usual; they become read-only again when you end." }
          $others = @($SharedFiles | Where-Object { $sharedReq -notcontains $_ })
          if ($others.Count) { $gateText += "`nRead-only for you: $($others -join ', '). Read and reference them, never save them. If you need to write one, stop at a clean point and say so in your report; the main chat restarts you with a line SHARED: <file>." }
        }
        # the veto of this unit's last finished run
        $lastMine = @($st.finished | Where-Object unit -eq $unit | Select-Object -Last 1)
        if ($lastMine.Count) {
          $rf = Join-Path $Iter ('{0}_referee.md' -f $lastMine[0].iter)
          if (Test-Path $rf) {
            $vl = @(Get-Content -Encoding UTF8 $rf -TotalCount 8 | Where-Object { $_ -match 'VERDICT' } | Select-Object -First 1)
            if ($vl.Count -and $vl[0] -match 'VETO') { $gateText += "`nThe last referee of this unit issued a VETO - fix it in this run or explain why not: Iteration $($lastMine[0].iter): $($vl[0].Trim())" }
          }
        }
        # v4 #5: remember where the strategy file ends now; the next STAGE: details checks the lines added after this
        $nLines = if (Test-Path $stratFile) { @([IO.File]::ReadAllLines($stratFile)).Count } else { 0 }
        [IO.File]::WriteAllText($stratMark, "$nLines", $Utf8)
      }
      'referee' {
        $waiting = @(@($st.needRef) + @($st.missingRef) | Sort-Object idx -Unique)
        if (-not $waiting.Count) { & $deny $(if ($Level -eq 'scout') { 'No unit is waiting for its referee (at scout the referee runs once per unit, after review/units/<unit>_report.md exists).' } else { 'No finished builder iteration is waiting for a referee.' }) }
        # with parallel lanes: take the waiting run of the unit named in the prompt, else the oldest
        $wMine = @($waiting | Where-Object unit -eq $unit)
        $b = if ($wMine.Count) { $wMine[0] } else { $waiting[0] }
        # v4 #2: at scout one referee covers all waiting runs of the unit
        $cover = if ($Level -eq 'scout') { @($waiting | Where-Object { (Base-Unit $_.unit) -eq (Base-Unit $b.unit) }) } else { @($b) }
        $itNo = (@($cover | ForEach-Object iter) -join ','); $unit = $b.unit
        $lastIt = $cover[-1].iter
        $reports = (@($cover | ForEach-Object { BuilderReport $_.iter }) -join ', ')
        # v4 #12: tools.log extract of the builders' window
        $from = (@($cover | ForEach-Object time) | Sort-Object | Select-Object -First 1)
        $endT = Get-Date
        $rp = @($cover | ForEach-Object { BuilderReport $_.iter } | Where-Object { Test-Path $_ } | ForEach-Object { (Get-Item $_).LastWriteTime } | Sort-Object | Select-Object -Last 1)
        if ($rp.Count) { $endT = $rp[0].AddMinutes(1) }
        $refExtract = Tools-Extract $from ($endT.ToString('s')) (Join-Path $Gate ("extract_{0}.log" -f $lastIt))
        $gateText = "GATE: you referee builder iteration(s) $itNo of unit $unit. Builder report(s): $reports. Write your report to $(Join-Path $Iter ($lastIt + '_referee.md')). Logs: $AgentsLog.`n$refExtract Read this extract, not the whole tools.log."
      }
      'qc' {
        if ($unit -eq 'ROUND') {
          # round QC: checks the whole goal against the done criteria (project document, goal)
          if (-not $st.finished.Count) { & $deny 'Round QC needs at least one finished builder run.' }
          if ($st.running.Count) { & $deny "Builder iteration $($st.running[0].iter) is still running; the round QC checks a finished state." }
          if ($st.open.Count) { & $deny ("Open obligations first: " + ($st.open -join ' ')) }
          $r1 = Join-Path $Work 'review\round_qc.md'; $r2 = Join-Path $Work 'review\round_qc_r2.md'
          $target = if (-not (Test-Path $r1)) { $r1 } elseif (-not (Test-Path $r2)) { $r2 } else { $null }
          if (-not $target) { & $deny 'Two round QCs are done (rule 15): the artist decides.' }
          $itNo = 'ROUND'
          $gateText = "GATE: you are the round QC. Check the whole goal against the done criteria in the project document: every work-list line of the goal, the last QC of every unit, open vetoes, the list for the artist. Write your report to $target; first line VERDICT: PASS or VERDICT: VETO - <criterion that fails>."
        } elseif ($stageName -eq 'targets') {
          # v4 #14: picture targets at unit start (study, final)
          if ($Level -eq 'scout') { & $deny 'At level scout there are no picture targets (levels.md). Start QC only for the check before showing.' }
          $target = Join-Path $Units "$($unit)_targets.md"
          $itNo = 'TARGETS'
          $gateText = "GATE: you are the targets QC of unit $unit (STAGE: targets, level $Level). Write the picture targets to $target. You do not judge this unit later: the hooks refuse a check report from you."
        } else {
          # the unit together with its packages (<unit>-<package>): after a package run the unit QC checks that state (the open obligation asks for it)
          $fin = @($st.finished | Where-Object { $_.unit -eq $unit -or ($unit -notmatch '-' -and $_.unit -like "$unit-*") } | Select-Object -Last 1)
          if (-not $fin.Count) { & $deny "No finished builder iteration for unit $unit to check." }
          # v4 #14: at study and final the check needs the targets first
          if ($Level -ne 'scout' -and -not (Test-Path (Join-Path $Units "$($unit)_targets.md"))) { & $deny "Unit $unit has no picture targets yet (review/units/$($unit)_targets.md). Start ROLE: qc UNIT: $unit STAGE: targets first - a different QC agent judges them." }
          $itNo = $fin[0].iter
          $f1 = Join-Path $Iter ($itNo + '_qc.md'); $f2 = Join-Path $Iter ($itNo + '_qc_r2.md')
          # v4 #2: QC rounds by level (scout, study: 1; final: up to 2)
          $maxQc = if ($Level -eq 'final') { 2 } else { 1 }
          $target = if (-not (Test-Path $f1)) { $f1 } elseif ($maxQc -ge 2 -and -not (Test-Path $f2)) { $f2 } else { $null }
          if (-not $target) { & $deny "$maxQc QC round(s) for iteration $itNo are done (rule 15, level $Level): work goes on anyway - fix a real problem in the next builder run and list open points for the artist's next review." }
          $gateText = "GATE: you are QC for unit $unit, state of builder iteration $itNo. Builder report: $(BuilderReport $itNo). Picture targets: $(Join-Path $Units "$($unit)_targets.md"). Write your report to $target."
        }
      }
      'engineer' {
        if ($unit -eq 'ROUND') {
          $rq = Join-Path $Work 'review\round_qc.md'
          if (-not (Test-Path $rq)) { & $deny 'The engineer of the round runs after the round QC (review/round_qc.md).' }
          $rep = $rq
        } else {
          $rep = Join-Path $Units "$($unit)_report.md"
          if (-not (Test-Path $rep)) { & $deny "The engineer runs after a finished unit: write $rep (four groups) first." }
        }
        $n = 1; do { $target = Join-Path $Units ("{0}_engineer{1}.md" -f $unit, $(if ($n -gt 1) { "_$n" } else { '' })); $n++ } while (Test-Path $target)
        $gateText = "GATE: you are the engineer for unit $unit. Report: $rep. Logs: $AgentsLog, $(Join-Path $Gate 'tools.log') and $(Join-Path $Gate 'commands.log') (expensive calls, duration, REPEAT). Iteration reports: $Iter. $(Unit-Effort $unit) Write your report to $target."
      }
      'helper' { $unit = if ($unit) { $unit } else { '-' }; $gateText = 'GATE: helper task - build no geometry.' }
      'standin' { $unit = if ($unit) { $unit } else { '-' }; $gateText = "GATE: stand-in - answer the question of taste; append it to $(Join-Path $Work 'review\standin_answers.md'). Build nothing, decide no process, rules or scope." }
      'viewer' { $unit = if ($unit) { $unit } else { '-' }; $gateText = 'GATE: viewer - show only. Never save, export or write any file. At your end the hooks compare the project files (*.hip*, *.blend, *.hda, *.usd*, export/) with your start; any change goes to the main chat as a VETO.' }
    }
    Add-Log $role $unit $itNo ([string]$ti.description) $(if ($typed) { $role } else { 'gp' })
    if ($role -eq 'builder' -and $sharedReq.Count) {
      $lno = @(Get-Content -Encoding UTF8 $AgentsLog).Count
      [IO.File]::AppendAllText((Join-Path $Gate 'shared_requests.tsv'), ("{0}`t{1}`r`n" -f $lno, ($sharedReq -join ';')), $Utf8)
    }
    $roleText = Get-Content -Raw -Encoding UTF8 (Join-Path $Brief "roles\$role.md")
    $paths = "PATHS: brief folder $Brief (rules.md, levels.md, project.md, brief.md) - work folder $Work (review/worklist.md, readings.md, decisions.md, assumed.md, bauwissen.md, units.md, strategy/, vis/, iter/, units/; scripts in tools/)."
    # the artist's process decisions and own words since the previous builder start reach every agent
    $extra = ''
    $dec = Join-Path $Work 'review\decisions.md'
    if (Test-Path $dec) { $extra += "`nARTIST'S PROCESS DECISIONS (review/decisions.md - binding like the rules):`n" + (Get-Content -Raw -Encoding UTF8 $dec) }
    if (@('builder', 'qc', 'engineer') -contains $role) { $extra += (Bauwissen-For $role ($prompt + ' ' + $unit + ' ' + (Base-Unit ([string]$unit)) + ' ' + $stageName)) }
    $al = Join-Path $Gate 'artist.log'
    if (@('helper', 'viewer') -notcontains $role -and (Test-Path $al)) {
      $prevB = @($st.builders | Select-Object -Last 1)
      $since = if ($prevB.Count) { [datetime]$prevB[0].time } else { [datetime]::MinValue }
      $msgs = @(([IO.File]::ReadAllText($al) -split '(?m)^===== ') | Where-Object { $_.Trim() } | ForEach-Object {
        $ts = ($_ -split "`r?`n", 2)[0].Trim(); $t = [datetime]::MinValue
        if ([datetime]::TryParse($ts, [ref]$t) -and $t -ge $since) { '===== ' + $_.TrimEnd() } })
      if ($msgs.Count) { $extra += "`nTHE ARTIST'S MESSAGES since the last builder started (verbatim, from review/gate/artist.log):`n" + (($msgs | Select-Object -Last 8) -join "`n") }
    }
    $newPrompt = $prompt + "`n`n==================== added by the gate hook ====================`n" + $Rules + "`n" + (Level-Row $Level) + "`n" + $roleText + "`n" + $gateText + "`n" + $paths + $extra
    $upd = @{}
    foreach ($p in $ti.PSObject.Properties) { $upd[$p.Name] = $p.Value }
    $upd['prompt'] = $newPrompt
    Out-Json @{ hookSpecificOutput = @{ hookEventName = 'PreToolUse'; permissionDecision = 'allow'; permissionDecisionReason = "gate: $role $unit $itNo"; updatedInput = $upd } }
  }

  'stop' {
    $in = Read-Input
    $st = Get-State
    if (-not $st.open.Count) { exit 0 }
    $msg = ($st.open -join ' ')
    # v4 #9: when no agent may start (budget, deadline), demanding one would only loop - tell, do not block
    $bs = Budget-Stop
    if ($bs -or (Deadline-Passed)) {
      Out-Json @{ systemMessage = "Gate: still open, but no agent may start ($(if ($bs) { $bs } else { 'deadline STOP_AT' })): $msg" }
      exit 0
    }
    if ($in -and $in.stop_hook_active) {
      Out-Json @{ systemMessage = "Gate still open after a reminder: $msg" }
      exit 0
    }
    $hd = Join-Path $Gate 'handover_due'; $ho = Join-Path $Work 'review\conductor_handover.md'
    if ((Test-Path $hd) -and (-not (Test-Path $ho) -or (Get-Item $ho).LastWriteTime -lt (Get-Item $hd).LastWriteTime)) { $msg = "First write the hand-over into review/conductor_handover.md (context above HANDOVER_AT; until then no agent starts). Then: $msg" }
    Out-Json @{ decision = 'block'; reason = "GATE (rule 2): $msg Do this before you end the turn. If you need the artist first, say so in one line and end the turn again." }
  }
}
exit 0

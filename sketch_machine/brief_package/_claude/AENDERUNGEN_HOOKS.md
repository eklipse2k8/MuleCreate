# Änderungen an den Hooks für v4 (Basis: 006, Stand 2026-11-09 00:17)
Paket: `fassung_v4/_claude/` (bewusst inaktiv). Tests: `tests/run_tests.sh` (Git Bash), Stand 85/85 grün. Die Fixtures liegen in `tests/_runs/<zeit>/` und werden nie gelöscht.
Im Code sind alle Änderungen mit „v4 #n“ markiert.

## Verifiziert
- **`agent_type`:**
  - Bei SubagentStart/Stop ist das Feld vorhanden; die 006-Logs zeigen 158× `general-purpose`.
  - Laut Doku tragen die Werkzeug-Hooks innerhalb eines Subagenten `agent_id` und `agent_type` (= `name` aus dem Frontmatter von `.claude/agents/*.md`).
  - Live in PreToolUse **nicht** geprüft: Es gibt keine `claude`-CLI und keinen Testlauf. Deshalb doppelt abgesichert: Die Rolle kommt aus `agent_type`, sonst aus `agent_roles.tsv` (Zuordnung per SubagentStart).
- **Kontext:** Das Transkript-JSONL enthält `"type":"assistant"` … `"usage":{input_tokens, cache_creation_input_tokens, cache_read_input_tokens}`. Geprüft am echten Transkript dieser Sitzung; getestet mit einem Fake-Transkript.
- **SendMessage:** Das Ziel steht im Feld `to` (Agent-ID). Das ergibt sich aus dem Werkzeugtext, ist aber keine Hook-Doku.

## Je Punkt
| # | Stand | Datei | Umsetzung / Begründung |
|---|---|---|---|
| 1 | umgesetzt (agent_type in PreToolUse nur laut Doku) | gate.ps1, common.sh, subagent.sh, agents/*.md | Die Rolle kommt aus `subagent_type` bzw. `agent_type`; die `ROLE:`-Zeile bleibt als Fallback. Widersprechen sich Typ und `ROLE:`-Zeile, wird der Start verweigert. `agents.log` hat eine neue Spalte 7 (Starttyp). Zwei Starts mit Typ in einer Nachricht sind erlaubt; Starts nur per ROLE-Zeile bleiben „einer je Nachricht“. Zwei gleiche Rollen mit `SHARED:` in einer Nachricht werden verweigert. |
| 2 | umgesetzt | gate.ps1 | Die Spalte der Stufe aus `levels.md` geht in jeden Agent-Prompt. **scout:** ein Referee je Einheit über alle Läufe, fällig ab dem Einheitsbericht; Ingenieur nie fällig. **study:** Ingenieur einmal nach der Runden-QC. **final:** wie 006. QC-Runden je Iteration: scout/study 1, final 2. Ohne `LEVEL` gilt final. |
| 3 | umgesetzt | gate.ps1 (context), common.sh | `SET:`-Zeilen nur aus UserPromptSubmit ohne `agent_id` und ohne task-notification/agent-message. Erlaubt sind level, max_builders, pause, max_weekly; sie gehen nach `hooks/gate.local.conf` und überlagern `gate.conf`. Schreibt das Modell die Datei (Write oder Shell), wird verweigert. |
| 4 | umgesetzt | gate.ps1 | scout: goal, level, units, approach. study/final: alle 10 Schlüssel. |
| 5 | umgesetzt | gate.ps1 | `STAGE: details` braucht `review/vis/<unit>_vis.md`, neuer als der jüngste Export der Einheit (`WORK/export/<unit>/…` oder `WORK/export/<unit>_*` – nur der oberste Ordner/Dateiname zählt, geteilte Review-Dateien wie `export/review/…/hide_<unit>.usda` nicht). Jede neue Zeile in `strategy/<unit>.md` seit dem letzten Builder-Start der Einheit braucht als 6. Spalte A/B/C/S/D. |
| 6 | umgesetzt | pretool_build.sh, settings.json | Der Hauptchat darf Houdini `inspect`, `geo`, `problems`, `screenshot` und Blender `get_*`, `search_*`. Alles andere Live wird verweigert, auch `save`, `vex`, `render_*`. Der Matcher umfasst jetzt `mcp__houdini.*` und `mcp__blender.*`. |
| 7 | umgesetzt | subagent.sh, pretool_build.sh, gate.ps1 | Der Viewer darf `run_python` bzw. `execute` (öffnen, Kamera). Verweigert werden Datei-Werkzeuge, save/vex/render und Shell-Schreiben. Bei Stop vergleicht der Hook die mtimes; Treffer gehen nach `viewer_veto.log` und erscheinen im GATE STATUS als „VETO (viewer)“. |
| 8 | umgesetzt | pretool_build.sh | `SendMessage` vom Hauptchat an eine bekannte Agent-ID, deren Bericht mit `ABORTED:` beginnt (Builder, Referee, QC), geht einmal durch. Der Bericht wird nach `<n>_<rolle>_aborted.md` umbenannt, damit die Iteration wieder als laufend gilt. Ein zweiter Versuch wird verweigert. |
| 9 | umgesetzt | gate.ps1, posttool.sh, pretool_build.sh | Ab `weekly >= MAX_WEEKLY` oder `5h >= MAX_5H` startet kein Agent mehr. Ist `usage.txt` älter als 20 min oder fehlt sie, erinnern Status und posttool (höchstens alle 10 min). Der Hauptchat darf `review/gate/usage.txt` nur mit dem Write-Werkzeug schreiben, und nur im Format `weekly=.. 5h=..`. Bei Budget-Stopp blockiert der Stop-Hook nicht. |
| 10 | umgesetzt | pretool_build.sh | Für alle Rollen verweigert: `>`, `>>`, `tee`, Set-/Add-Content, Out-File, Clear-/Remove-/Move-/Copy-/New-/Rename-Item, `sed -i`, `cp`, `mv`, `rm`, `del`, `truncate`, `dd`, `WriteAll*`/`AppendAll*` mit Ziel `review/…/*.md`. |
| 11 | umgesetzt | posttool.sh | Nur für den Hauptchat: Er liest das letzte Assistant-`usage` aus `transcript_path` (die letzten 3 MB). Ab `HANDOVER_AT` (500 k) kommt eine Erinnerung je weitere 100 k; unter der Schwelle wird zurückgesetzt. |
| 12 | umgesetzt | gate.ps1 | Der Referee bekommt `review/gate/extract_<iter>.log`: die Zeilen vom Builder-Start bis 1 min nach dem Bericht, mit Zählung (Bau-Aufrufe, davon `main`, Verweigerungen). |
| 13 | umgesetzt (Heuristik) | gate.ps1 | Abschnitte (Überschriften #–####) gehen mit, wenn ein Wort der Überschrift oder einer `keywords:`-Zeile im Auftrag, in der Einheit oder in der Stufe vorkommt. „pitfall“ geht immer mit, ebenso der Vorspann. Ausgelassene Abschnitte werden mit Namen genannt. Der Ingenieur bekommt alles; eine Datei ohne Überschriften geht ganz mit (wie 006). |
| 14 | umgesetzt | gate.ps1, pretool_build.sh | `STAGE: targets` ist zu Beginn der Einheit erlaubt, aber nicht bei scout. Bei study/final wird die Prüf-QC verweigert, bis `units/<unit>_targets.md` existiert. Die Ziele schreibt nur eine QC. Die Agent-ID des Ziel-Schreibers darf keinen `_qc`-Bericht schreiben, und umgekehrt. |
| 15 | umgesetzt | gate.ps1 | Status-Zeile: Sprache des Künstlers, mit dem Anfang seiner letzten Nachricht aus `artist.log`. |
| alt | übernommen | gate.ps1, pretool_build.sh | Aus dem v4-Entwurf: Pflichtschlüssel `goal`, Runden-QC `UNIT: ROUND` (`round_qc.md`/`_r2`, nur QC). |

## Bewusst unverändert (006)
- Regeln im Kontext: Start, Compaction, Künstlernachricht, alle `REMIND_EVERY` Aufrufe.
- `artist.log`.
- Keine Forks.
- Hauptchat: keine Bau-Werkzeuge, keine Skripte schreiben oder starten, nur ABORTED-Builderberichte.
- Referee nach jedem Builder (study/final).
- QC nach dem letzten Build einer berichteten Einheit.
- Ingenieur je Einheit (final).
- Ein Builder je Einheit; `MAX_BUILDERS`; offene Einheiten ≤ `MAX_BUILDERS`; Pakete und `STAGE: integrate`.
- `SHARED:` mit Dateisperren und Schreibschutz; `attrib`-Sperre.
- Gemeinsame Textdateien nur per Edit.
- Ein Agent je Live-Sitzung (nur bei run_python/execute).
- Berichts-Eigentum.
- STOP_AT, PAUSE.
- VETO-Weitergabe an den nächsten Builder.
- Stop-Gate.
- Fail-closed-Trap.

## Neu oder geändert, ohne eigenen Spezifikationspunkt
- **PAUSE:** Ein leeres `PAUSE=` pausiert nicht mehr. Nötig, weil die Vorlage den Schlüssel leer enthält.
- **SendMessage von Subagenten:** jetzt verweigert, damit kein Agent dem Hauptchat eine `SET:`-Zeile unterschieben kann.
- **Geschützte Dateien:** Neu geschützt sind `.claude/agents`, `levels.md`, `conductor.md`, `project.md` und `gate.local.conf`.
- **Helper:** darf nach Baubeginn noch `tools/vis_map` starten. Nötig, weil `conductor.md` ihn dafür vorsieht und 006 das gesperrt hätte.
- **Prüfrollen:** Referee, Ingenieur und Stand-in dürfen kein Houdini-save oder -vex und kein Blender-render.
- **Bauteil-Ansichten (Regel 7, Hafen-Test 13.11.):** `STAGE: details` braucht bei study/final die Zeilen der Einheit in `review/components.md` und für jedes Bauteil oder jede Strecke vom Rang, den die Stufe verlangt (study 1, final 1–2), eine `review/vis/*_views.json` mit seinem Namen. Rang 3 und Flächen sind ausgenommen. Nötig, weil die Hero-Kameras im Hafen fast jedes Detail auf Stufe S drückten und Detail dort gebaut wurde, wo es niemand lesen kann.
- **Usage ohne Watcher (#9, 13.11.):** Die Statuszeile (`hooks/statusline.sh`, in `settings.json`) schreibt `usage.txt` aus den Plan-Zahlen, die Claude Code ihr mitgibt, höchstens einmal pro Minute. Der wiederkehrende Job im Hauptchat entfällt: Er kostete im Hafen-Test 8 % aller Tokens, weil jeder Tick den ganzen Kontext liest. Bleibt die Datei alt, erinnert das Gate wie bisher, dann einmal von Hand.
- **Aufwand wird gemessen (#17, 13.11.):** `commands.log` (teure Aufrufe mit Dauer, Fingerabdruck, REPEAT), `agent_tokens.tsv` (Tokens und Minuten je Agent). Referee-Auszug und Engineer-Auftrag nennen beides. Nötig, weil im Hafen-Test niemand Wiederholungen und Kosten sehen konnte.
- **Karte nach Inhalt, im Bau-Lauf (#18, 13.11.):** Die Karte veraltet nur, wenn sich der Inhalt eines Exports der Einheit ändert (Signatur in `vis_<unit>.sig`), nicht durch ein neueres Datum. Ein Builder-Lauf nur für die Karte wird abgelehnt (Helfer-Aufgabe, ohne Referee und QC); der Builder, der die Geometrie ändert, lässt die Karte am Ende seines Laufs laufen. Im Hafen-Test waren Kartenläufe 45 % der Agentenzeit.
- **Übergabe erzwungen (#19, 13.11.):** Über `HANDOVER_AT` startet kein neuer Agent, bis `review/conductor_handover.md` neuer ist als die Marke (alle 100 k erneut). Laufende Agenten und das Ende eines Zugs werden nie blockiert; nach einer Kompaktierung fällt die Sperre. Im Hafen-Test lief der Hauptchat bis 966 k und verbrauchte 35 % aller Tokens.

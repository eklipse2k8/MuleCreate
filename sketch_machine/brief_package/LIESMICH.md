# Brief v4 – zusammengeführte Fassung (2026-11-09)
**Grundlage:** Stand von Test 006 (Regeln, Rollen und Hooks ab 00:17), dazu der v4-Entwurf (Zielblock), alle Vormerkungen in `../AENDERUNGEN.md`, die Auswertung `../../auswertung_004_005_006.md` und die Eigenanalyse von 006 vom 09.11.
Englisch sind die Dateien, die die Agenten lesen. Deutsch sind die Dateien für den Künstler.

## Dateien
| Datei | Wofür | Wer liest |
|---|---|---|
| `rules.md` | 17 Regeln, das oberste Gesetz | alle |
| `levels.md` | Stufen scout / study / final | alle |
| `conductor.md` | Ablauf, Dateien, Hooks, erste Runde, Bericht | nur Hauptchat |
| `roles/*.md` | builder, referee, qc, engineer, helper, standin, viewer | je Rolle |
| `project_template.md` | Projekt-Dokument, schreibt Mule bei jedem Export: Ziel, Rundenkarte, Auftrag | alle |
| `hooks_spec.md` | 15 Änderungen an den Hooks von 006, jeweils mit Prüffall | Umsetzung |
| `CLAUDE.md`, `STARTPROMPT.md` | Vorlagen | – |

## Was neu ist gegenüber 006
1. **Detail folgt Sichtbarkeit** (Regel 7): Die Sichtkarte (`tools/vis_map`) misst die Stufen A–D. Der Hook verlangt sie vor jeder Detail-Stufe. QC zählt Detail in C und D als Verschwendung.
2. **Grundsatz „streng im Sichtbaren, locker im Papier“** steht über allen Regeln.
2c. **Verdichtet (v5.0):** Nach unabhängiger Prüfung und zwei Blindtests keine neuen Regeln, sondern weniger Text: Regel 4 ist eine Reihenfolge für alle (neuestes Wort des Künstlers > bestätigt gebaut > gezeichnete Form > Konstruktion und Passform > Messzahlen), Rollen-Texte sind aus rules.md in die Rollen gewandert, Widersprüche aufgelöst. Regelnummern unverändert.
2b. **Wortlaut und Rückwirkung (v4.12):** Arbeitspunkte zitieren den Künstler wörtlich, die eigene Lesart steht darunter; keine Option, die er nicht gegeben hat. Neue Grundsätze gelten rückwirkend für alte Lesarten. Offene Fragen laufen mit der skizzentreuesten Option weiter. Konstruktion frei; Gestaltung frei und mutig nur, wo der Künstler sie übergibt (v4.14), sonst leise und mit Varianten zum Künstler. Keine Prüfung bestraft versteckte Überschneidungen. QC wertet verfehlte Absicht als Fehler, auch über Unit-Grenzen. Review-Runden bringen ein neueres Paket in laufende Briefs mit (`PACKAGE_CHANGES.md`).
2a. **Skizze zuerst (v4.11):** Die Form bindet, die Bauweise ist frei (Regel 10). Eine präzise Linie bleibt innerhalb von etwa 3 % ihrer eigenen Länge, ihre Richtung innerhalb von 10°, Kurven bleiben Kurven; Gesten etwa 10 %, Routen nach Start, Ziel und Reihenfolge. Passform wird innerhalb dieser Toleranz gesucht, nie gegen sie (Regel 11). Eine Abweichung vom Gezeichneten ist ein `DEPART:`, den nur der Künstler freigibt, nie ein `ASSUMED` (Regel 6). Gemessen mit `tools/sketch_overlay`: Striche über dem Modell in Hero-Kameras und drei Orthoansichten, Linie für Linie.
3. **Drei Stufen** (`levels.md`): scout, study, final. Beim Hochstufen bleibt die Arbeit erhalten.
4. **QC mit Bildzielen:** Eine QC setzt die Ziele, eine andere bewertet sie. Statt „zu wenig Dichte“ liefert sie bis zu 3 Arbeitszeilen.
5. **Größere Einheiten** nach Bereichen einer Hero-Ansicht. Schnittstellen werden versioniert.
6. **Bremsen gelöst:**
   - Nur-Lesen-Werkzeuge für den Hauptchat und eine Rolle `viewer`;
   - abgebrochene Agenten fortsetzen;
   - Budget-Sperre über `usage.txt`;
   - keine Shell-Schreibzugriffe in `review/`;
   - Rollen als Agent-Typen (behebt den fälschlich gesperrten Referee);
   - bauwissen nach Abschnitt statt komplett;
   - Erinnerung an die Übergabe des Dirigenten ab 500 k Kontext.
7. **Erste Runde straffer:**
   - Ausnahmen zuerst, Antwort per Ausnahme;
   - Markierungen späterer Einheiten erst beim Start der Einheit;
   - Pflichtschlüssel neu: `goal`, `level`, `units`, `visibility`;
   - Zielvorschlag nach den Antworten.
8. **Allgemein formuliert:**
   - Agent mit Personenname → Stand-in (`standin`);
   - Schläuche und Kabel → Verläufe;
   - 94 % → Toleranz aus der ersten Runde;
   - Modellier-Liste nur als Beispiel;
   - Houdini und Blender nur noch im Projekt-Dokument;
   - Sprache des Künstlers;
   - Core geteilt in Projekt-Dokument und Arbeitsweise-Paket.

## Bewusst unverändert
Die Mechanik, die in 006 gehalten hat, auch über eine Compaction:
- Hauptchat baut nie;
- frische Agenten;
- Referee nach jedem Lauf;
- QC und Ingenieur am Einheitsende;
- Spuren und Pakete mit Vertrag;
- `SHARED:`, Veröffentlichen statt Szenen teilen;
- 2 QC-Runden je Tor;
- Bericht in vier Gruppen.

## Noch nicht getan (ehrlich)
- **Hooks umgebaut, aber nur simuliert getestet:** `_claude/` enthält alle 15 Punkte, 7 Agent-Typen und die Vorlagen für `gate.conf` und `settings.json`. `bash _claude/tests/run_tests.sh` meldet 85/85 grün. Einen echten Claude-Code-Lauf gab es noch nicht. Darin offen bleiben:
  - ob `agent_type` auch bei Werkzeugaufrufen ankommt (laut Doku ja);
  - das Verhalten von `SET:`.

  Stand je Punkt und bekannte Lücken: `_claude/AENDERUNGEN_HOOKS.md`.
- **Sichtkarte:** Der Pilot an U45 ist fertig (`../../vis_pilot/`, mit README).
  - **Ergebnis:** 65 % der Polygone liegen in C, S oder D. 25 k davon sind völlig verdeckt, der große Rest ist zu klein (Ösen, Wagen, Stangen).
  - **Folgen für Regel 7:** Gemessen wird je Teilstück, nicht je Objekt; neu ist die Stufe S („zu klein“); es braucht mindestens 4 Zustände.
  - **Laufzeit:** etwa 2 bis 6 min je Einheit.
  - **Für den Einbau fehlen noch:**
    - ein Selbsttest (ein absichtlich verstecktes Teil muss D werden);
    - durchscheinende Verdecker;
    - Kameras, die an Gelenken mitfahren;
    - stabile Teilstück-Namen;
    - das Zurückschreiben von `vis_tier` am Laufende.
- **Kaltlese-Quiz (09.11.) bestanden:** 16 von 16 Praxisfragen hat ein frischer Agent im Kern richtig beantwortet, nur aus den v4-Texten. Seine 5 Unklarheiten sind behoben:
  - Stufe C bei study;
  - Zahl der QC-Runden;
  - wer Arbeitszeilen für Schnittstellen schreibt;
  - Ablauf von Wächter und Budget-Stopp;
  - wem eine Live-Sitzung gehört.

  Dazu kam: Der Schlüssel `away` hat Vorrang vor dem Stand-in.
- **Mule-Export** (Projekt-Dokument füllen, Paket kopieren) gehört in den Mule-Chat.
- **Stufen scout und study** sind ungetestet.
- **Kostenanteile** der Stufen sind nicht gemessen.

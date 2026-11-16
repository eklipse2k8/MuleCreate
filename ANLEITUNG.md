# Mule Create – Anleitung für Tester (Alpha 1)

Mule Create ist ein Programm zum Skizzieren im 3D-Raum, mit Linien. Man zeichnet auf Ebenen, die man im Raum
aufspannt, legt Notizen und Referenzbilder dazu und exportiert daraus einen **Sketch Brief**: einen Ordner mit
Bildern und Text, nach dem eine KI (z. B. Claude Code oder Codex) das Objekt in Houdini oder Blender nachbaut.

Das ist eine frühe, öffentliche Alpha. Es wird Fehler geben – bitte melden (siehe unten).

## Installation und Start

**Windows (empfohlen):** `Mule_Windows.zip` in einen eigenen Ordner entpacken und `Mule\Mule.exe` starten.
Kein Python, keine Installation nötig. Windows SmartScreen warnt, weil das Programm nicht signiert ist:
„Weitere Informationen“ → „Trotzdem ausführen“.

**Linux / aus dem Quellcode:** `Mule_Quellcode.zip` entpacken, dann
- Linux: `./start.sh` (richtet beim ersten Start mit [uv](https://docs.astral.sh/uv/) ein eigenes Python 3.14
  im Ordner ein, braucht dafür einmal Internet),
- Windows: `start.bat` (der erste Start richtet alles selbst ein, braucht Python 3.14 und einmal Internet), oder von Hand `py -3.14 -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`,
  `.venv\Scripts\python -m sketch_machine`.

Unter Linux ist Mule bisher kaum getestet.

Mule braucht eine Grafikkarte mit OpenGL 3.3. Spuren außerhalb des Ordners: Einstellungen in der Registry
(`HKCU\Software\SketchMachine`), Protokoll und Aufnahmen in `%APPDATA%\Mule` (unter Linux im Home-Ordner).

**Sprache:** Menü Ansicht → Sprache / Language, danach neu starten.

## Die wichtigsten Abläufe

Das Handbuch im Programm (**F1**) erklärt alles ausführlicher; alle Funktionen und Kürzel stehen in `LIESMICH.md` und – für KI-Assistenten geschrieben, auf Englisch – in
`AI_HANDBOOK.md`: einfach der eigenen KI geben und sie fragen.

**Zeichnen.** Mit der linken Maustaste auf die aktive Ebene zeichnen. Kamera: Alt (oder Space) + linke / mittlere /
rechte Maustaste. Am Strichende kurz stillhalten macht eine Gerade oder eine erkannte Form (Kreis, Rechteck …).
**X / Y / Z** wählt die Grundebene, **Space + N** legt eine neue Ebene aus der Kamerasicht an, **Q** zeichnet frei
ohne Ebene. Im **Edit**-Modus verschieben, drehen und skalieren (**T / R / E**). Rückgängig: Strg + Z.

**Notizen und Referenzbilder.** Im Notizmodus Notizen an Teile der Zeichnung hängen. Jede Notiz hat ein
Notizbrett: Bilder und Videos hineinziehen, in Schreibschrift oder mit der Tastatur schreiben, Pfeile auf Bildstellen
ziehen, Screenshots aus der Szene machen. Mit dem Haken „hero camera“ wird ein Screenshot zur Kamera, aus der die
KI die Szene später ansieht.

**Sketch Brief.** Datei → Sketch Brief exportieren: zuerst den Auftrag in einem Satz, dann einen Ordner wählen.
Mule legt dort Bilder, Notizen und Arbeitsregeln für die KI ab. Den Ordner öffnet man in Claude Code oder Codex
und lässt die KI danach arbeiten. Die KI fragt in der ersten Runde nach, was die Notizen offen lassen.

**Review-Modus.** Durch die Szene gehen und Feedback einsprechen wie in einer Review-Session.
- **Review → Review starten** beginnt die Aufnahme (Review beenden bzw. Review absenden beendet sie). Mule nimmt das
  Mikrofon auf und merkt sich Kamera, Cursor und Auswahl (kein Video).
- Während des Reviews ist das Werkzeug **Markieren** an (Knopf neben „Review“): jeder Klick in die Ansicht setzt eine
  Marke an genau dieser Stelle, ein Klick auf ein Bild im Brett merkt sich dieses Bild (z. B. „der Tank soll so
  aussehen“) – die KI legt es dann in die Notiz zum Teil. Navigieren mit Alt oder Leertaste wie immer; **Strg + Z**
  nimmt die letzte Marke zurück. Knopf aus: normal weiterarbeiten, die Aufnahme läuft weiter. Gesprochenes „hier“
  oder „dort“ bei ruhigem Cursor zählt auch als Zeigen.
- **Review absenden** (Knopf neben „Review“) beendet die Aufnahme, schreibt das Transkript und legt einen Satz in die
  Zwischenablage. Im Chat mit der KI „Review ist da“ schreiben: Die KI legt Entwurfs-Notizen in die offene Szene
  (gestrichelt). Jeder Entwurf zeigt den Originalsatz, **▶ Anhören** spielt die Stelle, **✓ Übernehmen** macht eine
  normale Notiz daraus. Gespeichert wird erst, wenn du speicherst.
- Das Transkript braucht Whisper (siehe unten). Ohne Whisper wird aufgenommen, aber nicht verschriftet.

**KI-Anbindung (MCP).** Solange Mule läuft, stellt es auf diesem Rechner einen MCP-Server bereit:
`http://127.0.0.1:8770/mcp` (nur lokal erreichbar, keine Anmeldung). Damit sieht die KI die offene Szene, kann
Bilder aus den Hero-Kameras rendern, Notizen diktieren lassen, den Brief exportieren und Reviews auswerten.

- **Claude Code:** im Projektordner eine Datei `.mcp.json` anlegen:
  ```json
  {"mcpServers": {"sketch_machine": {"type": "http", "url": "http://127.0.0.1:8770/mcp"}}}
  ```
  oder einmal `claude mcp add --transport http sketch_machine http://127.0.0.1:8770/mcp` ausführen.
- **Codex:** in `~/.codex/config.toml` (oder `.codex/config.toml` im Projekt):
  ```toml
  [mcp_servers.sketch_machine]
  url = "http://127.0.0.1:8770/mcp"
  ```
- Mule muss offen sein, bevor die KI-Sitzung startet. Eine zweite Mule startet keinen zweiten Server.

## Whisper (optional, für Review-Transkripte)

Mule bringt die Spracherkennung nicht mit, sie ist groß und läuft in einem eigenen Python. Mule richtet sie
selbst ein: Beim ersten Review fragt Mule nach (**Einrichten …** / Später / Nicht mehr fragen), sonst jederzeit über
das Review-Menü → **„Transkription einrichten …“**.

- Dafür braucht es einmalig ein **Python 3.10–3.13** von [python.org](https://www.python.org/downloads/). Im
  Installer unten den Haken **„Add python.exe to PATH“** setzen. Findet Mule kein Python, erklärt der Dialog das.
- Den Rest macht Mule: eigene Umgebung in `%APPDATA%\Mule\whisper_venv`, faster-whisper (mit NVIDIA-Grafikkarte
  auch die CUDA-Bibliotheken) und das Sprachmodell `large-v3-turbo`. Zusammen etwa **2–4 GB** Download, einige
  Minuten je nach Internet.
- Mit NVIDIA-Grafikkarte geht das Transkribieren schnell, sonst rechnet der Prozessor (deutlich langsamer, läuft
  aber im Hintergrund).

Für Fortgeschrittene: Ein eigenes Python mit faster-whisper geht auch. Mule findet es unter `~/mcp/whisper_venv`
oder über die Umgebungsvariable `SM_WHISPER_PYTHON`.

## Bekannte Grenzen

- Alpha: Szenendateien können sich zwischen Versionen ändern; ältere Szenen werden nicht immer weiter unterstützt.
  Wichtige Szenen vorher kopieren.
- Nur Windows ist im Paket geprüft. Linux läuft aus dem Quellcode und ist kaum getestet; macOS gar nicht.
- Das Programm ist nicht signiert (SmartScreen-Warnung).
- Whisper ist nicht im Paket (siehe oben). Für die KI-Anbindung braucht man ein eigenes Claude- oder Codex-Konto.
- Teile der Oberfläche, die ausführliche Funktionsliste `LIESMICH.md`, einzelne Code-Kommentare und die Testnamen sind
  noch deutsch; das Handbuch (F1) gibt es auf Deutsch und Englisch.
- Intern heißen Paket, Einstellungen, Szenenformat und MCP-Server noch „Sketch Machine“.
- Große Szenen können beim Zeichnen langsam werden.
- Videos im Notizbrett spielen stumm.
- Der MCP-Server hat kein Passwort: Er lauscht nur auf diesem Rechner (127.0.0.1), aber jedes Programm auf diesem
  Rechner könnte die offene Szene lesen und Notizen schreiben, solange Mule läuft.

## Probleme melden

Eine eingebaute Funktion „Problem melden“ gibt es noch nicht. Bitte als Issue auf GitHub melden (siehe `CONTRIBUTING.md`), mit:

1. was du gemacht hast, was du erwartet hast und was passiert ist,
2. die Version (steht im Namen des Releases, z. B. „Mule Create Alpha 1 (v0.99.229)“),
3. die Datei `mule.log` aus `%APPDATA%\Mule` (Windows: `Win + R`, `%APPDATA%\Mule` eingeben),
4. wenn möglich die Szene (die `.mule`-Datei; bei Videos auch den Ordner `videos/` daneben) und einen Screenshot.

Ideen, was dich stört oder was beim Arbeiten mit der KI gut oder schlecht lief, sind genauso willkommen wie
Fehlerberichte.

## Lizenz

Mule Create – Copyright (C) 2026 Felix Barthel. Freie Software unter der GNU General Public License v3.0 (`LICENSE`).
Fremde Software im Paket mit ihren Lizenzen: `THIRD_PARTY_NOTICES.md` und Ordner `licenses/` neben `Mule.exe`.
Der Name „Mule Create“ und das Mule-Logo sind von der Lizenz ausgenommen.

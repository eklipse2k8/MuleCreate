# Changelog

## Mule Create Alpha 1 – v0.99.254 (2026-11-16)

Erste öffentliche Fassung (Open Source, GPL-3.0). Neu gegenüber v0.99.229:

- **`AI_HANDBOOK.md`:** vollständige Dokumentation für KI-Assistenten – alle Funktionen, Kürzel, Abläufe, der Brief
  und alle MCP-Werkzeuge, mit Glossar Deutsch → Englisch. Fragen zu Mule einfach der eigenen KI mit dieser Datei
  stellen. Ein Test hält sie mit dem Programm im Gleichstand.
- **Einführung im Programm:** Diashow mit den 18 Bildern (Hilfe → Einführung in Bildern), oben im Handbuch (F1)
  als erster Knopf, daneben der Weg zum KI-Handbuch; beim ersten Start fragt Mule einmal nach.
- **`start.bat`** richtet beim ersten Start unter Windows die Umgebung `.venv` selbst ein (vorher: Fehlermeldung
  „pythonw.exe nicht gefunden“ in einer frischen Kopie) und installiert fehlende Pakete nach.
- **Einführung in Bildern:** `docs/INTRODUCTION.md` (auf GitHub durchklicken) und `docs/introduction.html` (Diashow) –
  18 Bilder aus dem echten Programm zu den wichtigsten Funktionen, erzeugt mit `packaging/handbook_images.py`; ganz
  oben im Handbuch verlinkt, ihr Text steht für die KI im Handbuch. Abschnitt „Start here“: Stift/Pinsel,
  Zeichen-/Malmodus, Frei-Modus.
- **README auf Englisch;** die ausführliche deutsche Funktionsliste heißt jetzt `LIESMICH.md`.
- Code-Kommentare auf Englisch.
- **Review:** Werkzeug **Markieren** neben dem Review-Knopf statt F8/F9; Klick auf ein Bild im Brett merkt das
  Referenzbild für die Notiz zum Teil; **Review absenden** mit Satz für den Chat (auf Englisch, wenn Mule Englisch
  spricht); „Claude arbeitet …“ geht aus, wenn Claude fertig ist; Claudes Pfeile im Brett folgen Text und Bild.
- **Baut auf** im Brief-Dialog ist jetzt eine Review-Runde im laufenden Chat (ersetzt die Folgerunde).
- **Arbeitsweise-Paket v5.0** im Bau-Brief: Skizze zuerst (Form bindet, Toleranz je Linie), Skizzen-Overlay, Wortlaut
  des Künstlers als Liste, Gestaltung beim Künstler, wo er sie nicht übergibt; verdichtet nach unabhängiger Prüfung.
- Behoben: Kurvenflächen verloren beim Speichern ihre Randlinie; gemischte Kantenauswahl wurde nicht ganz eingefärbt.
- Behoben: **Strg+L** (Loop entlang des Netzes) wirkte über die Tastatur nicht; der Druckregler des **Radierers** wirkte
  nirgends (jetzt: Druck steuert die Größe des Radierkreises); Rechtsklick-Menü nannte für Maximieren Space+B statt
  Space+F; Info-Spalte im Outliner auf Englisch („missing“, „tris“).
- Ist Port 8770 belegt (zweite Mule), sagt die Statusleiste jetzt, dass die KI-Anbindung aus ist.
- Die alte KI-Brief-Prüfung über die Anthropic-API (seit v0.99.78 abgeschaltet) ist ganz entfernt, samt dem Paket
  `anthropic`; Klären läuft über den Chat und MCP.
- Für Entwickler: `packaging/public_sync.py` überträgt neue Stände als je einen Commit ins öffentliche Repo,
  `release.py --public` legt dort das Release an.
- Die Workflow-Bible im öffentlichen Repo enthält Technik- und Werkzeug-Einträge; wie ein Bau abläuft, regelt das
  Arbeitsweise-Paket im Brief. Jede KI ergänzt beim Nutzer dessen eigene Kopie.
- Bau-Brief: die Hooks nehmen die Programme dieses Rechners (Git Bash auch außerhalb des Standardordners; unter
  Linux/macOS bash und PowerShell 7 `pwsh`, dort noch ungetestet); fehlt eins, nennt es der Brief-Dialog.
- Anleitungen: Probleme als GitHub-Issue melden, Szenen sind `.mule`-Dateien.

## Mule Create Alpha 1 – v0.99.229 (2026-11-14)

Erste Fassung zum internen Weitergeben. Neu gegenüber v0.99.227:

- **Transkription einrichten:** Mule richtet Whisper für Review-Transkripte selbst ein (Review-Menü oder Nachfrage
  beim ersten Review); braucht einmalig ein Python 3.10–3.13 von python.org, etwa 2–4 GB Download.
- Offizieller Name **Mule Create** in Fenstertitel, Handbuch, Anleitung und Release.
- Anleitung auf Deutsch (`ANLEITUNG.md`) und Englisch (`GUIDE.md`), dieses Changelog, Quellpaket.
- Drittlizenzen vollständig, jetzt auch Mesa/LLVM (`opengl32sw.dll`).

**Was Mule Create in dieser Fassung kann**

- **Skizzieren im Raum:** Linien auf Ebenen, Zeichenflächen und importierten Meshes (OBJ, USD), Frei-Modus ohne
  Ebene, Geraden und Formen durch Stillhalten, Smooth-Zeichnen, Malen.
- **Flächen aus Linien:** Kurvennetz mit gemeinsamen Punkten, Loft, Extrudieren, Füllflächen, Symmetrie und Array.
- **Edit-Modus:** Verschieben, Drehen, Skalieren mit Gizmo, Einrasten, Punkt auf Punkt, Welt / Lokal / Kamera.
- **Notizen und Notizbrett:** Notizen an Teilen der Zeichnung, Bretter mit Bildern, Videos, Schreibschrift, Pfeilen
  und Bildunterschriften; Screenshots als Hero-Kameras.
- **Sketch Brief:** Export als Ordner mit Bildern, Notizen, Klärungsliste und Arbeitsregeln für die KI; Folgerunden,
  die auf einem früheren Brief aufbauen.
- **KI-Anbindung über MCP** (lokal, Port 8770) für Claude Code, Codex und andere MCP-fähige KIs: Szene lesen,
  Ansichten rendern, Notizen diktieren, Bilder einfügen, Brief exportieren.
- **Review-Modus (neu):** Feedback beim Durchgehen der Szene einsprechen, Stellen markieren,
  Transkript lokal mit Whisper, die KI legt daraus Entwurfs-Notizen an, die man anhört und übernimmt.
- **Export:** Szene als USD für Houdini, Blender und Maya; Kurven als USD oder JSON.
- **Shots und Timing** (Prototyp): Kameras, Timeline, Flipbook-Ebenen.
- Oberfläche und Handbuch (F1) auf Deutsch und Englisch.

**Bekannt offen**

- Keine eingebaute Funktion „Problem melden“; Python für Whisper muss man selbst installieren.
- Linux nur aus dem Quellcode, kaum getestet; macOS ungetestet; Programm nicht signiert.
- Szenenformat kann sich bis zur Beta noch ändern.

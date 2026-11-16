# Tests

## Drei Stufen

| Stufe | Was | Dauer | Wann | Aufruf |
|---|---|---|---|---|
| 1 Kern | Datenmodell und Rechnung ohne Fenster | Sekunden | nach jeder Änderung | `python tests/run.py --kern` |
| 2 Bedienung | das echte Programm im echten Fenster, echte Mausereignisse | Minuten | betroffener Bereich beim Arbeiten, alles vor jedem Commit am gemeinsamen Kern | `python tests/run.py [Namensteil …]` |
| 3 Groß | Prüfrunde und Messung an der Hafenszene | Minuten | nach jedem Schritt des Umbau-Plans, vor jedem Paket | `python tests/run.py --gross`, `python bench/hafen.py` |

Ohne Angabe laufen Stufe 1 und 2, das Schnelle zuerst.

Eine Testdatei gehört zu Stufe 1, wenn sie die Zeile `STUFE = "kern"` trägt. Ihre Tests bekommen `h = None`, es wird
kein Fenster geöffnet; die Prüfmodi der Harness gelten trotzdem. Alles andere ist Stufe 2.

Stufe 3 braucht die eingefrorene Hafenszene (`Feedback/2026-11-11_architektur/messlatte/hafen_messlatte.mule`); sie
liegt nicht im Git.

## Ergebnisse

`OK`, `FEHLER`, `ERWARTET` (bekanntes Problem, mit `@expected_failure("Grund")` markiert), `BEHOBEN` (bekanntes Problem
läuft wieder – Markierung entfernen). Ein Gesamtlauf ist grün, wenn er keinen `FEHLER` hat.

Stufe 2 läuft in echten Fenstern: Wer nebenher am Rechner arbeitet, bekommt gelegentlich Fehlalarme (Fokus). Einzeln
nachprüfen.

## Prüfmodi

Die Harness schaltet in jedem Test Prüfmodi ein, die einen schnellen Weg gegen den sicheren, langsamen vergleichen
(`SM_FAST=1` schaltet sie für Messungen ab):

| Prüfmodus | vergleicht |
|---|---|
| `Renderer.VERIFY_STROKES` | Teil-Upload der Striche und gemerkte Flächen-Tabelle gegen die volle Aufbereitung |
| `DisplayListMixin.VERIFY_LISTS` | gemerkte Strich-Einträge je Linienobjekt gegen frisch zusammengestellte |
| `SurfaceSyncMixin.VERIFY_SYNC` | übersprungene und mitverschobene Flächen gegen den vollen Abgleich; Meldebuch gegen den Stempel |
| `Scene.VERIFY_UNDO` | geteilte Undo-Kopie gegen die volle Kopie |
| `Scene.VERIFY_INDEX` | Verzeichnisse (Objekt, Linie zu einer id) gegen die Suche über alle Listen |
| `SurfaceObject.VERIFY_KEY` | gemerkten Flächen-Schlüssel gegen den neu gerechneten |

Ein Prüfmodus fängt nur, was ein Test durchspielt. Jeder Eingriff in Abgleich, Undo oder Anzeige wird deshalb
zusätzlich von einem zweiten, unabhängigen Agenten durchgesehen (so wurden am 12.11. zwei Lücken im Meldebuch gefunden,
die alle Tests durchgelassen hatten).

## Regeln für neue Tests

- Was ohne Fenster prüfbar ist, kommt in Stufe 1.
- Die Szene über die Fragen der Harness lesen (`h.welt(linie)`, `h.objekt_von(linie)`, `h.verbunden(a, ka, b, kb)`,
  `h.flaechen_von(objekt)`, `h.form(fläche)`), nicht über innere Felder wie `curve.points` oder `curve.pids`. Mit den
  Objekt-Inseln und der Lage je Objekt (Umbau-Plan, Etappe 2) ändert sich, wo Punkte stehen und wie Verbindungen
  gespeichert sind; dann wird die Harness angepasst statt jeder Test. Alte Tests werden umgestellt, wenn sie brechen.
- Tempo nie über die Uhr prüfen, sondern über die Arbeitszähler (`sketch_machine/counters.py`, Beispiel
  `tests/test_messlatte.py`): Zeiten hängen am Rechner, Zähler nicht.
- Netze nie über Punktzahl oder `np.allclose` ohne Formprüfung vergleichen (die Einteilung hängt an der Krümmung).
- Bilder nur mit festem Textur-Versatz vergleichen (`surface.seed = 1.0`).

## Messlatte

`tests/test_messlatte.py` führt in `BEKANNT`, welche Zähler noch mit der Größe der Szene wachsen. Wächst ein neuer,
scheitert der Test; wächst ein bekannter nicht mehr, scheitert er auch (Eintrag streichen). Die Liste ist die
Arbeitsliste des Umbaus.

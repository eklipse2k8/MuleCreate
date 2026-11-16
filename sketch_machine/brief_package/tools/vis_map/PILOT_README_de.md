# Sichtkarte (visibility map) – Pilot, Test 006, Einheit U45

Werkzeug, kein Agenten-Urteil: misst, wie viele Pixel jedes Teil und jedes Teilstück einer Einheit in Hero-, Wolken- und Kontrollkameras bekommt, über mehrere Bewegungszustände, mit dem ganzen Objekt als Verdecker. Daraus folgen die Stufen A–D.

## Aufruf (nur headless)
```
hython  vis_export.py -- vis_config_U45.json        # ca. 15 s: Szene read-only laden, 4 Zustände -> npz, Kameras + Wolke
blender -b --factory-startup -P vis_map.py -- vis_config_U45.json [--skip_render] [--no_pics] [--only_states rest] [--max_cams N]
```
`--skip_render` nimmt die gespeicherten Pixelzahlen (`vis_counts_<unit>.json`) und rechnet nur Stufen, Bericht und Bilder neu (ca. 15 s).

## Weg und Begründung
- **Export in hython** aus der Review-Szene (`W1L_review.hip`, nur geladen, nie gespeichert): Zustände über Parameterpfade setzen, Weltgeometrie je Objekt triangulieren, Teile über ein Prim-Attribut (`name`), Teilstücke über eine Primitive-Connectivity. Grund: Nur dort sind alle Einheiten, Schläuche und Blockout in jedem Zustand richtig zusammengebaut.
- **Zählen in Blender Workbench**: Flat-Color-ID-Render (ohne AA, EXR mit 32 Bit, Farbe = ID), danach `bincount`. Grund: schnell (0,11 s je Bild bei 40 Objekten, 0,42 s bei 3 200 Teilstück-Objekten, 960×700), exakt dekodierbar (Fehler ≤ 0,13/255) und ohne Python-Raycast. Der GL-ROP in hython schafft nur ein Bild pro Prozess.
- Das Austauschformat ist allgemein (`geo_<state>.npz`: P, T, I + `scene.json`). Jede andere Quelle (Blender, USD, bgeo über `geo_files`) kann es schreiben.

## Parameter (Config-JSON)
`hip` bzw. `geo_files` · `objects` ("displayed" oder Liste) · `target_object` · `part_attrib` · `occluder_attrib` · `islands` (Teilstücke, Standard an) · `states` {Name: {Parm-Pfad: Wert}} · `hero_cams` (Knotenpfade) · `control_cams` ("NAME:eye:target:hfov") · `cloud` {n, ang_deg, dist_frac, seed, pivot "median_hit" | [x,y,z]} · `res_x` · `thresholds`, `threshold_main` · `cloud_sizes` (die kleinere Wolke = die ersten n der größeren, gleicher Seed) · `part_alias` {Regex: Teil} · `pictures` {heroes, overview, overview_hide_occluders, overview_hide_parts} · `cache_dir` · `out_dir`.
Wolke: Jeder Wolkenpunkt wird um den Drehpunkt gedreht (Gieren und Nicken je gleichverteilt in ±ang_deg) und im Abstand skaliert (×(1 ± dist_frac)); die Kamera schaut auf den Drehpunkt. Drehpunkt = Median der Treffertiefe eines 5×5-Strahlenrasters in der Bildmitte der Hero-Kamera.

## Empfohlene Standardwerte
960 px Breite · Schwelle **20 px für Teilstücke** und 100 px für ganze Teile · Wolke **16** Kameras, ±15°, ±20 % (16 und 32 ergeben fast dieselben Stufen: 9 von 2 455 Stücken ändern sich) · Zustände: Ruhe + Fold_In 0,5 + Fold_In 1 + ein Extrem (nur Ruhe würde 114 Stücke und 8 Teile falsch einstufen) · Bewertung **je Teilstück**, nicht je Objekt.

## Ergebnis U45 (Details in vis_U45.md / vis_U45.json)
- U45: 22 Teile, 294 918 Polygone, 2 455 Teilstücke (U1 hätte 142 499 Polygone in 71 Objekten).
- **Teil-Ebene:** 18 von 22 Teilen in A, C+D nur 930 Polygone (0,3 %). Das sagt wenig, denn ein zusammengeführtes Objekt mit 537 Ösen gilt schon als A, wenn irgendwo ein paar Ösen sichtbar sind.
- **Teilstück-Ebene:** C+D = 2 305 Stücke, **192 685 von 294 918 Polygonen (65 %)**. Davon bekommen 530 Stücke mit 25 350 Polygonen in keiner Kamera ein einziges Pixel. Der Rest ist sichtbar, bleibt aber unter 20 px. Die größten Brocken: Ösen 103 k Polygone (alle unter 20 px, keine in A), Carriages S2 34 k (849 von 858 Stücken in D), Rods 24 k in D.
- Stabilität: Bei Schwelle 100 statt 20 verschieben sich 34 k Polygone (12 %), bei Wolke 16 statt 32 nur 0,6 k.
- Laufzeit: Export 13 s. Zählen 844 Bilder in 6 min bei Teilstück-Auflösung (1,5 min bei Teil-Auflösung). Je Bild 0,11–0,42 s, Aufbau eines Zustands 1–2 s.

## Bilder
`pic_U45_hero_5_rest.png`, `pic_U45_hero_3_rest.png`, `pic_U45_hero_6_rest.png` (Ganzes Objekt grau, U45 nach Stufe) · `pic_U45_overview_CT_rest.png`, `pic_U45_overview_ROD_rest.png` (nur U45, Membran ausgeblendet, damit innere Stufen sichtbar werden) · `pic_U45_cloud_hero_5_c28_fold05.png` (Wolkenkamera, in der die meisten B-Polygone liegen). Farben: A grün, B gelb, C orange, D rot. `_parts_old/` enthält ältere Stände dieses Piloten (Teil-Ebene).

## Fallstricke und Grenzen
- **Teil gegen Teilstück:** Zusammengeführte Kit-Objekte machen die Teil-Ebene blind. Teilstück-Ebene (Connectivity) ist Pflicht. Dort heißt D aber „unter der Schwelle“, nicht unbedingt „verdeckt“. Darum zeigt die Spalte „nie ein Pixel“ das echte Verdeckte; der Rest ist Detail, das zu klein wirkt (passend für LOD, nicht zum Weglassen).
- **Wechselnde Darstellung je Zustand:** Die Review-Szene tauscht bei Fold_In > 0 die integrierte Membran (U45_mem, int_eyelets, int_rods, strings) gegen HDA-Caches mit anderen Teilnamen. Diese werden über `part_alias` dem Teil zugeordnet. Teilstücke behalten ihre Identität nur, wenn die Topologie gleich bleibt (wird geprüft, sonst Teil-Ebene).
- **Membran/Transparenz:** Alles wird opak gezählt. Ist die Membran im Look durchscheinend, sind die inneren Teile (Carriages, Rods) unterschätzt. Abhilfe: Verdecker-Liste mit „transparent“ als eigener Lauf (fehlt noch).
- **Dünne Teile** (Schnüre, Rods) liegen nahe an der Schwelle und reagieren auf die Auflösung. **Teile hinter Spalten** werden nur in den Zuständen und Kameras gesehen, die wirklich gerendert werden; die Wolke hilft. **Bewegung:** Zwischenzustände (z. B. Fold 0,25) und gelenkmitfahrende Kontrollkameras (TELE, ROOTF, PKT, OVL sind hier welt-fest in Ruhe) sind nicht abgedeckt.
- Der Blockout in der Review-Szene wird als Verdecker mitgezählt, so wie der Künstler ihn sieht.
- Die Kameras lesen keine Fensterverschiebung über winx/winy hinaus und kein Overscan.

## Was für den Einbau in einen allgemeinen Brief fehlt
1. Regel festlegen: Stufe je Teilstück, dazu die Spalte „nie ein Pixel“. Detail-Budget aus den Pixeln ableiten (z. B. Polygone je sichtbarem Pixel).
2. Transparente Verdecker als Option, plus eine Zustandsliste aus core.md statt von Hand.
3. Gelenkmitfahrende Kameras (Kamera an Gelenk binden) und Teilstück-Namen, die über Builds hinweg gleich bleiben (heute: Rang der Connectivity; ändert sich bei jedem Umbau).
4. Ein Schritt im Run-Close (`vis_tier` als Prim-Attribut zurück in den Export) und ein Selbsttest, der scheitern muss (absichtlich verstecktes Teil muss D werden).

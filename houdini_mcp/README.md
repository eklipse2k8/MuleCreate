# houdini_code – schlanker MCP-Server für Houdini

KI-Agenten (Claude, Astra/Codex) arbeiten in Houdini per Python (hou) und VEX statt über hunderte Einzelwerkzeuge.
Die Anweisung an den Agenten verlangt lesbare Netzwerke: ein Wrangle / Python-SOP je Zweck, sprechende Namen,
Kommentarkopf, Netzwerkbox je Baugruppe. Hard-Surface-Polymodelling gehört nach Blender, Houdini macht
Prozedurales, Rig, Montage und Export.

| Werkzeug | Zweck |
|---|---|
| run_python | Hauptwerkzeug: beliebiger Python-Code in Houdini, Variablen bleiben erhalten, `result` = Rückgabe |
| inspect | Knoten/Netzwerk kompakt: Typ, Flags, Eingänge, geänderte Parameter, Ausdrücke, Wrangle-Code, Kinder |
| geo | Geometrie-Zusammenfassung: Anzahl, Bounding Box, Attribute mit Wertebereich, Gruppen, offene Kanten |
| vex | Wrangle anlegen oder Code setzen, kocht und meldet Fehler oder Geometrie |
| problems | alle Fehler und Warnungen unter einem Pfad |
| screenshot | Bild vom Scene Viewer oder durch eine Kamera (nur mit Oberfläche) |
| save | Hip-Datei speichern |

Jeder Aufruf ist ein Undo-Schritt. Lange Antworten werden nach 4000 Zeichen gekürzt, der volle Text liegt in
`%TEMP%/houdini_code_mcp/`. Nach 50 s (`SM_HOUDINI_MCP_TIMEOUT`, unter den 60 s von Claude Code) antwortet der
Server mit einer Meldung, der Aufruf läuft in Houdini weiter. Der Screenshot holt den Scene Viewer kurz nach vorn,
falls ein anderer Reiter davor liegt (sonst rendert der Flipbook nichts).

**Einrichtung:** Houdini-Package `~/Documents/houdini22.0/packages/houdini_code_mcp.json` setzt
`SM_HOUDINI_MCP` auf diesen Ordner; `python3.13libs/uiready.py` startet den Server mit der Oberfläche auf
`http://127.0.0.1:8771/mcp` (nur lokal, keine Anmeldung). Von Hand: `import sm_houdini_mcp; sm_houdini_mcp.start()`.
In Claude Code (`.mcp.json`) und Codex (`.codex/config.toml`) als `houdini_code` eingetragen.

```json
{"env": [{"SM_HOUDINI_MCP": "<Pfad zum Repo>/houdini_mcp"},
         {"SM_HOUDINI_MCP_PORT": "8771"}, {"SM_HOUDINI_MCP_AUTOSTART": "1"}],
 "path": "$SM_HOUDINI_MCP"}
```

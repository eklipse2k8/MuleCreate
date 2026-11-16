# houdini_code – slim MCP server for Houdini

AI agents (Claude, Astra/Codex) work in Houdini through Python (hou) and VEX instead of hundreds of single tools.
The instruction to the agent demands readable networks: one wrangle / Python SOP per purpose, speaking names,
a comment header, a network box per group of parts. Hard-surface poly modelling belongs in Blender; Houdini does
the procedural parts, rig, assembly and export.

| Tool | Purpose |
|---|---|
| run_python | Main tool: any Python code in Houdini, variables persist, `result` = return value |
| inspect | Node/network, compact: type, flags, inputs, changed parameters, expressions, wrangle code, children |
| geo | Geometry summary: counts, bounding box, attributes with value range, groups, open edges |
| vex | Create a wrangle or set its code, cooks and reports errors or geometry |
| problems | All errors and warnings under a path |
| screenshot | Image of the Scene Viewer or through a camera (only with the UI) |
| save | Save the hip file |

Every call is one undo step. Long answers are cut after 4000 characters; the full text is in
`%TEMP%/houdini_code_mcp/`. After 50 s (`SM_HOUDINI_MCP_TIMEOUT`, below the 60 s of Claude Code) the server answers
with a message while the call keeps running in Houdini. The screenshot briefly brings the Scene Viewer to the front
if another tab is on top of it (otherwise the flipbook renders nothing).

**Setup:** the Houdini package `~/Documents/houdini22.0/packages/houdini_code_mcp.json` sets
`SM_HOUDINI_MCP` to this folder; `python3.13libs/uiready.py` starts the server with the UI on
`http://127.0.0.1:8771/mcp` (local only, no login). By hand: `import sm_houdini_mcp; sm_houdini_mcp.start()`.
Registered as `houdini_code` in Claude Code (`.mcp.json`) and Codex (`.codex/config.toml`).

```json
{"env": [{"SM_HOUDINI_MCP": "<path to the repo>/houdini_mcp"},
         {"SM_HOUDINI_MCP_PORT": "8771"}, {"SM_HOUDINI_MCP_AUTOSTART": "1"}],
 "path": "$SM_HOUDINI_MCP"}
```

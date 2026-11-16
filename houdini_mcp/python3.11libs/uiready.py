"""Startet den houdini_code-MCP-Server, sobald die Houdini-Oberfläche bereit ist (SM_HOUDINI_MCP_AUTOSTART=0: aus)."""
import os

if os.environ.get("SM_HOUDINI_MCP_AUTOSTART", "1") == "1":
    try:
        import sm_houdini_mcp
        sm_houdini_mcp.start()
    except Exception as e:
        print(f"[houdini_code] auto-start failed: {e}")

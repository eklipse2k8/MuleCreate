"""Starts the houdini_code MCP server as soon as the Houdini UI is ready (SM_HOUDINI_MCP_AUTOSTART=0: off)."""
import os

if os.environ.get("SM_HOUDINI_MCP_AUTOSTART", "1") == "1":
    try:
        import sm_houdini_mcp
        sm_houdini_mcp.start()
    except Exception as e:
        print(f"[houdini_code] auto-start failed: {e}")

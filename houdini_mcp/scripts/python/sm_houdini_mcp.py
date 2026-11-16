"""Schlanker MCP-Server für Houdini: Claude/Astra arbeiten per Python (hou) und VEX statt über hunderte Einzelwerkzeuge.
Läuft in Houdini auf http://127.0.0.1:PORT/mcp (nur lokal, Streamable HTTP, Antworten als JSON) – gleiches Muster wie
sketch_machine/mcp_server.py. Jeder Aufruf läuft im Hauptthread (hdefereval); in hython direkt, hinter einer Sperre.

Start: automatisch über das Houdini-Package (uiready.py), von Hand: import sm_houdini_mcp; sm_houdini_mcp.start()
Einbinden (.mcp.json): {"mcpServers": {"houdini_code": {"type": "http", "url": "http://127.0.0.1:8771/mcp"}}}"""
import base64
import contextlib
import io
import json
import os
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import hou

PORT = int(os.environ.get("SM_HOUDINI_MCP_PORT", "8771"))
VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # die neueste zuerst
TEXT_MAX = 4000      # längere Antworten landen vollständig in einer Datei, im Chat nur der Anfang
IMAGE_MAX = 1280
# unter der Zeitgrenze des Clients (Claude Code: 60 s), sonst schreibt Houdini später in eine geschlossene Verbindung
TIMEOUT = float(os.environ.get("SM_HOUDINI_MCP_TIMEOUT", "50"))
OUT_DIR = os.path.join(tempfile.gettempdir(), "houdini_code_mcp")

INSTRUCTIONS = """\
Houdini, driven by code. Work in Python (hou) and VEX – no node-by-node tool calls.
- run_python is the main tool: build, wire, set parameters, read rigs and networks, query geometry, all in one call.
  Several steps go in one call. Longer code goes into a module file in the project folder (import + importlib.reload).
- Geometry logic goes in VEX (attribwrangle) or a Python SOP – not in long chains of small nodes. Use native nodes
  where one node clearly does the job (file, merge, null, subdivide, polyextrude, boolean, sweep, copytopoints …).
- Keep networks readable for the artist, not as one lump of code: one wrangle / Python SOP per purpose, named by what
  it does (e.g. cable_path, bolt_pattern), a short comment header in the code, a network box per group of parts,
  an OUT null at the end. A dozen well-named nodes beat a hundred anonymous ones – and beat one 800-line wrangle.
- Hard-surface polygon modelling belongs in Blender unless the artist says otherwise; Houdini is for procedural parts
  (cables, hoses, patterns, arrays, scattering), rigs, assembly and export.
- Look before changing: inspect (networks, rigs, HDAs) and geo (geometry) give compact summaries. Never move nodes
  the artist placed; never delete or overwrite the artist's nodes without asking.
- Check results with geo / problems and a screenshot, not by reading long dumps. Return small results: set `result`
  in run_python to what you need (counts, names, short dicts), never whole point lists.
- Every call is one undo step in Houdini."""

_S = {"type": "string"}
TOOLS = [
    {"name": "run_python",
     "description": "Run Python inside Houdini (hou, plus helpers inspect(path), geo(path), problems(path) returning "
                    "the same text as the tools). Variables persist between calls. Assign `result` to return a value "
                    "(JSON-serialisable, keep it small); print output is returned too. Long output is cut and saved "
                    "to a file whose path is named.",
     "inputSchema": {"type": "object", "properties": {"code": _S}, "required": ["code"],
                     "additionalProperties": False}},
    {"name": "inspect",
     "description": "A compact view of a node and its network: type, flags, inputs, parameters that differ from "
                    "default (incl. expressions and channel references), VEX/Python code of wrangles and Python SOPs, "
                    "spare/HDA parameters, children (to depth). Use it to understand rigs, subnets and HDAs.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "node path, e.g. /obj or /obj/glider/rig"},
         "depth": {"type": "integer", "description": "levels of children to list (default 1)"},
         "code": {"type": "boolean", "description": "include full wrangle/Python code (default: first 12 lines)"}},
         "required": ["path"], "additionalProperties": False}},
    {"name": "geo",
     "description": "Summary of a SOP node's geometry (cooks it): points, prims by type, bounding box, attributes "
                    "with class/type/size and value range, groups with counts, open/non-manifold edges if polygonal, "
                    "cook errors and warnings.",
     "inputSchema": {"type": "object", "properties": {"path": _S}, "required": ["path"], "additionalProperties": False}},
    {"name": "vex",
     "description": "Set the VEX code of an attribute wrangle (path exists) or create one (path = new node path inside "
                    "a SOP network; input = node to wire in, run_over = points/prims/vertices/detail/numbers). Cooks "
                    "and returns compile errors or the geometry summary.",
     "inputSchema": {"type": "object", "properties": {
         "path": _S, "code": _S, "input": _S,
         "run_over": {"type": "string", "enum": ["points", "prims", "vertices", "detail", "numbers"]},
         "display": {"type": "boolean", "description": "set display/render flag on it (default: only when created)"}},
         "required": ["path", "code"], "additionalProperties": False}},
    {"name": "problems",
     "description": "All nodes with errors or warnings below a path (default /), with their messages.",
     "inputSchema": {"type": "object", "properties": {"path": _S}, "additionalProperties": False}},
    {"name": "screenshot",
     "description": "Picture of the Scene Viewer (needs the Houdini UI) at the current frame, as the artist sees it, "
                    "or through a camera node (the artist's view is restored afterwards). frame: optional frame.",
     "inputSchema": {"type": "object", "properties": {
         "camera": _S, "frame": {"type": "number"},
         "width": {"type": "integer"}, "height": {"type": "integer"}},
         "additionalProperties": False}},
    {"name": "save",
     "description": "Save the hip file (optionally under a new path). Returns the path.",
     "inputSchema": {"type": "object", "properties": {"path": _S}, "additionalProperties": False}},
]


# --- Hilfen ------------------------------------------------------------------------------------------------------

def _node(path):
    n = hou.node(path)
    if n is None:
        raise ValueError(f"no node at {path}")
    return n


def _cut(text, name):
    """Kurz halten: bis TEXT_MAX Zeichen, sonst Anfang + Datei mit allem."""
    if len(text) <= TEXT_MAX:
        return text
    os.makedirs(OUT_DIR, exist_ok=True)
    f = os.path.join(OUT_DIR, f"{name}.txt")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text[:TEXT_MAX] + f"\n… cut at {TEXT_MAX} of {len(text)} characters – full text: {f}"


def _val(v):
    if isinstance(v, float):
        return round(v, 5)
    if isinstance(v, (tuple, list)):
        return [_val(x) for x in v]
    return v


def _parm_lines(node):
    out = []
    for p in node.parms():
        t = p.parmTemplate()
        if t.type() in (hou.parmTemplateType.Folder, hou.parmTemplateType.FolderSet, hou.parmTemplateType.Label,
                        hou.parmTemplateType.Separator, hou.parmTemplateType.Button):
            continue
        if p.name() in ("snippet", "python"):
            continue
        try:
            expr = p.expression()
            out.append(f"{p.name()} = `{expr}` → {_val(p.eval())}")
            continue
        except hou.OperationFailed:
            pass
        ref = p.getReferencedParm()
        if ref.path() != p.path():
            out.append(f"{p.name()} → ch({ref.path()})")
        elif not p.isAtDefault():
            try:
                v = p.evalAsString() if t.type() == hou.parmTemplateType.String else _val(p.eval())
            except hou.Error:
                v = p.unexpandedString()
            out.append(f"{p.name()} = {v}")
    return out


def _code_of(node):
    for name in ("snippet", "python", "code"):
        p = node.parm(name)
        if p is not None and p.parmTemplate().type() == hou.parmTemplateType.String and p.unexpandedString().strip():
            return name, p.unexpandedString()
    return None, None


def _flags(node):
    f = []
    for name, test in (("display", "isDisplayFlagSet"), ("render", "isRenderFlagSet"), ("bypass", "isBypassed"),
                       ("template", "isTemplateFlagSet")):
        fn = getattr(node, test, None)
        if fn is not None:
            with contextlib.suppress(hou.Error):
                if fn():
                    f.append(name)
    return f


def inspect(path="/obj", depth=1, code=False):
    node = _node(path)
    lines = []

    def head(n, ind):
        bits = [f"{ind}{n.path() if ind == '' else n.name()}  [{n.type().nameWithCategory()}]"]
        fl = _flags(n)
        if fl:
            bits.append("{" + ",".join(fl) + "}")
        ins = [i.name() if i else "-" for i in n.inputs()]
        if any(i != "-" for i in ins):
            bits.append("← " + ", ".join(ins))
        if n.comment():
            bits.append(f"# {n.comment()}")
        with contextlib.suppress(hou.Error):
            if n.errors():
                bits.append("ERROR: " + "; ".join(n.errors())[:200])
        return "  ".join(bits)

    def body(n, ind, full):
        for pl in _parm_lines(n)[:40 if full else 12]:
            lines.append(f"{ind}  · {pl}")
        name, src = _code_of(n)
        if src:
            src_lines = src.splitlines()
            show = src_lines if (code or full and len(src_lines) <= 12) else src_lines[:12]
            lines.append(f"{ind}  {name} ({len(src_lines)} lines):")
            lines.extend(f"{ind}  | {l}" for l in show)
            if len(show) < len(src_lines):
                lines.append(f"{ind}  | … {len(src_lines) - len(show)} more (code=true)")

    def walk(n, d, ind):
        kids = n.children()
        if not kids:
            return
        if d <= 0:
            lines.append(f"{ind}  ({len(kids)} children)")
            return
        for k in kids:
            lines.append(head(k, ind + "  "))
            if d == 1 or not k.children():
                body(k, ind + "  ", False)
            walk(k, d - 1, ind + "  ")

    lines.append(head(node, ""))
    defn = node.type().definition()
    if defn is not None and not os.path.basename(defn.libraryFilePath()).startswith("OPlib"):  # nur eigene HDAs
        lines.append(f"  HDA {defn.nodeTypeName()} from {defn.libraryFilePath()}")
    body(node, "", True)
    with contextlib.suppress(hou.Error):
        sp = [p.name() for p in node.spareParms()]
        if sp:
            lines.append("  spare parms: " + ", ".join(sp))
    walk(node, max(0, int(depth)), "")
    return "\n".join(lines)


def geo(path):
    node = _node(path)
    if not isinstance(node, hou.SopNode):
        raise ValueError(f"{path} is not a SOP node")
    node.cook(force=False)
    g = node.geometry()
    lines = [f"{path}: {len(g.points())} points, {len(g.prims())} prims, {g.intrinsicValue('vertexcount')} vertices"]
    kinds = {}
    for p in g.iterPrims():
        kinds[p.type().name()] = kinds.get(p.type().name(), 0) + 1
    if kinds:
        lines.append("prims: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    bb = g.boundingBox()
    lines.append(f"bbox: min {_val(tuple(bb.minvec()))} max {_val(tuple(bb.maxvec()))} size {_val(tuple(bb.sizevec()))}")
    for cls, attrs in (("point", g.pointAttribs()), ("prim", g.primAttribs()), ("vertex", g.vertexAttribs()),
                       ("detail", g.globalAttribs())):
        for a in attrs:
            desc = f"{cls} {a.name()} {a.dataType().name().lower()}[{a.size()}]"
            if cls == "detail":
                with contextlib.suppress(Exception):
                    v = g.attribValue(a)
                    desc += f" = {str(_val(v))[:80]}"
            elif a.dataType() in (hou.attribData.Float, hou.attribData.Int) and a.size() == 1:
                with contextlib.suppress(Exception):
                    kind = "Float" if a.dataType() == hou.attribData.Float else "Int"
                    vals = getattr(g, f"{cls}{kind}AttribValues")(a.name())
                    if vals:
                        desc += f" {_val(min(vals))}…{_val(max(vals))}"
            lines.append("attr " + desc)
    for cls, groups in (("point", g.pointGroups()), ("prim", g.primGroups()), ("edge", g.edgeGroups())):
        for gr in groups:
            n = len(gr.points()) if cls == "point" else len(gr.prims()) if cls == "prim" else len(gr.edges())
            lines.append(f"group {cls} {gr.name()}: {n}")
    if kinds.get("Poly") and len(g.prims()) < 500000:
        edges = {}
        for p in g.iterPrims():
            pts = [v.point().number() for v in p.vertices()]
            for a, b in zip(pts, pts[1:] + pts[:1]):
                k = (a, b) if a < b else (b, a)
                edges[k] = edges.get(k, 0) + 1
        open_e = sum(1 for c in edges.values() if c == 1)
        nonman = sum(1 for c in edges.values() if c > 2)
        lines.append(f"edges: {len(edges)}, open {open_e}, non-manifold {nonman}")
    for kind, msgs in (("error", node.errors()), ("warning", node.warnings())):
        for m in msgs:
            lines.append(f"{kind}: {m}")
    return "\n".join(lines)


def problems(path="/"):
    out = []
    for n in _node(path).allSubChildren():
        with contextlib.suppress(hou.Error):
            for kind, msgs in (("ERROR", n.errors()), ("warning", n.warnings())):
                for m in msgs:
                    out.append(f"{kind} {n.path()}: {m.strip()[:300]}")
    return "\n".join(out) or f"no errors or warnings below {path}"


# --- Werkzeuge (laufen im Hauptthread) ----------------------------------------------------------------------------

class Tools:
    def __init__(self):
        self.ns = {"hou": hou, "inspect": inspect, "geo": geo, "problems": problems}

    def run_python(self, code):
        self.ns.pop("result", None)
        buf = io.StringIO()
        err = None
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf), hou.undos.group("MCP run_python"):
            try:
                exec(compile(code, "<mcp>", "exec"), self.ns)
            except Exception:
                err = traceback.format_exc(limit=6)
        parts = []
        if buf.getvalue().strip():
            parts.append("output:\n" + buf.getvalue().rstrip())
        if "result" in self.ns:
            try:
                parts.append("result: " + json.dumps(self.ns["result"], ensure_ascii=False, default=str))
            except Exception:
                parts.append("result: " + repr(self.ns["result"]))
        if err:
            parts.append("ERROR:\n" + err.rstrip())
        text = _cut("\n".join(parts) or "ok (no output)", "run_python")
        return [{"type": "text", "text": text}], bool(err)

    def inspect(self, path, depth=1, code=False):
        return [{"type": "text", "text": _cut(inspect(path, depth, code), "inspect")}], False

    def geo(self, path):
        return [{"type": "text", "text": _cut(geo(path), "geo")}], False

    def problems(self, path="/"):
        return [{"type": "text", "text": _cut(problems(path), "problems")}], False

    def vex(self, path, code, input=None, run_over=None, display=None):
        node = hou.node(path)
        created = node is None
        with hou.undos.group("MCP vex"):
            if created:
                parent_path, name = path.rstrip("/").rsplit("/", 1)
                parent = _node(parent_path or "/")
                node = parent.createNode("attribwrangle", name)
                if input:
                    node.setInput(0, _node(input))
                    node.moveToGoodPosition()
            if node.parm("snippet") is None:
                raise ValueError(f"{path} has no VEX snippet (not a wrangle)")
            node.parm("snippet").set(code)
            if run_over:
                node.parm("class").set({"detail": 0, "prims": 1, "points": 2, "vertices": 3, "numbers": 4}[run_over])
            if display or (display is None and created):
                node.setDisplayFlag(True)
                node.setRenderFlag(True)
        try:
            node.cook(force=True)
        except hou.OperationFailed:
            pass
        if node.errors():
            return [{"type": "text", "text": "VEX errors:\n" + "\n".join(node.errors())}], True
        return [{"type": "text", "text": ("created " if created else "updated ") + _cut(geo(node.path()), "vex")}], False

    def screenshot(self, camera=None, frame=None, width=None, height=None):
        if not hou.isUIAvailable():
            raise RuntimeError("screenshot needs the Houdini UI (not hython)")
        viewers = [t for t in hou.ui.paneTabs() if t.type() == hou.paneTabType.SceneViewer]
        if not viewers:
            raise RuntimeError("no Scene Viewer open")
        sv = next((t for t in viewers if t.isCurrentTab()), viewers[0])
        vp = sv.curViewport()
        old_cam, old_view = vp.camera(), vp.defaultCamera().stash()
        # Flipbook rendert still nichts, wenn der Scene Viewer hinter einem anderen Reiter liegt
        front = None if sv.isCurrentTab() else next((t for t in sv.pane().tabs() if t.isCurrentTab()), None)
        os.makedirs(OUT_DIR, exist_ok=True)
        out = os.path.join(OUT_DIR, "screenshot.png").replace("\\", "/")
        if os.path.exists(out):
            os.remove(out)  # sonst käme bei stillem Fehlschlag das alte Bild zurück
        f = hou.frame() if frame is None else float(frame)
        try:
            if front is not None:
                sv.setIsCurrentTab()
            if camera:
                vp.setCamera(_node(camera))
            s = sv.flipbookSettings().stash()
            s.frameRange((f, f))
            s.output(out)
            s.outputToMPlay(False)
            if width and height:
                s.useResolution(True)
                s.resolution((int(width), int(height)))
            sv.flipbook(vp, s)
        finally:
            if camera:
                if old_cam is not None:
                    vp.setCamera(old_cam)
                else:
                    vp.useDefaultCamera()
                    vp.setDefaultCamera(old_view)
            if front is not None:
                front.setIsCurrentTab()
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImage
        img = QImage(out)
        if img.isNull():
            raise RuntimeError(f"flipbook wrote no image ({out})")
        if max(img.width(), img.height()) > IMAGE_MAX:
            img = img.scaled(IMAGE_MAX, IMAGE_MAX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        return [{"type": "image", "mimeType": "image/png",
                 "data": base64.standard_b64encode(bytes(data)).decode("ascii")},
                {"type": "text", "text": f"frame {f}, saved {out}"}], False

    def save(self, path=None):
        if path:
            hou.hipFile.save(path.replace("\\", "/"))
        else:
            hou.hipFile.save()
        return [{"type": "text", "text": hou.hipFile.path()}], False


# --- Hauptthread --------------------------------------------------------------------------------------------------

_lock = threading.Lock()


def _in_main(fn):
    """fn im Hauptthread ausführen (UI: hdefereval, mit Zeitgrenze); in hython direkt hinter einer Sperre."""
    if not hou.isUIAvailable():
        with _lock:
            return fn()
    import hdefereval
    box, done = {}, threading.Event()

    def job():
        try:
            box["result"] = fn()
        except Exception as exc:
            box["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            done.set()

    hdefereval.executeDeferred(job)
    if not done.wait(TIMEOUT):
        raise TimeoutError(f"Houdini did not answer within {TIMEOUT:.0f} s (still cooking, or a dialog is open) – "
                           "the call keeps running in Houdini")
    if "error" in box:
        raise RuntimeError(box["error"])
    return box["result"]


# --- MCP über HTTP ------------------------------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, payload=None):
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            if payload is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:  # Client hat aufgegeben (Zeitgrenze) – kein Traceback in Houdinis Shell
            pass

    def do_GET(self):  # kein Server-Push (SSE): nur Anfrage/Antwort
        self._send(405)

    def do_DELETE(self):
        self._send(405)

    def do_POST(self):
        if self.path.rstrip("/") != "/mcp":
            return self._send(404)
        try:
            msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"null")
        except json.JSONDecodeError:
            return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
        msgs = msg if isinstance(msg, list) else [msg]
        replies = [r for r in (self.server.mcp.handle(m) for m in msgs) if r is not None]
        if not replies:
            return self._send(202)
        self._send(200, replies if isinstance(msg, list) else replies[0])


class Server:
    def __init__(self, port=PORT):
        self.tools = Tools()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.mcp = self
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def handle(self, m):
        """Eine JSON-RPC-Nachricht; None für Benachrichtigungen (ohne id)."""
        if not isinstance(m, dict) or "method" not in m:
            return None
        rid, method, params = m.get("id"), m["method"], m.get("params") or {}
        if rid is None:
            return None
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                result = {"protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "houdini_code", "version": "1"},
                          "instructions": INSTRUCTIONS}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                name, args = params.get("name"), params.get("arguments") or {}
                fn = getattr(self.tools, name, None) if any(t["name"] == name for t in TOOLS) else None
                if fn is None:
                    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
                try:
                    content, is_err = _in_main(lambda: fn(**args))
                    result = {"content": content, "isError": is_err}
                except Exception as exc:
                    result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            else:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method}"}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}


_server = None


def start(port=PORT):
    """Server starten (einmal je Houdini-Sitzung); None, wenn der Port belegt ist."""
    global _server
    if _server is not None:
        return _server
    try:
        _server = Server(port).start()
        print(f"[houdini_code] MCP server on http://127.0.0.1:{_server.port}/mcp")
    except OSError as exc:
        print(f"[houdini_code] port {port} busy, not started ({exc})")
    return _server


def stop():
    global _server
    if _server is not None:
        _server.stop()
        _server = None

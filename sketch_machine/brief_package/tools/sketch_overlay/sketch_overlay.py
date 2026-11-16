# sketch_overlay.py – the artist's Mule strokes laid over the build, measured line by line (rules 10 and 11).
#   blender -b --factory-startup -P tools/sketch_overlay/sketch_overlay.py -- <config.json>
#   blender -b --factory-startup -P tools/sketch_overlay/sketch_overlay.py -- --selftest
# A measurement in pictures, not a judgement: in every view (hero cameras of the brief + three orthographic views) the
# built geometry is rendered flat (part id, depth, face normal), its visible edges are found (outline, part borders,
# creases), and every drawn line is compared with the edge or tube it should be:
#   distance  – how far the build runs from the drawn line, as a share of the line's own length (scale-free);
#   direction – how much the build's direction differs from the line's, in degrees;
#   curves    – a bow stays a bow in the same direction, a straight stays straight.
# Never opens a project scene for writing, never saves. See README.md next to this file.
import bpy, sys, os, json, re, math, time
import numpy as np
from mathutils import Matrix

C3 = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)   # Blender (Z up) -> brief (Y up): (x, y, z) -> (x, z, -y)
B3 = C3.T                                                    # brief -> Blender
MESHY = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"}
DEFAULT_TOL = {"precise": {"dist": 0.03, "angle": 10.0, "curves": True},
               "gesture": {"dist": 0.10, "angle": None, "curves": False},
               "route": {"dist": 0.05, "angle": None, "curves": False, "ends_only": True}}


# ---------- input --------------------------------------------------------------------------------------------------
def import_groups(st, cfg):
    """imported models in the Mule scene (M# prims referencing a file) grouped by their placement.
    -> [{name, map (4x4, row vectors: sketch world -> the file's own coordinates), lo, hi (sketch world bbox)}]
    A review mark drawn on an imported copy of the build is mapped back into the build's coordinates with `map`."""
    from pxr import Usd, UsdGeom, Sdf
    base = os.path.dirname(os.path.abspath(cfg["scene_usd"]))
    files, groups = {}, {}
    bb = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    for p in st.Traverse():
        if not re.match(r"^M\d+", p.GetName()) or "/notes/" in str(p.GetPath()):
            continue
        refs = [r for spec in p.GetPrimStack() for r in spec.referenceList.prependedItems]
        if not refs:
            continue
        ref = refs[0]
        W = np.array(UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default()), float)
        S = np.eye(4)
        try:
            ap = ref.assetPath if os.path.isabs(ref.assetPath) else os.path.normpath(os.path.join(base, ref.assetPath))
            if ap not in files:
                files[ap] = Usd.Stage.Open(ap)
            fs = files[ap]
            src = fs.GetPrimAtPath(ref.primPath) if ref.primPath and not ref.primPath.isEmpty else fs.GetDefaultPrim()
            if src and src.IsValid():
                S = np.array(UsdGeom.Xformable(src).ComputeLocalToWorldTransform(Usd.TimeCode.Default()), float)
        except Exception:
            pass
        M = np.linalg.inv(W) @ S
        key = tuple(np.round(M, 4).ravel())
        r = bb.ComputeWorldBound(p).ComputeAlignedRange()
        if r.IsEmpty():
            continue
        lo, hi = np.array(r.GetMin(), float), np.array(r.GetMax(), float)
        g = groups.setdefault(key, {"map": M, "lo": lo, "hi": hi, "file": os.path.basename(ref.assetPath), "n": 0})
        g["lo"], g["hi"] = np.minimum(g["lo"], lo), np.maximum(g["hi"], hi); g["n"] += 1
    return [g for g in groups.values() if not np.allclose(g["map"], np.eye(4), atol=1e-4)]


def read_strokes(cfg):
    """BasisCurves of scene.usd (Mule) -> [{id, path, pts (N,3) Blender world}]; notes and painting left out."""
    from pxr import Usd, UsdGeom
    st = Usd.Stage.Open(cfg["scene_usd"])
    inc = re.compile(cfg["lines"]) if cfg.get("lines") else None
    exc = re.compile(cfg["exclude_lines"]) if cfg.get("exclude_lines") else None
    s = float(cfg.get("brief_scale", 1.0))
    out, seen, skipped_copies = [], set(), []
    groups = import_groups(st, cfg) if cfg.get("marks_on_imports", True) else []
    own = None                                               # the sketch's own region: its sketched surfaces
    for p in st.Traverse():
        if p.GetTypeName() == "Mesh" and re.match(r"^F\d+", p.GetName()):
            r = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_]).ComputeWorldBound(p).ComputeAlignedRange()
            if not r.IsEmpty():
                lo, hi = np.array(r.GetMin(), float), np.array(r.GetMax(), float)
                own = (lo, hi) if own is None else (np.minimum(own[0], lo), np.maximum(own[1], hi))
    def inside(c, lo, hi, pad=0.03):
        e = (hi - lo) * pad
        return bool(np.all(c >= lo - e) and np.all(c <= hi + e))
    for p in st.Traverse():
        if p.GetTypeName() != "BasisCurves":
            continue
        path = str(p.GetPath())
        if "/notes/" in path or path.endswith("_leaders"):
            continue
        pv = UsdGeom.PrimvarsAPI(p)
        paint = pv.GetPrimvar("sketch_paint")
        if paint and paint.Get() and not cfg.get("include_paint"):
            continue
        if inc and not inc.search(path) or exc and exc.search(path):
            continue
        bc = UsdGeom.BasisCurves(p)
        P = np.array(bc.GetPointsAttr().Get() or [], float)
        counts = list(bc.GetCurveVertexCountsAttr().Get() or [len(P)])
        xf = np.array(UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default()), float)
        if len(P):
            P = P @ xf[:3, :3] + xf[3, :3]                    # USD: row vectors
        sid = pv.GetPrimvar("sketch_id")
        lid = (sid.Get() if sid else None) or p.GetName()
        o = 0
        for k, n in enumerate(counts):
            q = P[o:o + n]; o += n
            mapped = None
            if len(q) >= 2 and groups:
                c = q.mean(0)
                for g in groups:                             # drawn on an imported copy of the build -> back to the build
                    if inside(c, g["lo"], g["hi"]) and not (own and inside(c, *own, pad=0.0)):
                        q = q @ g["map"][:3, :3] + g["map"][3, :3]; mapped = g["file"]
                        break
            if mapped and "__copy" in path:                  # Mule mirrored the mark about the sketch's plane, not the
                skipped_copies.append(p.GetName())           # import's: the copy lies beside the build – judge the drawn side
                continue
            if len(q) >= 2:
                name = p.GetName() + (f"_{k + 1}" if len(counts) > 1 else "")
                if name in seen:                                   # same name twice (copies, board copies): add the parent
                    name = f"{name}@{p.GetParent().GetName()}"
                    while name in seen:
                        name += "'"
                seen.add(name)
                out.append({"id": name, "line": lid, "path": path, "pts": (q * s) @ B3.T, "mapped": mapped})
    if skipped_copies and not cfg.get("_quiet"):
        print("OVERLAY_NOTE mirrored copies of marks drawn on an imported model left out:", len(skipped_copies))
    return out


def read_surfaces(cfg):
    """sketched surfaces of scene.usd (Mesh prims F#; with sketch_meshes also the imported M#) -> V, T (Blender world)"""
    from pxr import Usd, UsdGeom
    st = Usd.Stage.Open(cfg["scene_usd"])
    rx = re.compile(cfg.get("sketch_surfaces") or (r"^[FM]\d+" if cfg.get("sketch_meshes") else r"^F\d+"))
    s = float(cfg.get("brief_scale", 1.0))
    Vs, Ts, off = [], [], 0
    for p in st.Traverse():
        if p.GetTypeName() != "Mesh" or "/notes/" in str(p.GetPath()) or not rx.search(p.GetName()):
            continue
        m = UsdGeom.Mesh(p)
        P = np.array(m.GetPointsAttr().Get() or [], float)
        cnt = np.array(m.GetFaceVertexCountsAttr().Get() or [], int); idx = np.array(m.GetFaceVertexIndicesAttr().Get() or [], int)
        if not len(P) or not len(cnt):
            continue
        xf = np.array(UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default()), float)
        P = (P @ xf[:3, :3] + xf[3, :3]) * s
        starts = np.concatenate([[0], np.cumsum(cnt)[:-1]]); tris = []
        for k in range(3, int(cnt.max()) + 1):                     # fan per face size
            f = starts[cnt == k]
            for j in range(1, k - 1):
                tris.append(np.stack([idx[f], idx[f + j], idx[f + j + 1]], 1))
        if tris:
            Vs.append(P @ B3.T); Ts.append(np.concatenate(tris) + off); off += len(P)
    if not Vs:
        return None
    V, T = np.concatenate(Vs), np.concatenate(Ts)
    return V, T, np.zeros(len(T), int)


def kind_of(path, cfg):
    for rx, kind in (cfg.get("kinds") or {}).items():
        if re.search(rx, path):
            return kind
    return cfg.get("default_kind", "precise")


def tolerance(kind, cfg):
    t = dict(DEFAULT_TOL.get(kind, DEFAULT_TOL["precise"]))
    t.update((cfg.get("tolerance") or {}).get(kind, {}))
    return t


def _rot_x(deg):
    a = math.radians(deg); c, s_ = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0, 0], [0, c, -s_, 0], [0, s_, c, 0], [0, 0, 0, 1]], float)


def fix_up_axis(new_objs, ref, setting):
    """a file whose up axis was not carried over lies on its side: try 0, +90, -90 degrees about X and keep the one
    that puts most of its points into the sketch's box (`geo_rotate_x` in the config overrides: 0, 90, -90)."""
    tops = [o for o in new_objs if o.parent is None or o.parent not in new_objs]
    if not tops:
        return 0
    if setting not in (None, "auto"):
        best = float(setting)
    else:
        pts = []
        for o in new_objs:
            if o.type == "MESH" and len(o.data.vertices):
                V = np.empty(len(o.data.vertices) * 3, np.float32); o.data.vertices.foreach_get("co", V)
                V = V.reshape(-1, 3)[:: max(1, len(o.data.vertices) // 400)].astype(float)
                M = np.array(o.matrix_world); pts.append(V @ M[:3, :3].T + M[:3, 3])
        if not pts or ref is None:
            return 0
        P = np.concatenate(pts); lo, hi = ref; e = (hi - lo) * 0.1
        def score(deg):
            Q = P @ _rot_x(deg)[:3, :3].T
            return float(np.mean(np.all((Q >= lo - e) & (Q <= hi + e), axis=1)))
        sc = {d: score(d) for d in (0, 90, -90)}
        best = max(sc, key=lambda d: (sc[d], d == 0))
        if sc[best] <= sc[0] + 0.05:
            best = 0
    if best:
        R = _rot_x(best)
        for o in tops:
            o.matrix_world = Matrix((R @ np.array(o.matrix_world)).tolist())
        bpy.context.view_layer.update()
    return best


def load_geometry(cfg, ref=None):
    if cfg.get("blend"):
        bpy.ops.wm.open_mainfile(filepath=cfg["blend"], load_ui=False)   # read only: this script never saves
    else:
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o)
    turned = {}
    for f in cfg.get("geo_files") or []:
        before = set(bpy.data.objects)
        ext = os.path.splitext(f)[1].lower()
        if ext in (".usd", ".usda", ".usdc", ".usdz"):
            try:
                bpy.ops.wm.usd_import(filepath=f, import_cameras=False, import_curves=False, import_lights=False,
                                      import_materials=False, import_subdiv=True)
            except TypeError:
                bpy.ops.wm.usd_import(filepath=f)
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=f)
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=f)
        elif ext in (".abc",):
            bpy.ops.wm.alembic_import(filepath=f)
        elif ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=f)
        elif ext == ".ply":
            bpy.ops.wm.ply_import(filepath=f)
        elif ext == ".stl":
            bpy.ops.wm.stl_import(filepath=f)
        else:
            raise SystemExit("OVERLAY_ERROR unknown geometry file type: %s" % f)
        turned[os.path.basename(f)] = fix_up_axis([o for o in bpy.data.objects if o not in before], ref,
                                                  cfg.get("geo_rotate_x", "auto"))
        print("OVERLAY_GEO", os.path.basename(f), "turned about X by", turned[os.path.basename(f)])
    return turned


def collect(cfg):
    """all visible meshes (modifiers, instances evaluated) -> V (Blender world), T, part index per triangle, names"""
    hide = re.compile(cfg["hide"]) if cfg.get("hide") else None
    only = re.compile(cfg["objects"]) if cfg.get("objects") else None
    dg = bpy.context.evaluated_depsgraph_get()
    Vs, Ts, Is, names, off = [], [], [], [], 0
    for inst in dg.object_instances:
        ob = inst.object
        if ob.type not in MESHY:
            continue
        owner = inst.parent.original if inst.is_instance and inst.parent else ob.original
        if owner.hide_render or owner.hide_get() if hasattr(owner, "hide_get") else False:
            continue
        if hide and hide.search(owner.name) or only and not only.search(owner.name):
            continue
        try:
            me = ob.to_mesh()
        except RuntimeError:
            continue
        if me is None or not len(me.polygons):
            ob.to_mesh_clear(); continue
        me.calc_loop_triangles()
        V = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", V)
        T = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get("vertices", T)
        M = np.array(inst.matrix_world)
        V = V.reshape(-1, 3).astype(float) @ M[:3, :3].T + M[:3, 3]
        if owner.name not in names:
            names.append(owner.name)
        Vs.append(V); Ts.append(T.reshape(-1, 3) + off); Is.append(np.full(len(T) // 3, names.index(owner.name)))
        off += len(V)
        ob.to_mesh_clear()
    if not Vs:
        raise SystemExit("OVERLAY_ERROR no geometry found (check blend / geo_files / hide / objects)")
    return np.concatenate(Vs), np.concatenate(Ts), np.concatenate(Is), names


# ---------- render passes ------------------------------------------------------------------------------------------
class Passes:
    """one triangle mesh with two colour attributes: face normal, and (depth, part id lo, part id hi)."""
    def __init__(self, meshes, res_x, tmp):
        """meshes: {name: (V, T, part index per triangle)} – rendered one at a time from the same camera"""
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o)
        sc = bpy.context.scene
        self.sc, self.tmp, self.RX, self.m = sc, tmp, res_x, {}
        for name, (V, T, I) in meshes.items():
            F = T.reshape(-1)
            me = bpy.data.meshes.new("ov_" + name)
            me.vertices.add(len(V)); me.vertices.foreach_set("co", V.astype(np.float32).ravel())
            me.loops.add(len(F)); me.loops.foreach_set("vertex_index", F.astype(np.int32))
            me.polygons.add(len(T)); me.polygons.foreach_set("loop_start", np.arange(0, len(F), 3, dtype=np.int32))
            me.update(calc_edges=True)
            n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-20)
            nrm = me.color_attributes.new("ov_nrm", "FLOAT_COLOR", "CORNER")
            c = np.ones((len(T), 3, 4), np.float32); c[:, :, :3] = (n[:, None, :] * 0.5 + 0.5)
            nrm.data.foreach_set("color", c.ravel())
            ids = me.color_attributes.new("ov_dep", "FLOAT_COLOR", "CORNER")
            k = (I + 1).astype(np.int64)
            ob = bpy.data.objects.new("ov_" + name, me); sc.collection.objects.link(ob)
            self.m[name] = {"V": V, "T": T, "me": me, "ob": ob, "nrm": nrm, "ids": ids,
                            "idc": np.stack([(k % 256) / 255.0, (k // 256) / 255.0], 1)}
        self.V = np.concatenate([d["V"] for d in self.m.values()])
        self.cam = bpy.data.objects.new("ov_cam", bpy.data.cameras.new("ov_cam")); sc.collection.objects.link(self.cam)
        sc.camera = self.cam
        r = sc.render; r.engine = "BLENDER_WORKBENCH"; r.resolution_percentage = 100
        r.film_transparent = True; r.dither_intensity = 0.0
        sh = sc.display.shading; sh.light = "FLAT"; sh.color_type = "VERTEX"
        for a in ("show_cavity", "show_shadows", "show_object_outline", "show_specular_highlight", "show_xray",
                  "show_backface_culling", "use_dof"):
            if hasattr(sh, a): setattr(sh, a, False)
        sc.display.render_aa = "OFF"
        try: sc.view_settings.view_transform = "Raw"
        except Exception: sc.view_settings.view_transform = "Standard"
        im = r.image_settings; im.file_format = "OPEN_EXR"; im.color_mode = "RGBA"; im.color_depth = "32"
        try: im.exr_codec = "NONE"
        except Exception: pass
        r.filepath = tmp

    def _active(self, me, attr):
        ca = me.color_attributes
        try: ca.active_color = attr
        except Exception: pass
        try: ca.active_color_name = attr.name
        except Exception: pass
        try: ca.render_color_index = list(ca).index(attr)
        except Exception: pass

    def _render(self):
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(self.tmp, check_existing=False)
        a = np.empty(self.RX * self.RY * 4, np.float32); img.pixels.foreach_get(a); bpy.data.images.remove(img)
        return np.flipud(a.reshape(self.RY, self.RX, 4))       # row 0 = top

    def view(self, v):
        """v: {eye, fwd, up, ortho (width) | tan_v, aspect} in Blender world -> pixel passes + projector"""
        self.RY = int(round(self.RX / v["aspect"]))
        self.sc.render.resolution_x, self.sc.render.resolution_y = self.RX, self.RY
        fwd = v["fwd"] / np.linalg.norm(v["fwd"]); right = np.cross(fwd, v["up"]); right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        M = np.eye(4); M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = right, up, -fwd, v["eye"]
        d = self.cam.data; d.sensor_fit = "HORIZONTAL"; d.sensor_width = 36.0; d.shift_x = d.shift_y = 0.0
        dep = (self.V - v["eye"]) @ fwd
        far = float(dep.max()) * 1.05 + 1e-3
        if v.get("ortho"):
            d.type = "ORTHO"; d.ortho_scale = v["ortho"]
            near = max(float(dep.min()) - 0.05 * far, -far)       # orthographic: the eye may sit inside the box
            d.clip_start, d.clip_end = 1e-4, far - min(near, 0) + 1e-3
            if near < 0:
                M[:3, 3] = v["eye"] + fwd * (near - 1e-3); v = dict(v, eye=M[:3, 3])
                dep = (self.V - v["eye"]) @ fwd; far = float(dep.max()) * 1.05 + 1e-3
        else:
            d.type = "PERSP"; tan_h = v["tan_v"] * self.RX / self.RY
            d.lens = 18.0 / tan_h
            d.clip_start, d.clip_end = max(1e-3, far * 2e-5), far
        self.cam.matrix_world = Matrix(M.tolist())
        self.base = {"eye": np.array(v["eye"], float), "fwd": fwd, "right": right, "up": up, "ortho": v.get("ortho"),
                     "tan_h": None if v.get("ortho") else v["tan_v"] * self.RX / self.RY, "RX": self.RX, "RY": self.RY,
                     "far": far}
        return self.base

    def passes(self, name):
        """render one mesh from the current camera -> coverage, part id, depth, normal (+ the camera of view())"""
        b = self.base; d = self.m[name]; far = b["far"]
        for n, o in self.m.items():
            o["ob"].hide_render = n != name
        self._active(d["me"], d["nrm"]); A = self._render()
        dep = (d["V"] - b["eye"]) @ b["fwd"]
        cdep = np.ones((len(d["T"]), 3, 4), np.float32)
        cdep[:, :, 0] = (dep[d["T"]] / far).astype(np.float32); cdep[:, :, 1:3] = d["idc"][:, None, :]
        d["ids"].data.foreach_set("color", cdep.ravel())
        self._active(d["me"], d["ids"]); B = self._render()
        cov = A[:, :, 3] > 0.5
        part = np.where(cov, np.round(B[:, :, 1] * 255) + 256 * np.round(B[:, :, 2] * 255) - 1, -1).astype(np.int64)
        depth = np.where(cov, B[:, :, 0] * far, np.inf)
        return dict(b, cov=cov, part=part, depth=depth, nrm=A[:, :, :3] * 2 - 1)


def project(P, pv):
    """Blender world points -> pixel x, y (row 0 top), depth along the view"""
    q = P - pv["eye"]
    z = q @ pv["fwd"]; x = q @ pv["right"]; y = q @ pv["up"]
    RX, RY = pv["RX"], pv["RY"]
    if pv["ortho"]:
        w = pv["ortho"]; h = w * RY / RX
        return (0.5 + x / w) * RX, (0.5 - y / h) * RY, z
    zz = np.maximum(z, 1e-9); th = pv["tan_h"]; tv = th * RY / RX
    return (0.5 + 0.5 * x / zz / th) * RX, (0.5 - 0.5 * y / zz / tv) * RY, z


def edge_map(pv, crease_deg, parts=True):
    cov, part, depth, nrm = pv["cov"], pv["part"], pv["depth"], pv["nrm"]
    E = np.zeros_like(cov)
    cosl = math.cos(math.radians(crease_deg))
    for dy, dx in ((0, 1), (1, 0)):
        a = (slice(0, cov.shape[0] - dy), slice(0, cov.shape[1] - dx))
        b = (slice(dy, None), slice(dx, None))
        ca, cb = cov[a], cov[b]
        e = ca != cb                                                  # outline against the background
        both = ca & cb
        if parts:
            e |= both & (part[a] != part[b])                          # border between two parts
        e |= both & ((nrm[a] * nrm[b]).sum(-1) < cosl)                # crease
        da, db = depth[a], depth[b]
        with np.errstate(invalid="ignore"):
            e |= both & (np.abs(da - db) > 0.02 * np.minimum(da, db) + 1e-6)   # one surface in front of another
        E[a] |= e & ca; E[b] |= e & cb                                # the edge pixel sits on the geometry
        E[a] |= e & ~ca & ~cb                                         # (never both empty)
    return E


# ---------- measuring ----------------------------------------------------------------------------------------------
def resample(P, step_px, pv, max_n=160):
    x, y, z = project(P, pv)
    seg = np.hypot(np.diff(x), np.diff(y)); L = float(seg.sum())
    if L < 1e-6:
        return None
    s = np.concatenate([[0], np.cumsum(seg)])
    n = int(min(max_n, max(8, L / step_px)))
    t = np.linspace(0, L, n)
    Q = np.stack([np.interp(t, s, P[:, k]) for k in range(3)], 1)
    x, y, z = project(Q, pv)
    return Q, x, y, z, L, t


def smooth(a, w):
    if w < 2:
        return a
    k = np.ones(w) / w
    pad = np.pad(a, (w // 2, w - 1 - w // 2), mode="edge")
    return np.convolve(pad, k, mode="valid")


def bow(x, y):
    """signed sagitta of a polyline / chord length (+ = bends to the left of the chord direction)"""
    c = np.array([x[-1] - x[0], y[-1] - y[0]]); L = float(np.hypot(*c))
    if L < 1e-9:
        return 0.0, 0.0
    d = ((x - x[0]) * c[1] - (y - y[0]) * c[0]) / L
    i = int(np.argmax(np.abs(d)))
    return float(-d[i] / L), L


def measure(stroke, pv, E, tol, cfg, pvS=None, ES=None):
    """pv/E: build passes and edges; pvS/ES: the same for the artist's sketched surfaces (None if there are none).
    What the line shows in this view decides what the build must show there:
      an edge of the sketched form  -> an edge of the build nearby;
      a line on a sketched surface  -> the built surface at the same place (depth difference counts);
      a free line (frame, cable)    -> a tube around it (its middle) or an edge nearby."""
    RX, RY = pv["RX"], pv["RY"]
    r = resample(stroke["pts"], float(cfg.get("step_px", 3.0)), pv)
    if r is None:
        return None
    Q, x, y, z, L, t = r
    L3 = float(np.linalg.norm(np.diff(stroke["pts"], axis=0), axis=1).sum())
    inside = (x >= 1) & (x < RX - 1) & (y >= 1) & (y < RY - 1) & (z > 0)
    min_len = float(cfg.get("min_line_px", 40))
    if L < min_len or inside.mean() < 0.5:
        return None
    # 2D normal of the drawn line
    tx, ty = np.gradient(x), np.gradient(y); tn = np.maximum(np.hypot(tx, ty), 1e-9); nx, ny = -ty / tn, tx / tn
    tol_px = tol["dist"] * L
    R = round(float(min(max(3 * tol_px, 12.0), 0.25 * RX)) * 2) / 2
    steps = np.arange(-R, R + 0.25, 0.5); c0 = int(round(R * 2)); M = len(steps)
    xi = np.clip(np.round(x[:, None] + nx[:, None] * steps[None]).astype(int), 0, RX - 1)
    yi = np.clip(np.round(y[:, None] + ny[:, None] * steps[None]).astype(int), 0, RY - 1)
    px, py = np.clip(np.round(x).astype(int), 0, RX - 1), np.clip(np.round(y).astype(int), 0, RY - 1)
    dr = pv["depth"][py, px]; cov = pv["cov"][py, px]
    margin = 2 * tol["dist"] * L3 + 0.002 * np.maximum(z, 0)
    occluded = cov & (dr < z - margin)                       # something else stands in front of the drawn line
    # only geometry at the depth of the drawn line counts (not a wall far behind it)
    match = pv["cov"][yi, xi] & (np.abs(pv["depth"][yi, xi] - z[:, None]) < np.maximum(margin, 0.1 * L3)[:, None])
    hitE = E[yi, xi] & match
    thin = 0.2 * L                                           # a part this narrow around the line is a tube: use its middle
    def first(a):                                            # index of the first True per row, M if none
        return np.where(a.any(1), a.argmax(1), M)
    rp, rm = match[:, c0:], match[:, c0::-1]                 # rays to + and to - (index 0 = the line itself)
    # the line lies on the part: the run of part pixels around it
    b = first(~rp) * 0.5; a = first(~rm) * 0.5
    on_off = np.where(a + b <= thin, (b - a) / 2.0, np.nan)
    ep, em = first(hitE[:, c0:]) * 0.5, first(hitE[:, c0::-1]) * 0.5
    edge_off = np.where(ep <= em, ep, -em)
    edge_off = np.where(np.minimum(ep, em) >= M * 0.5, np.nan, edge_off)
    on_off = np.where(np.isnan(on_off), edge_off, on_off)    # wide surface: the nearest edge (an outline line)
    # the line lies beside the part: the nearest part on either side, its middle if it is narrow
    def beside(r):                                           # -> (offset to use, distance to the part), inf if none
        n = r.shape[1]; ent = first(r)
        later = np.arange(n)[None] > ent[:, None]
        ext = first(~r & later)                              # n if the part runs to the end of the ray
        e, x_ = ent * 0.5, ext * 0.5
        mid = np.where((ext < n) & (x_ - e <= thin), (e + x_) / 2.0, e)
        none = ent >= n
        return np.where(none, np.inf, mid), np.where(none, np.inf, e)
    mp, ent_p = beside(rp); mm, ent_m = beside(rm)
    side_off = np.where(ent_p <= ent_m, mp, -mm)             # +-inf where nothing on either side
    on_line = match[:, c0]
    off = np.where(on_line, on_off, side_off)
    kind = np.zeros(len(x), int)                             # 0 free · 1 edge of the sketch · 2 on a sketched surface
    if pvS is not None:
        mS = np.maximum(0.03 * L3, 0.004 * np.maximum(z, 0))
        onS = pvS["cov"][py, px] & (np.abs(pvS["depth"][py, px] - z) < mS)
        near = np.zeros(len(x), bool)
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                yy, xx = np.clip(py + dy, 0, RY - 1), np.clip(px + dx, 0, RX - 1)
                near |= ES[yy, xx] & (np.abs(pvS["depth"][yy, xx] - z) < mS)
        kind = np.where(near, 1, np.where(onS, 2, 0))
        off = np.where(kind == 1, np.where(on_line | ~np.isnan(edge_off), edge_off, side_off), off)
        dz = (pv["depth"][py, px] - z) / max(L3, 1e-9) * L   # depth difference, in pixels of this line's length
        surf_off = np.where(cov & ~occluded & np.isfinite(dz), np.where(np.isfinite(dz), dz, np.nan), side_off)
        off = np.where(kind == 2, surf_off, off)
    off = np.where(np.isinf(off), np.nan, off)
    missing = np.isnan(off) & ~occluded & inside
    valid = inside & ~occluded & ~np.isnan(off)
    judged = inside & ~occluded
    if judged.mean() < 0.4 or judged.sum() < 6:
        return None
    min_px = float(cfg.get("min_px", 3.0))
    dev = np.where(valid, np.maximum(np.abs(off) - min_px, 0), R)
    k = max(1, len(t) // 20); ends = np.zeros(len(t), bool); ends[:k] = ends[-k:] = True
    sel = judged & (ends if tol.get("ends_only") else ~ends)  # line ends sit in joints and caps: judged by the next line
    if not sel.any():
        return None
    # typical offset over the line (80th percentile): a stretch that runs away counts, a pixel at a joint does not
    dv = dev[sel & valid]
    dist = float(np.percentile(dv, 80)) / L if len(dv) else R / L
    res = {"view_len_px": round(L, 1), "dist": round(dist, 4), "missing": round(float(missing[judged].mean()), 3),
           "seen": round(float(judged.mean()), 3), "angle": None, "curve": None}
    # where it is worst (pixel position for the report)
    j = int(np.argmax(np.where(sel, dev, -1)))
    res["worst_px"] = [int(px[j]), int(py[j])]
    # direction: slope of the offset along the line, smoothed over ~6 % of its length
    oo = np.where(valid, off, np.nan)
    if np.isfinite(oo).sum() >= 6:
        idx = np.arange(len(oo)); good = np.isfinite(oo)
        of = np.interp(idx, idx[good], oo[good])
        w = max(3, int(len(of) * 0.10))
        from numpy.lib.stride_tricks import sliding_window_view
        med = np.median(sliding_window_view(np.pad(of, (w // 2, w - 1 - w // 2), mode="edge"), w), axis=1)
        ofs = smooth(med, w)                                 # median first: a jump between tube middle and edge is no bend
        if tol.get("angle") is not None and L >= 60:
            ds = np.gradient(t)
            ang = np.degrees(np.arctan(np.abs(np.gradient(ofs) / np.maximum(ds, 1e-9))))
            ang = ang[good & sel]
            if len(ang):
                res["angle"] = round(float(np.percentile(ang, 75)), 1)
        if tol.get("curves"):
            mx, my = x + nx * ofs, y + ny * ofs
            n = len(x); verdicts = []
            wins = [(0, n)] + ([(0, n // 2), (n // 4, 3 * n // 4), (n // 2, n)] if n >= 24 else [])
            for a, b in wins:
                if good[a:b].mean() < 0.6:
                    continue
                bs, Lc = bow(x[a:b], y[a:b])
                if Lc < 40:
                    continue
                bm, _ = bow(mx[a:b], my[a:b])
                if abs(bs) >= 0.015 and (np.sign(bm) != np.sign(bs) or abs(bm) < 0.4 * abs(bs)):
                    verdicts.append("bow flattened" if np.sign(bm) == np.sign(bs) or abs(bm) < 0.005 else "bow flipped")
                elif abs(bs) < 0.005 and abs(bm) > max(0.02, tol["dist"]):
                    verdicts.append("straight bent")
            res["curve"] = verdicts[0] if verdicts else "kept"
    res["fail"] = [k for k, bad in (("distance", dist > tol["dist"]),
                                    ("missing", res["missing"] > 0.2),
                                    ("direction", res["angle"] is not None and res["angle"] > tol["angle"]),
                                    ("curve", res["curve"] not in (None, "kept"))) if bad]
    res["_samples"] = (x, y, judged, occluded, np.where(valid, np.abs(off), np.inf), tol_px + min_px)
    return res


# ---------- views --------------------------------------------------------------------------------------------------
def views(cfg, strokes):
    out = []
    want = cfg.get("views", "all")
    if cfg.get("brief_json") and want in ("all", "hero"):
        s = float(cfg.get("brief_scale", 1.0))
        for c in json.load(open(cfg["brief_json"], encoding="utf-8")).get("cameras") or []:
            if cfg.get("hero_names") and c["id"] not in cfg["hero_names"]:
                continue
            eye, tgt, up = (np.array(c[k], float) for k in ("eye", "target", "up"))
            v = {"name": c["id"], "eye": B3 @ (eye * s), "fwd": B3 @ (tgt - eye), "up": B3 @ up, "aspect": c["aspect"]}
            if c.get("orthographic_height"):
                v["ortho"] = c["orthographic_height"] * s * c["aspect"]
            else:
                v["tan_v"] = math.tan(math.radians(c["fov_vertical_deg"]) / 2)
            out.append(v)
    if cfg.get("ortho", True) and want in ("all", "ortho"):
        frame = re.compile(cfg["ortho_frame"]) if cfg.get("ortho_frame") else None
        P = np.concatenate([s["pts"] for s in strokes if not frame or frame.search(s["path"])])
        lo, hi = P.min(0), P.max(0); c = (lo + hi) / 2; ext = hi - lo; D = float(np.linalg.norm(ext)) + 1e-6
        a = float(cfg.get("ortho_aspect", 1.5))
        # brief axes (Y up): side = looking along -Z of the brief, front = along -X, top = down -Y
        for name, fwd, up, wh in (("ortho_side", (0, 0, -1), (0, 1, 0), (0, 1)), ("ortho_front", (-1, 0, 0), (0, 1, 0), (2, 1)),
                                  ("ortho_top", (0, -1, 0), (-1, 0, 0), (2, 0))):
            f, u = B3 @ np.array(fwd, float), B3 @ np.array(up, float)
            eb = C3 @ ext; w, h = eb[wh[0]], eb[wh[1]]
            width = max(w, h * a) * 1.12 + 1e-6
            out.append({"name": name, "eye": c - f * D, "fwd": f, "up": u, "ortho": width, "aspect": a})
    return out


# ---------- pictures -----------------------------------------------------------------------------------------------
def picture(pv, results, fn):
    RX, RY = pv["RX"], pv["RY"]
    light = np.array([0.35, 0.55, 0.75]); light /= np.linalg.norm(light)
    L = pv["right"] * light[0] + pv["up"] * light[1] - pv["fwd"] * light[2]
    sh = 0.42 + 0.5 * np.clip((pv["nrm"] * L).sum(-1), 0, 1)
    img = np.ones((RY, RX, 3), np.float32) * 0.96
    img[pv["cov"]] = (sh[pv["cov"]][:, None] * np.array([0.82, 0.82, 0.84]))
    def dot(x, y, col, r=1):
        xi, yi = np.round(x).astype(int), np.round(y).astype(int)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                m = (xi + dx >= 0) & (xi + dx < RX) & (yi + dy >= 0) & (yi + dy < RY)
                img[yi[m] + dy, xi[m] + dx] = col
    for res in results:
        x, y, judged, occl, dev, lim = res["_samples"]
        # dense polyline for drawing
        n = max(2, int(np.hypot(np.diff(x), np.diff(y)).sum() / 0.7))
        tt = np.linspace(0, len(x) - 1, n); k = np.arange(len(x))
        xx, yy = np.interp(tt, k, x), np.interp(tt, k, y)
        jj = np.interp(tt, k, judged.astype(float)) > 0.5; oc = np.interp(tt, k, occl.astype(float)) > 0.5
        dd = np.interp(tt, k, np.where(np.isfinite(dev), dev, 1e9))
        dot(xx[oc], yy[oc], (0.55, 0.7, 0.95), 0)
        ok = jj & (dd <= lim); bad = jj & (dd > lim) & (dd < 1e8); miss = jj & (dd >= 1e8)
        dot(xx[ok], yy[ok], (0.05, 0.6, 0.15), 1)
        dot(xx[bad], yy[bad], (0.9, 0.08, 0.05), 1)
        dot(xx[miss], yy[miss], (1.0, 0.55, 0.0), 1)
    write_png(fn, img)


def write_png(fn, img):
    """RGB float image (row 0 top) -> 8-bit PNG, without Blender's image buffers"""
    import zlib, struct
    a = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    h, w = a.shape[:2]
    raw = b"".join(b"\x00" + a[r].tobytes() for r in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(fn, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ---------- run ----------------------------------------------------------------------------------------------------
def run(cfg):
    t0 = time.time()
    name = cfg.get("name") or cfg.get("unit") or "overlay"
    out = cfg.get("out_dir", "review/overlay"); os.makedirs(out, exist_ok=True)
    strokes = read_strokes(cfg)
    if not strokes:
        raise SystemExit("OVERLAY_ERROR no strokes matched (check scene_usd / lines)")
    sk = read_surfaces(cfg) if cfg.get("use_sketch_surfaces", True) else None
    allp = np.concatenate([x["pts"] for x in read_strokes(dict(cfg, lines=None, exclude_lines=None, _quiet=True))])
    turned = load_geometry(cfg, (allp.min(0), allp.max(0)))
    mapped = sorted({x["mapped"] for x in strokes if x.get("mapped")})
    nmapped = sum(1 for x in strokes if x.get("mapped"))
    V, T, I, parts = collect(cfg)
    vs = views(cfg, strokes)
    if cfg.get("max_views"):
        vs = vs[:int(cfg["max_views"])]
    ps = Passes(dict({"build": (V, T, I)}, **({"sketch": sk} if sk else {})), int(cfg.get("res_x", 1200)),
                os.path.join(out, "_ov_tmp.exr"))
    per = {s["id"]: {"id": s["id"], "line": s["line"], "path": s["path"], "kind": kind_of(s["path"], cfg), "views": {}}
           for s in strokes}
    crease = float(cfg.get("crease_deg", 35))
    for v in vs:
        ps.view(v); pv = ps.passes("build"); E = edge_map(pv, crease); shown = []
        pvS = ps.passes("sketch") if sk else None
        ES = edge_map(pvS, crease, parts=False) if sk else None
        for s in strokes:
            rec = per[s["id"]]
            if rec["kind"] == "ignore":
                continue
            m = measure(s, pv, E, tolerance(rec["kind"], cfg), cfg, pvS, ES)
            if m:
                shown.append(m); rec["views"][v["name"]] = m
        if cfg.get("pictures", True):
            picture(pv, shown, os.path.join(out, "ov_%s_%s.png" % (name, v["name"])))
        for m in shown:
            m.pop("_samples", None)
        print("OVERLAY_VIEW", v["name"], "lines", len(shown))
    try: os.remove(os.path.join(out, "_ov_tmp.exr"))
    except OSError: pass
    rows = []
    for rec in per.values():
        if rec["kind"] == "ignore":
            continue
        vv = rec["views"]
        if not vv:
            rec["verdict"] = "NOT SEEN"; rows.append(rec); continue
        # one view alone can mislead (a line grazing a silhouette, a view nearly along the line): a finding counts when
        # an orthographic view or two views agree; distance also when one view sees it beyond twice the tolerance
        fails = set()
        dtol = tolerance(rec["kind"], cfg)["dist"]
        for f in ("distance", "missing", "direction", "curve"):
            hit = [n for n, m in vv.items() if f in m["fail"]]
            strong = f == "distance" and any(vv[n]["dist"] > 2 * dtol and vv[n]["seen"] >= 0.7 for n in hit)
            if any(n.startswith("ortho") for n in hit) or len(hit) >= 2 or strong:
                fails.add(f)
        fails = sorted(fails)
        rec["verdict"] = "FAIL" if fails else "PASS"; rec["fails"] = fails
        wn, wm = max(vv.items(), key=lambda kv: kv[1]["dist"])
        rec["worst"] = {"view": wn, "dist": wm["dist"], "px": wm["worst_px"]}
        rec["angle"] = max((m["angle"] for m in vv.values() if m["angle"] is not None), default=None)
        bad = [m["curve"] for m in vv.values() if m["curve"] not in (None, "kept")]
        rec["curve"] = bad[0] if "curve" in fails and bad else ("kept" if any(m["curve"] for m in vv.values()) else None)
        rows.append(rec)
    rows.sort(key=lambda r: ({"FAIL": 0, "PASS": 1}.get(r["verdict"], 2), -(r.get("worst") or {}).get("dist", 0)))
    data = {"name": name, "views": [v["name"] for v in vs], "parts": len(parts), "lines": rows,
            "geo_turned_x": turned, "marks_mapped": {"lines": nmapped, "from": mapped},
            "tolerance": {k: tolerance(k, cfg) for k in DEFAULT_TOL}, "seconds": round(time.time() - t0, 1)}
    json.dump(data, open(os.path.join(out, "overlay_%s.json" % name), "w", encoding="utf-8"), indent=1)
    write_md(data, os.path.join(out, "%s_overlay.md" % name), name)
    nf = sum(r["verdict"] == "FAIL" for r in rows); npass = sum(r["verdict"] == "PASS" for r in rows)
    print("OVERLAY_DONE", name, "pass", npass, "fail", nf, "not_seen", len(rows) - nf - npass, "s", data["seconds"])
    return data


def write_md(d, fn, name):
    rows = d["lines"]
    nf = [r for r in rows if r["verdict"] == "FAIL"]; npass = sum(r["verdict"] == "PASS" for r in rows)
    ns = [r for r in rows if r["verdict"] == "NOT SEEN"]
    t = d["tolerance"]
    L = ["# Sketch overlay – %s" % name, "",
         "A measurement on pictures (rule 11: numbers sort, pictures judge). Views: %s. Pictures `ov_%s_<view>.png`: "
         "green = within tolerance, red = beyond, orange = nothing built there, blue = hidden in that view." % (", ".join(d["views"]), name), "",
         "Tolerance (share of each line's own length; direction in degrees): precise %.0f %% · %s° · curves kept; gesture %.0f %%; "
         "route: ends %.0f %%." % (t["precise"]["dist"] * 100, t["precise"]["angle"], t["gesture"]["dist"] * 100, t["route"]["dist"] * 100), "",
         "**%d FAIL · %d PASS · %d not seen in any view**" % (len(nf), npass, len(ns)), ""]
    if d.get("marks_mapped", {}).get("lines"):
        L += ["%d lines were drawn on an imported copy of the build (%s) and are measured at their place on the build." % (
            d["marks_mapped"]["lines"], ", ".join(d["marks_mapped"]["from"])), ""]
    if any(d.get("geo_turned_x", {}).values()):
        L += ["Geometry turned to the sketch's up axis: " + ", ".join("%s %+d°" % (k, v) for k, v in d["geo_turned_x"].items() if v), ""]
    if nf:
        L += ["| line | kind | fails | worst distance | direction | curve | where (view, px) |", "|---|---|---|---|---|---|---|"]
        for r in nf[:200]:
            w = r["worst"]
            L.append("| %s | %s | %s | %.1f %% | %s | %s | %s (%d, %d) |" % (
                r["id"], r["kind"], ", ".join(r["fails"]), w["dist"] * 100,
                "–" if r["angle"] is None else "%.0f°" % r["angle"], r["curve"] or "–", w["view"], w["px"][0], w["px"][1]))
    if ns:
        L += ["", "Not seen in any view (hidden, too short or end-on): " + ", ".join(r["id"] for r in ns[:80])
              + (" …" if len(ns) > 80 else "")]
    L += ["", "Limits: a tube's centre line that lies beside its tube is measured to the tube's near edge (less than the "
          "true shift by the tube radius); kinks and states of motion are judged on the pictures. Data: `overlay_%s.json`." % name]
    open(fn, "w", encoding="utf-8").write("\n".join(L) + "\n")


# ---------- selftest -----------------------------------------------------------------------------------------------
def selftest():
    """synthetic: tubes along drawn lines; true copies must pass, shifted / straightened / missing ones fail."""
    import tempfile
    from pxr import Usd, UsdGeom, Vt, Gf
    tmp = tempfile.mkdtemp(prefix="ov_selftest_")
    def arc(c, R, a0, a1, n=60, z=0.0):
        a = np.linspace(a0, a1, n); return np.stack([c[0] + R * np.cos(a), c[1] + R * np.sin(a), np.full(n, z)], 1)
    def line(p, q, n=40):
        return np.linspace(p, q, n)
    def sag_arc(p, q, sag, n=60):           # bow through p, q with sagitta = sag * |pq| (in the XY plane of the brief)
        p, q = np.array(p, float), np.array(q, float); t = np.linspace(0, 1, n)
        d = q - p; nrm = np.array([-d[1], d[0], 0]) / np.linalg.norm(d)
        return p + t[:, None] * d + (4 * sag * np.linalg.norm(d) * t * (1 - t))[:, None] * nrm
    drawn = {  # brief coordinates (Y up), metres
        "L1": sag_arc((0, 0, 0), (2, 0, 0), 0.12),            # built true -> PASS
        "L2": sag_arc((0, 1, 0), (2, 1, 0), 0.12),            # built as the straight chord -> FAIL distance + curve
        "L3": line((0, 2, 0), (2, 2, 0)),                     # built true (straight) -> PASS
        "L4": line((0, 3, 0), (2, 3, 0)),                     # nothing built -> FAIL missing
        "L5": sag_arc((0, 4, 0), (2, 4, 0), 0.025),           # shallow bow built straight -> FAIL curve (distance passes)
        "L6": line((0, 5, 0), (2, 5, 0)),                     # built shifted by 8 % -> FAIL distance
        "L7": line((0.2, 6.4, 0), (1.8, 6.4, 0)),             # line drawn ON the sketched panel, panel built -> PASS
        "L8": line((0, 7, 0), (2, 7, 0)),                     # upper outline of the panel, built 0.15 m lower -> FAIL
        "L9": line((0, 6, 0), (2, 6, 0)),                     # lower outline, built true -> PASS
    }
    built = {"L1": drawn["L1"], "L2": line((0, 1, 0), (2, 1, 0)), "L3": drawn["L3"], "L5": line((0, 4, 0), (2, 4, 0)),
             "L6": drawn["L6"] + np.array([0, 0.16, 0])}
    st = Usd.Stage.CreateNew(os.path.join(tmp, "scene.usda")); UsdGeom.Xform.Define(st, "/sketch")
    UsdGeom.Xform.Define(st, "/sketch/S1_test")
    for k, P in drawn.items():
        c = UsdGeom.BasisCurves.Define(st, "/sketch/S1_test/" + k)
        c.CreateTypeAttr("linear"); c.CreateCurveVertexCountsAttr([len(P)])
        c.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(*map(float, p)) for p in P]))
    pm = UsdGeom.Mesh.Define(st, "/sketch/F1_panel")         # the sketched panel (brief coordinates)
    pm.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(0, 6, 0), Gf.Vec3f(2, 6, 0), Gf.Vec3f(2, 7, 0), Gf.Vec3f(0, 7, 0)]))
    pm.CreateFaceVertexCountsAttr([4]); pm.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    st.GetRootLayer().Save()
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    pb = bpy.data.meshes.new("panel")                        # the built panel: upper edge 0.15 m lower
    pb.from_pydata([tuple(B3 @ np.array(q, float)) for q in ((0, 6, 0), (2, 6, 0), (2, 6.85, 0), (0, 6.85, 0))], [], [(0, 1, 2, 3)])
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("built_panel", pb))
    for k, P in built.items():                               # tubes, r = 2 cm, in Blender coordinates
        cu = bpy.data.curves.new("c" + k, "CURVE"); cu.dimensions = "3D"; cu.bevel_depth = 0.02; cu.bevel_resolution = 3
        sp = cu.splines.new("POLY"); sp.points.add(len(P) - 1)
        for i, p in enumerate(P):
            b = B3 @ p; sp.points[i].co = (b[0], b[1], b[2], 1)
        ob = bpy.data.objects.new("tube_" + k, cu); bpy.context.scene.collection.objects.link(ob)
    cfg = {"name": "selftest", "scene_usd": os.path.join(tmp, "scene.usda"), "views": "ortho", "out_dir": tmp,
           "res_x": 900, "pictures": True}
    # keep the tubes: no blend, no geo_files -> load_geometry would clear the scene, so run the steps by hand
    strokes = read_strokes(cfg); sk = read_surfaces(cfg); V, T, I, parts = collect(cfg)
    ps = Passes({"build": (V, T, I), "sketch": sk}, cfg["res_x"], os.path.join(tmp, "_t.exr"))
    v = [x for x in views(cfg, strokes) if x["name"] == "ortho_side"][0]
    ps.view(v); pv = ps.passes("build"); E = edge_map(pv, 35)
    pvS = ps.passes("sketch"); ES = edge_map(pvS, 35, parts=False)
    got, shown = {}, []
    for s in strokes:
        m = measure(s, pv, E, tolerance("precise", cfg), cfg, pvS, ES)
        got[s["id"]] = m["fail"] if m else None
        if m: shown.append(m)
    picture(pv, shown, os.path.join(tmp, "ov_selftest.png"))
    want = {"L1": set(), "L2": {"distance", "curve"}, "L3": set(), "L4": {"missing"}, "L5": {"curve"}, "L6": {"distance"},
            "L7": set(), "L8": {"distance"}, "L9": set()}
    ok = True
    for k, w in want.items():
        g = {"NOT SEEN"} if got[k] is None else set(got[k])
        good = (not w and not g) or (w and w <= g and "NOT SEEN" not in g)
        ok &= bool(good)
        print("SELFTEST", k, "expected", sorted(w) or "pass", "got", sorted(g) or "pass", "ok" if good else "WRONG")
    print("SELFTEST PASS" if ok else "SELFTEST FAIL", "picture", os.path.join(tmp, "ov_selftest.png"))


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("usage: blender -b --factory-startup -P sketch_overlay.py -- <config.json> | --selftest")
    if argv[0] == "--selftest":
        selftest()
    else:
        run(json.load(open(argv[0], encoding="utf-8")))

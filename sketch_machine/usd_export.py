"""Scene as USD: the Mule scene compactly for Houdini, Blender, Maya … (and for the AI to look at).

  /sketch                      Xform (defaultPrim), Y up, 1 unit = 1 m
    <Null>                     Xform per null (hierarchy as in the outliner), below it its objects
      S#_<Name>                Xform per stroke object, in it L# as BasisCurves (width, color, orient/pscale, hardness)
      F#_<Name>                Mesh per surface: quads from the grid (loft, curve surface, extrusion), fill surfaces as
                               triangles; normals per corner as in the viewport (hard edges stay hard), UV per corner,
                               displayColor, material as primvar
      M#_<Name>                imported USD: reference to the file/prim (nothing copied), position as matrix;
                               OBJ & co. (USD cannot reference them): embedded
    notes                      notes as points with heading, text, images and anchor lines
Everything in world coordinates (the null Xforms are groups without their own translation; origin and axes of the
null are attached as sketch:origin/sketch:axes). Symmetry and array are factored out (when enabled: each copy
its own prim "…__copyN", the mirror side cut at the plane). Visible only – as in the sketch brief, with
the same identifiers.
"""
import math
import os
import re

import numpy as np

from . import components, generators, loft, network, timing_export
from .scene import ExtrudeSurface, LoftSurface

NEUTRAL = (0.8, 0.8, 0.8)  # displayColor of a surface without coloring
DEFAULT_MULT = 0.25  # resolution of the grid surfaces in the export (× viewport): the viewport is very dense for smooth display
#                      (a 50 cm cushion > 5000 quads) – a quarter is enough as a starting point
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


# --- Surfaces as polymesh -----------------------------------------------------------------------------------

def surface_polymesh(f, mult=1.0):
    """(points (N,3), faces as index arrays (F,4) or (F,3), UV per face corner (F,k,2)) of a surface – quads
    from its grid, fill surfaces as triangles; None: no geometry. mult: resolution in addition to that of the surface
    (slider in the outliner) – grid surfaces only, the shape stays (resampled smoothly, hard net lines stay)."""
    if isinstance(f, LoftSurface):
        if len(f.curves) < 2:
            return None
        g = np.asarray(f.grid(), float)
        ring = bool(f.wrap) and len(f.curves) >= 3
        factor = float(f.resolution) * float(mult)
        if abs(factor - 1.0) > 1e-9:
            geo = getattr(f, "_net_geo", None)  # like LoftSurface._build: sample separately at hard net lines
            br = [r for r, h in zip(geo["rows"], geo["hard_u"]) if h.max() > 1e-3] if geo else ()
            bc = [c for c, h in zip(geo["cols"], geo["hard_v"]) if h.max() > 1e-3] if geo else ()
            g = loft.resample_grid(g, factor, f.closed, br, bc, ring=ring)
        return _grid_quads(g, bool(f.closed), ring)
    if isinstance(f, ExtrudeSurface):
        rows = f.rows()
        if len(rows) < 2 or len(rows[0]) < 2 or any(len(r) != len(rows[0]) for r in rows):
            return None
        return _grid_quads(np.array(rows, float), False, False)
    mesh = f.fill_mesh()
    if mesh is None or not len(mesh[1]):
        return None
    v, t = np.asarray(mesh[0], float), np.asarray(mesh[1]).reshape(-1, 3)
    uv = np.asarray(mesh[2], float)[t] if len(mesh) > 2 and mesh[2] is not None and len(mesh[2]) == len(v) else \
        np.zeros((len(t), 3, 2))
    return v, t, uv


def _grid_quads(g, closed, ring):
    """Grid (R, M, 3) -> quads; closed: columns run all around, ring: rows too (last row = first, welded).
    Winding as loft.build (the surface faces the same side). UV in meters: mean length of the rows or columns."""
    r, m = g.shape[:2]
    if ring and np.allclose(g[-1], g[0]):
        g = g[:-1]
        r -= 1
    pts = g.reshape(-1, 3)
    rows = [(k, k + 1) for k in range(r - 1)] + ([(r - 1, 0)] if ring else [])
    cols = [(i, i + 1) for i in range(m - 1)] + ([(m - 1, 0)] if closed else [])
    if not rows or not cols:
        return None
    seg_u = np.linalg.norm(np.diff(np.concatenate([g, g[:, :1]], 1) if closed else g, axis=1), axis=2)
    seg_v = np.linalg.norm(np.diff(np.concatenate([g, g[:1]], 0) if ring else g, axis=0), axis=2)
    len_u, len_v = float(seg_u.sum(axis=1).mean()), float(seg_v.sum(axis=0).mean())
    nu, nv = len(cols), len(rows)
    quads, uv = [], []
    for kr, (k, k2) in enumerate(rows):
        for ki, (i, j) in enumerate(cols):
            quads.append((k * m + i, k * m + j, k2 * m + j, k2 * m + i))
            u0, u1, v0, v1 = ki / nu * len_u, (ki + 1) / nu * len_u, kr / nv * len_v, (kr + 1) / nv * len_v
            uv.append(((u0, v0), (u1, v0), (u1, v1), (u0, v1)))
    return pts, np.array(quads, np.int64), np.array(uv, float)


TUBE_SIDES = 8


def tube(points, widths, sides=TUBE_SIDES):
    """Tube around a polyline: (points, quads (F,4), normals per point) or None. Radius = half width per point;
    frame carried along (parallel transport), so the tube does not twist; open ends."""
    p = np.asarray(points, float)
    keep = np.concatenate([[True], np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-9])  # duplicate points out
    p, r = p[keep], np.asarray(widths, float)[keep] / 2
    if len(p) < 2:
        return None
    t = np.gradient(p, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    up = np.array([0.0, 1.0, 0.0]) if abs(t[0][1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    n = [np.cross(t[0], up)]
    n[0] /= np.linalg.norm(n[0])
    for k in range(1, len(p)):
        m = n[-1] - (n[-1] @ t[k]) * t[k]
        n.append(m / max(float(np.linalg.norm(m)), 1e-12))
    n = np.array(n)
    b = np.cross(t, n)
    ang = np.linspace(0, 2 * np.pi, sides, endpoint=False)
    dirs = np.cos(ang)[None, :, None] * n[:, None, :] + np.sin(ang)[None, :, None] * b[:, None, :]  # (N, s, 3)
    verts = (p[:, None, :] + r[:, None, None] * dirs).reshape(-1, 3)
    i = np.arange(len(p) - 1)[:, None] * sides
    j = np.arange(sides)[None, :]
    quads = np.stack([i + j, i + (j + 1) % sides, i + sides + (j + 1) % sides, i + sides + j], axis=-1).reshape(-1, 4)
    return verts, quads, dirs.reshape(-1, 3)


def corner_normals(pts, faces):
    """Normals per face corner (F, k, 3) – the same rule as in the viewport (renderer._corner_normals: averaged over up to 15°
    kink, split from 45°), quads as two triangles (0,1,2)+(0,2,3)."""
    from .renderer import _corner_normals
    pts = np.ascontiguousarray(pts, float)
    if faces.shape[1] == 3:
        return _corner_normals(pts, faces)[0]
    tris = np.concatenate([faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]])
    n = _corner_normals(pts, tris)[0]
    f = len(faces)
    a, b = n[:f], n[f:]
    out = np.stack([a[:, 0] + b[:, 0], a[:, 1], a[:, 2] + b[:, 1], b[:, 2]], axis=1)
    return out / np.maximum(np.linalg.norm(out, axis=2, keepdims=True), 1e-18)


def _apply_ops(pts, faces, uv, normals, ops):
    """Copy of a generator: quads stay quads (mirroring reverses the winding), unless the surface extends beyond
    a cut plane – then cut exactly as in the display (triangles, normals new)."""
    for op in ops:
        if op[0] == "clip" and np.any((pts - op[2]) @ op[1] < -generators.CLIP_EPS):
            tris = faces if faces.shape[1] == 3 else np.concatenate([faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]])
            v, t = generators.apply_mesh(pts, tris, ops)
            return v, t, np.zeros((len(t), 3, 2)), corner_normals(v, t)
    m = generators.matrix_of(ops)
    pts = generators.transform_points(pts, m)
    normals = normals @ np.linalg.inv(m[:3, :3])  # inverse transpose (row vectors)
    normals /= np.maximum(np.linalg.norm(normals, axis=2, keepdims=True), 1e-18)
    if generators.flips(ops):
        order = [0] + list(range(faces.shape[1] - 1, 0, -1))
        faces, uv, normals = faces[:, order], uv[:, order], normals[:, order]
    return pts, faces, uv, normals


def _per_point(faces, values, n_pts, tol):
    """Values per face corner (F, k, d) -> per point (N, d) if all corners of a point agree (smooth surface
    without seam: a quarter of the data), otherwise unchanged per corner. -> (values, USD interpolation)"""
    flat_idx, flat = faces.ravel(), values.reshape(len(faces) * faces.shape[1], -1)
    out = np.zeros((n_pts, flat.shape[1]))
    out[flat_idx] = flat
    if np.all(np.abs(out[flat_idx] - flat) <= tol):
        return out, "vertex"
    return flat, "faceVarying"


# --- Writing --------------------------------------------------------------------------------------------

def _name(prefix, name):
    clean = re.sub(r"[^A-Za-z0-9_]", "_", str(name).translate(_TRANSLIT)).strip("_")
    clean = re.sub(r"_+", "_", clean)[:48]
    return f"{prefix}_{clean}" if clean else prefix


def _str(s):
    import json
    return json.dumps(str(s), ensure_ascii=False)


def _f3(arr):
    return "[" + ", ".join(f"({a:.6g}, {b:.6g}, {c:.6g})" for a, b, c in np.asarray(arr, float).reshape(-1, 3)) + "]"


def _f2(arr):
    return "[" + ", ".join(f"({a:.5g}, {b:.5g})" for a, b in np.asarray(arr, float).reshape(-1, 2)) + "]"


def _fl(arr):
    return "[" + ", ".join(f"{x:.4g}" for x in np.asarray(arr, float).ravel()) + "]"


def _ints(arr):
    return "[" + ", ".join(str(int(x)) for x in np.asarray(arr).ravel()) + "]"


def _matrix(m):
    """4x4 (column vectors) -> USD matrix4d (row vectors, also transposed)."""
    return "(" + ", ".join("(" + ", ".join(f"{float(x):.9g}" for x in row) + ")" for row in np.asarray(m).T) + ")"


def _source_frame(m):
    """Position of the referenced prim in its file (4x4, column vectors), including conversion to Y up and meters –
    on import it is already in the points (geometry._mesh_arrays), on the reference prim it has to go into the matrix.
    None: file or prim not readable (then embedded). Without prim (older scenes: whole file): the
    default prim."""
    from . import geometry
    try:
        stage, (to_y_up, meters, cache) = geometry._open_stage(m.path)
    except Exception:
        return None
    prim = stage.GetPrimAtPath(m.prim) if m.prim else stage.GetDefaultPrim()
    if not prim or not prim.IsValid():
        return None
    conv = np.eye(4)
    conv[:3, :3] = to_y_up * meters
    return conv @ np.asarray(cache.GetLocalToWorldTransform(prim), float).T


def _asset(path, out_dir):
    """Path to the referenced file relative to the USD file (other drive: absolute), with /."""
    try:
        rel = os.path.relpath(path, out_dir) if out_dir else path
    except ValueError:
        rel = path
    return rel.replace("\\", "/")


def _light_data(scene):
    """What the USD export needs from the brief (identifiers, hierarchy, notes) – without the full analysis (line groups,
    plane fits …), which costs many seconds on large scenes."""
    from . import brief
    vis, maps = brief.index(scene)
    ids = {**maps["sid"], **maps["fid"], **maps["mid"], **maps["hid"]}
    notes = []
    for n in scene.notes:
        items = n.board.get("items", [])
        notes.append({"id": maps["nid"][n.id], "title": n.title or "(untitled)",
                      "text": [it["text"] for it in items if it.get("kind") == "text"],
                      "images": [f"notes/{it['file']}" for it in items if it.get("kind") == "image"]})
    return {"_vis": vis, "_maps": maps, "notes": notes,
            "hierarchy": [brief._null_entry(scene, n, ids, maps["lid"]) for n in vis["nulls"]]}


class _Writer:
    def __init__(self, scene, data, out_dir, mult, image_root, tubes=False):
        self.tubes = tubes
        self.scene, self.out_dir, self.mult, self.images = scene, out_dir, mult, image_root
        self.data = data if data is not None else _light_data(scene)
        self.vis = self.data["_vis"]
        maps = self.data["_maps"]
        self.lid, self.sid, self.fid, self.mid, self.hid = (maps[k] for k in ("lid", "sid", "fid", "mid", "hid"))
        self.copies = generators.copies_by_object(scene)
        self.focus = self.data.get("_focus") or set()  # focus on brief export: these prims carry sketch:focus
        self.refs = network.refs_by_pid(scene)
        self.out = []

    def write(self, path):
        o = self.out
        o += ["#usda 1.0", "(", '    defaultPrim = "sketch"', "    metersPerUnit = 1", '    upAxis = "Y"',
              '    doc = "Mule - scene as USD (sketch/usd_export.py). Ids as in the Sketch Brief; everything in '
              'world coordinates, symmetry/array resolved."', *timing_export.usd_header(self.scene), ")", "",
              'def Xform "sketch"', "{"]
        kids = self._children(None)
        self._block(kids, 1)
        self._notes(1)
        self._cameras(1)
        o += timing_export.usd_lines(self.scene, 1, self.scene.timing.interp)  # timing cameras
        o += ["}", ""]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(o))

    def _children(self, parent_id):
        vis = self.vis
        return ([n for n in vis["nulls"] if n.parent == parent_id or (parent_id is None and n.parent not in self.hid)]
                + [s for s in vis["strokes"] if s.parent == parent_id or (parent_id is None and s.parent not in self.hid)]
                + [f for f in vis["surfaces"] if f.parent == parent_id or (parent_id is None and f.parent not in self.hid)]
                + [m for m in vis["meshes"] if m.parent == parent_id or (parent_id is None and m.parent not in self.hid)])

    def _block(self, objs, depth):
        used = set()

        def unique(name):
            base, k = name, 2
            while name in used:
                name, k = f"{base}_{k}", k + 1
            used.add(name)
            return name
        for obj in objs:
            if obj.id in self.hid:
                self._null(obj, unique(_name(self.hid[obj.id], obj.name)), depth)
            elif obj.id in self.fid:
                for name, ops in self._instances(obj, unique):
                    self._surface(obj, name, ops, depth)
            elif obj.id in self.sid:
                for name, ops in self._instances(obj, unique):
                    self._stroke(obj, name, ops, depth)
            elif obj.id in self.mid:
                for name, ops in self._instances(obj, unique):
                    self._mesh(obj, name, ops, depth)

    def _instances(self, obj, unique):
        ids = {**self.sid, **self.fid, **self.mid}
        base = _name(ids[obj.id], obj.name)
        out, k = [], 0
        for _, ops in self.copies.get(obj.id, [((), ())]):
            if generators.is_original(ops):
                out.append((unique(base), ops))
            else:
                k += 1
                out.append((unique(f"{base}__copy{k}"), ops))  # "__" has no cleaned name
        return out

    def _null(self, n, name, depth):
        pad = "    " * depth
        self.out += [f'{pad}def Xform "{name}"', f"{pad}{{",
                     f"{pad}    custom string sketch:id = {_str(self.hid[n.id])}",
                     *([f"{pad}    custom bool sketch:focus = 1"] if n.id in self.focus else []),
                     f"{pad}    custom string sketch:name = {_str(n.name)}",
                     f"{pad}    custom string sketch:kind = {_str(n.kind)}",
                     f"{pad}    custom point3d sketch:origin = {tuple(round(float(x), 6) for x in n.origin)}",
                     f"{pad}    custom matrix3d sketch:axes = ({', '.join(str(tuple(round(float(x), 6) for x in row)) for row in n.axes.T)})"]
        if n.kind != "null":  # generator: factored out; its settings stand next to it for rebuilding
            h = next((x for x in self.data["hierarchy"] if x["id"] == self.hid[n.id]), {})
            self.out.append(f"{pad}    custom bool sketch:baked = {int(generators.is_on(n))}")
            if "mirror" in h:
                self.out += [f"{pad}    custom point3d sketch:mirror_origin = {tuple(h['mirror']['origin'])}",
                             f"{pad}    custom vector3d sketch:mirror_normal = {tuple(h['mirror']['normal_kept_side'])}"]
            if "array" in h:
                mats = ", ".join(_matrix(np.array(m, float)) for m in h["array"]["copy_matrices"])
                self.out.append(f"{pad}    custom matrix4d[] sketch:copies = [{mats}]")
        self._block(self._children(n.id), depth + 1)
        self.out.append(f"{pad}}}")

    def _surface(self, f, name, ops, depth):
        poly = surface_polymesh(f, self.mult)
        if poly is None:
            return
        pts, faces, uv = poly
        normals = corner_normals(pts, faces)
        if ops:
            pts, faces, uv, normals = _apply_ops(pts, faces, uv, normals, ops)
        pad = "    " * depth
        color = tuple(f.tint) if getattr(f, "tint", None) is not None else NEUTRAL
        kind = {"patch": "curve_surface"}.get(f.kind, f.kind)
        o = self.out
        nrm, nrm_mode = _per_point(faces, normals, len(pts), 1e-4)
        st, st_mode = _per_point(faces, uv, len(pts), 1e-6)
        o += [f'{pad}def Mesh "{name}"', f"{pad}{{",
              f"{pad}    int[] faceVertexCounts = {_ints(np.full(len(faces), faces.shape[1]))}",
              f"{pad}    int[] faceVertexIndices = {_ints(faces)}",
              f"{pad}    point3f[] points = {_f3(pts)}",
              f'{pad}    normal3f[] normals = {_f3(nrm)} (interpolation = "{nrm_mode}")',
              f'{pad}    texCoord2f[] primvars:st = {_f2(st)} (interpolation = "{st_mode}")',
              f'{pad}    uniform token subdivisionScheme = "none"',
              f'{pad}    uniform token orientation = "rightHanded"',
              f'{pad}    color3f[] primvars:displayColor = {_f3([color])} (interpolation = "constant")']
        if getattr(f, "opacity", 1.0) < 1.0:
            o.append(f'{pad}    float[] primvars:displayOpacity = [{float(f.opacity):.3g}] (interpolation = "constant")')
        o += [f'{pad}    string primvars:sketch_id = {_str(self.fid[f.id])} (interpolation = "constant")',
              *([f"{pad}    custom bool sketch:focus = 1"] if f.id in self.focus else []),
              f'{pad}    string primvars:sketch_name = {_str(f.name)} (interpolation = "constant")',
              f'{pad}    string primvars:sketch_kind = {_str(kind)} (interpolation = "constant")',
              f'{pad}    string primvars:sketch_material = {_str(getattr(f, "material", "papier"))} (interpolation = "constant")']
        if getattr(f, "aid", False):
            o.append(f'{pad}    token purpose = "guide"')  # helper surface: drawing aid only
        o.append(f"{pad}}}")

    def _stroke(self, st, name, ops, depth):
        from .brief import _point_attrs
        pad = "    " * depth
        o = self.out
        o += [f'{pad}def Xform "{name}"', f"{pad}{{",
              f"{pad}    custom string sketch:id = {_str(self.sid[st.id])}",
              *([f"{pad}    custom bool sketch:focus = 1"] if st.id in self.focus else []),
              f"{pad}    custom string sketch:name = {_str(st.name)}"]
        for c in st.curves:
            if c.id not in self.lid:
                continue
            pieces = generators.apply_polyline(c.points, ops, (c.widths,)) if ops else [(c.points, (c.widths,))]
            for k, (p, (w,)) in enumerate(pieces):
                if len(p) < 2:
                    continue
                cname = self.lid[c.id] + (f"_{k + 1}" if len(pieces) > 1 else "")
                o += [f'{pad}    def BasisCurves "{cname}"', f"{pad}    {{",
                      f'{pad}        uniform token type = "linear"',
                      f"{pad}        int[] curveVertexCounts = [{len(p)}]",
                      f"{pad}        point3f[] points = {_f3(p)}",
                      f'{pad}        float[] widths = {_fl(w)} (interpolation = "vertex")']
                if not ops:  # point attributes only on the original (copies: rotated/mirrored, orient would be wrong)
                    o += ["    " + line for line in _point_attrs(c, self.refs)]
                if c.style == "brush" and c.color is not None:
                    o += [f'{pad}        color3f[] primvars:displayColor = {_f3([c.color])} (interpolation = "constant")',
                          f'{pad}        string primvars:sketch_style = "brush" (interpolation = "constant")']
                if c.paint:
                    o += [f'{pad}        bool primvars:sketch_paint = 1 (interpolation = "constant")',
                          f'{pad}        int primvars:sketch_paint_order = {int(c.seq)} (interpolation = "constant")']
                o += [f'{pad}        string primvars:sketch_id = {_str(self.lid[c.id])} (interpolation = "constant")',
                      f"{pad}    }}"]
                if self.tubes:
                    self._tube(p, w, c, cname, pad + "    ")
        o.append(f"{pad}}}")

    def _tube(self, pts, widths, c, cname, pad):
        """Line additionally as a tube (polymesh): diameter = stroke width, color as the line."""
        mesh = tube(pts, widths)
        if mesh is None:
            return
        v, quads, normals = mesh
        color = tuple(c.color) if c.style == "brush" and c.color is not None else (0.23, 0.22, 0.21)
        self.out += [f'{pad}def Mesh "{cname}_tube"', f"{pad}{{",
                     f"{pad}    int[] faceVertexCounts = {_ints(np.full(len(quads), 4))}",
                     f"{pad}    int[] faceVertexIndices = {_ints(quads)}",
                     f"{pad}    point3f[] points = {_f3(v)}",
                     f'{pad}    normal3f[] normals = {_f3(normals)} (interpolation = "vertex")',
                     f'{pad}    uniform token subdivisionScheme = "none"',
                     f'{pad}    color3f[] primvars:displayColor = {_f3([color])} (interpolation = "constant")',
                     f'{pad}    string primvars:sketch_id = {_str(self.lid[c.id])} (interpolation = "constant")',
                     f"{pad}}}"]

    def _mesh(self, m, name, ops, depth):
        pad = "    " * depth
        world = generators.matrix_of(ops) @ m.xform if ops else m.xform
        o = self.out
        is_usd = os.path.splitext(m.path)[1].lower() in (".usd", ".usda", ".usdc", ".usdz")
        source = _source_frame(m) if is_usd else None
        if source is not None:  # referenced: the file stays where it is; our matrix replaces the prim's position
            world = world @ source
            target = f"@{_asset(m.path, self.out_dir)}@" + (f"<{m.prim}>" if m.prim else "")
            o += [f'{pad}def "{name}" (', f"{pad}    prepend references = {target}", f"{pad})", f"{pad}{{"]
        else:  # OBJ & co. (or the USD file is missing): embedded, points as imported, position as matrix
            v, t = m.geo.vertices, np.asarray(m.geo.faces).reshape(-1, 3)
            o += [f'{pad}def Mesh "{name}"', f"{pad}{{",
                  f"{pad}    int[] faceVertexCounts = {_ints(np.full(len(t), 3))}",
                  f"{pad}    int[] faceVertexIndices = {_ints(t)}",
                  f"{pad}    point3f[] points = {_f3(v)}",
                  f'{pad}    uniform token subdivisionScheme = "none"']
        o += [f"{pad}    matrix4d xformOp:transform = {_matrix(world)}",
              f'{pad}    uniform token[] xformOpOrder = ["xformOp:transform"]',
              f"{pad}    custom string sketch:id = {_str(self.mid[m.id])}",
              *([f"{pad}    custom bool sketch:focus = 1"] if m.id in self.focus else []),
              f"{pad}    custom string sketch:source = {_str(m.path)}"]
        if m.prim:
            o.append(f"{pad}    custom string sketch:prim = {_str(m.prim)}")
        o.append(f"{pad}}}")

    def _cameras(self, depth):
        """Hero cameras from the brief (data["cameras"]) as USD cameras – same view as views/hero_*.png."""
        cams = (self.data or {}).get("cameras") or []
        if not cams:
            return
        pad = "    " * depth
        o = self.out
        o += [f'{pad}def Scope "cameras"', f"{pad}{{"]
        for c in cams:
            eye, target, up = (np.array(c[k], float) for k in ("eye", "target", "up"))
            back = (eye - target) / max(float(np.linalg.norm(eye - target)), 1e-12)
            right = np.cross(up, back)
            right /= max(float(np.linalg.norm(right)), 1e-12)
            up = np.cross(back, right)
            rows = [(*right, 0.0), (*up, 0.0), (*back, 0.0), (*eye, 1.0)]  # USD: row vectors, camera looks along -Z
            vertical = 20.955 / c["aspect"]  # aperture in mm (horizontal as USD default)
            if c.get("orthographic_height"):  # orthographic: aperture in tenths of the scene unit
                vertical = c["orthographic_height"] * 10
            focal = vertical / 2 / math.tan(math.radians(c["fov_vertical_deg"]) / 2)
            o += [f'{pad}    def Camera "{c["id"]}"', f"{pad}    {{",
                  f"{pad}        matrix4d xformOp:transform = ({', '.join('(' + ', '.join(f'{x:.6g}' for x in r) + ')' for r in rows)})",
                  f'{pad}        uniform token[] xformOpOrder = ["xformOp:transform"]',
                  f"{pad}        float focalLength = {focal:.4f}",
                  f"{pad}        float horizontalAperture = {vertical * c['aspect']:.4f}",
                  f"{pad}        float verticalAperture = {vertical:.4f}",
                  *([f'{pad}        token projection = "orthographic"'] if c.get("orthographic_height") else []),
                  f'{pad}        string primvars:sketch_name = {_str(c["name"])} (interpolation = "constant")',
                  f'{pad}        string primvars:sketch_image = {_str(c["image"])} (interpolation = "constant")',
                  f"{pad}    }}"]
        o.append(f"{pad}}}")

    def _notes(self, depth):
        pad = "    " * depth
        o = self.out
        notes = [(n, e) for n, e in zip(self.scene.notes, self.data["notes"])]
        if not notes:
            return
        o += [f'{pad}def Scope "notes"', f"{pad}{{"]
        for n, entry in notes:
            lines = [self.lid[a.curve_id] for a in n.anchors if a.curve_id in self.lid]
            images = [i for i in entry["images"]] if self.images else []
            o += [f'{pad}    def Points "{entry["id"]}"', f"{pad}    {{",
                  f"{pad}        point3f[] points = {_f3([n.pos])}",
                  f'{pad}        string primvars:sketch_id = {_str(entry["id"])} (interpolation = "constant")',
                  f'{pad}        string primvars:sketch_title = {_str(entry["title"])} (interpolation = "constant")',
                  f'{pad}        string primvars:sketch_text = {_str(chr(10).join(entry["text"]))} (interpolation = "constant")',
                  f'{pad}        string[] primvars:sketch_images = [{", ".join(_str(i) for i in images)}] (interpolation = "constant")',
                  f'{pad}        string[] primvars:sketch_anchor_lines = [{", ".join(_str(x) for x in lines)}] (interpolation = "constant")',
                  f"{pad}    }}"]
            if n.anchors:
                segs = np.vstack([[n.pos, a.point] for a in n.anchors])
                o += [f'{pad}    def BasisCurves "{entry["id"]}_leaders"', f"{pad}    {{",
                      f'{pad}        uniform token type = "linear"',
                      f"{pad}        int[] curveVertexCounts = {_ints(np.full(len(n.anchors), 2))}",
                      f"{pad}        point3f[] points = {_f3(segs)}",
                      f'{pad}        string primvars:sketch_id = {_str(entry["id"])} (interpolation = "constant")',
                      f"{pad}    }}"]
        o.append(f"{pad}}}")


def write(scene, path, data=None, mult=DEFAULT_MULT, image_root=False, tubes=False):
    """Scene as USD to path (.usda: text; .usd/.usdc: binary, rewritten via usd-core). data: finished
    brief analysis (same identifiers), otherwise new; mult: resolution of the grid surfaces (1 = as in the viewport);
    image_root: note images lie next to it (brief folder) – then their paths are on the notes; tubes: lines
    additionally as tube meshes (L#_tube)."""
    out_dir = os.path.dirname(os.path.abspath(path))
    w = _Writer(scene, data, out_dir, mult, image_root, tubes)
    if os.path.splitext(path)[1].lower() == ".usda":
        w.write(path)
        return path
    tmp = os.path.splitext(path)[0] + ".tmp.usda"
    try:
        w.write(tmp)
        from pxr import Sdf
        layer = Sdf.Layer.FindOrOpen(tmp)
        layer.Export(path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path

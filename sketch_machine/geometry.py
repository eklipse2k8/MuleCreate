"""Geometry import: OBJ (trimesh) and USD (usd-core), triangles + optional colors only.

Everything is converted to Houdini convention: Y up, 1 unit = 1 meter.
"""
import os

import numpy as np
from .i18n import tr

DEFAULT_COLOR = np.array([0.64, 0.645, 0.66], dtype=np.float32)  # imported meshes without own color: medium gray – pencil readable, paper set off
Z_UP_TO_Y_UP = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)  # (x, y, z) -> (x, z, -y)


class Geometry:
    """Immutable mesh data. Not copied in the undo snapshot but shared."""

    def __init__(self, vertices, faces, colors=None, edges=None):
        self.vertices = np.ascontiguousarray(vertices, dtype=np.float32)  # (N, 3)
        self.faces = np.ascontiguousarray(faces, dtype=np.int32)  # (M, 3)
        # edges for the wireframe (E, 2): the polygon edges of the file; None = derived from the triangles on first need
        self._edges = None if edges is None else np.ascontiguousarray(edges, dtype=np.int32)
        if colors is None:
            colors = np.broadcast_to(DEFAULT_COLOR, self.vertices.shape)
        self.colors = np.ascontiguousarray(colors, dtype=np.float32)  # (N, 3)
        if len(self.vertices):
            self.bbox = (self.vertices.min(axis=0).astype(float), self.vertices.max(axis=0).astype(float))
        else:
            self.bbox = (np.zeros(3), np.zeros(3))

    @property
    def triangle_count(self):
        return len(self.faces)

    def normals_near(self, points):
        """Normal (unit vector, local) at the nearest point of the mesh for each of the points – area-weighted per
        mesh point, cached. Direction as the triangles are wound (the caller checks the sign)."""
        from scipy.spatial import cKDTree
        if getattr(self, "_near", None) is None:
            v = self.vertices.astype(np.float64)
            f = self.faces
            fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
            vn = np.zeros_like(v)
            for k in range(3):
                np.add.at(vn, f[:, k], fn)
            vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-30)
            self._near = (cKDTree(v), vn)
        tree, vn = self._near
        _, idx = tree.query(np.asarray(points, np.float64))
        return vn[idx]

    @property
    def edges(self):
        if self._edges is None:
            self._edges = feature_edges(self.vertices, self.faces)
        return self._edges

    def __deepcopy__(self, memo):
        return self


EMPTY = Geometry(np.zeros((0, 3)), np.zeros((0, 3)))


def _unique_edges(a, b):
    """Edges (a[i], b[i]) without duplicates and without direction -> (E, 2) int32."""
    lo, hi = np.minimum(a, b).astype(np.int64), np.maximum(a, b).astype(np.int64)
    n = int(hi.max(initial=0)) + 1
    keys = np.sort(lo * n + hi)  # sort instead of np.unique: its hash path is ~20x slower here (USD loading)
    keys = keys[np.concatenate([[True], keys[1:] != keys[:-1]])] if len(keys) else keys
    return np.stack([keys // n, keys % n], axis=1).astype(np.int32)


def polygon_edges(counts, indices):
    """Edges of the polygons (counts, flat indices) in corner positions of the flat array: (corner, next corner)."""
    counts = np.asarray(counts, dtype=np.int64)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    valid = counts >= 3
    counts, starts = counts[valid], starts[valid]
    pos = np.repeat(starts, counts) + (np.arange(int(counts.sum())) - np.repeat(np.cumsum(counts) - counts, counts))
    nxt = pos + 1
    last = np.cumsum(counts) - 1  # last corner of each polygon -> back to the first
    nxt[last] = starts
    return pos, nxt


def feature_edges(vertices, faces):
    """Wireframe without polygon info (OBJ): triangle edges, except between two triangles of the same plane
    (diagonals of quads and flat surfaces are dropped)."""
    faces = np.asarray(faces, dtype=np.int64)
    if not len(faces):
        return np.zeros((0, 2), np.int32)
    v = np.asarray(vertices, dtype=np.float64)
    n = np.cross(v[faces[:, 1]] - v[faces[:, 0]], v[faces[:, 2]] - v[faces[:, 0]])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    a = faces[:, [0, 1, 2]].reshape(-1)
    b = faces[:, [1, 2, 0]].reshape(-1)
    tri = np.repeat(np.arange(len(faces)), 3)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    key = lo * (len(v) + 1) + hi
    order = np.argsort(key, kind="stable")
    key, tri = key[order], tri[order]
    first = np.concatenate([[True], key[1:] != key[:-1]])
    group = np.cumsum(first) - 1
    counts = np.bincount(group)
    keep = counts != 2  # border or more than two triangles: always
    pair = np.flatnonzero(~first)  # second triangle of an edge
    two = group[pair][counts[group[pair]] == 2]
    other = pair[counts[group[pair]] == 2]
    flat = np.abs(np.einsum("ij,ij->i", n[tri[other - 1]], n[tri[other]])) > 0.9999
    keep[two[~flat]] = True
    keys = key[first][keep]
    m = len(v) + 1
    return np.stack([keys // m, keys % m], axis=1).astype(np.int32)


USD_EXT = (".usd", ".usda", ".usdc", ".usdz")


def load(path, prim=None):
    """Geometry of a file; prim: for USD only this mesh prim."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        return load_obj(path)
    if ext in USD_EXT:
        return load_usd(path, prim)
    raise ValueError(tr("Format nicht unterstützt: {0}").format(ext))


# --- OBJ -------------------------------------------------------------------
def load_obj(path):
    import trimesh

    try:
        mesh = trimesh.load(path, force="mesh", process=False, skip_materials=True)
    except TypeError:  # older trimesh versions do not know skip_materials
        mesh = trimesh.load(path, force="mesh", process=False)
    if mesh.is_empty:
        raise ValueError(tr("Die OBJ-Datei enthält keine Flächen."))
    colors = None
    visual = getattr(mesh, "visual", None)
    if visual is not None and getattr(visual, "kind", None) == "vertex":
        colors = np.asarray(visual.vertex_colors)[:, :3] / 255.0
    return Geometry(mesh.vertices, mesh.faces, colors)


# --- USD -------------------------------------------------------------------
def _fan_triangulate(counts, indices):
    """Polygons (counts, flat indices) -> triangles (M, 3) and origin index per triangle corner."""
    counts = np.asarray(counts, dtype=np.int64)
    valid = counts >= 3
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    counts, starts = counts[valid], starts[valid]
    tris_per_face = counts - 2
    face_of_tri = np.repeat(np.arange(len(counts)), tris_per_face)
    first_tri = np.concatenate([[0], np.cumsum(tris_per_face)[:-1]])
    k = np.arange(len(face_of_tri)) - np.repeat(first_tri, tris_per_face) + 1  # 1 .. n-2
    s = starts[face_of_tri]
    corners = np.stack([s, s + k, s + k + 1], axis=1)  # positions in the flat index array
    valid_face_ids = np.flatnonzero(valid)[face_of_tri]
    return np.asarray(indices)[corners], corners, valid_face_ids


_STAGES = {}  # path -> (modification time, stage, frame): a file with many meshes is opened once
STAGE_CACHE_MAX = 4


def _open_stage(path):
    """(Stage, (to_y_up, meters, xform_cache)) – cached as long as the file does not change."""
    from pxr import Usd, UsdGeom

    path = os.path.abspath(path)
    mtime = os.path.getmtime(path)
    hit = _STAGES.get(path)
    if hit is not None and hit[0] == mtime:
        return hit[1], hit[2]
    stage = Usd.Stage.Open(path)
    if stage is None:
        raise ValueError(tr("USD-Datei konnte nicht geöffnet werden."))
    to_y_up = Z_UP_TO_Y_UP if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z else np.eye(3)
    # Without a value, centimeters apply per the USD specification. But many tools do not write the value
    # and mean meters (Houdini creates stages with 1 m per unit) -> only an explicitly set unit counts.
    authored = stage.HasAuthoredMetadata(UsdGeom.Tokens.metersPerUnit)
    meters = (UsdGeom.GetStageMetersPerUnit(stage) or 1.0) if authored else 1.0
    frame = (to_y_up, meters, UsdGeom.XformCache(Usd.TimeCode.Default()))
    while len(_STAGES) >= STAGE_CACHE_MAX:
        _STAGES.pop(next(iter(_STAGES)))
    _STAGES[path] = (mtime, stage, frame)
    return stage, frame


def _shown(prim):
    """Visible and meant for rendering (no guides/proxies)."""
    from pxr import UsdGeom

    img = UsdGeom.Imageable(prim)
    return img.ComputeVisibility() != UsdGeom.Tokens.invisible and img.ComputePurpose() not in (
        UsdGeom.Tokens.guide, UsdGeom.Tokens.proxy)


def _mesh_arrays(prim, frame):
    """(points, triangles, colors, edges) of a mesh prim in world (Y up, meters) – or None if empty."""
    from pxr import Usd, UsdGeom

    to_y_up, meters, xform_cache = frame
    mesh = UsdGeom.Mesh(prim)
    time = Usd.TimeCode.Default()
    points = mesh.GetPointsAttr().Get(time)
    if points is None:  # only time samples present
        time = Usd.TimeCode.EarliestTime()
        points = mesh.GetPointsAttr().Get(time)
    counts = mesh.GetFaceVertexCountsAttr().Get(time)
    indices = mesh.GetFaceVertexIndicesAttr().Get(time)
    if points is None or counts is None or indices is None or len(points) == 0:
        return None
    pts = np.asarray(points, dtype=np.float64)
    m = np.asarray(xform_cache.GetLocalToWorldTransform(prim), dtype=np.float64)  # row vector convention
    pts = pts @ m[:3, :3] + m[3, :3]
    pts = (pts @ to_y_up.T) * meters

    tris, corners, face_ids = _fan_triangulate(counts, indices)
    colors, per_corner = _display_colors(mesh, len(pts), len(indices), len(counts), corners, face_ids, time)
    pos, nxt = polygon_edges(counts, indices)  # wireframe: polygon edges, no triangle diagonals
    idx = np.asarray(indices, dtype=np.int64)
    if not per_corner:
        colors = colors if colors is not None else np.broadcast_to(DEFAULT_COLOR, pts.shape)
        return pts, tris, colors, _unique_edges(idx[pos], idx[nxt])
    flat = tris.reshape(-1)  # colors per corner -> decouple corners
    vertex_of_corner = np.zeros(len(idx), np.int64)  # corner -> one of its decoupled points
    vertex_of_corner[corners.reshape(-1)] = np.arange(len(flat))
    return pts[flat], np.arange(len(flat)).reshape(-1, 3), colors, \
        _unique_edges(vertex_of_corner[pos], vertex_of_corner[nxt])


def load_usd(path, prim=None):
    """All visible meshes of the file as one Geometry – or only the mesh prim prim (path, e.g. "/Glider/Seat")."""
    from pxr import Usd, UsdGeom

    stage, frame = _open_stage(path)
    if prim is not None:
        p = stage.GetPrimAtPath(prim)
        if not p or not p.IsA(UsdGeom.Mesh):
            raise ValueError(tr("Prim {0} fehlt in der USD-Datei.").format(prim))
        prims = [p]
    else:
        prims = [p for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
                 if p.IsA(UsdGeom.Mesh) and _shown(p)]
    all_v, all_f, all_c, all_e, offset = [], [], [], [], 0
    for p in prims:
        arrays = _mesh_arrays(p, frame)
        if arrays is None:
            continue
        v, f, c, e = arrays
        all_v.append(v)
        all_f.append(f + offset)
        all_c.append(c)
        all_e.append(e + offset)
        offset += len(v)
    if not all_v:
        if prim is not None:
            return EMPTY
        raise ValueError(tr("Die USD-Datei enthält keine sichtbaren Meshes."))
    return Geometry(np.vstack(all_v), np.vstack(all_f), np.vstack(all_c), np.vstack(all_e))


def usd_tree(path):
    """Structure of the file as in Solaris: [dict(path, name, kind "group"/"mesh", parent, origin, axes)] in
    traversal order – groups (Xform, Scope …) only if visible meshes lie below them. origin/axes: position
    of the prim in the world (Y up, meters; axes orthonormal) – the null's handle."""
    from pxr import Usd, UsdGeom

    stage, (to_y_up, meters, xform_cache) = _open_stage(path)
    meshes = [p for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
              if p.IsA(UsdGeom.Mesh) and _shown(p)]
    groups = set()
    for p in meshes:
        q = p.GetParent()
        while q and not q.IsPseudoRoot():
            groups.add(q.GetPath())
            q = q.GetParent()
    wanted = groups | {p.GetPath() for p in meshes}
    out = []
    for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if p.GetPath() not in wanted:
            continue
        m = np.asarray(xform_cache.GetLocalToWorldTransform(p), dtype=np.float64)
        origin = (m[3, :3] @ to_y_up.T) * meters
        rot = to_y_up @ m[:3, :3].T  # columns: local axes in world (Y up)
        u, _, vt = np.linalg.svd(rot)
        axes = u @ vt
        if np.linalg.det(axes) < 0:  # mirrored: use a right-handed frame as the handle
            axes[:, 2] *= -1
        parent = p.GetParent()
        out.append({"path": str(p.GetPath()), "name": p.GetName(), "kind": "mesh" if p.IsA(UsdGeom.Mesh) else "group",
                    "parent": None if parent.IsPseudoRoot() else str(parent.GetPath()), "origin": origin, "axes": axes})
    return out


def _display_colors(mesh, n_points, n_indices, n_faces, corners, face_ids, time):
    """(colors, per_corner): (n_points, 3) for vertex/constant, (n_tri*3, 3) per triangle corner
    for uniform/faceVarying, or (None, False) without displayColor."""
    from pxr import UsdGeom

    primvar = UsdGeom.PrimvarsAPI(mesh.GetPrim()).GetPrimvar("displayColor")
    if not primvar or not primvar.HasValue():
        return None, False
    values = primvar.ComputeFlattened(time)
    if values is None or len(values) == 0:
        return None, False
    values = np.asarray(values, dtype=np.float32)
    interp = primvar.GetInterpolation()
    if interp == UsdGeom.Tokens.constant or len(values) == 1:
        return np.broadcast_to(values[0], (n_points, 3)), False
    if interp in (UsdGeom.Tokens.vertex, UsdGeom.Tokens.varying) and len(values) == n_points:
        return values, False
    if interp == UsdGeom.Tokens.uniform and len(values) == n_faces:
        return np.repeat(values[face_ids], 3, axis=0), True
    if interp == UsdGeom.Tokens.faceVarying and len(values) == n_indices:
        return values[corners.reshape(-1)], True
    return None, False

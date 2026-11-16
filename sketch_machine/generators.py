"""Generators (symmetry, array): instances of the objects below them – display and export only, until converted.

Only the children and the generator's settings are stored. What it produces is a list of copies;
each copy is a sequence of operations on the world geometry of a child:
  ("clip", n, o)  cut off everything on the side n·(x-o) < 0 (symmetry: the mirror side)
  ("xform", M)    apply 4x4 matrix (mirroring, array copy)
Nested (symmetry in array, array in array ...) the sequences are chained: first those of the inner
generator, then those of the outer – so each generator acts on the finished result of the generators below it.

A sequence without "xform" is the original itself (for symmetry: cut at the plane); it keeps its id.
Every other copy gets its own fixed display id (vid) – for the coverage map: lines belong to the copy
of their surface that has the same sequence.
"""
import itertools

import numpy as np

from .scene import SYMMETRY_PLANES, NullObject

CLIP_EPS = 1e-7  # this close to the mirror plane a point counts as on it (stays)
_vid_counter = itertools.count(8_000_000)  # display ids of the copies: separate from the object ids, exact as float32
_VIDS = {}


def mirror_plane(null):
    """(Normal, point) of the mirror plane of a symmetry in world coordinates; the normal points to the kept side."""
    n = null.axes[:, SYMMETRY_PLANES.get(null.params.get("plane", "zy"), 0)].astype(float)
    n = n / max(float(np.linalg.norm(n)), 1e-12)
    return n * (1.0 if null.params.get("side", 1) >= 0 else -1.0), null.origin.astype(float)


def reflection(n, o):
    """4x4 reflection at the plane through o with normal n."""
    m = np.eye(4)
    m[:3, :3] -= 2.0 * np.outer(n, n)
    m[:3, 3] = 2.0 * (o @ n) * n
    return m


# --- Copies of a generator ---
def is_on(null):
    """Generator switched on (outliner switch)? Off: it cuts and multiplies nothing, its content stays as it
    is – like a plain null."""
    return bool(null.params.get("on", True))


def generator_copies(scene, null):
    """[(key, operations)] of a generator – the first copy is always the original (without xform)."""
    if not is_on(null):
        return [((null.id, 0), ())]
    if null.kind == "symmetry":
        n, o = mirror_plane(null)
        clip = ("clip", n, o)
        return [((null.id, 0), (clip,)), ((null.id, 1), (clip, ("xform", reflection(n, o))))]
    if null.kind == "array":
        from . import arrays
        mats = arrays.matrices(scene, null)
        return [((null.id, 0), ())] + [((null.id, k), (("xform", m),)) for k, m in enumerate(mats[1:], start=1)]
    return [((null.id, 0), ())]


def copies_by_object(scene):
    """{id of an object: [(key, operations)]} for all objects under at least one generator (strokes,
    surfaces, meshes). If an object is missing, it is drawn as it is. Hidden generators produce nothing –
    they are hidden together with everything below."""
    gens = {}
    out = {}
    for obj in scene.strokes + scene.surfaces + scene.meshes:
        chain = [n for n in scene.ancestors(obj) if n.kind != "null"]
        if not chain:
            continue
        seqs = [((), ())]
        for null in chain:  # the inner generator first
            if null.id not in gens:
                gens[null.id] = generator_copies(scene, null)
            seqs = [(key + (gk,), ops + gops) for key, ops in seqs for gk, gops in gens[null.id]]
        out[obj.id] = seqs
    return out


def is_original(ops):
    return not any(op[0] == "xform" for op in ops)


def vid(oid, key):
    """Fixed display id of the copy key of the object oid (the original keeps its id)."""
    k = (oid, key)
    if k not in _VIDS:
        _VIDS[k] = next(_vid_counter)
    return _VIDS[k]


def vid_owner(v):
    """id of the object whose copy has the display id v (None: no known copy)."""
    return next((oid for (oid, _), x in _VIDS.items() if x == v), None)


def ops_key(ops):
    """Hashable fingerprint of an operation sequence (for caches)."""
    parts = []
    for op in ops:
        parts.append(op[0])
        for a in op[1:]:
            parts.append(np.round(np.asarray(a, float), 9).tobytes())
    return tuple(parts)


def matrix_of(ops):
    """Total matrix of the xform steps (cuts do not change position)."""
    m = np.eye(4)
    for op in ops:
        if op[0] == "xform":
            m = op[1] @ m
    return m


def flips(ops):
    """Does the sequence reverse the orientation (odd number of mirrorings)?"""
    return float(np.linalg.det(matrix_of(ops)[:3, :3])) < 0


# --- Geometry: polylines ---
def clip_polyline(points, n, o, extra=()):
    """Cut a polyline at the plane, n·(x-o) >= 0 is kept. extra: further arrays per point (widths,
    normals) that are interpolated too. Returns [(points, extras)] of the kept pieces (at least 2 points)."""
    pts = np.asarray(points, float)
    if len(pts) < 2:
        return []
    d = (pts - o) @ n
    if np.all(d >= -CLIP_EPS):
        return [(pts, tuple(extra))]
    if np.all(d <= CLIP_EPS):
        return []
    pieces, cur = [], None

    def at(i, j, t):
        return pts[i] + (pts[j] - pts[i]) * t, tuple(np.asarray(e)[i] + (np.asarray(e)[j] - np.asarray(e)[i]) * t
                                                     for e in extra)

    def start():
        return [[], [[] for _ in extra]]

    def push(piece, p, ex):
        piece[0].append(p)
        for lst, v in zip(piece[1], ex):
            lst.append(v)

    inside = d >= -CLIP_EPS
    for i in range(len(pts)):
        if inside[i]:
            if cur is None:
                cur = start()
                if i > 0:  # coming in from outside: intersection point first
                    t = d[i - 1] / (d[i - 1] - d[i])
                    push(cur, *at(i - 1, i, t))
            push(cur, pts[i], tuple(np.asarray(e)[i] for e in extra))
        elif cur is not None:  # going out: intersection point, piece finished
            t = d[i - 1] / (d[i - 1] - d[i])
            push(cur, *at(i - 1, i, t))
            pieces.append(cur)
            cur = None
    if cur is not None:
        pieces.append(cur)
    out = []
    for p, ex in pieces:
        p = np.array(p)
        if len(p) < 2:
            continue
        keep = np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-12]  # cut exactly on a point
        p = p[keep]
        if len(p) >= 2:
            out.append((p, tuple(np.array(e)[keep] for e in ex)))
    return out


def transform_points(points, m):
    return np.asarray(points, float) @ m[:3, :3].T + m[:3, 3]


def apply_polyline(points, ops, extra=(), normal_slots=()):
    """Operations on a polyline: [(points, extras)]. normal_slots: indices of the extras that are directions
    (normals – rotate/mirror along, without offset)."""
    pieces = [(np.asarray(points, float), tuple(extra))]
    for op in ops:
        if op[0] == "clip":
            pieces = [q for p, ex in pieces for q in clip_polyline(p, op[1], op[2], ex)]
        else:
            m = op[1]
            pieces = [(transform_points(p, m), tuple(e @ m[:3, :3].T if k in normal_slots else e
                                                     for k, e in enumerate(ex))) for p, ex in pieces]
    return pieces


# --- Geometry: triangle meshes ---
def clip_mesh(verts, tris, n, o):
    """Cut a triangle mesh at the plane (kept: n·(x-o) >= 0). New points on split edges are shared by
    both triangles – the mesh stays connected, the cut border lies exactly on the plane."""
    verts = np.asarray(verts, float)
    tris = np.asarray(tris, np.int64).reshape(-1, 3)
    if not len(tris):
        return verts, tris
    d = (verts - o) @ n
    inside = d >= -CLIP_EPS
    tin = inside[tris]
    full = tris[tin.all(axis=1)]
    mixed = tris[tin.any(axis=1) & ~tin.all(axis=1)]
    if not len(mixed) and len(full) == len(tris):
        return verts, tris
    new_pts, edge_index = [], {}

    def cut(a, b):
        key = (a, b) if a < b else (b, a)
        if key not in edge_index:
            t = d[a] / (d[a] - d[b])
            edge_index[key] = len(verts) + len(new_pts)
            new_pts.append(verts[a] + (verts[b] - verts[a]) * t)
        return edge_index[key]

    extra = []
    for tri in mixed:
        poly = []
        for k in range(3):  # Sutherland-Hodgman at one plane, winding order stays
            a, b = int(tri[k]), int(tri[(k + 1) % 3])
            if inside[a]:
                poly.append(a)
            if inside[a] != inside[b]:
                poly.append(cut(a, b))
        for k in range(1, len(poly) - 1):
            extra.append((poly[0], poly[k], poly[k + 1]))
    all_verts = np.vstack([verts] + ([np.array(new_pts)] if new_pts else []))
    all_tris = np.vstack([full] + ([np.array(extra, np.int64)] if extra else [])) if len(full) or extra \
        else np.zeros((0, 3), np.int64)
    used = np.unique(all_tris)  # keep only used points (smaller, bounds are correct)
    remap = np.full(len(all_verts), -1, np.int64)
    remap[used] = np.arange(len(used))
    return all_verts[used], remap[all_tris]


def apply_mesh(verts, tris, ops):
    """Operations on a triangle mesh; when mirrored the winding order is reversed (normals point correctly)."""
    v, t = np.asarray(verts, float), np.asarray(tris).reshape(-1, 3)
    for op in ops:
        if op[0] == "clip":
            v, t = clip_mesh(v, t, op[1], op[2])
        else:
            v = transform_points(v, op[1])
            if float(np.linalg.det(op[1][:3, :3])) < 0:
                t = t[:, [0, 2, 1]]
    return v, t


class LRU:
    """Cache: same input (identity of the arrays + operations) -> same output objects, so that the
    renderer can reuse its buffers. Holds on to the input (so its id stays unique). When it is full,
    the least recently used entry drops out – never everything at once (otherwise with large scenes every
    frame would be recomputed and uploaded in full)."""

    def __init__(self, size=50000):
        from collections import OrderedDict
        self.size, self.data = size, OrderedDict()

    def get(self, sources, key, make):
        k = tuple(id(s) for s in sources) + (key,)
        hit = self.data.get(k)
        if hit is not None and all(a is b for a, b in zip(hit[0], sources)):
            self.data.move_to_end(k)
            return hit[1]
        value = make()
        self.data[k] = (tuple(sources), value)
        while len(self.data) > self.size:
            self.data.popitem(last=False)
        return value


def descendants_of_generator(scene, null):
    return [o for o in scene.descendants(null) if not isinstance(o, NullObject)]

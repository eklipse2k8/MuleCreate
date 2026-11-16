"""Array generator: where the copies go (4x4 matrices per copy, world coordinates).

The original always stays where and as it is – it is edited as usual; the copies follow.
  radial  number of copies around the null's Y axis (through its origin) over the angle (360°: evenly all around)
  linear  each copy further by the offset (in the null's axes)
  line    copies evenly along a line (arc length): the null is mapped onto each point of the line –
          x = direction of travel, y = up (towards the up line, or the null's y axis carried along), z = across. If the null lies at
          the start of the line, the original is the first copy (it is dropped then, since it would lie exactly on it).
For each following copy (around the center of the content, in the copy's axes):
  spin      rotation around up per copy (copy k: k × spin)
  rand_rot  0..1 random rotation (up to ±180°) around the enabled axes (rot_axes)
  rand_off  0..1 random offset (up to ± size of the content) along the enabled axes (off_axes)
The randomness depends on seed and the copy number: more copies do not reshuffle the existing ones.
"""
import numpy as np

from .scene import MeshObject, NullObject, StrokeObject

IDENTITY_TOL = 1e-6


def _rot(axis, angle):
    axis = np.asarray(axis, float)
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
    x, y, z = axis
    c, s = np.cos(angle), np.sin(angle)
    k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + s * k + (1 - c) * (k @ k)


def _about(r3, pivot):
    m = np.eye(4)
    m[:3, :3] = r3
    m[:3, 3] = pivot - r3 @ pivot
    return m


def _shift(v):
    m = np.eye(4)
    m[:3, 3] = v
    return m


_BOX_CACHE = {}  # id(object) -> (object, arrays, box)


def content_box(scene, null):
    """(min, max) of the geometry under the generator (lines, surface outlines, meshes); None if empty."""
    boxes = []
    for o in scene.descendants(null):
        if isinstance(o, NullObject):
            continue
        if isinstance(o, MeshObject):
            if not o.missing:
                boxes.append(np.array(o.bounds()))
        elif isinstance(o, StrokeObject):
            boxes.append(_object_box(o))
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    allb = np.vstack(boxes)
    return allb.min(axis=0), allb.max(axis=0)


def _object_box(o):
    """(2, 3) box of the lines or grid rows of an object; asked per frame (mirror plane), surfaces bring thousands
    of grid rows: remembered as long as the same arrays (points are never changed in place but replaced
    – as in network.sync). If a surface changes, only it is measured again."""
    pts = [c.points for c in o.curves if len(c.points)]
    if not pts:
        return None
    cached = _BOX_CACHE.get(id(o))
    if cached is not None and cached[0] is o and len(cached[1]) == len(pts) and all(a is b for a, b in zip(cached[1], pts)):
        return cached[2]
    allp = np.vstack(pts)
    box = np.array([allp.min(axis=0), allp.max(axis=0)])
    if len(_BOX_CACHE) > 4096:
        _BOX_CACHE.pop(next(iter(_BOX_CACHE)))
    _BOX_CACHE[id(o)] = (o, pts, box)
    return box


def path_points(scene, cid):
    """Points of line cid (split line: its pieces joined together) or None."""
    if cid is None:
        return None
    ids = scene.split_pieces(cid) or [cid]
    parts = [scene.curve_by_id(i) for i in ids]
    parts = [c.points for c in parts if c is not None and len(c.points) >= 2]
    if not parts:
        return None
    pts = [parts[0]]
    for p in parts[1:]:  # append pieces in direction of travel (shared point only once)
        if np.linalg.norm(p[-1] - pts[-1][-1]) < np.linalg.norm(p[0] - pts[-1][-1]):
            p = p[::-1]
        pts.append(p[1:] if np.linalg.norm(p[0] - pts[-1][-1]) < 1e-9 else p)
    return np.vstack(pts)


def _sample(pts, fractions):
    """Points and tangents of the polyline at fractions of the arc length."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    total = max(float(arc[-1]), 1e-12)
    out_p, out_t = [], []
    for f in fractions:
        s = min(max(float(f), 0.0), 1.0) * total
        i = int(np.clip(np.searchsorted(arc, s, side="right") - 1, 0, len(seg) - 1))
        t = (s - arc[i]) / max(seg[i], 1e-12)
        out_p.append(pts[i] + (pts[i + 1] - pts[i]) * t)
        # tangent: over a small window (smooth at knots of the polyline)
        a = pts[max(i - 1, 0)] if t < 0.5 else pts[i]
        b = pts[min(i + 2, len(pts) - 1)] if t >= 0.5 else pts[i + 1]
        d = b - a
        out_t.append(d / max(float(np.linalg.norm(d)), 1e-12))
    return np.array(out_p), np.array(out_t)


def _perp(v, ref):
    """ref made perpendicular to v (normalized); failing that, any perpendicular."""
    u = ref - v * float(ref @ v)
    if np.linalg.norm(u) < 1e-6:
        alt = np.eye(3)[int(np.argmin(np.abs(v)))]
        u = alt - v * float(alt @ v)
    return u / np.linalg.norm(u)


def _line_frames(scene, null, count):
    """Frames (4x4: local -> world) of the copies along the line, or [] without a valid line."""
    pts = path_points(scene, null.params.get("path"))
    if pts is None or count < 1:
        return []
    closed = np.linalg.norm(pts[0] - pts[-1]) < 1e-6 * max(1.0, float(np.ptp(pts, axis=0).max()))
    fr = [k / count for k in range(count)] if closed else \
        ([0.0] if count == 1 else [k / (count - 1) for k in range(count)])
    p, t = _sample(pts, fr)
    up_pts = path_points(scene, null.params.get("up"))
    frames = []
    up_prev = null.axes[:, 1].astype(float)
    if up_pts is not None:
        q, _ = _sample(up_pts, fr)
    for k in range(len(fr)):
        if up_pts is not None:
            u = _perp(t[k], q[k] - p[k])
        else:  # carry up along (parallel transported): no flipping on the line
            u = _perp(t[k], up_prev)
        up_prev = u
        m = np.eye(4)
        m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = t[k], u, np.cross(t[k], u), p[k]
        frames.append(m)
    return frames


def matrices(scene, null):
    """Matrices of all copies; the first is the original (identity matrix), then the instances."""
    prm = null.params
    count = max(1, int(prm.get("count", 1)))
    mode = prm.get("mode", "radial")
    origin, axes = null.origin.astype(float), null.axes.astype(float)
    base = []  # (matrix, copy number for rotation/random)
    if mode == "linear":
        step = axes @ np.asarray(prm.get("offset", [1.0, 0, 0]), float)
        base = [(_shift(step * k), k) for k in range(1, count)]
    elif mode == "line":
        frame0 = null.frame()
        inv = np.linalg.inv(frame0)
        base = [(f @ inv, k) for k, f in enumerate(_line_frames(scene, null, count))]
    else:
        angle = np.radians(float(prm.get("angle", 360.0)))
        full = abs(abs(np.degrees(angle)) - 360.0) < 1e-6
        step = angle / count if full else (angle / (count - 1) if count > 1 else 0.0)
        base = [(_about(_rot(axes[:, 1], step * k), origin), k) for k in range(1, count)]
    box = content_box(scene, null)
    center = (box[0] + box[1]) / 2 if box is not None else origin
    size = float(np.linalg.norm(box[1] - box[0])) if box is not None else 1.0
    size = size if size > 1e-9 else 1.0
    spin = np.radians(float(prm.get("spin", 0.0)))
    rr, ro = float(prm.get("rand_rot", 0.0)), float(prm.get("rand_off", 0.0))
    rot_on, off_on = list(prm.get("rot_axes", [True] * 3)), list(prm.get("off_axes", [True] * 3))
    seed = int(prm.get("seed", 1))
    out = [np.eye(4)]
    for m, k in base:
        c = transform(m, center)
        ax = m[:3, :3] @ axes  # axes of the copy
        ax = ax / np.maximum(np.linalg.norm(ax, axis=0), 1e-12)
        extra = np.eye(4)
        if spin and k:
            extra = _about(_rot(ax[:, 1], spin * k), c) @ extra
        if rr > 0 or ro > 0:
            rng = np.random.default_rng([seed, k])
            angles, offs = rng.uniform(-1, 1, 3), rng.uniform(-1, 1, 3)
            if rr > 0:
                r3 = np.eye(3)
                for i in range(3):
                    if rot_on[i]:
                        r3 = _rot(ax[:, i], angles[i] * np.pi * rr) @ r3
                extra = _about(r3, c) @ extra
            if ro > 0:
                extra = _shift(sum(ax[:, i] * offs[i] * ro * size for i in range(3) if off_on[i])) @ extra
        full_m = extra @ m
        if np.abs(full_m - np.eye(4)).max() < IDENTITY_TOL:
            continue  # would lie exactly on the original
        out.append(full_m)
    return out


def transform(m, p):
    return m[:3, :3] @ np.asarray(p, float) + m[:3, 3]

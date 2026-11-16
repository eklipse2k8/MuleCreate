"""Drawing surfaces that follow their outline: the outline is a "cage" of CAGE_POINTS points, everything on
the surface (painting, lines drawn on it) is attached to it via mean value
coordinates (Floater 2003).

- Rest cage (rest, 2D): the outline at link time, flat in its best-fit plane. Bound items store
  their position relative to it (uv in these 2D coordinates).
- If the outline deforms, the weights per cage point are determined from the rest pose and applied to the
  current cage (3D): smooth, also with indentations, without jumps.
- The cage is sampled separately per outline piece (line), with a fixed number of points per piece: this way
  the cage points stay on "their" line, even if one line becomes longer than the others.
"""
import numpy as np

from . import fill

CAGE_POINTS = 64


def resample(points, n):
    """Polyline -> n points evenly by arc length, from the start (incl.) up to before the end."""
    pts = np.asarray(points, float)
    if len(pts) < 2 or n < 1:
        return np.repeat(pts[:1], max(n, 0), axis=0)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    t = np.linspace(0, arc[-1], n, endpoint=False)
    return np.stack([np.interp(t, arc, pts[:, i]) for i in range(3)], axis=1)


def allocate(lengths, total=CAGE_POINTS):
    """Distribute cage points over the outline pieces: by length, at least 2 per piece."""
    lengths = np.maximum(np.asarray(lengths, float), 1e-9)
    raw = lengths / lengths.sum() * total
    counts = np.maximum(np.round(raw).astype(int), 2)
    return [int(c) for c in counts]


def build(pieces, counts):
    """Current cage (K, 3) from the outline pieces in running direction."""
    return np.vstack([resample(p, c) for p, c in zip(pieces, counts)])


def flat(points, frame=None):
    """3D -> 2D in the best-fit plane (frame = (center, u, v, normal), otherwise from the points)."""
    center, u, v, n = frame if frame is not None else fill.fit_plane(np.asarray(points, float))
    d = np.asarray(points, float) - center
    return np.stack([d @ u, d @ v], axis=1)


def weights(x, poly, block=4096):
    """Mean value coordinates of the points x (N, 2) with respect to the polygon poly (K, 2) -> (N, K), rows sum
    to 1. Also defined outside and for non-convex outlines (signed angles)."""
    x = np.asarray(x, float)
    poly = np.asarray(poly, float)
    out = np.zeros((len(x), len(poly)))
    for s in range(0, len(x), block):
        d = poly[None] - x[s:s + block, None]                       # (B, K, 2)
        r = np.linalg.norm(d, axis=2)
        nxt = np.roll(d, -1, axis=1)
        cross = d[..., 0] * nxt[..., 1] - d[..., 1] * nxt[..., 0]
        dot = np.einsum("bkj,bkj->bk", d, nxt)
        ang = np.clip(np.arctan2(cross, dot), -np.pi + 1e-6, np.pi - 1e-6)
        th = np.tan(ang / 2)
        w = (np.roll(th, 1, axis=1) + th) / np.maximum(r, 1e-12)
        hit = r < 1e-9                                              # exactly on a cage point
        rows = hit.any(axis=1)
        if rows.any():
            w[rows] = hit[rows].astype(float)
        sums = w.sum(axis=1, keepdims=True)
        out[s:s + block] = w / np.where(np.abs(sums) < 1e-12, 1.0, sums)
    return out


def bind(points, cage_now, rest):
    """Points (3D) on the surface -> rest pose (N, 2): weights in the current cage, applied to the rest cage."""
    frame = fill.fit_plane(cage_now)
    return weights(flat(points, frame), flat(cage_now, frame)) @ rest


def evaluate(uv, rest, cage_now):
    """Rest pose (N, 2) -> points (N, 3) in the current cage."""
    return weights(uv, rest) @ cage_now


def normal(cage_now, previous=None):
    """Normal of the current surface (best-fit plane of the cage), oriented the same as previous where possible."""
    n = fill.fit_plane(np.asarray(cage_now, float))[3]
    if previous is not None and float(np.mean(np.asarray(previous) @ n)) < 0:
        n = -n
    return n

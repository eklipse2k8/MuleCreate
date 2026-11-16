"""Cleanup (menu in edit mode): tidy-up functions for lines and surfaces.

Each function gets the lines it should act on (selection or - with "Global" - all), changes the scene directly and
returns how much it did. Undo step and notice are handled by the viewport.
"""
import numpy as np

from . import components

STRAIGHT_REL = 0.02  # A piece between two points counts as almost straight up to this deviation (fraction of the length)
TINY_REL = 0.002  # A line counts as tiny below this fraction of the scene size


def _length(pts):
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()) if len(pts) > 1 else 0.0


def scene_size(scene):
    pts = [c.points for c in scene.pickable_curves() if len(c.points)]
    return float(np.linalg.norm(np.ptp(np.vstack(pts), axis=0))) if pts else 1.0


def dissolve_inserted(curves):
    """Dissolve inserted points: inner nodes that are not a real corner (the line stays as it is)."""
    done = 0
    for c in curves:
        ks = components.knots(c)[1:-1]
        if not ks:
            continue
        corners = set(components.detect_corners(c.points))
        for k in ks:
            if k not in corners and components.dissolve(c, k):
                done += 1
    return done


def remove_duplicates(scene, curves, size):
    """Lines lying on another one (same shape, also reversed and with a different point count): the second one is
    removed, surfaces/lofts/notes follow the kept one via split_map (previously they came loose - harbor test 09.11.).
    Reversed lines in an ordered fill-surface outline stay (the outline would twist)."""
    from . import topology
    tol = 1e-4 * max(size, 1e-9)
    chosen = {id(c) for c in curves}
    seen, gone = [], []
    for st in scene.strokes:
        for c in st.curves:
            if id(c) not in chosen or len(c.points) < 2 or c.paint:
                continue
            keep = None
            for o in seen:
                ends = (np.linalg.norm(o.points[0] - c.points[0]) < tol and np.linalg.norm(o.points[-1] - c.points[-1]) < tol,
                        np.linalg.norm(o.points[0] - c.points[-1]) < tol and np.linalg.norm(o.points[-1] - c.points[0]) < tol)
                if any(ends) and topology.same_shape(o, c, tol):
                    if ends[0] or topology._only_unordered_refs(scene, c.id):
                        keep = o
                        break
            if keep is not None:
                gone.append((st, c, keep))
            else:
                seen.append(c)
    for st, c, keep in gone:
        st.curves.remove(c)
        scene.split_map[c.id] = [keep.id]
    return len(gone)


def remove_tiny(scene, curves, size):
    """Delete tiny lines and points (leftovers of misclicks)."""
    limit = TINY_REL * max(size, 1e-9)
    chosen = {id(c) for c in curves}
    gone = [(st, c) for st in scene.strokes for c in st.curves if id(c) in chosen and _length(c.points) < limit]
    for st, c in gone:
        st.curves.remove(c)
    return len(gone)


def remove_empty_strokes(scene, strokes):
    gone = [st for st in strokes if not st.curves and st in scene.strokes]
    for st in gone:
        scene.strokes.remove(st)
        if scene.active_stroke is st:
            scene.active_stroke = scene.strokes[-1] if scene.strokes else None
    return len(gone)


def straighten(curves):
    """Pull almost straight pieces between two points (corners, ends) exactly straight - freehand-drawn edges
    become clean, corners and the point count stay."""
    done = 0
    for c in curves:
        ks = components.knots(c)
        pts = c.points.copy()
        changed = False
        for a, b in zip(ks[:-1], ks[1:]):
            if b - a < 2:
                continue
            seg = pts[a:b + 1]
            chord = seg[-1] - seg[0]
            n = float(np.linalg.norm(chord))
            if n < 1e-12:
                continue
            u = chord / n
            rel = seg - seg[0]
            dev = float(np.linalg.norm(rel - np.outer(rel @ u, u), axis=1).max())
            if 1e-9 < dev <= STRAIGHT_REL * n:
                t = np.clip(rel @ u / n, 0, 1)
                t = np.maximum.accumulate(t)  # order stays
                pts[a:b + 1] = seg[0] + np.outer(t, chord)
                changed = True
                done += 1
        if changed:
            c.points = pts
    return done


def relink_surfaces(scene, surfaces):
    """Re-attach surfaces that lost their lines to the lines lying exactly on them: fill surfaces
    (gone rigid) to their outline, curve surfaces to missing border lines."""
    from .scene import PatchSurface, SurfaceObject
    done = 0
    for f in surfaces:
        if isinstance(f, PatchSurface):
            done += 1 if scene.relink_patch(f) else 0
            continue
        if type(f) is not SurfaceObject:
            continue
        if f.links and f.rest is not None and scene._fill_pieces(f) is not None:
            continue  # follows already
        f.links, f.rest = [], None
        if scene._relink_fill(f, min_cover=0.6):
            done += 1
    return done

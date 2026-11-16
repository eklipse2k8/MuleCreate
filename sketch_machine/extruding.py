"""Extrude on the scene (X): copy of the lines, connecting lines, side surfaces - and in surface mode the
surface itself, which moves up along.

Rules:
  - Lines: offset copy (same points, connected among themselves like the original) plus connecting lines along
    extrude.rail_points; original and copy are split at the connecting lines.
  - Points of the line (nodes: corners, inserted points, junctions): kink from RAIL_KNOT_DEG (5°) or another
    line joins there -> connecting line (artist 2026-11-09: what is drawn gets pulled along).
  - Side surfaces (default): created like a loft between original and copy. Split at hard points -
    each piece between two hard connecting lines is its own surface, so a box stays sharp-edged while
    soft connecting lines (roundings, flat kinks) only shape the surface. A smooth ring without a hard point becomes
    a tube. A node with a kink from HARD_KNOT_DEG (15°, measured at the point) is hard, otherwise - away from the nodes -
    a corner (kink from CORNER_DEG).
  - Extrude surface (surface mode): the surface moves along with its lines and its painting onto the copy of its
    outline; the original border lines stay below as a floor ring (neighboring surfaces stay attached to it). Side walls only at the
    border of the selected surfaces - no wall is created between two selected neighboring surfaces.
"""
import numpy as np

from . import components, extrude, network
from .scene import Curve, PatchSurface, SurfaceObject, _new_id, inherit, split_curve

RAIL_KNOT_DEG = 5.0  # nodes with a kink from here on get a connecting line (below: practically straight through)
HARD_KNOT_DEG = 15.0  # from here on a connecting line at the node is hard: the side surface is split there


def knot_marks(scene, walls):
    """Nodes of the wall lines: [(point, kink in degrees, does another line join?)]. The kink is measured at the point
    (components.pair_kink - a rounding does not fake one), between the wall lines themselves (junction of
    two selected lines = their kink); a free line end counts as 180°."""
    walls = [c for c in walls if len(c.points) >= 2]
    if not walls:
        return []
    index = components.KnotIndex(scene)
    ids = {c.id for c in walls}
    out = []
    for c in walls:
        for k in components.knots(c):
            refs = components._refs_at(c, k, index)
            mine = [(o, j) for o, j in refs if o.id in ids]
            others = any(o.id not in ids and not o.paint for o, _ in refs)
            pairs = components.pairs_at(mine)
            ring = extrude.is_closed(c.points)
            end = not pairs and not ring and k in (0, len(c.points) - 1)
            kink = 180.0 if end else max((components.pair_kink(p) for p in pairs), default=0.0)
            out.append((np.asarray(c.points[k], float).copy(), kink, others))
    return out


def knot_rails(marks):
    """Points that get a connecting line in any case (see knot_marks)."""
    return [p for p, kink, others in marks if kink >= RAIL_KNOT_DEG or others]



def face_outline(scene, surface):
    """Border lines of a surface (current pieces) or None (loft/tube: no own outline to extrude)."""
    if isinstance(surface, PatchSurface):
        return scene.patch_border(surface) or None
    if type(surface) is SurfaceObject and surface.links:
        out = []
        for cid, _ in surface.links:
            for i in scene.link_ids(cid):
                for sub in scene.split_pieces(i) or []:
                    c = scene.curve_by_id(sub)
                    if c is not None and not any(c is o for o in out):
                        out.append(c)
        return out or None
    return None


def _inner_lines(scene, surface, border):
    """Real lines on the surface (they shape it) - move along when extruding surfaces."""
    ids = {c.id for c in border}
    out = []
    for c in scene.curves:
        if c.paint or c.id in ids:
            continue
        if c.plane_id == surface.id or c.id in (getattr(surface, "attached", None) or {}):
            out.append(c)
    return out


def _clone(c, offset):
    copy = Curve(c.points + offset, None, c.widths.copy(), c.generated)
    inherit(copy, c)
    copy.knots = c.knots
    copy.pids = dict(c.pids) if c.pids else None
    return copy


def _split_at(pieces, cuts, tol):
    """Split lines at points (nodes and net points stay) -> new list, in running direction."""
    if pieces:  # only cuts in the line's bounding box (many surfaces: otherwise every copy against all cuts)
        pts = np.vstack([c.points for c in pieces])
        lo, hi = pts.min(axis=0) - tol, pts.max(axis=0) + tol
        cuts = [q for q in cuts if np.all(q >= lo) and np.all(q <= hi)]
    for cut in cuts:
        out = []
        for c in pieces:
            a, b = c.points[:-1], c.points[1:]
            ab = b - a
            t = np.clip(np.einsum("ij,ij->i", cut - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
            d = np.linalg.norm(a + ab * t[:, None] - cut, axis=1)
            i = int(np.argmin(d))
            parts = split_curve(c, np.asarray(cut, float), i, float(t[i])) if d[i] <= tol else None
            out += list(parts) if parts else [c]
        pieces = out
    return pieces


def _hard_at(index, chain, point, span):
    """Is the connecting line at point (on the chain) hard? The kink of the chain there decides (like the hardness)."""
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(chain, axis=0), axis=1))])
    i = int(np.argmin(np.linalg.norm(chain - point, axis=1)))
    s = arc[i]
    closed = extrude.is_closed(chain)
    total = arc[-1]

    def at(x):
        if closed:
            x %= total
        elif x < 0 or x > total:
            return None
        return np.array([np.interp(x, arc, chain[:, j]) for j in range(3)])
    before, after = at(s - span), at(s + span)
    if before is None or after is None:
        return True  # line end
    return extrude._angle(point - before, after - point) >= extrude.CORNER_DEG


def _pieces(chain, cuts):
    """Split chain at the points cuts (lying on it) into pieces -> [polyline]; piece ends are exactly the points."""
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(chain, axis=0), axis=1))])
    closed = extrude.is_closed(chain)
    pos = []
    for p in cuts:
        a, b = chain[:-1], chain[1:]
        ab = b - a
        t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
        i = int(np.argmin(np.linalg.norm(a + ab * t[:, None] - p, axis=1)))
        pos.append((arc[i] + t[i] * (arc[i + 1] - arc[i]), np.asarray(p, float)))
    pos.sort(key=lambda x: x[0])
    if not closed:
        pos = [(0.0, chain[0])] + [x for x in pos if 1e-9 < x[0] < arc[-1] - 1e-9] + [(arc[-1], chain[-1])]
        spans = list(zip(pos[:-1], pos[1:]))
    else:
        spans = [(pos[k], pos[(k + 1) % len(pos)]) for k in range(len(pos))]
    out = []
    for (s0, p0), (s1, p1) in spans:
        if s1 <= s0:  # ring: across the seam
            inner = [chain[j] for j in range(len(chain)) if arc[j] > s0 + 1e-12] + \
                    [chain[j] for j in range(1, len(chain)) if arc[j] < s1 - 1e-12]
        else:
            inner = [chain[j] for j in range(len(chain)) if s0 + 1e-12 < arc[j] < s1 - 1e-12]
        poly = np.vstack([p0, *inner, p1]) if inner else np.vstack([p0, p1])
        if len(poly) >= 2 and np.linalg.norm(np.diff(poly, axis=0), axis=1).sum() > 1e-9:
            out.append(poly)
    return out


def _hard_rail(marks, index, chain, r, span, tol):
    """Hard? If the connecting line lies on a node, its kink decides (from HARD_KNOT_DEG); otherwise as before
    the kink of the chain over a short span (corner from CORNER_DEG)."""
    near = [kink for p, kink, _ in marks if np.linalg.norm(p - r) <= max(tol * 10, 1e-9)]
    if near:
        return max(near) >= HARD_KNOT_DEG
    return _hard_at(index, chain, r, span)


def _side_surfaces(scene, chains, rails, offset, tol, style=None, marks=()):
    """Side surfaces per chain, split at hard connecting lines. Returns the new surfaces."""
    made = []
    index = components.KnotIndex(scene)
    for chain in chains:
        length = float(np.linalg.norm(np.diff(chain, axis=0), axis=1).sum())
        span = extrude.CORNER_SPAN * length
        on = [r for r in rails if _dist_to(chain, r) < max(tol * 10, 1e-9)]
        hard = [r for r in on if _hard_rail(marks, index, chain, r, span, tol)]
        closed = extrude.is_closed(chain)
        if closed and len(hard) < 2:
            parts = [chain]  # smooth ring: one tube
        else:
            parts = _pieces(chain, hard)
        for poly in parts:
            surface = scene.create_extrude_loft(poly, offset)
            if surface is None:
                continue
            if not surface.closed:
                surface = scene.loft_to_patch(surface) or surface
            if style is not None:
                surface.material, surface.tint, surface.opacity = style
            made.append(surface)
    return made


def _dist_to(chain, p):
    a, b = chain[:-1], chain[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    return float(np.min(np.linalg.norm(a + ab * t[:, None] - p, axis=1)))


def snap_rails(rails, curves):
    """Place connecting lines that lie just beside a point of the lines (corners are measured on the slightly smoothed line)
    exactly on that point - its hardness hangs there, and the line is not split beside the corner."""
    knots = []
    for c in curves:
        length = float(np.linalg.norm(np.diff(c.points, axis=0), axis=1).sum())
        knots += [(c.points[k], extrude.CORNER_SPAN * length) for k in components.knots(c)]
    out = []
    for r in rails:
        best = min(knots, key=lambda kn: np.linalg.norm(kn[0] - r), default=None)
        q = best[0] if best is not None and np.linalg.norm(best[0] - r) < best[1] else r
        if all(np.linalg.norm(q - o) > 1e-12 for o in out):
            out.append(np.asarray(q, float).copy())
    return out


def walls_of(scene, faces):
    """Border lines of the selected surfaces that belong to only one of them (side walls arise there)."""
    count = {}
    lines = {}
    for f in faces:
        for c in face_outline(scene, f) or []:
            count[c.id] = count.get(c.id, 0) + 1
            lines[c.id] = c
    return [lines[i] for i, n in count.items() if n == 1]


def apply(scene, curves, offset, rails, tol, faces=(), surfaces=True, view=None):
    """Perform the extrusion (after scene.checkpoint). curves: lines to copy (surface mode: all border lines of the
    surfaces); rails: points of the connecting lines. Returns [(stroke_id, line)] of the copy."""
    faces = list(faces)
    network.sync(scene)
    walls = walls_of(scene, faces) if faces else list(curves)
    marks = knot_marks(scene, walls)  # before moving the seam: nodes including kink (hard or soft)
    # Line mode: closed lines with the seam moved onto a connecting line (otherwise a surplus piece).
    # Surface borders stay as they are (the surface hangs on them).
    if not faces:
        for c in curves:
            if extrude.is_closed(c.points) and rails:
                on_c = min(rails, key=lambda r: float(np.min(np.linalg.norm(c.points - r, axis=1))))
                c.points, c.widths = extrude.reseat(c.points, c.widths, on_c)
                c.knots, c.pids = None, None
        network.sync(scene)
    chains = [pts.copy() for pts, _ in extrude.chains([c.points for c in walls], tol)]
    # Copies: same nodes; net points new, but connected within the copy (and with the surfaces'
    # moving-along lines) as in the original
    clones = {c.id: _clone(c, offset) for c in curves}
    inner = []
    for f in faces:
        for c in _inner_lines(scene, f, face_outline(scene, f) or []):
            if not any(c is o for o in inner):
                inner.append(c)
    for c in inner:
        c.translate(offset)
    network.fresh_ids(list(clones.values()) + inner)
    copy_pieces = {cid: _split_at([c], [r + offset for r in rails], tol) for cid, c in clones.items()}
    owner_of = {c.id: scene.owner_of(c) for c in curves}
    rail_owner = None
    out = []
    for c in curves:
        owner = owner_of[c.id] or scene.active_stroke or scene.new_stroke()
        rail_owner = rail_owner or owner
        for piece in copy_pieces[c.id]:
            owner.curves.append(piece)
            out.append((owner.id, piece))
    w = float(curves[0].widths.mean()) if curves else 0.02
    rail_owner = rail_owner or scene.active_stroke or scene.new_stroke()
    # Edges: stroke width of the profile where they attach (the copy on top has the same widths)
    rail_owner.curves += [Curve(np.array([p, p + offset]), None, np.full(2, components.width_near(curves, p, w)))
                          for p in rails]
    for f in faces:
        _move_face(scene, f, copy_pieces, inner, offset)
    scene.split_all_at_many(rails, tol)  # split originals at the connecting lines
    network.sync(scene)
    if surfaces:
        style = None
        if faces:
            style = (faces[0].material, faces[0].tint, faces[0].opacity)
        _side_surfaces(scene, chains, rails, offset, tol, style, marks)
    return out


def _move_face(scene, surface, copy_pieces, inner, offset):
    """Rehang surface onto the copy of its outline: border references point to the copies, the rest shape moves along.
    Lines and painting on it keep their position on the surface."""
    def copies_of(cid):
        out = []
        for sub in scene.split_pieces(cid) or []:
            out += [c.id for c in copy_pieces.get(sub, [])]
        return out
    if isinstance(surface, PatchSurface):
        new_lines = []
        for cid in surface.patch_lines:
            ids = copies_of(cid)
            if len(ids) == 1:
                new_lines.append(ids[0])
            else:  # several pieces: reference as a split line (split_pieces follows the chain)
                virtual = _new_id()
                scene.split_map[virtual] = ids
                new_lines.append(virtual)
        surface.patch_lines = new_lines
        for c in surface.curves:  # rest shape (Coons rows) moves along
            c.translate(offset)
        surface._patch_key = None
    elif type(surface) is SurfaceObject:
        links = []
        for cid, flipped in surface.links:
            if cid is None:
                links.append((None, flipped))
                continue
            ids = [x for i in scene.link_ids(cid) for x in copies_of(i)]
            links.append((ids if len(ids) > 1 else ids[0], flipped))
        surface.links = links
        for c in surface.curves:
            c.translate(offset)
    att = getattr(surface, "attached", None) or {}
    for c in inner:  # lines moved along: same position on the surface (do not rebind)
        a = att.get(c.id)
        if a is not None:
            a["last"] = c.points.tobytes()
            if a.get("pos") is not None:
                a["pos"] = c.points.copy()

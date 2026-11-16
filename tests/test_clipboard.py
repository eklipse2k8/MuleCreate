"""Copy and paste: pasted surfaces follow their pasted lines, the original stays untouched."""
import numpy as np

from tests.harness import H, Qt, line
from sketch_machine import edges
from sketch_machine.clipboard import Clipboard, paste


def _bend(c, h):  # raise the middle, ends stay (outline stays closed)
    c.points = c.points + np.outer(np.sin(np.linspace(0, np.pi, len(c.points))), [0.0, h, 0.0])


def _check(sc, surf, lines, move_index):
    clip = Clipboard()
    clip.copy(sc, [surf], [("line", sc.owner_of(c).id, c.id) for c in lines])
    objs, refs = paste(sc, clip, "elements")
    new_surf = next(o for o in objs if o.name.endswith("_copy"))
    new_lines = [edges.ref_to_curve(sc, r) for r in refs]
    sc.sync_lofts()
    orig, new = surf.fill_mesh()[0].copy(), new_surf.fill_mesh()[0].copy()
    _bend(new_lines[move_index], 0.7)
    sc.sync_lofts()
    # (the displayed net depends on the curvature: bent, it also has a different point count)
    same = lambda a, b: a.shape == b.shape and np.allclose(a, b)
    assert not same(new_surf.fill_mesh()[0], new), "pasted surface follows its pasted line"
    assert same(surf.fill_mesh()[0], orig), "original stays untouched"


def _square(sc):
    sc.new_stroke()
    P = [np.array(p, float) for p in ([0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2])]
    out = []
    for a, b in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(a, b, 10), None)
        out.append(sc.curves[-1])
    return out


def test_fill_surface(h: H):
    sc = h.sc
    lines = _square(sc)
    f = sc.create_fill([(c, False) for c in lines])
    sc.sync_lofts()
    _check(sc, f, lines, 1)


def test_loft_with_rails(h: H):
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 12)
    secs = []
    for z in (0.0, 1.0, 2.0):
        sc.add_curve(np.stack([t * 2, 0.4 * np.sin(t * np.pi), np.full_like(t, z)], axis=1), None)
        secs.append(sc.curves[-1])
    lo = sc.create_loft([("lines", [c.id]) for c in secs], [c.points for c in secs])
    sc.add_loft_rails(lo, np.array([0, 0, 1.0]))
    sc.sync_lofts()
    rails = [sc.curve_by_id(cid) for cid, _ in lo.rails]
    _check(sc, lo, secs + rails, 2)


def test_curve_patch(h: H):
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 12)
    sides = [np.stack([t * 2, 0.3 * np.sin(t * np.pi), t * 0], 1), np.stack([np.full_like(t, 2), 0.3 * np.sin(t * np.pi), t * 2], 1),
             np.stack([2 - t * 2, 0.3 * np.sin(t * np.pi), np.full_like(t, 2)], 1), np.stack([t * 0, 0.3 * np.sin(t * np.pi), 2 - t * 2], 1)]
    lines = []
    for s in sides:
        sc.add_curve(s, None)
        lines.append(sc.curves[-1])
    ps = sc.create_patch(lines)
    sc.sync_lofts()
    _check(sc, ps, lines, 1)


def test_copy_paste_in_the_program(h: H):
    sc = h.sc
    lines = _square(sc)
    for c in lines:
        c.plane_id = sc.planes[0].id
    f = sc.create_fill([(c, False) for c in lines])
    h.v._changed()
    h.camera([1, 0, 1], 6, [0.2, 0.9, 0.4])
    h.edit_mode("face")
    h.v.select_loop(h.scrf([1.0, 0.0, 1.0]), "replace")
    assert h.v.selection == [f.id] and len(h.v.edge_selection) == 4
    h.key(Qt.Key_C, Qt.ControlModifier)
    h.key(Qt.Key_V, Qt.ControlModifier)
    new = sc.surfaces[-1]
    originals = {c.id for c in lines}
    linked = [cid for cid, _ in new.links]
    assert len(sc.surfaces) == 2 and len(linked) == 4
    assert all(cid not in originals and h.sc.curve_by_id(cid) is not None for cid in linked)


def test_duplicate_lines_with_surfaces_own_object(h: H):
    """Ctrl+D with lines and surfaces (e.g. a whole wing): the copied lines go into a new stroke object
    next to the original (same group), not into the original object; copy moved -> original stays."""
    sc = h.sc
    lines = _square(sc)
    st = sc.owner_of(lines[0])
    h.v.edge_selection = [("line", st.id, c.id) for c in lines]
    h.v.do_patch()
    surf = sc.surfaces[-1]
    h.v._changed()
    h.edit_mode("edge")
    h.v.selection = [surf.id]
    h.v.edge_selection = [("line", st.id, c.id) for c in lines]
    before = {c.id: c.points.copy() for c in lines}
    h.v.duplicate("elements")
    new_st = {r[1] for r in h.v.edge_selection}
    assert len(new_st) == 1 and st.id not in new_st, "copied lines in a new object"
    assert len(st.curves) == 4, "original object keeps only its lines"
    h.v.transform_target.translate(np.array([0.0, 1.0, 0.0]))
    h.v._changed()
    assert all(np.allclose(c.points, before[c.id]) for c in lines), "original lines stay"

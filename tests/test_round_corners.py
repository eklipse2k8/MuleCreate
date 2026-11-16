"""Rounding (Ctrl+B) an outline corner of a fill surface: the surface follows the arc, as if a point had been inserted
and the line rounded by hand. Formerly the surface stayed with a sharp corner (outline counted as interrupted) and
then followed nothing at all - the arc lay next to its edge."""
import numpy as np
from PySide6.QtCore import Qt, QPointF

from tests.harness import H
from tests.test_loft import _size
from tests.test_picking import _z_fill, _bend
from sketch_machine.vp.snapping import _point_mesh_distance


def _bevel_corner(h: H, corner, px=60):
    """Select the corner in point mode, Ctrl+B, mouse px to the left, click. -> new lines"""
    before = {c.id for c in h.curves()}
    h.edit_mode("point")
    h.click(h.scr(corner))
    h.key(Qt.Key_B, Qt.ControlModifier)
    p0 = h.scrf(corner)
    h.move(QPointF(p0.x() - px, p0.y()))
    h.click(QPointF(p0.x() - px, p0.y()).toPoint())
    h.sc.sync_lofts()
    h.grab()
    return [c for c in h.curves() if c.id not in before]


def _check_follows(surf, arc, corner):
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    loop = surf.loop_points()
    assert min(np.linalg.norm(loop - corner, axis=1)) > 0.02 * size, "surface still has the sharp corner"
    on_rim = max(min(np.linalg.norm(loop - p, axis=1)) for p in arc.points)
    assert on_rim < 1e-6 * size, f"outline of the surface runs {on_rim:.3f} beside the arc"
    off = max(_point_mesh_distance(p, verts, tris) for p in arc.points) / size
    assert off < 0.01, f"arc {off:.1%} beside the surface"


def test_rounding_an_outline_corner(h: H):
    for bent in (False, True):
        surf, lines = _z_fill(h)
        if bent:
            _bend(h, lines)
        corner = lines[1].points[0].copy()  # (6, 0, 0): line 0 meets line 1
        new = _bevel_corner(h, corner)
        assert len(new) == 1, f"one arc expected, {len(new)} new lines"
        arc = new[0]
        _check_follows(surf, arc, corner)
        # the surface keeps following its outline (it is not frozen)
        before = surf.fill_mesh()[0].copy()
        c = lines[5]  # lower edge (6, 0, 6) -> (0, 0, 6)
        c.points = c.points.copy()
        c.points[:, 1] += 0.6 * np.sin(np.linspace(0, np.pi, len(c.points)))
        h.v._changed()
        h.sc.sync_lofts()
        verts = surf.fill_mesh()[0]
        assert verts.shape != before.shape or np.abs(verts - before).max() > 0.1, "surface no longer follows the outline"
        _check_follows(surf, arc, corner)
        # Ctrl+Z (first the selection, then the rounding): corner and surface as before
        h.key(Qt.Key_Z, Qt.ControlModifier)
        h.key(Qt.Key_Z, Qt.ControlModifier)
        h.sc.sync_lofts()
        h.v._changed()
        loop = h.sc.surfaces[0].loop_points()
        assert min(np.linalg.norm(loop - corner, axis=1)) < 1e-6, "after undo the corner is sharp again"

"""Im Gizmo-Zug wird gespart, was man in der Bewegung nicht sieht: Flächen, die sich verformen, bekommen einfache
Licht-Normalen (genau nach dem Loslassen), und die Verdeckung der Punkte wird nur in jedem vierten Bild zurückgelesen."""
import numpy as np

from sketch_machine import components
from tests.harness import H
from tests.test_undo_tempo import _two_patches


def _point_drag(h):
    sc, st, patches = _two_patches(h)
    h.camera([3.5, 0.0, 1.0], 12, [0.2, 0.8, 0.5])
    c = sc.curve_by_id(patches[0].patch_lines[0])
    h.edit_mode("point")
    h.v.selection, h.v.edge_selection, h.v.seg_selection = [], [], []
    h.v.point_selection = [("pt", st.id, c.id, components.knots(c)[0])]
    h.v._changed()
    h.grab()
    target = h.v.transform_target
    target.in_drag = True
    h.v.gizmo._drag = {"target": target}
    h.v._mode = "transform"
    return sc, patches, target


def _release(h, target):
    h.v.gizmo._drag = None
    h.v._mode = None
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    h.grab()


def _rough_blocks(h):
    return [hit[3] for hit in h.v.renderer._block_cache.values()]


def test_verformte_flaeche_im_zug_ungefaehr_danach_genau(h: H):
    sc, patches, target = _point_drag(h)
    target.translate(np.array([0.0, 0.3, 0.0]))
    h.v.update()
    h.grab()
    assert any(_rough_blocks(h)), "die verformte Fläche hat im Zug einfache Normalen"
    assert not all(_rough_blocks(h)), "die unberührte Fläche behält ihre genauen"
    _release(h, target)
    assert not any(_rough_blocks(h)), "nach dem Loslassen sind alle Normalen genau"
    after = h.grab()
    h.v.renderer._block_cache, h.v.renderer._normal_cache, h.v.renderer._surface_key = {}, {}, None
    h.v.update()
    fresh = h.grab()
    assert h.diff(after, fresh, threshold=2) == 0, "Bild nach dem Loslassen = frisch gerechnetes Bild"


def test_punkt_verdeckung_im_zug_nur_jedes_vierte_bild(h: H):
    sc, patches, target = _point_drag(h)
    r = h.v.renderer
    calls = []
    real = r.points_visible
    r.points_visible = lambda pts: (calls.append(len(pts)), real(pts))[1]
    try:
        for _ in range(8):
            target.translate(np.array([0.0, 0.02, 0.0]))
            h.v.update()
            h.grab()
        assert len(calls) == 2, f"im Zug jedes vierte Bild zurückgelesen ({len(calls)} von 8)"
        _release(h, target)
        n = len(calls)
        h.v.update()
        h.grab()
        h.v.update()
        h.grab()
        assert len(calls) - n >= 2, "ohne Zug wieder in jedem Bild"
    finally:
        r.points_visible = real

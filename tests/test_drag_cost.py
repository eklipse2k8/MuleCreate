"""What a gizmo drag must not cost (artist's recording of 12.11.: 300-650 ms per frame, Ctrl+Z 1.8-2.5 s): uninvolved
surfaces do not count as changed afterwards, and the shadow ribbons of all strokes are built in one go - with the same
result as line by line."""
import numpy as np

import sketch_machine.scene as S
from sketch_machine import network, renderer

LEVEL = "core"


def _flaeche(sc, x0):
    st = sc.new_stroke()
    st.parent = None
    q = [[x0, 0, 0], [x0 + 2, 0, 0], [x0 + 2, 0, 2], [x0, 0, 2]]
    for i in range(4):
        sc.add_curve(np.linspace(q[i], q[(i + 1) % 4], 8), None)
    network.sync(sc)
    patch = sc.create_patch(list(st.curves))
    assert patch is not None
    return st, patch


def test_uninvolved_surface_does_not_count_as_changed_after_rigid_drag(h=None):
    """In a rigid drag every surface of the scene is held. The marker attributes for that must be gone afterwards:
    otherwise every surface differs from its undo image and is copied in full at every step."""
    sc = S.Scene()
    a, pa = _flaeche(sc, 0.0)
    _b, pb = _flaeche(sc, 10.0)
    for _ in range(4):
        sc.sync_lofts()
    sc.checkpoint()
    sc.checkpoint()  # (the first step copies everything; from the second on every surface has an image of the state before)
    vorher = set(pb.__dict__)
    t = S.TransformSet([a], scene=sc)
    t.in_drag = True
    for _ in range(3):
        t.translate(np.array([0.0, 0.5, 0.0]))
        sc.sync_lofts()
    assert pb.__dict__.get("_carried"), "precondition of the test: the uninvolved surface is held during the drag"
    t.in_drag = False
    t.end_rigid()
    for _ in range(3):
        sc.sync_lofts()
    neu = {k for k in set(pb.__dict__) - vorher if k.startswith("_carr") or k == "_idle_hold"}
    assert not neu, f"the drag left marker attributes on the uninvolved surface: {sorted(neu)}"
    memo, _keep = sc._twin_memo()
    assert id(pb) in memo, "the uninvolved surface counts as changed for undo (would be copied in full)"
    assert id(pa) not in memo, "the moved surface counts as unchanged"
    form = np.array(pb.fill_mesh()[0], float)
    sc.undo()
    pb2 = next(f for f in sc.surfaces if f.id == pb.id)
    assert pb2 is pb, "the uninvolved surface was replaced on restore"
    assert np.allclose(np.array(pb2.fill_mesh()[0], float), form)


def _baender_einzeln(lines, sun, min_w, r):
    """The computation line by line (version up to v0.99.198) as a comparison."""
    sun = np.asarray(sun, float)
    tris = []
    for pts, w in lines:
        hw = np.maximum(np.broadcast_to(np.asarray(w, float), (len(pts),)), min_w) * 0.5
        pts = pts - sun * hw[:, None]
        a, b = pts[:-1], pts[1:]
        t = b - a
        t = t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
        a, b = a - t * hw[:-1, None], b + t * hw[1:, None]
        side = np.cross(t, sun)
        ln = np.linalg.norm(side, axis=1, keepdims=True)
        side = np.where(ln > 1e-9, side / np.maximum(ln, 1e-12), r)
        sa, sb = side * hw[:-1, None], side * hw[1:, None]
        q = [a - sa, a + sa, b + sb, b - sb]
        tris.append(np.stack([q[0], q[1], q[2], q[0], q[2], q[3]], axis=1).reshape(-1, 3))
    return np.vstack(tris).astype("f4")


def test_shadow_ribbons_in_one_go_like_individually(h=None):
    rng = np.random.default_rng(7)
    lines = [(rng.random((n, 3)) * 20, rng.random(n) * 0.4 if n % 2 else 0.07) for n in (2, 3, 11, 2, 60, 5, 8)]
    lines.append((np.array([[0, 0, 0], [0, 0, 0], [1, 0, 0]], float), 0.1))  # segment without length
    sun = np.array([0.3, 0.8, 0.5])
    sun /= np.linalg.norm(sun)
    quer = np.array([1.0, 0.0, 0.0])
    alle = renderer.shadow_ribbons(lines, sun, 0.02, quer)
    assert np.array_equal(alle, _baender_einzeln(lines, sun, 0.02, quer)), "shadow ribbons differ from the individual computation"
    mit_kurzer = lines[:2] + [(np.zeros((1, 3)), 0.1)] + lines[2:]  # a line made of one point casts no shadow
    assert np.array_equal(renderer.shadow_ribbons(mit_kurzer, sun, 0.02, quer), alle)
    assert renderer.shadow_ribbons([], sun, 0.02, quer).shape == (0, 3)

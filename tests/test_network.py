"""Curve net (F3): points with identity - snapping connects, proximity does not; copies are their own points; migration."""
import json
import os
import time

import numpy as np

from tests.harness import H, OUT, ROOT, Qt, line
from sketch_machine import components, network
from sketch_machine.clipboard import Clipboard, paste
from sketch_machine.scene import Scene


def _ground(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [2, 0, 0], 12), sc.planes[0].id)
    h.v._changed()
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    return sc.curves[-1]


def test_snapping_at_the_end_connects(h: H):
    a = _ground(h)
    h.stroke_world([[2, 0, 0], [2, 0, 0.7], [2, 0, 1.5]])
    b = h.curves()[-1]
    assert np.allclose(b.points[0], a.points[-1]), "stroke snaps to the line end"
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0), "shared point"


def test_proximity_does_not_connect(h: H):
    a = _ground(h)
    h.v.ws.magnet = False  # without snapping: ends just beside it
    try:
        h.stroke_world([[2.0005, 0, 0.0005], [2, 0, 0.7], [2, 0, 1.5]])
    finally:
        h.v.ws.magnet = True
    b = h.curves()[-1]
    assert network.pid_of(a, len(a.points) - 1) != network.pid_of(b, 0)


def test_snapping_mid_line_does_not_split(h: H):
    a = _ground(h)
    h.stroke_world([[1.0, 0, 0], [1.0, 0, 0.7], [1.0, 0, 1.5]])
    curves = h.curves()
    assert len(curves) == 2, f"{len(curves)} lines - the line stays whole, the new stroke is added"
    b = curves[-1]
    a = curves[0]
    ks = components.knots(a)
    mid = [k for k in ks[1:-1] if np.linalg.norm(a.points[k] - b.points[0]) < 1e-6]
    assert mid, "knot at the snap location"
    assert network.pid_of(a, mid[0]) == network.pid_of(b, 0), "T-junction is a shared point"
    refs = network.refs_by_pid(h.sc)[network.pid_of(b, 0)]
    assert network.degree(refs) == 3


def test_corners_while_drawing(h: H):
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    h.v.ws.magnet = False
    try:
        h.stroke_world([[0, 0, 0], [1, 0, 0], [2, 0, 0], [2, 0, 1], [2, 0, 2]])
    finally:
        h.v.ws.magnet = True
    c = h.curves()[-1]
    ks = components.knots(c)
    assert len(ks) == 3, f"one corner detected ({ks})"
    corner = c.points[ks[1]].copy()
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(c.points, axis=0), axis=1))])
    t = np.linspace(0, arc[-1], len(c.points) * 2 + 1)
    c.points = np.stack([np.interp(t, arc, c.points[:, i]) for i in range(3)], axis=1)
    c.widths = np.full(len(c.points), c.widths.mean())
    ks2 = components.knots(c)
    assert len(ks2) == 3 and np.linalg.norm(c.points[ks2[1]] - corner) < 0.05, "corner stays in place"


def test_copy_is_not_connected_to_the_original(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 10), None)
    sc.add_curve(line([1, 0, 0], [1, 0, 1], 10), None)
    a, b = sc.curves[-2:]
    network.sync(sc)
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0)
    clip = Clipboard()
    clip.copy(sc, [], [("line", sc.owner_of(c).id, c.id) for c in (a, b)])
    paste(sc, clip, "elements")
    network.sync(sc)
    a2, b2 = sc.curves[-2:]
    assert network.pid_of(a2, len(a2.points) - 1) == network.pid_of(b2, 0), "connected within the copy"
    assert network.pid_of(a2, 0) != network.pid_of(a, 0), "not connected to the original"
    group = components.ComponentGroup(sc, [(a2, 0)], [])
    group.translate(np.array([0.0, 0.5, 0.0]))
    assert np.allclose(a.points[0], [0, 0, 0]), "dragging the copy leaves the original in place"


def test_splitting_keeps_points(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [2, 0, 0], 21), None)
    sc.add_curve(line([2, 0, 0], [2, 0, 1], 10), None)
    a, b = sc.curves[-2:]
    network.sync(sc)
    end_pid = network.pid_of(b, 0)
    sc.split_all_at(np.array([1.0, 0, 0]))
    network.sync(sc)
    first, second = sc.curves[0], sc.curves[1]
    assert network.pid_of(first, len(first.points) - 1) == network.pid_of(second, 0), "the cut is a shared point"
    assert network.pid_of(second, len(second.points) - 1) == end_pid, "old connection stays"


def test_migration_of_an_old_file(h: H):
    # rebuild an older file: the same scene without point IDs on the lines
    with open(os.path.join(ROOT, "tests", "scenes", "topologie.sketch.json"), encoding="utf-8") as f:
        raw = json.load(f)

    def strip(o):
        if isinstance(o, dict):
            o.pop("pids", None)
            for v in o.values():
                strip(v)
        elif isinstance(o, list):
            for v in o:
                strip(v)
    strip(raw)
    path = os.path.join(OUT, "net_alt.sketch.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    scene, data = Scene.load(path)
    rep = scene.net_report
    assert rep["migrated"] and rep["points"] > 0, rep
    out = os.path.join(OUT, "net_rt.sketch.json")
    scene.save(out)
    s2, _ = Scene.load(out)
    rep2 = s2.net_report
    assert not rep2["migrated"] and {k: rep2[k] for k in ("points", "shared", "free_ends")} == \
        {k: rep[k] for k in ("points", "shared", "free_ends")}, (rep, rep2)
    h.v.set_scene(s2)
    t0 = time.perf_counter()
    for _ in range(20):
        network.sync(s2)
    dt = (time.perf_counter() - t0) / 20
    assert dt < 0.01, f"sync without change {dt * 1000:.1f} ms"
    return f"{rep['points']} points, {rep['shared']} connected, {rep['free_ends']} open ends"


def test_connection_display(h: H):
    a = _ground(h)
    h.stroke_world([[2, 0, 0], [2, 0, 0.7], [2, 0, 1.5]])
    h.edit_mode("point")
    shared, free, plain = h.v._net_marks()
    assert len(shared) == 1 and len(free) == 2, (len(shared), len(free), len(plain))
    h.save_image("netz_punkte.png")


def test_loop_up_to_the_t_junction_and_fill(h: H):
    """Rectangle with a centre line (T-junctions top and bottom): double-click on the left side selects the left half -
    up to the shared points; F fills exactly that (only then are the lines split)."""
    sc = h.sc
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    for a, b in (([0, 0, 0], [2, 0, 0]), ([2, 0, 0], [2, 0, 2]), ([2, 0, 2], [0, 0, 2]), ([0, 0, 2], [0, 0, 0])):
        h.stroke_world([a, (np.array(a) + np.array(b)) / 2, b])
    h.stroke_world([[1, 0, 0], [1, 0, 1], [1, 0, 2]])
    assert len(h.curves()) == 5, "centre line does not split the rectangle sides"
    h.edit_mode("edge")
    h.v.select_loop(h.scrf([0, 0, 1.0]), "replace")
    assert len(h.v.edge_selection) == 2 and len(h.v.seg_selection) == 2, (h.v.edge_selection, h.v.seg_selection)
    h.key(Qt.Key_F)
    verts = sc.surfaces[-1].fill_mesh()[0]
    assert np.allclose(verts.max(axis=0), [1, 0, 2], atol=1e-3) and np.allclose(verts.min(axis=0), [0, 0, 0], atol=1e-3)


def _patch_square(h: H):
    """Curve surface from four slightly arched boundary lines on the ground (like the artist's test: outline -> surface)."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 16)
    sides = [np.stack([t * 4, 0.3 * np.sin(t * np.pi), t * 0], 1), np.stack([np.full_like(t, 4), 0.3 * np.sin(t * np.pi), t * 4], 1),
             np.stack([4 - t * 4, 0.3 * np.sin(t * np.pi), np.full_like(t, 4)], 1), np.stack([t * 0, 0.3 * np.sin(t * np.pi), 4 - t * 4], 1)]
    lines = []
    for s in sides:
        sc.add_curve(s, None)
        lines.append(sc.curves[-1])
    ps = sc.create_patch(lines)
    sc.sync_lofts()
    h.v._changed()
    h.camera([2, 0.2, 2], 9, [0.05, 1, 0.05])
    h.v._activate(ps)
    return ps, lines


def test_stroke_over_the_surface_edge_ends_on_the_boundary_line(h: H):
    ps, lines = _patch_square(h)
    h.stroke_world([[2.0, 0.3, 2.0], [3.0, 0.3, 2.0], [3.8, 0.3, 2.0], [4.6, 0.0, 2.0], [5.2, 0.0, 2.0]])
    c = h.curves()[-1]
    assert c.plane_id == ps.id
    right = lines[1]
    assert network.pid_of(c, len(c.points) - 1) in set(right.pids.values()), "end is a shared point of the boundary line"
    assert len([x for x in h.curves() if not x.paint]) == 5, "boundary line stays one stroke"


def test_crossing_on_the_same_plane_becomes_a_point(h: H):
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    h.v.ws.magnet = False
    try:
        h.stroke_world([[0, 0, 1], [1, 0, 1], [2, 0, 1]])
        h.stroke_world([[1, 0, 0], [1, 0, 1], [1, 0, 2]])
    finally:
        h.v.ws.magnet = True
    a, b = h.curves()
    shared = set(a.pids.values()) & set(b.pids.values())
    assert len(shared) == 1, "one shared crossing"
    refs = network.refs_by_pid(h.sc)[shared.pop()]
    assert network.degree(refs) == 4 and len(h.curves()) == 2


def test_merely_apparent_crossing_stays_separate(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 1], [2, 0, 1], 20), sc.planes[0].id)
    h.v._changed()
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    other = sc.custom[0] if sc.custom else None
    lifted = np.array([[1, 1.0, 0], [1, 1.0, 2]])  # 1 above the ground: seen from above it crosses
    sc.add_curve(np.linspace(lifted[0], lifted[1], 20), sc.planes[0].id)
    h.v._connect_new_crossings([sc.curves[-1]])
    a, b = sc.curves[-2:]
    network.sync(sc)
    assert not set(a.pids.values()) & set(b.pids.values())


def test_cleanup_crossings_between_planes(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 1], [2, 0, 1], 20), sc.planes[0].id)  # on the ground
    sc.add_curve(line([1, -1, 1], [1, 1, 1], 20), sc.planes[2].id)  # vertical, through the ground
    h.v._changed()
    h.v.set_cleanup_global(True)
    try:
        h.v.run_cleanup("crossings")
    finally:
        h.v.set_cleanup_global(False)
    a, b = sc.curves[-2:]
    assert set(a.pids.values()) & set(b.pids.values()), "crossing in space connected"


def test_welding_connects_ends_lying_on_each_other(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 10), None)
    network.sync(sc)
    sc.add_curve(line([1, 0, 0], [1, 0, 1], 10), None)
    b = sc.curves[-1]
    b.pids = {0: network.new_pid(), len(b.points) - 1: network.new_pid()}  # own point, but lies exactly on it
    a = sc.curves[0]
    network.sync(sc)
    assert network.pid_of(a, len(a.points) - 1) != network.pid_of(b, 0)
    h.camera([0.5, 0, 0.5], 4, [0, 1, 0.01])
    h.v.set_cleanup_global(True)
    try:
        h.v.run_cleanup("weld")
    finally:
        h.v.set_cleanup_global(False)
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0), "welded = connected"


def test_v_snapping_connects(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 10), None)
    sc.add_curve(line([1.0, 0, 0.5], [1, 0, 1], 10), None)
    a, b = sc.curves[-2:]
    network.sync(sc)
    b.translate(np.array([0.0, 0.0, -0.5]))  # like a V drag: end exactly onto the other end
    h.v._connect_at(a.points[-1])
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0)
    c = sc.curves[0]
    sc.add_curve(line([0.5, 0, 0.6], [0.5, 0, 1.5], 10), None)
    d = sc.curves[-1]
    d.translate(np.array([0.0, 0.0, -0.6]))  # onto the middle of the line
    h.v._connect_at(d.points[0])
    assert network.pid_of(d, 0) in set(c.pids.values()), "line middle gets a shared point"


def test_crossing_on_fill_surface_stays_one_point(h: H):
    """The artist's scene (new_topology_v002): second stroke over a fill surface, crosses the first and runs past the
    edge. The outer line gets new points in the process, the surface follows it - the crossing must still remain a
    shared point, and drawing must not throw errors in the image (coloured boxes)."""
    h.load("tests/scenes/netz_fuellflaeche_kreuz.sketch.json")
    sc = h.sc
    surf = sc.surfaces[0]
    h.v._activate(surf)
    a, b = np.array([0.12, 0, -9.19]), np.array([2.54, 0, 2.95])
    d = (b - a) / np.linalg.norm(b - a)
    h.stroke_frames([h.scrf(p) for p in [a + t * (b - a) for t in np.linspace(0.02, 0.98, 30)] + [b + d * 0.6]])
    new = h.curves()[-1]
    first = next(c for c in h.curves() if c.plane_id == surf.id and c is not new)
    assert set(first.pids.values()) & set(new.pids.values()), "crossing is a shared point"
    assert len(new.widths) == len(new.points) and len(first.widths) == len(first.points)
    h.edit_mode("point")
    h.save_image("netz_fuellflaeche_kreuz.png")


def test_copying_a_surface_as_a_subgraph(h: H):
    """Copy only the surface (surface mode) and paste: the copy takes its net along - boundary lines and a line
    on it -, is internally connected like the original, but not with the original; material and tint come along.
    Moved, the whole copy moves, the original stays."""
    from sketch_machine import loft
    sc = h.sc
    ps, lines = _patch_square(h)
    h.stroke_world([[-0.5, 0.3, 2.0], [2.0, 0.3, 2.0], [4.5, 0.3, 2.0]])  # real line across the surface
    across = h.curves()[-1]
    assert across.plane_id == ps.id
    ps.material, ps.tint = "holz", (0.8, 0.3, 0.2)
    n_lines = len(h.curves())
    before = {c.id: c.points.copy() for c in h.curves()}
    h.edit_mode("face")
    h.v.selection = [ps.id]
    h.v.edge_selection = []
    h.v.copy_selection()
    h.v.paste()
    copy_s = sc.surfaces[-1]
    assert copy_s is not ps and type(copy_s) is type(ps), "copy is a curve surface again"
    assert len(h.curves()) == n_lines + 5, f"{len(h.curves()) - n_lines} new lines instead of 5 (edge + line on it)"
    assert copy_s.material == "holz" and copy_s.tint == ps.tint, "material and tint copied along"
    border = sc.patch_border(copy_s)
    assert len(border) == 4 and not any(any(c is x for x in lines) for c in border), "edge of the copy = copied lines"
    new_across = [c for c in h.curves() if c.plane_id == copy_s.id]
    assert len(new_across) == 1, "line on the surface belongs to the copy"
    network.sync(sc)
    old_pids = {p for c in lines + [across] for p in (c.pids or {}).values()}
    new_pids = {p for c in border + new_across for p in (c.pids or {}).values()}
    assert not old_pids & new_pids, "not connected to the original"
    ends = {network.pid_of(new_across[0], 0), network.pid_of(new_across[0], len(new_across[0].points) - 1)}
    assert ends <= {p for c in border for p in (c.pids or {}).values()}, "internally connected like the original"
    target = h.v.transform_target
    target.translate(np.array([6.0, 0, 0]))
    h.v._changed()
    for cid, pts0 in before.items():
        assert np.allclose(sc.curve_by_id(cid).points, pts0), "original stays"
    v = copy_s.fill_mesh()[0]
    assert v[:, 0].min() > 5.9, "copy moved along completely"


def test_copying_fill_surface_and_tube_as_a_subgraph(h: H):
    """Fill surface (L shape) and tube copied alone: outline or cross-sections and rails come along, the copy
    follows its own lines (not the original)."""
    from sketch_machine.scene import LoftSurface, SurfaceObject
    sc = h.sc
    sc.new_stroke()
    poly = [[0, 0], [4, 0], [4, 1.5], [1.5, 1.5], [1.5, 4], [0, 4]]
    pts = [np.array([x, 0.0, z]) for x, z in poly]
    outline = []
    for i in range(len(pts)):
        sc.add_curve(np.linspace(pts[i], pts[(i + 1) % len(pts)], 20), None)
        outline.append(sc.curves[-1])
    fill_s = sc.create_fill([(c, False) for c in outline])
    t = np.linspace(0, 2 * np.pi, 33)
    rings = []
    for y in (0.0, 2.0, 3.0):
        sc.add_curve(np.stack([8 + np.cos(t), np.full_like(t, y), np.sin(t)], 1), None)
        rings.append(sc.curves[-1])
    tube = sc.create_loft([("lines", [c.id]) for c in rings], [c.points for c in rings])
    sc.add_loft_rails(tube, np.array([0.3, 0.4, 1.0]))
    sc.sync_lofts()
    h.v._changed()
    for s, kind, n in ((fill_s, SurfaceObject, len(outline)), (tube, LoftSurface, len(rings) + len(tube.rails))):
        before = len(h.curves())
        mesh0 = s.fill_mesh()[0].copy()
        h.edit_mode("face")
        h.v.selection = [s.id]
        h.v.edge_selection = []
        h.v.copy_selection()
        h.v.paste()
        c = sc.surfaces[-1]
        assert type(c) is kind and c is not s
        assert len(h.curves()) == before + n, f"{s.name}: {len(h.curves()) - before} new lines instead of {n}"
        h.v.transform_target.translate(np.array([0, 0, 10.0]))
        h.v._changed()
        assert c.fill_mesh()[0][:, 2].min() > mesh0[:, 2].min() + 9.9, f"{s.name}: copy follows its lines"
        assert np.allclose(s.fill_mesh()[0], mesh0), f"{s.name}: original stays"


def test_inserted_point_on_boundary_line_is_connected(h: H):
    """Ctrl+click on a boundary line: the new point lies in the middle of the line and is displayed as connected (filled),
    not as an open or light point."""
    ps, lines = _patch_square(h)
    h.edit_mode("point")
    before = len(h.v._net_marks()[0])
    p = lines[0].points[len(lines[0].points) // 3]
    h.click(h.scr(p), Qt.ControlModifier)
    shared, free, plain = h.v._net_marks()
    assert len(shared) == before + 1 and not plain, (before, len(shared), len(plain))
    assert min(np.linalg.norm(np.array(shared) - p, axis=1)) < 0.05, "the new point is filled"


def test_dragging_a_whole_line_connected_only_via_point_id(h: H):
    """Drag a whole line with the gizmo: a line connected at its end (same point ID) goes along; one
    whose end merely happens to lie in the same place stays (connected is what shares a point - never the position)."""
    from sketch_machine import edges
    sc = h.sc
    for joined in (True, False):
        h.new_scene()
        sc = h.sc
        sc.new_stroke()
        sc.add_curve(line([0, 0, 0], [2, 0, 0], 21), None)
        sc.add_curve(line([2, 0, 0], [2, 0, 2], 21), None)
        a, b = sc.curves[-2:]
        network.sync(sc)
        if joined:
            network.join(sc, a, len(a.points) - 1, b, 0)
        else:
            b.pids = dict(b.pids)
            b.pids[0] = network.new_pid()
        network.sync(sc)
        assert (network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0)) == joined
        before = b.points.copy()
        edges.handles_for(sc, [edges.curve_to_ref(sc, a)])[0].translate(np.array([0.0, 1.0, 0.0]))
        moved = float(np.linalg.norm(b.points[0] - before[0]))
        if joined:
            assert moved > 0.99 and np.allclose(b.points[-1], before[-1]), "connected line goes along (soft, end stays)"
        else:
            assert moved == 0.0, "merely lying on top of each other: stays put"


def test_sync_notices_every_change_despite_the_fast_path(h: H):
    """network.sync answers from the counter without a change (fast path) - moving points, line removed, line
    added again: every time it is really resynced."""
    sc = h.sc
    a = _ground(h)
    sc.add_curve(line([2, 0, 0], [2, 2, 0], 12), sc.planes[0].id)
    b = sc.curves[-1]
    network.sync(sc)
    state = sc._net_sync
    assert network.sync(sc) is state[1] and sc._net_sync is state, "without change: same state"
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0), "end to start: one point"
    pts = b.points.copy()
    pts[0] += [0.5, 0, 0]
    b.points = pts
    network.sync(sc)
    assert sc._net_sync is not state, "moved line: resynced"
    assert network.pid_of(a, len(a.points) - 1) != network.pid_of(b, 0), "apart: two points"
    state = sc._net_sync
    owner = sc.owner_of(b)
    owner.curves.remove(b)
    assert network.sync(sc)["points"] != state[1]["points"], "line gone: counted anew"
    owner.curves.append(b)
    sc.strokes[:] = list(sc.strokes)  # same list, same content: may come from the fast path
    stats = network.sync(sc)
    assert stats["points"] == state[1]["points"], "line back: same count as before"


def test_stroke_through_two_nearly_identical_points_connects_both(h: H):
    """Random sequence 3: Two lines each have their own point at almost the same place, a new stroke crosses both. Its
    one point connects all three - formerly the second connection tore the first one off again."""
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [4, 0, 0], 41), None)
    sc.add_curve(line([2.001, 0, -1], [2.001, 0, 1], 21), None)
    sc.add_curve(line([1, 0, -1], [3, 0, 1], 41), None)
    first, second, stroke = sc.curves[-3:]
    a, b = network.knot_at(first, [2.0, 0, 0]), network.knot_at(second, [2.001, 0, -0.001])
    network.sync(sc)
    tol = 0.0125
    network.connect_crossings(sc, stroke, [second], tol, 0.2)
    network.connect_crossings(sc, stroke, [first], tol, 0.2)
    network.sync(sc)
    a = min(components.knots(first), key=lambda k: np.linalg.norm(first.points[k] - [2.0, 0, 0]))
    b = min(components.knots(second), key=lambda k: np.linalg.norm(second.points[k] - [2.001, 0, 0]))
    shared = set(stroke.pids.values())
    assert network.pid_of(first, a) in shared and network.pid_of(second, b) in shared, "all three at the same point"
    assert network.pid_of(first, a) == network.pid_of(second, b)
    assert np.allclose(first.points[a], second.points[b]), "same point: same position"

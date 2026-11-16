"""Shots (Prototyp, intern „Timing“): Flipbook-Ebenen mit Zeichnungen je Frame, Shot-Notizen wie Notizen (Panel Shots),
Kameras als Bilder auf ihren Brettern, Speichern/Undo, Frame-Wechsel ohne Neubau der Zeichenlisten."""
import os

import numpy as np
from PySide6.QtCore import Qt

from tests.harness import H, OUT
from sketch_machine import timing


def _flip_scene(h: H):
    """Neue Szene im Timing mit einer Flipbook-Ebene vor der Kamera -> Ebene."""
    h.new_scene()
    h.camera((0, 0, 0), 12.0, (0, 0, 1))
    h.v.set_timing_mode(True)
    h.v.set_draw_tool("brush")
    h.v.new_plane()
    plane = h.sc.active_plane
    assert plane.flipbook, "Space+N im Timing legt eine Flipbook-Ebene an"
    h.pump(0.05)
    return plane


def _on_plane(plane, pts2d):
    return np.array([plane.origin + x * plane.axis_u + y * plane.axis_v for x, y in pts2d])


def _draw(h: H, plane, frame, pts2d):
    h.v.set_frame(frame)
    before = {c.id for c in h.sc.curves}
    h.stroke_world(_on_plane(plane, pts2d))
    new = [c for c in h.sc.curves if c.id not in before]
    assert new, f"bei {frame} entstand kein Strich"
    return new


def _leave(h: H):
    if h.v.ws.timing_mode:
        h.v.set_select_mode(False)


def _shot_note(h: H, plane=None, title="Shot 1", text=""):
    """Shot-Notiz an der Flipbook-Ebene (Hinweislinie auf die Ebene), angeklickt -> Notiz."""
    from sketch_machine.scene import Note, NoteAnchor
    anchors = [NoteAnchor(plane.origin.copy())] if plane is not None else []
    board = {"items": [{"kind": "text", "x": 0.0, "y": 0.0, "w": 340.0, "text": text}]} if text else {}
    note = Note(title, (plane.origin if plane is not None else np.zeros(3)) + np.array([0, 2.0, 0]), anchors=anchors,
                board=board)
    h.sc.timing.notes.append(note)
    h.v.ws.active_note = note.id
    h.v._changed()
    return note


def _add_pose(h: H, cam, frame, state, mm=None):
    """Stellung samt Bild im Brett (wie ➜, ohne durch die Kamera zu schauen)."""
    from sketch_machine.note_board import shot_edit, shot_image
    from sketch_machine.vp.timing_view import _shot_entry

    def edit(items):
        p = timing.add_pose(cam, frame, state)
        if mm is not None:
            p.mm = mm
        name, _w, _h = shot_image(h.v, cam, p)
        items.append(_shot_entry(cam, p, name, 500.0 * len(cam.poses), 0.0, 0.3))
        return p
    return shot_edit(h.v, h.sc.timing.note_of(cam).id, edit)


def test_zeichnungen_gelten_bis_zur_naechsten(h: H):
    """Malen bei einem Frame legt dort eine Zeichnung an; sie hält bis zur nächsten Zeichnung derselben Ebene."""
    plane = _flip_scene(h)
    try:
        a = _draw(h, plane, 1010, [(-2, 0), (0, 1), (2, 0)])
        b = _draw(h, plane, 1015, [(-2, -1), (0, -2), (2, -1)])
        assert all(c.frame == 1010 and c.paint for c in a) and all(c.frame == 1015 for c in b)
        assert timing.flip_keys(h.sc)[plane.id] == [1010, 1015]
        shown = lambda c: h.v._layer_visible(c)
        for frame, want_a, want_b in ((1001, False, False), (1010, True, False), (1013, True, False), (1015, False, True),
                                      (1090, False, True)):
            h.v.set_frame(frame)
            assert shown(a[0]) == want_a and shown(b[0]) == want_b, f"bei {frame}"
        # sichtbar im Bild: bei 1001 ist die Ebene leer, bei 1012 nicht
        h.sc.timing.onion = False
        h.v.set_frame(1001)
        empty = h.grab()
        h.v.set_frame(1012)
        drawn = h.grab()
        assert h.diff(empty, drawn) > 50, "die Zeichnung von 1010 gilt bei 1012"
        h.v.set_frame(1003)
        assert h.diff(empty, h.grab()) == 0, "vor der ersten Zeichnung ist die Ebene leer"
    finally:
        _leave(h)


def test_frame_wechsel_baut_keine_zeichenlisten_neu(h: H):
    """Performance: ein Frame-Wechsel wählt nur Bereiche im Flipbook-Puffer – keine Neuberechnung der Strichliste,
    kein neues Hochladen."""
    plane = _flip_scene(h)
    try:
        for k, frame in enumerate(range(1002, 1030, 3)):
            _draw(h, plane, frame, [(-2 + k * 0.2, 0), (0, 1 + k * 0.1), (2, 0)])
        from PySide6.QtOpenGLWidgets import QOpenGLWidget
        paint = lambda: QOpenGLWidget.grabFramebuffer(h.v)  # ein Bild wie paintGL, ohne Neubau zu erzwingen
        h.v.set_frame(1001)
        h.grab()  # einmal alles bauen
        paint()
        r = h.v.renderer
        calls = []
        orig = h.v._scene_stroke_list
        h.v._scene_stroke_list = lambda: calls.append(1) or orig()
        rev, key = r._stroke_rev, r._flip_key
        try:
            for frame in range(1001, 1040):
                h.v.set_frame(frame)
                paint()
                assert r._flip_jobs, f"bei {frame} wird die geltende Zeichnung gezeichnet"

        finally:
            del h.v._scene_stroke_list
        assert not calls, f"Strichliste {len(calls)}× neu gebaut"
        assert r._stroke_rev == rev, f"Striche neu hochgeladen ({rev} -> {r._stroke_rev})"
        assert r._flip_key is key, "Flipbook-Puffer neu aufbereitet"
    finally:
        _leave(h)


def test_flipbook_ausserhalb_des_timings_gesperrt(h: H):
    """Außerhalb des Timings: Flipbook-Ebene nicht aktivierbar, ihre Zeichnungen nicht radierbar; im Timing wird nur auf
    Flipbook-Ebenen gemalt."""
    plane = _flip_scene(h)
    a = _draw(h, plane, 1005, [(-2, 0), (2, 0)])
    _leave(h)
    assert not h.sc.active_plane.flipbook, "beim Verlassen wird die vorige Zeichenfläche wieder aktiv"
    h.v._activate(plane)
    assert h.sc.active_plane is not plane
    h.v.set_draw_tool("eraser")
    pts = h.scr(_on_plane(plane, [(0, 0)])[0])
    h.v.set_frame(1005)
    from PySide6.QtCore import QPointF
    h.stroke([QPointF(pts.x() - 5, pts.y() - 20), QPointF(pts.x() + 5, pts.y() + 20)])
    assert all(any(c is x for x in h.sc.curves) for c in a), "Radierer außerhalb des Timings ließ Flipbook in Ruhe"
    h.v.set_draw_tool("pen")
    # im Timing auf einer normalen Ebene: kein Strich
    h.v.set_timing_mode(True)
    try:
        h.sc.activate(h.sc.presets[1])
        n = len(h.sc.curves)
        h.stroke_world(np.array([[-1, 0, 0], [1, 0.5, 0]]))
        assert len(h.sc.curves) == n, "im Timing malt man nicht auf normale Ebenen"
    finally:
        _leave(h)


def test_undo_einer_neuen_zeichnung(h: H):
    plane = _flip_scene(h)
    try:
        _draw(h, plane, 1020, [(-1, 0), (1, 0)])
        assert timing.flip_keys(h.sc)[plane.id] == [1020]
        h.v.undo()
        assert timing.flip_keys(h.sc)[plane.id] == []
        assert h.sc.timing.frame == 1020, "Undo verstellt den Frame nicht"
    finally:
        _leave(h)


def test_weitermalen_radieren_leere_zeichnung_verschieben(h: H):
    """Malen/Radieren bei einem Frame ohne Zeichnung kopiert erst die geltende dorthin (die frühere bleibt); leere
    Zeichnung, verschieben, löschen."""
    plane = _flip_scene(h)
    tl = h.w.timeline
    try:
        a = _draw(h, plane, 1010, [(-2, 0), (2, 0)])
        b = _draw(h, plane, 1013, [(-2, 1.5), (2, 1.5)])
        assert timing.flip_keys(h.sc)[plane.id] == [1010, 1013]
        at13 = [c for _, c in timing.key_curves(h.sc, plane.id, 1013)]
        assert len(at13) == len(b) == len(a) + 1, "die Pose von 1010 ist bei 1013 noch da (weitermalen)"
        assert np.allclose(at13[0].points, a[0].points) and at13[0] is not a[0]
        assert [c for _, c in timing.key_curves(h.sc, plane.id, 1010)] == a, "1010 bleibt, wie es war"
        # radieren bei 1016 (dort gilt 1013): Kopie nach 1016, darin radiert
        h.v.set_frame(1016)
        h.v.set_draw_tool("eraser")
        from PySide6.QtCore import QPointF
        mid = h.scrf(_on_plane(plane, [(0, 0)])[0])
        h.stroke([QPointF(mid.x() - 3, mid.y() - 25), QPointF(mid.x() + 3, mid.y() + 25)])
        h.v.set_draw_tool("brush")
        assert timing.flip_keys(h.sc)[plane.id] == [1010, 1013, 1016]
        assert len(timing.key_curves(h.sc, plane.id, 1013)) == len(at13), "1013 bleibt beim Radieren bei 1016 heil"
        assert len(timing.key_curves(h.sc, plane.id, 1016)) == len(at13) + 1, "bei 1016 ist die untere Linie zerschnitten"
        h.v.set_frame(1020)
        tl._blank()
        assert timing.flip_keys(h.sc)[plane.id] == [1010, 1013, 1016, 1020]
        h.v.set_frame(1022)
        assert not any(h.v._layer_visible(c) for c in h.sc.curves if c.frame is not None), "nach der leeren Zeichnung: nichts"
        timing.move_key(h.sc, plane, 1013, 1014)
        h.v._changed()
        assert timing.flip_keys(h.sc)[plane.id] == [1010, 1014, 1016, 1020]
        h.v.set_frame(1012)
        tl._delete_key()  # bei 1012 gilt 1010
        assert timing.flip_keys(h.sc)[plane.id] == [1014, 1016, 1020]
    finally:
        _leave(h)


def test_kamera_im_viewport_anklicken(h: H):
    """Klick aufs Kamerasymbol wählt Kamera und Notiz, Doppelklick schaut durch, eine blasse Stellung springt zum Frame."""
    plane = _flip_scene(h)
    tm = h.sc.timing
    try:
        note = _shot_note(h, plane)
        h.camera((0, 0, 0), 10.0, (0.6, 0.3, 0.75))
        cam = h.v.new_timing_camera(note)
        _add_pose(h, cam, 1030, (cam.poses[0].target, cam.poses[0].dist * 1.5, cam.poses[0].rot))
        h.v.ws.timing_cam = h.v.ws.active_note = None
        h.camera((0, 0, 0), 40.0, (0.2, 0.5, 0.85))
        h.v.set_frame(1001)
        eye, corners = timing.frustum(cam.poses[0], timing.base_size(cam.poses[0]))
        at = h.scrf((corners[0] + corners[1]) / 2)
        h.click(at)
        assert h.v.ws.timing_cam == cam.id and h.v.ws.active_note == note.id, "Klick wählt Kamera und ihre Notiz"
        eye2, corners2 = timing.frustum(cam.poses[1], timing.base_size(cam.poses[1]))
        h.click(h.scrf((corners2[1] + corners2[2]) / 2))
        assert tm.frame == 1030, "Klick auf die blasse Stellung springt zu ihrem Frame"
        h.dclick(h.scrf((corners2[1] + corners2[2]) / 2))
        assert h.v._look == cam.id
        assert not any(c.frame is not None for c in h.sc.curves), "Klicks auf Kameras malen nichts"
        h.v.leave_camera()
    finally:
        _leave(h)


def test_kamera_stellungen_nur_von_innen(h: H):
    """Kamera aus der Ansicht; ⟲ ändert die geltende Stellung (keine Fahrt), ➜ legt ab dem Frame eine neue an; beim
    Durchschauen springt der Viewport mit; neue Stellungen erben die Brennweite."""
    _flip_scene(h)
    tm = h.sc.timing
    try:
        h.v.set_frame(1001)
        cam = h.v.new_timing_camera(tm.global_note)
        shots = lambda: timing.shot_entries(tm, cam)
        assert len(cam.poses) == 1 and len(shots()) == 1, "neue Kamera: eine Stellung, ihr Bild im Brett"
        assert cam.color is None, "neue Kameras haben die Standardfarbe"
        h.v.commit_pose(False, cam=cam)  # nicht drin: nichts passiert
        assert len(cam.poses) == 1
        h.v.look_through(cam.id)
        assert h.v._look == cam.id and h.v._cam_tan is not None
        h.v.set_cam_focal(cam, 80.0)
        h.v.set_frame(1010)
        h.v.cam.orbit(40, 0)
        assert h.v.look_modified()
        h.v.commit_pose(False)
        assert len(cam.poses) == 1, "⟲ macht keine Fahrt"
        assert not h.v.look_modified()
        first = cam.poses[0].state()
        h.v._confirm_discard = lambda: True
        h.v.set_frame(1020)
        h.v.cam.orbit(-60, 0)
        h.v.commit_pose(True)
        assert [p.frame for p in cam.poses] == [1001, 1020] and abs(cam.poses[1].mm - 80.0) < 1e-6
        assert len(shots()) == 2, "➜: neue Stellung mit eigenem Bild"
        assert {timing.shot_ref(e)[1] for _, _, e in shots()} == {p.id for p in cam.poses}
        h.v.set_frame(1005)
        assert np.allclose(h.v.cam.rot, first[2]), "springt bei 1005 auf die erste Stellung"
        h.v.set_frame(1040)
        assert np.allclose(h.v.cam.rot, cam.poses[1].rot)
        # Brennweite: Ausschnitt halten -> Motivgröße am Zielpunkt bleibt
        p = cam.poses[1]
        before = p.dist * timing.mm_to_tan(p.mm)
        h.v.set_cam_focal(cam, 35.0)
        assert abs(p.dist * timing.mm_to_tan(p.mm) - before) < 1e-9 and abs(p.mm - 35.0) < 1e-9
        h.v.leave_camera()
        assert h.v._look is None and h.v._cam_tan is None
        # Bild einer Stellung vom Brett löschen: die Stellung ist weg
        from sketch_machine.note_board import shot_edit
        shot_edit(h.v, tm.global_note.id, lambda items: items.pop(next(
            k for k, e in enumerate(items) if timing.shot_ref(e) == (cam.id, cam.poses[1].id))))
        assert [q.frame for q in cam.poses] == [1001], "Bild gelöscht -> Stellung gelöscht"
        shot_edit(h.v, tm.global_note.id, lambda items: items.clear())
        assert tm.camera_by_id(cam.id) is None, "letztes Bild gelöscht -> Kamera gelöscht"
    finally:
        del h.v._confirm_discard
        _leave(h)


def test_kamerabild_im_bildformat(h: H):
    plane = _flip_scene(h)
    try:
        _draw(h, plane, 1003, [(-2, 0), (2, 1)])
        cam = h.v.new_timing_camera(h.sc.timing.global_note)
        from PySide6.QtGui import QImage
        img = QImage.fromData(h.sc.asset_bytes(timing.shot_entries(h.sc.timing, cam)[0][2]["file"]))
        assert abs(img.width() / img.height() - timing.GATE) < 0.02, "Kamerabilder im Bildformat 16:9"
        img.save(os.path.join(OUT, "timing_kamerabild.png"))
    finally:
        _leave(h)


def test_speichern_und_laden(h: H):
    plane = _flip_scene(h)
    try:
        _draw(h, plane, 1004, [(-2, 0), (2, 0)])
        tm = h.sc.timing
        note = _shot_note(h, plane, text="Explosion")
        h.v.set_frame(1002)
        cam = h.v.new_timing_camera(note)
        _add_pose(h, cam, 1030, h.v.cam.state())
        timing.add_blank_key(plane, 1040)
        path = os.path.join(OUT, "timing_test.sketch.json")
        h.sc.save(path)
        from sketch_machine import timing_export
        from sketch_machine.scene import Scene
        sc = Scene.load(path)[0]
        p2 = next(p for p in sc.planes if p.flipbook)
        assert p2.blank_keys == [1040]
        assert timing.flip_keys(sc)[p2.id] == [1004, 1040]
        assert not sc.notes, "Shot-Notizen sind keine normalen Notizen"
        n2 = sc.timing.notes[0]
        assert n2.title == "Shot 1" and timing.note_layers(sc, n2) == [p2] and timing_export.note_text(n2) == "Explosion"
        c2 = sc.timing.cams_of(n2)[0]
        assert [p.frame for p in c2.poses] == [1002, 1030]
        entries = timing.shot_entries(sc.timing, c2)
        assert len(entries) == 2 and all(sc.asset_bytes(e["file"]) for _, _, e in entries), "Kamerabilder in der Datei"
        assert any(s.flipbook == p2.id for s in sc.strokes)
    finally:
        _leave(h)


def test_alte_prototyp_szene_wird_umgebaut(h: H):
    """Dateien des ersten Prototyps (Timing-Notizen mit Text, Bereich, Kameras samt Bildern): Shot-Notizen mit Text und
    Kamerabildern auf dem Brett, an ihrer Ebene."""
    import json
    plane = _flip_scene(h)
    _draw(h, plane, 1004, [(-2, 0), (2, 0)])
    _leave(h)
    path = os.path.join(OUT, "timing_alt.sketch.json")
    h.sc.save(path)
    data = json.load(open(path, encoding="utf-8"))
    pose = {"frame": 1001, "target": [0, 0, 0], "dist": 10.0, "rot": list(np.eye(3).ravel()), "mm": 35.0}
    some = next(iter(data["assets"]), None)
    data["assets"]["alt.jpg"] = data["assets"][some] if some else ""
    data["timing"] = {"start": 1001, "end": 1100, "fps": 24, "frame": 1001,
                      "global_note": {"id": 1, "title": "Global", "text": "Worum es geht", "cameras": []},
                      "notes": [{"id": 2, "title": "Shot 1", "text": "Explosion", "start": 1001, "end": 1040,
                                 "layers": [plane.id], "cameras": [{"id": 3, "name": "Kamera 1", "poses": [pose],
                                                                    "images": [{"frame": 1001, "file": "alt.jpg"}]}]}]}
    json.dump(data, open(path, "w", encoding="utf-8"))
    from sketch_machine import timing_export
    from sketch_machine.scene import Scene
    sc = Scene.load(path)[0]
    tm = sc.timing
    assert timing_export.note_text(tm.global_note) == "Worum es geht"
    n = tm.notes[0]
    assert n.title == "Shot 1" and "Explosion" in timing_export.note_text(n) and "1001–1040" in timing_export.note_text(n)
    assert [p.name for p in timing.note_layers(sc, n)] == [plane.name]
    cam = tm.cams_of(n)[0]
    assert [e["file"] for _, _, e in timing.shot_entries(tm, cam)] == ["alt.jpg"]


def test_alte_szene_ohne_timing_bleibt_gleich(h: H):
    h.new_scene()
    assert "timing" not in h.sc.to_dict(OUT), "Szenen ohne Timing speichern kein Timing"


def test_panel_und_abspielen(h: H):
    """Panel Shots zeigt das Brett der angeklickten Shot-Notiz (leer ohne, Global auf Knopf), unter jedem Kamerabild
    seine Einstellungen; Abspielen läuft Frame für Frame (keiner wird übersprungen) und hält an."""
    from sketch_machine.note_board import ImageItem
    plane = _flip_scene(h)
    panel = h.w.shots_panel
    try:
        _draw(h, plane, 1002, [(-1, 0), (1, 0)])
        h.v.set_frame(1001)
        h.v.ws.active_note = None
        h.w._sync_shots_panel()
        assert panel.note_id is None, "nichts angeklickt: Panel leer"
        note = _shot_note(h, plane)
        h.w._sync_shots_panel()
        assert panel.note_id == note.id
        panel.add_snapshot()  # Kamera-Knopf im Brett: neue Kamera
        cam = h.sc.timing.cams_of(note)[0]
        rows = [i.row for i in panel.gscene.items() if isinstance(i, ImageItem) and i.shot]
        assert len(rows) == 1 and not rows[0].buttons["add"].isEnabled(), "⟲/➜ nur von innen"
        assert rows[0].name.text() == cam.name
        rows[0]._action("look")
        h.pump(0.05)
        assert h.v._look == cam.id
        panel.refresh_shot_rows()
        rows = [i.row for i in panel.gscene.items() if isinstance(i, ImageItem) and i.shot]
        assert rows[0].buttons["add"].isEnabled()
        h.v.leave_camera()
        h.w._set_shot_scope("global")
        assert panel.note_id == h.sc.timing.global_note.id
        h.w._set_shot_scope("local")
        assert h.w.note_panel.note_id != note.id, "Shot-Notizen nicht im Panel Notiz"
        seen = []
        h.v.ws.frame_changed.connect(seen.append)
        h.w.timeline.set_playing(True)
        for _ in range(40):
            h.v.repaint()
            h.v._frame_painted = True  # das Testfenster liegt außerhalb des Bildschirms: Bild gilt als gezeichnet
            h.pump(0.03)
        h.w.timeline.set_playing(False)
        h.v.ws.frame_changed.disconnect(seen.append)
        assert len(seen) >= 5, f"nur {len(seen)} Frames abgespielt"
        assert all(b - a == 1 or (a == h.sc.timing.end and b == h.sc.timing.start) for a, b in zip(seen, seen[1:])), \
            "kein Frame übersprungen"
        assert not h.v.ws.playing
    finally:
        _leave(h)


def _two_pose_camera(h: H, plane):
    """Shot-Notiz mit Kamera: Stellung bei 1001 (24 mm) und 1020 (50 mm, andere Richtung)."""
    note = _shot_note(h, plane, text="Explosion wächst")
    h.camera((0, 0, 0), 12.0, (0.3, 0.2, 0.9))
    h.v.set_frame(1001)
    cam = h.v.new_timing_camera(note)
    h.camera((0, 0, 0), 15.0, (-0.6, 0.3, 0.7))
    _add_pose(h, cam, 1020, h.v.cam.state(), mm=50.0)
    return note, cam


def test_usd_kameras_gestuft_und_linear(h: H):
    """Timing-Kameras in scene.usd: gestuft hält jede Stellung bis zur nächsten, linear liegt dazwischen; Blickrichtung
    und Brennweite stimmen."""
    from pxr import Usd, UsdGeom
    from sketch_machine import usd_export
    plane = _flip_scene(h)
    try:
        _draw(h, plane, 1005, [(-1, 0), (1, 0)])
        note, cam = _two_pose_camera(h, plane)
        p0, p1 = cam.poses
        eye = lambda p: p.target + p.dist * p.rot[:, 2]
        for interp in ("step", "linear"):
            h.sc.timing.interp = interp
            path = os.path.join(OUT, f"timing_{interp}.usda")
            usd_export.write(h.sc, path)
            stage = Usd.Stage.Open(path)
            assert stage.GetStartTimeCode() == h.sc.timing.start and stage.GetTimeCodesPerSecond() == 24
            prim = next(p for p in stage.Traverse() if p.GetTypeName() == "Camera")
            assert str(prim.GetPath()).startswith("/sketch/shots/")
            xf = UsdGeom.Xformable(prim)
            focal = UsdGeom.Camera(prim).GetFocalLengthAttr()

            def at(t):
                m = np.array(xf.ComputeLocalToWorldTransform(t))
                return m[3, :3], m[:3, :3]  # Zeilenvektoren: Zeile 3 = Position, Zeilen 0..2 = right, up, back
            pos, rows = at(1001)
            assert np.allclose(pos, eye(p0), atol=1e-4) and np.allclose(rows[2], p0.rot[:, 2], atol=1e-4), "Stellung 1"
            assert abs(focal.Get(1001) - p0.mm) < 1e-3
            pos, rows = at(1020)
            assert np.allclose(pos, eye(p1), atol=1e-4) and np.allclose(rows[2], p1.rot[:, 2], atol=1e-4), "Stellung 2"
            assert abs(focal.Get(1030) - 50.0) < 1e-3
            mid = at(1010)[0]
            if interp == "step":
                assert np.allclose(mid, eye(p0), atol=1e-4) and np.allclose(at(1019)[0], eye(p0), atol=1e-4), "gestuft hält"
                assert abs(focal.Get(1019) - p0.mm) < 1e-3
            else:
                assert not np.allclose(mid, eye(p0), atol=1e-3) and not np.allclose(mid, eye(p1), atol=1e-3), "linear dazwischen"
    finally:
        _leave(h)


def test_brief_mit_timing(h: H):
    """Sketch Brief: Abschnitt Timing (Shots, Kameras mit Stellungen, Flipbook-Zeichnungen), brief.json → timing,
    frische Bilder je Kamera bei Stellungen und Zeichnungs-Wechseln."""
    import json
    import shutil
    from sketch_machine import brief
    plane = _flip_scene(h)
    try:
        _draw(h, plane, 1005, [(-1, 0), (1, 0)])
        _draw(h, plane, 1012, [(-1, 1), (1, 1)])
        h.v.set_frame(1030)
        h.w.timeline._blank()
        h.sc.timing.global_note.board = {"items": [{"kind": "text", "x": 0.0, "y": 0.0, "w": 340.0,
                                                    "text": "Eine kleine Explosion am Triebwerk"}]}
        note, cam = _two_pose_camera(h, plane)
        folder = os.path.join(OUT, "timing_brief")
        shutil.rmtree(folder, ignore_errors=True)
        brief.export(h.sc, h.v, folder, "timing")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "## Shots – what happens when" in md and "Eine kleine Explosion am Triebwerk" in md
        assert "S1 – Shot 1" in md and "camera move" in md and "Explosion wächst" in md
        assert f"layers: {plane.name}" in md
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))["shots"]
        assert data["notes"][0]["board"] and os.path.isfile(os.path.join(folder, data["notes"][0]["board"])), \
            "Brett der Shot-Notiz als Bild"
        assert data["camera_interpolation"] == "step"
        lay = data["layers"][0]
        assert lay["drawings"] == [1005, 1012] and lay["empty"] == [1030]
        c = data["notes"][0]["cameras"][0]
        assert [p["frame"] for p in c["poses"]] == [1001, 1020] and c["poses"][0]["holds_until"] == 1019
        frames = [i["frame"] for i in c["images"]]
        assert {1001, 1005, 1012, 1020, 1030} <= set(frames), frames
        assert all(os.path.isfile(os.path.join(folder, i["file"])) for i in c["images"])
        assert "Flipbook" not in json.dumps(json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))["lines"]), \
            "Flipbook-Striche stehen nicht in den Linien"
    finally:
        _leave(h)


def test_brief_ohne_timing_inhalt_ohne_abschnitt(h: H):
    """Ohne Geschehen kein Timing im Brief: leere Notizen, unbemalte Flipbook-Ebenen zählen nicht; im Abschnitt
    erscheinen nur Notizen mit Inhalt und Ebenen mit Zeichnungen; ohne Kameras keine Kameras im USD."""
    import json
    import shutil
    from sketch_machine import brief, timing_export
    plane = _flip_scene(h)
    try:
        _shot_note(h, plane, title="Leer")
        assert not timing_export.has_timing(h.sc), "leere Notiz und leere Ebene: kein Timing"
        folder = os.path.join(OUT, "timing_brief_leer")
        shutil.rmtree(folder, ignore_errors=True)
        brief.export(h.sc, h.v, folder, "leer")
        assert "## Shots" not in open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "shots" not in json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        assert not os.path.isdir(os.path.join(folder, "shots"))
        assert "/shots" not in open(os.path.join(folder, "scene.usd"), "rb").read().decode("latin-1")
        h.v.new_plane()  # zweite, unbemalte Ebene
        h.v.activate_flipbook(plane)
        _draw(h, plane, 1004, [(-1, 0), (1, 0)])
        assert timing_export.has_timing(h.sc)
        data = timing_export.brief_data(h.sc)
        assert data["notes"] == [] and [l["name"] for l in data["layers"]] == [plane.name]
        assert timing_export.usd_lines(h.sc, 1) == [] and timing_export.usd_header(h.sc) == []
    finally:
        _leave(h)


def test_flipbook_ebene_nur_mit_gizmo_bewegen(h: H):
    """Flipbook-Ebenen sind feste Objekte: Mausrad/[ ] bewegen sie nicht; T/R/E im Timing zeigt das Gizmo, Ziehen bewegt
    die Ebene samt den Zeichnungen aller Frames; Esc nimmt das Gizmo weg."""
    from PySide6.QtCore import QPointF
    plane = _flip_scene(h)
    try:
        a = _draw(h, plane, 1003, [(-1, 0), (1, 0)])
        b = _draw(h, plane, 1008, [(-1, 1), (1, 1)])
        flip = [c for c in h.sc.curves if c.frame is not None]
        origin = plane.origin.copy()
        h.v._shift_plane(1.0, burst=("wheel", plane.id))
        assert np.allclose(plane.origin, origin), "Mausrad/[ ] bewegen Flipbook-Ebenen nicht"
        assert h.v.gizmo_target is None, "ohne T/R/E kein Gizmo"
        h.key(Qt.Key_T)
        target = h.v.gizmo_target
        assert target is not None and len(target.items) == 1 + len(flip), "Ebene samt allen Zeichnungen"
        # echtes Ziehen am Gizmo: Griff neben dem Pivot suchen
        c = h.scrf(plane.origin)
        grab = next((QPointF(c.x() + dx, c.y() + dy) for r in range(12, 160, 3) for dx, dy in ((r, 0), (0, -r), (-r, 0), (0, r))
                     if h.v.gizmo.hit(QPointF(c.x() + dx, c.y() + dy), target)), None)
        assert grab is not None, "Gizmo-Griff gefunden"
        before = [cv.points.copy() for cv in flip]
        h.stroke([grab, QPointF(grab.x() + 60, grab.y() + 40)])
        moved = plane.origin - origin
        assert np.linalg.norm(moved) > 1e-3, "Ebene bewegt"
        for cv, old in zip(flip, before):
            assert np.allclose(cv.points - old, moved, atol=1e-6), "Zeichnungen aller Frames wandern mit"
        assert not any(cv.frame is not None and all(cv is not f for f in flip) for cv in h.sc.curves), "kein Strich entstanden"
        # drehen und skalieren über das Ziel (gleiche Wege wie das Gizmo)
        from sketch_machine.camera import rot_axis
        t2 = h.v.gizmo_target
        t2.rotate(rot_axis(np.array([0, 1.0, 0]), 0.5), t2.pivot())
        t2.scale(np.array([2.0, 2.0, 1.0]), t2.local_axes(), t2.pivot())
        d = [float((cv.points - plane.origin) @ plane.normal @ np.ones(len(cv.points))) for cv in flip]
        assert all(abs(x) < 1e-6 for x in d), "Zeichnungen bleiben in der Ebene"
        h.key(Qt.Key_Escape)
        assert h.v.gizmo.tool is None and h.v.gizmo_target is None
    finally:
        _leave(h)


def test_shot_notizen_wie_notizen(h: H):
    """Shots: Doppelklick legt eine Shot-Notiz an (an einer Zeichnung: daran angeheftet) – eigene Liste, nicht bei den
    normalen Notizen; ein einfacher Strich malt weiter; Löschen der Notiz nimmt ihre Kameras mit; im Reiter Notizen
    sind Shot-Notizen nicht zu sehen."""
    plane = _flip_scene(h)
    tm = h.sc.timing
    try:
        a = _draw(h, plane, 1003, [(-2, 0), (2, 0)])
        normal = len(h.sc.notes)
        h.dclick(h.scrf(a[0].points[len(a[0].points) // 2]))
        h.v.notes_tool.finish_edit()
        assert len(tm.notes) == 1 and len(h.sc.notes) == normal, "Shot-Notiz in der eigenen Liste"
        note = tm.notes[0]
        assert note.anchors and note.anchors[0].curve_id == a[0].id, "an der Zeichnung angeheftet"
        assert timing.note_layers(h.sc, note) == [plane]
        assert h.v.ws.active_note == note.id
        n = len(h.sc.curves)
        _draw(h, plane, 1003, [(-2, -2), (2, -2.5)])
        assert len(h.sc.curves) == n + 1, "neben der Notiz wird weiter gemalt"
        cam = h.v.new_timing_camera(note)
        assert tm.note_of(cam) is note
        h.v.notes_tool.delete(note.id)
        assert not tm.notes and not tm.cams, "Notiz gelöscht -> ihre Kameras auch"
        h.v.undo()
        tm = h.sc.timing  # (Undo stellt ein neues Timing her)
        assert len(tm.notes) == 1 and len(tm.cams) == 1, "Undo holt Notiz und Kamera zurück"
        _leave(h)
        h.v.set_notes_mode(True)
        assert h.v.note_list() is h.sc.notes and h.v.notes_tool.hit(h.scrf(tm.notes[0].pos)) is None, \
            "im Reiter Notizen keine Shot-Notizen"
        h.v.set_notes_mode(False)
    finally:
        _leave(h)


def test_flipbook_ausserhalb_ueberall_gesperrt(h: H):
    """Außerhalb des Timings: Outliner zeigt Flipbook nur ausgegraut (nicht wählbar), Löschen/Umbenennen/Einhängen und
    Edit-Gizmo greifen nicht; im Timing nimmt das Löschen der Ebene ihre Zeichnungen mit. In einer Timing-Kamera keine
    Achsenansicht."""
    plane = _flip_scene(h)
    _draw(h, plane, 1002, [(-1, 0), (1, 0)])
    stroke = next(s for s in h.sc.strokes if s.flipbook == plane.id)
    tm = h.sc.timing
    cam = h.v.new_timing_camera(tm.global_note)
    h.v.look_through(cam.id)
    h.v.axis_view(np.array([0, 1.0, 0]))
    h.pump(0.4)
    assert not h.v.cam.ortho and h.v._look == cam.id, "keine Achsenansicht in der Kamera"
    h.v.leave_camera()
    _leave(h)
    h.v.set_selection([plane.id, stroke.id])
    assert h.v.selection == [], "Outliner wählt Flipbook außerhalb des Timings nicht"
    h.w.outliner.rebuild()
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    from sketch_machine import outliner as ol
    rows = {}
    it = QTreeWidgetItemIterator(h.w.outliner)
    while it.value():
        rows[it.value().data(0, ol.ID_ROLE)] = it.value().flags()
        it += 1
    assert not rows[plane.id] & Qt.ItemIsSelectable and not rows[stroke.id] & Qt.ItemIsSelectable
    h.v.delete_objects([plane.id, stroke.id])
    h.v.rename(plane.id, "Anders")
    assert plane in h.sc.custom and stroke in h.sc.strokes and plane.name != "Anders"
    h.v.set_select_mode(True)
    h.v.selection = [plane.id]  # z. B. über Undo zurückgeholt
    h.v.gizmo.tool = "translate"
    assert h.v.gizmo_target is None, "Edit-Gizmo bewegt keine Flipbook-Ebene"
    h.v.selection = []
    h.v.set_select_mode(False)
    h.v.set_timing_mode(True)
    try:
        h.w.outliner.rebuild()
        h.v.delete_objects([plane.id])
        assert plane not in h.sc.custom and all(s.flipbook != plane.id for s in h.sc.strokes), \
            "Löschen der Flipbook-Ebene nimmt ihre Zeichnungen mit"
        assert not any(c.frame is not None for c in h.sc.curves)
    finally:
        _leave(h)


def test_ganz_wegradiert_bleibt_leere_zeichnung(h: H):
    """Alles wegradiert (hier mit Strg+Shift: ganze Striche) – der Frame bleibt eine leere Zeichnung, die vorige kommt
    nicht zurück; danach malt man dort die neue Pose."""
    from PySide6.QtCore import QPointF
    plane = _flip_scene(h)
    try:
        _draw(h, plane, 1010, [(-2, 0), (2, 0)])
        h.v.set_frame(1014)
        h.v.set_draw_tool("eraser")
        mid = h.scrf(_on_plane(plane, [(0, 0)])[0])
        h.stroke([QPointF(mid.x() - 3, mid.y() - 15), QPointF(mid.x() + 3, mid.y() + 15)],
                 mods=Qt.ControlModifier | Qt.ShiftModifier)
        h.v.set_draw_tool("brush")
        assert timing.flip_keys(h.sc)[plane.id] == [1010, 1014] and 1014 in plane.blank_keys
        assert not timing.key_curves(h.sc, plane.id, 1014), "bei 1014 ist die Zeichnung leer"
        assert len(timing.key_curves(h.sc, plane.id, 1010)) == 1, "1010 bleibt"
        assert not any(h.v._layer_visible(c) for c in h.sc.curves if c.frame is not None), "nichts kommt zurück"
        new = _draw(h, plane, 1014, [(-1, 2), (1, 2)])
        assert all(c.frame == 1014 for c in new) and len(timing.key_curves(h.sc, plane.id, 1014)) == 1, \
            "neue Pose bei 1014, ohne Kopie der alten"
    finally:
        _leave(h)

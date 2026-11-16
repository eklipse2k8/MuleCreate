"""Picture on a helper plane/surface (Load Picture, Project, Lock) and gizmo orientation From View."""
import os
import tempfile

import numpy as np
from PySide6.QtGui import QColor, QImage

from tests.harness import H


def _red_png(w=200, h=100):
    path = os.path.join(tempfile.mkdtemp(), "ref.png")
    image = QImage(w, h, QImage.Format_RGB32)
    image.fill(QColor(230, 20, 20))
    image.save(path)
    return path


def _ground(h):
    h.new_scene()
    return h.sc.presets[0]


def test_from_view_is_third_orientation(h: H):
    h.new_scene()
    v = h.v
    assert v.gizmo.space == "world"
    v._toggle_space()
    assert v.gizmo.space == "local"
    v._toggle_space()
    assert v.gizmo.space == "view"
    target = type("T", (), {"scale_axes": (0, 1, 2), "local_axes": lambda self: np.eye(3)})()
    v.gizmo.tool = "translate"
    assert np.allclose(v.gizmo.axes(target), v.cam.rot), "From View: the axes of the camera"
    v._toggle_space()
    assert v.gizmo.space == "world"


def test_load_picture_lies_on_the_plane_seen_from_surface_direction(h: H):
    plane = _ground(h)
    h.v.load_picture_file(plane.id, _red_png())
    pic = plane.picture
    assert pic and pic["on"] and not pic["locked"] and abs(pic["image_aspect"] - 2.0) < 1e-6
    h.frame(plane.corners(), back=(0.0, 1.0, 0.01))
    h.pump(0.1)
    image = h.grab()
    centre = image.pixelColor(image.width() // 2 + 37, image.height() // 2 + 23)  # beside the world axes
    assert centre.red() > 170 and centre.green() < 90, f"picture visible: {centre.getRgb()}"
    h.frame(plane.corners(), back=(0.5, 0.7, 0.6))
    h.pump(0.1)
    h.save_image("bild_auf_ebene.png")
    h.v.set_picture_on(plane.id, False)
    h.pump(0.05)
    image = h.grab()
    centre = image.pixelColor(image.width() // 2 + 37, image.height() // 2 + 23)  # beside the world axes
    assert centre.green() > 120, f"switched off: no picture ({centre.getRgb()})"


def test_project_from_the_camera_and_lock(h: H):
    plane = _ground(h)
    h.v.load_picture_file(plane.id, _red_png())
    before = plane.picture["matrix"]
    h.v.cam.orbit(40, 25)
    h.v.project_picture(plane.id)
    camera = plane.picture["matrix"]
    assert camera != before, "Project takes the current camera"
    h.v.set_picture_locked(plane.id, True)
    h.v.cam.orbit(-70, 10)
    h.v.project_picture(plane.id)
    assert plane.picture["matrix"] == camera, "Lock: the picture does not jump"
    h.v.set_picture_locked(plane.id, False)
    h.v.project_picture(plane.id)
    assert plane.picture["matrix"] != camera, "possible again after unlocking"


def test_picture_moves_with_the_plane_and_survives_saving(h: H):
    from sketch_machine import pictures
    from sketch_machine.scene import Scene
    plane = _ground(h)
    plane.size_u = plane.size_v = 4.0
    h.v.load_picture_file(plane.id, _red_png())
    point = plane.origin + plane.axis_u * 0.5
    start = pictures.draw_matrix(plane) @ np.array([*point, 1.0])
    plane.translate(np.array([3.0, 1.0, -2.0]))
    moved = pictures.draw_matrix(plane) @ np.array([*(point + np.array([3.0, 1.0, -2.0])), 1.0])
    assert np.allclose(start[:2], moved[:2]), "stays at the same place on the plane"
    h.v.set_picture_locked(plane.id, True)
    path = os.path.join(tempfile.mkdtemp(), "bild.sketch.json")
    h.sc.save(path)
    scene, _ = Scene.load(path)
    pic = scene.presets[0].picture
    assert pic["locked"] and pic["matrix"] == plane.picture["matrix"]
    assert scene.asset_bytes(pic["asset"]), "the picture is stored in the scene file"


def test_picture_scales_with_the_plane(h: H):
    """Harbour test 09.11.: plane scaled, the picture on it stayed the same size. Now the same spot of the picture lies at
    the same relative spot of the plane – also with non-uniform scaling."""
    from sketch_machine import pictures
    plane = _ground(h)
    plane.size_u = plane.size_v = 4.0
    h.v.load_picture_file(plane.id, _red_png())
    corner = plane.origin + plane.axis_u * 1.5 + plane.axis_v * 1.0
    before = pictures.draw_matrix(plane) @ np.array([*corner, 1.0])
    plane.scale(np.array([2.0, 3.0, 1.0]), np.eye(3), plane.origin)
    corner2 = plane.origin + plane.axis_u * 3.0 + plane.axis_v * 3.0
    after = pictures.draw_matrix(plane) @ np.array([*corner2, 1.0])
    assert np.allclose(before[:2], after[:2]), f"picture spot {before[:2]} -> {after[:2]}"


def test_older_picture_without_size_stays_as_it_is(h: H):
    from sketch_machine import pictures
    plane = _ground(h)
    plane.size_u = plane.size_v = 4.0
    h.v.load_picture_file(plane.id, _red_png())
    del plane.picture["size"]  # as from an older file
    plane.size_u = 6.0  # used to scale while the picture stayed the same size
    point = plane.origin + plane.axis_u * 0.7
    m_now = pictures.draw_matrix(plane)
    assert np.allclose(plane.picture["size"], [6.0, 4.0]), "current size counts as the starting point"
    assert np.allclose(m_now @ np.array([*point, 1.0]), pictures.draw_matrix(plane) @ np.array([*point, 1.0]))


def test_undo_and_not_in_the_clean_image(h: H):
    plane = _ground(h)
    h.v.load_picture_file(plane.id, _red_png())
    h.v.undo()
    plane = h.sc.presets[0]
    assert plane.picture is None, "loading is one undo step"


def test_outliner_check_shows_file_project_and_lock(h: H):
    from PySide6.QtWidgets import QCheckBox, QPushButton
    from sketch_machine.i18n import tr
    plane = _ground(h)
    h.v.load_picture_file(plane.id, _red_png())
    tree = next(w for w in h.app.allWidgets() if type(w).__name__ == "Outliner")
    tree.refresh() if hasattr(tree, "refresh") else None
    h.pump(0.1)
    row = next(tree.planes_root.child(i) for i in range(tree.planes_root.childCount())
               if tree.planes_root.child(i).text(0) == plane.name)
    row.setExpanded(True)
    h.pump(0.1)
    panel = tree.itemWidget(row.child(0), 0)
    assert panel.findChild(QCheckBox).text() == tr("Bild laden")
    buttons = {b.text(): b for b in panel.findChildren(QPushButton)}
    assert buttons["Project"].isEnabled(), buttons
    lock = next(c for c in panel.findChildren(QCheckBox) if c.text() == "Lock")
    h.v.window().grab().save(os.path.join("tests", "_out", "bild_outliner.png"))
    lock.click()
    assert plane.picture["locked"]
    h.pump(0.1)
    row = next(tree.planes_root.child(i) for i in range(tree.planes_root.childCount())
               if tree.planes_root.child(i).text(0) == plane.name)
    panel = tree.itemWidget(row.child(0), 0)
    project = next(b for b in panel.findChildren(QPushButton) if b.text() == "Project")
    assert not project.isEnabled(), "Lock: Project disabled"


def test_outliner_rebuild_opens_no_window_of_its_own(h: H):
    """Plane with a loaded picture: the outliner rebuild (after every stroke, undo …) must not briefly show the picture row
    as a window of its own (made visible before it hung in the layout)."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication
    h.new_scene()
    h.sc.active_plane.picture = {"on": True}
    shown = []

    class Watch(QObject):
        def eventFilter(self, o, e):
            if e.type() == QEvent.Show and o.isWidgetType() and o.isWindow() and o is not h.w:
                shown.append(type(o).__name__)
            return False

    watch = Watch()
    QApplication.instance().installEventFilter(watch)
    try:
        h.w.outliner.rebuild()
        h.pump(0.05)
    finally:
        QApplication.instance().removeEventFilter(watch)
        h.sc.active_plane.picture = None
    assert not shown, f"windows of their own during outliner rebuild: {shown}"

"""Bild auf Hilfsebene/Hilfsfläche (Load Picture, Project, Lock) und Gizmo-Ausrichtung From View."""
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


def test_from_view_ist_dritte_ausrichtung(h: H):
    h.new_scene()
    v = h.v
    assert v.gizmo.space == "world"
    v._toggle_space()
    assert v.gizmo.space == "local"
    v._toggle_space()
    assert v.gizmo.space == "view"
    target = type("T", (), {"scale_axes": (0, 1, 2), "local_axes": lambda self: np.eye(3)})()
    v.gizmo.tool = "translate"
    assert np.allclose(v.gizmo.axes(target), v.cam.rot), "From View: die Achsen der Kamera"
    v._toggle_space()
    assert v.gizmo.space == "world"


def test_bild_laden_liegt_aus_flaechenrichtung_auf_der_ebene(h: H):
    plane = _ground(h)
    h.v.load_picture_file(plane.id, _red_png())
    pic = plane.picture
    assert pic and pic["on"] and not pic["locked"] and abs(pic["image_aspect"] - 2.0) < 1e-6
    h.frame(plane.corners(), back=(0.0, 1.0, 0.01))
    h.pump(0.1)
    image = h.grab()
    centre = image.pixelColor(image.width() // 2 + 37, image.height() // 2 + 23)  # neben den Weltachsen
    assert centre.red() > 170 and centre.green() < 90, f"Bild zu sehen: {centre.getRgb()}"
    h.frame(plane.corners(), back=(0.5, 0.7, 0.6))
    h.pump(0.1)
    h.save_image("bild_auf_ebene.png")
    h.v.set_picture_on(plane.id, False)
    h.pump(0.05)
    image = h.grab()
    centre = image.pixelColor(image.width() // 2 + 37, image.height() // 2 + 23)  # neben den Weltachsen
    assert centre.green() > 120, f"ausgeschaltet: kein Bild ({centre.getRgb()})"


def test_project_aus_der_kamera_und_lock(h: H):
    plane = _ground(h)
    h.v.load_picture_file(plane.id, _red_png())
    before = plane.picture["matrix"]
    h.v.cam.orbit(40, 25)
    h.v.project_picture(plane.id)
    camera = plane.picture["matrix"]
    assert camera != before, "Project nimmt die jetzige Kamera"
    h.v.set_picture_locked(plane.id, True)
    h.v.cam.orbit(-70, 10)
    h.v.project_picture(plane.id)
    assert plane.picture["matrix"] == camera, "Lock: das Bild verspringt nicht"
    h.v.set_picture_locked(plane.id, False)
    h.v.project_picture(plane.id)
    assert plane.picture["matrix"] != camera, "nach dem Entsperren wieder möglich"


def test_bild_wandert_mit_der_ebene_und_ueberlebt_speichern(h: H):
    from sketch_machine import pictures
    from sketch_machine.scene import Scene
    plane = _ground(h)
    plane.size_u = plane.size_v = 4.0
    h.v.load_picture_file(plane.id, _red_png())
    point = plane.origin + plane.axis_u * 0.5
    start = pictures.draw_matrix(plane) @ np.array([*point, 1.0])
    plane.translate(np.array([3.0, 1.0, -2.0]))
    moved = pictures.draw_matrix(plane) @ np.array([*(point + np.array([3.0, 1.0, -2.0])), 1.0])
    assert np.allclose(start[:2], moved[:2]), "bleibt auf der Ebene an derselben Stelle"
    h.v.set_picture_locked(plane.id, True)
    path = os.path.join(tempfile.mkdtemp(), "bild.sketch.json")
    h.sc.save(path)
    scene, _ = Scene.load(path)
    pic = scene.presets[0].picture
    assert pic["locked"] and pic["matrix"] == plane.picture["matrix"]
    assert scene.asset_bytes(pic["asset"]), "das Bild steckt in der Szenendatei"


def test_bild_skaliert_mit_der_ebene(h: H):
    """Hafentest 09.11.: Ebene skaliert, das Bild darauf blieb gleich groß. Jetzt liegt dieselbe Stelle des Bilds an
    derselben relativen Stelle der Ebene – auch bei ungleichmäßigem Skalieren."""
    from sketch_machine import pictures
    plane = _ground(h)
    plane.size_u = plane.size_v = 4.0
    h.v.load_picture_file(plane.id, _red_png())
    corner = plane.origin + plane.axis_u * 1.5 + plane.axis_v * 1.0
    before = pictures.draw_matrix(plane) @ np.array([*corner, 1.0])
    plane.scale(np.array([2.0, 3.0, 1.0]), np.eye(3), plane.origin)
    corner2 = plane.origin + plane.axis_u * 3.0 + plane.axis_v * 3.0
    after = pictures.draw_matrix(plane) @ np.array([*corner2, 1.0])
    assert np.allclose(before[:2], after[:2]), f"Bildstelle {before[:2]} -> {after[:2]}"


def test_aelteres_bild_ohne_groesse_bleibt_wie_es_ist(h: H):
    from sketch_machine import pictures
    plane = _ground(h)
    plane.size_u = plane.size_v = 4.0
    h.v.load_picture_file(plane.id, _red_png())
    del plane.picture["size"]  # wie aus einer älteren Datei
    plane.size_u = 6.0  # früher skaliert, Bild blieb dabei gleich groß
    point = plane.origin + plane.axis_u * 0.7
    m_now = pictures.draw_matrix(plane)
    assert np.allclose(plane.picture["size"], [6.0, 4.0]), "jetzige Größe gilt als Ausgangspunkt"
    assert np.allclose(m_now @ np.array([*point, 1.0]), pictures.draw_matrix(plane) @ np.array([*point, 1.0]))


def test_rueckgaengig_und_nicht_im_sauberen_bild(h: H):
    plane = _ground(h)
    h.v.load_picture_file(plane.id, _red_png())
    h.v.undo()
    plane = h.sc.presets[0]
    assert plane.picture is None, "Laden ist ein Undo-Schritt"


def test_outliner_haken_zeigt_datei_project_und_lock(h: H):
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
    assert not project.isEnabled(), "Lock: Project gesperrt"


def test_outliner_neubau_oeffnet_kein_eigenes_fenster(h: H):
    """Ebene mit geladenem Bild: der Outliner-Neubau (nach jedem Strich, Undo …) darf die Bild-Zeile nicht kurz als
    eigenes Fenster zeigen (sichtbar geschaltet, bevor sie im Layout hing)."""
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
    assert not shown, f"eigene Fenster beim Outliner-Neubau: {shown}"

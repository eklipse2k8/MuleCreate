"""Tempo: was ein Bild ohne Änderung an der Szene nicht neu rechnen darf – und dass es trotzdem richtig aussieht."""
import numpy as np
from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from tests.harness import H, Qt
from tests.test_material import _square


def _orbit(h: H, steps=6):
    """Alt + linke Maustaste ziehen (Drehen), jedes Bild wie in der App (ohne erzwungenen Neubau)."""
    v = h.v

    def send(kind, pos, buttons):
        button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
        h.app.sendEvent(v, QMouseEvent(kind, pos, pos, button, buttons, Qt.AltModifier))

    send(QEvent.MouseButtonPress, QPointF(500, 400), Qt.LeftButton)
    for i in range(steps):
        send(QEvent.MouseMove, QPointF(500 + 6 * (i + 1), 400 + 2 * i), Qt.LeftButton)
        img = QOpenGLWidget.grabFramebuffer(v)
    assert v._mode == "orbit", f"Ziehen mit Alt sollte drehen (Modus {v._mode})"
    return img, lambda: send(QEvent.MouseButtonRelease, QPointF(540, 410), Qt.NoButton)


def test_drehen_baut_striche_und_flaechen_nicht_neu(h: H):
    """Drehen ändert nur die Kamera: Zeichenlisten und Flächenabgleich laufen nicht je Bild (Drehen kostet sonst bei
    vielen Linien/Flächen ein Vielfaches), und das Bild ist trotzdem genau das frisch gebaute."""
    h.new_scene()
    _square(h, y=0.0, x0=-1.0, size=2.0)
    h.sc.add_curve(np.linspace([-1.0, 0.5, 0.0], [1.0, 0.5, 1.0], 12), None, np.full(12, 0.03))
    h.v._changed()
    h.camera([0.0, 0.0, 0.5], 6, [0.3, 0.8, 0.5])
    v, sc = h.v, h.sc
    calls = []
    orig = (v._surface_draw_list, v._stroke_draw_list, sc.sync_lofts)
    v._surface_draw_list = lambda: calls.append("flaechen") or orig[0]()
    v._stroke_draw_list = lambda: calls.append("striche") or orig[1]()
    sc.sync_lofts = lambda *a, **k: calls.append("sync") or orig[2](*a, **k)
    try:
        QOpenGLWidget.grabFramebuffer(v)  # letztes Bild vor dem Drehen
        calls.clear()
        cached, release = _orbit(h)
        # einmal beim Ansetzen (Klick, Moduswechsel), danach in keinem der 6 Bilder mehr
        many = {k: calls.count(k) for k in set(calls) if calls.count(k) > 1}
        assert not many, f"beim Drehen je Bild neu gebaut: {many}"
        fresh = v.grabFramebuffer()  # erzwingt Neubau
        n = h.diff(cached, fresh, threshold=2)
        assert n == 0, f"Bild beim Drehen weicht vom frisch gebauten ab ({n} Pixel)"
        release()
    finally:
        v._surface_draw_list, v._stroke_draw_list, sc.sync_lofts = orig


def test_kamera_ansetzen_und_loslassen_baut_nichts_neu(h: H):
    """Alt+Klick, Drehen, Loslassen: kein Neubau der Zeichenlisten und kein Flächenabgleich – auch nicht beim
    Ansetzen (sonst ruckt das erste Bild bei großen Szenen spürbar) und auch nicht in den anderen Viewports."""
    h.new_scene()
    _square(h, y=0.0, x0=-1.0, size=2.0)
    h.sc.add_curve(np.linspace([-1.0, 0.5, 0.0], [1.0, 0.5, 1.0], 12), None, np.full(12, 0.03))
    h.v._changed()
    h.camera([0.0, 0.0, 0.5], 6, [0.3, 0.8, 0.5])
    v, sc = h.v, h.sc
    calls = []
    orig = (v._surface_draw_list, v._scene_stroke_list, sc.sync_lofts)
    v._surface_draw_list = lambda: calls.append("flaechen") or orig[0]()
    v._scene_stroke_list = lambda: calls.append("striche") or orig[1]()
    sc.sync_lofts = lambda *a, **k: calls.append("sync") or orig[2](*a, **k)
    try:
        QOpenGLWidget.grabFramebuffer(v)
        calls.clear()
        _, release = _orbit(h)
        release()
        QOpenGLWidget.grabFramebuffer(v)
        assert not calls, f"Kamera ansetzen/loslassen hat neu gebaut: {calls}"
        assert v._mode is None, f"nach dem Loslassen kein Modus mehr ({v._mode})"
    finally:
        v._surface_draw_list, v._scene_stroke_list, sc.sync_lofts = orig


def test_hover_baut_nur_bei_wechsel_neu(h: H):
    """Edit-Modus: Maus ohne Taste bewegen baut Striche/Flächen nur neu, wenn sich die hervorgehobene Kante ändert –
    die Einfärbung beim Darüberfahren kommt trotzdem (und geht wieder)."""
    h.new_scene()
    h.sc.new_stroke()
    h.sc.add_curve(np.linspace([-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], 20), None, np.full(20, 0.03))
    line = h.sc.curves[-1]
    h.v._changed()
    h.camera([0.0, 0.0, 0.0], 4, [0.0, 1.0, 0.02])
    h.edit_mode("edge")
    v = h.v

    def move(p):
        h.app.sendEvent(v, QMouseEvent(QEvent.MouseMove, p, p, Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        return QOpenGLWidget.grabFramebuffer(v)

    on = QPointF(h.scr(line.points[10]))
    off = on + QPointF(0, 120)
    base = move(off)
    move(off + QPointF(3, 0))
    assert not v._lists_dirty, "Bewegen ohne Hover-Wechsel: keine neuen Zeichenlisten"
    hot = move(on)
    assert v._select_hover is not None, "über der Linie: Hover"
    assert h.diff(hot, base) > 0, "Linie unter dem Cursor wird hervorgehoben"
    cold = move(off)
    assert v._select_hover is None
    assert h.diff(cold, base) == 0, "Hervorhebung verschwindet wieder"
    h.draw_mode()


def test_zeichnen_baut_nur_den_strich_neu(h: H):
    """Während des Strichs ändert sich nur der laufende Strich: Flächenabgleich und die Linien der Szene laufen nicht je
    Bild (in glider_owl 42 -> 11 ms je Bild) – und das Bild mitten im Strich ist genau das frisch gebaute; nach dem
    Loslassen ist der Strich eine Linie der Szene."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    h.new_scene()
    _square(h, y=0.0, x0=-1.0, size=2.0)
    h.sc.add_curve(np.linspace([-1.0, 0.5, 0.0], [1.0, 0.5, 1.0], 12), None, np.full(12, 0.03))
    h.v._changed()
    h.camera([0.0, 0.0, 0.5], 6, [0.3, 0.8, 0.5])
    v, sc = h.v, h.sc
    sc.activate(sc.presets[1] if len(sc.presets) > 1 else sc.presets[0])
    sc.new_stroke()
    v._changed()
    QOpenGLWidget.grabFramebuffer(v)
    n_lines = len(h.curves())
    calls = []
    orig = (v._surface_draw_list, v._scene_stroke_list, sc.sync_lofts)
    v._surface_draw_list = lambda: calls.append("flaechen") or orig[0]()
    v._scene_stroke_list = lambda: calls.append("striche") or orig[1]()
    sc.sync_lofts = lambda *a, **k: calls.append("sync") or orig[2](*a, **k)
    try:
        c = QPointF(v.width() / 2, v.height() / 2)
        pts = [c + QPointF(-120 + 8 * k, 30 * np.sin(k / 4)) for k in range(30)]
        h.move(pts[0])
        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pts[0].toPoint())
        for p in pts[1:]:
            h.move(p, Qt.LeftButton)
            cached = QOpenGLWidget.grabFramebuffer(v)
        assert v._mode == "draw", f"Strich läuft ({v._mode})"
        many = {k: calls.count(k) for k in set(calls) if calls.count(k) > 2}
        assert not many, f"beim Zeichnen je Bild neu gebaut: {many}"
        fresh = v.grabFramebuffer()  # erzwingt Neubau
        n = h.diff(cached, fresh, threshold=2)
        assert n == 0, f"Bild mitten im Strich weicht vom frisch gebauten ab ({n} Pixel)"
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pts[-1].toPoint())
        h.pump(0.02)
        after = QOpenGLWidget.grabFramebuffer(v)
        assert len(h.curves()) == n_lines + 1, "der Strich ist eine Linie der Szene"
        assert h.diff(after, v.grabFramebuffer(), threshold=2) == 0, "nach dem Loslassen: Bild = frisch gebaut"
    finally:
        v._surface_draw_list, v._scene_stroke_list, sc.sync_lofts = orig

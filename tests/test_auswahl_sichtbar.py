"""Gewählte Linien leuchten in der Auswahlfarbe – auch hinter einer Hilfsebene und im Licht-Modus (Hafentest 10.11.:
eine gewählte Pinsellinie hinter der aktiven Ebene war dunkelbraun, kaum zu erkennen). Im Kantenmodus haben die kleinen
Punkte einen Hof in Hintergrundfarbe, damit sie auch auf einer weißen Linie zu sehen sind."""
import numpy as np
from PySide6.QtGui import QColor

from sketch_machine import theme
from tests.harness import H, line


def _near(img, target, tol=28):
    """Zahl der Pixel nahe der Farbe target (QColor)."""
    rgba = img.convertToFormat(img.Format.Format_RGBA8888)  # festhalten: der Puffer gehört dem Bild
    w, h = rgba.width(), rgba.height()
    buf = np.frombuffer(rgba.constBits(), np.uint8)[:h * rgba.bytesPerLine()].reshape(h, rgba.bytesPerLine())[:, :w * 4]
    buf = buf.reshape(h, w, 4).copy()
    want = np.array([target.red(), target.green(), target.blue()], int)
    return int((np.abs(buf[..., :3].astype(int) - want).max(axis=2) <= tol).sum())


def _scene(h):
    h.new_scene()
    sc = h.sc
    st = sc.new_stroke()
    sc.add_curve(line([-1.5, 0, 0], [1.5, 0, 0], 16), None)
    c = st.curves[-1]
    c.style, c.color = "brush", (1.0, 1.0, 1.0)
    c.widths = np.full(len(c.points), 0.08)
    # Hilfsebene zwischen Kamera und Linie (die Kamera schaut von +z)
    sc.new_plane(np.array([0.0, 0.0, 1.0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0]))
    h.camera([0.0, 0.0, 0.0], 6, [0.0, 0.0, 1.0])
    return sc, st, c


def test_gewaehlte_linie_leuchtet_auch_hinter_einer_ebene(h: H):
    sc, st, c = _scene(h)
    h.edit_mode("edge")
    h.v.edge_selection = [("line", st.id, c.id)]
    h.v._changed()
    img = h.grab()
    n = _near(img, QColor(theme.SELECTED_STROKE_COLOR))
    assert n > 150, f"gewählte Linie in voller Auswahlfarbe ({n} Pixel)"
    h.v.edge_selection = []
    h.v._changed()
    assert _near(h.grab(), QColor(theme.SELECTED_STROKE_COLOR)) < n // 10, "abgewählt: keine Auswahlfarbe mehr"


def test_gewaehlte_linie_leuchtet_im_licht_modus(h: H):
    sc, st, c = _scene(h)
    on = h.v.ws.light_on
    try:
        h.v.ws.light_on = True
        h.edit_mode("edge")
        h.v.edge_selection = [("line", st.id, c.id)]
        h.v._changed()
        n = _near(h.grab(), QColor(theme.SELECTED_STROKE_COLOR))
        assert n > 150, f"Licht und Schatten verdunkeln die Auswahlfarbe nicht ({n} Pixel)"
    finally:
        h.v.ws.light_on = on


def test_punkte_im_kantenmodus_haben_einen_hof(h: H):
    sc, st, c = _scene(h)
    sc.custom.clear()
    c.color = tuple(theme.rgb(theme.STROKE_COLOR))  # Linie in Strichfarbe: genau die Farbe der kleinen Punkte
    h.edit_mode("edge")
    h.v.edge_selection = []
    h.v._changed()
    img = h.grab()
    q = h.scr(c.points[0])  # Linienende: Punkt-Symbol auf der Linie
    paper, ink = QColor(theme.PAPER), QColor(theme.STROKE_COLOR)
    dist = lambda px, col: max(abs(px.red() - col.red()), abs(px.green() - col.green()), abs(px.blue() - col.blue()))
    inside = img.pixelColor(q.x() + 3, q.y())  # ein Stück die Linie entlang: dort liegt der Hof
    assert dist(inside, paper) < dist(inside, ink), "Hof in Hintergrundfarbe trennt den Punkt von seiner Linie"

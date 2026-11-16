"""Selected lines glow in the selection colour - also behind a helper plane and in light mode (harbour test 10.11.:
a selected brush line behind the active plane was dark brown, hardly visible). In edge mode the small
points have a halo in background colour so that they are visible on a white line too."""
import numpy as np
from PySide6.QtGui import QColor

from sketch_machine import theme
from tests.harness import H, line


def _near(img, target, tol=28):
    """Number of pixels close to the colour target (QColor)."""
    rgba = img.convertToFormat(img.Format.Format_RGBA8888)  # hold on to it: the buffer belongs to the image
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
    # helper plane between camera and line (the camera looks from +z)
    sc.new_plane(np.array([0.0, 0.0, 1.0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0]))
    h.camera([0.0, 0.0, 0.0], 6, [0.0, 0.0, 1.0])
    return sc, st, c


def test_selected_line_glows_even_behind_a_plane(h: H):
    sc, st, c = _scene(h)
    h.edit_mode("edge")
    h.v.edge_selection = [("line", st.id, c.id)]
    h.v._changed()
    img = h.grab()
    n = _near(img, QColor(theme.SELECTED_STROKE_COLOR))
    assert n > 150, f"selected line in full selection colour ({n} pixels)"
    h.v.edge_selection = []
    h.v._changed()
    assert _near(h.grab(), QColor(theme.SELECTED_STROKE_COLOR)) < n // 10, "deselected: no selection colour any more"


def test_selected_line_glows_in_light_mode(h: H):
    sc, st, c = _scene(h)
    on = h.v.ws.light_on
    try:
        h.v.ws.light_on = True
        h.edit_mode("edge")
        h.v.edge_selection = [("line", st.id, c.id)]
        h.v._changed()
        n = _near(h.grab(), QColor(theme.SELECTED_STROKE_COLOR))
        assert n > 150, f"light and shadow do not darken the selection colour ({n} pixels)"
    finally:
        h.v.ws.light_on = on


def test_points_in_edge_mode_have_a_halo(h: H):
    sc, st, c = _scene(h)
    sc.custom.clear()
    c.color = tuple(theme.rgb(theme.STROKE_COLOR))  # line in stroke colour: exactly the colour of the small points
    h.edit_mode("edge")
    h.v.edge_selection = []
    h.v._changed()
    img = h.grab()
    q = h.scr(c.points[0])  # line end: point symbol on the line
    paper, ink = QColor(theme.PAPER), QColor(theme.STROKE_COLOR)
    dist = lambda px, col: max(abs(px.red() - col.red()), abs(px.green() - col.green()), abs(px.blue() - col.blue()))
    inside = img.pixelColor(q.x() + 3, q.y())  # a bit along the line: there lies the halo
    assert dist(inside, paper) < dist(inside, ink), "halo in background colour separates the point from its line"

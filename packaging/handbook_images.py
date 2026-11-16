"""Pictures for AI_HANDBOOK.md: the real program (English UI, light theme) set up step by step like a user would,
screenshot of the whole window, red marks with numbers on what matters, a caption bar at the bottom.
Written to docs/handbook/*.png; rerun after UI changes.

Call in the repo root:  .venv/Scripts/python.exe packaging/handbook_images.py [name …]   (no name: all)
"""
import math
import os
import sys

os.environ["MULE_LANG"] = "en"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "handbook")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF  # noqa: E402
from PySide6.QtWidgets import QDockWidget, QToolBar  # noqa: E402

from tests.harness import H, line  # noqa: E402  (redirects the settings: the real ones stay untouched)

RED = QColor(220, 30, 40)
SIZE = (1500, 940)
WIDTH = 1600  # width of every picture
BG, PANEL, LINE, TEXT, DIM, ACCENT = (QColor(c) for c in ("#1e1e1f", "#262627", "#3a3a3d", "#e2dfda", "#a9a5a0",
                                                           "#d08a5e"))  # as sketch_machine/ui.py, text a bit lighter
FONT = "Segoe UI"


INDEX = os.path.join(OUT, "pictures.json")  # title, sentence and legend per picture – for the introduction pages


def _record(name, title, summary, legend, steps):
    import json
    try:
        with open(INDEX, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data[name] = {"file": name + ".png", "title": title, "summary": summary,
                  "steps": [t for t in steps if t], "legend": [[n, t] for n, t in legend]}
    with open(INDEX, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(dict(sorted(data.items())), fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def _font(px, bold=False):
    f = QFont(FONT)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


class Shot:
    """One picture: one or more panels (window screenshots, optionally cropped, scaled down side by side) with red
    marks – box or ring with a number, arrow, short label – and below a legend in the colours of the UI that
    explains the numbers (at least 15 % of the height)."""

    def __init__(self, h):
        self.h = h
        self.panels = []
        self.marks = []

    # --- positions in window pixels ---
    def widget_rect(self, widget, pad=3, base=None):
        p = widget.mapTo(base or self.h.w, QPoint(0, 0))
        return QRect(p.x() - pad, p.y() - pad, widget.width() + 2 * pad, widget.height() + 2 * pad)

    def view_point(self, world):
        """World point → window pixel (through the viewport)."""
        q = self.h.scrf(world)
        p = self.h.v.mapTo(self.h.w, QPoint(0, 0))
        return QPointF(p.x() + q.x(), p.y() + q.y())

    # --- marks for the next snap ---
    def box(self, rect, number, at="tl"):
        """at: where the number sits – tl/tr/bl/br (corner), r/l/t/b (beside the middle), or a window point."""
        self.marks.append(("box", QRectF(rect), number, at))

    def ring(self, point, number, radius=24, at="tr"):
        self.marks.append(("ring", (QPointF(point), radius), number, at))

    def arrow(self, a, b, number=None):
        self.marks.append(("arrow", (QPointF(a), QPointF(b)), number, None))

    def label(self, point, text, align="r"):
        """Short text on a dark tag next to point (r: to the right, l: left, t: above, b: below)."""
        self.marks.append(("label", (QPointF(point), text), None, align))

    def snap(self, title="", crop=None, widget=None, settle=0.15):
        """Screenshot of the window (or of widget, e.g. a dialog) now, with the marks given so far; crop: rect to keep.
        settle: waiting time – in the middle of a stroke keep it tiny, waiting counts as holding still."""
        self.h.pump(settle)
        self.h.v.update()
        self.h.pump(settle)
        img = (widget or self.h.w).grab().toImage()
        if widget is None:  # the window grab misses what the viewport paints over its 3D image (gizmo, points, notes)
            fb = self.h.v.grabFramebuffer()
            pos = self.h.v.mapTo(self.h.w, QPoint(0, 0))
            p = QPainter(img)
            p.drawImage(QRectF(pos.x(), pos.y(), self.h.v.width(), self.h.v.height()), fb)
            p.end()
        crop = QRect(crop) if crop is not None else QRect(0, 0, img.width(), img.height())
        self.panels.append({"img": img.copy(crop), "crop": crop, "title": title, "marks": self.marks})
        self.marks = []

    # --- the picture ---
    def save(self, name, title, legend, summary="", cols=None, index=True):
        """title and summary (one sentence: what the picture explains) on top, the panels in a grid (more than three:
        two per row), the legend below. legend: [(number or None, text)]."""
        if self.marks or not self.panels:
            self.snap()
        n = len(self.panels)
        margin, gap = 20, 18
        cols = cols or (n if n <= 3 else 2)
        grid_rows = -(-n // cols)
        cell = (WIDTH - 2 * margin - gap * (cols - 1)) / cols
        max_h = 800 if grid_rows == 1 else 500
        scales = [min(cell / pn["img"].width(), max_h / pn["img"].height()) for pn in self.panels]
        head = 40 if any(pn["title"] for pn in self.panels) else 0
        probe = QImage(10, 10, QImage.Format_RGB32)
        pp = QPainter(probe)
        pp.setFont(_font(21))
        summary_h = pp.boundingRect(QRectF(0, 0, WIDTH - 2 * margin, 400), Qt.TextWordWrap, summary).height() if summary else 0
        pp.end()
        header = margin + 38 + (summary_h + 8 if summary else 0) + 14
        row_h = [head + max(self.panels[i].get("img").height() * scales[i] for i in range(r * cols, min(n, (r + 1) * cols)))
                 for r in range(grid_rows)]
        top = header + sum(row_h) + gap * (grid_rows - 1) + margin
        lcols = 2 if len(legend) > 3 else 1
        lrows = -(-len(legend) // lcols)
        legend_h = max(24 + lrows * 38 + 20, top * 0.15 / 0.85)
        out = QImage(WIDTH, int(top + legend_h), QImage.Format_RGB32)
        out.fill(BG)
        p = QPainter(out)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        p.setPen(ACCENT)
        p.setFont(_font(28, True))
        p.drawText(QRectF(margin, margin - 4, WIDTH - 2 * margin, 40), Qt.AlignLeft | Qt.AlignVCenter, title)
        if summary:
            p.setPen(TEXT)
            p.setFont(_font(21))
            p.drawText(QRectF(margin, margin + 40, WIDTH - 2 * margin, summary_h + 4), Qt.TextWordWrap, summary)
        p.fillRect(QRectF(margin, header - 8, WIDTH - 2 * margin, 1), LINE)
        y_row = header
        for i, (pn, sc) in enumerate(zip(self.panels, scales)):
            r, c = divmod(i, cols)
            if c == 0 and r > 0:
                y_row += row_h[r - 1] + gap
            w, hgt = pn["img"].width() * sc, pn["img"].height() * sc
            x0 = margin + c * (cell + gap) + (cell - w) / 2
            y0 = y_row + head
            if pn["title"]:
                p.setPen(ACCENT)
                p.setFont(_font(19, True))
                p.drawText(QRectF(x0, y_row, w, head - 8), Qt.AlignLeft | Qt.AlignVCenter, pn["title"])
            p.drawImage(QRectF(x0, y0, w, hgt), pn["img"])
            p.setPen(QPen(LINE, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x0, y0, w, hgt))
            to = lambda q, cr=pn["crop"], x0=x0, y0=y0, sc=sc: QPointF(x0 + (q.x() - cr.x()) * sc, y0 + (q.y() - cr.y()) * sc)
            self._bounds = QRectF(x0, y0, w, hgt)
            p.save()
            p.setClipRect(QRectF(x0 - 14, y0 - 14, w + 28, hgt + 28))
            for kind, geo, number, at in pn["marks"]:
                self._mark(p, kind, geo, number, at, to, sc)
            p.restore()
        # legend
        y = top
        p.fillRect(QRectF(0, y, WIDTH, legend_h), PANEL)
        p.fillRect(QRectF(0, y, WIDTH, 2), ACCENT)
        col_w = (WIDTH - 2 * margin) / lcols
        for k, (number, text) in enumerate(legend):
            c, r = k // lrows, k % lrows
            x, yy = margin + c * col_w, y + 24 + r * 38
            if number is not None:
                self._badge(p, QPointF(x + 18, yy + 15), number)
            p.setPen(TEXT)
            p.setFont(_font(18))
            p.drawText(QRectF(x + 42, yy, col_w - 52, 32), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.end()
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, name + ".png")
        out.save(path)
        print("written", os.path.relpath(path, ROOT))
        if index:  # not for pictures outside the introduction (the README picture)
            _record(name, title, summary, legend, [pn["title"] for pn in self.panels])
        self.panels = []

    def _mark(self, p, kind, geo, number, at, to, sc):
        if isinstance(at, (QPointF, QPoint)):  # a fixed number position is a window point too
            at = to(QPointF(at))
        pen = QPen(RED, 3.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if kind == "box":
            r = QRectF(to(geo.topLeft()), to(geo.bottomRight()))
            p.drawRoundedRect(r, 6, 6)
            self._badge(p, self._anchor(r, at), number)
        elif kind == "ring":
            centre, radius = to(geo[0]), geo[1]
            p.drawEllipse(centre, radius, radius)
            k = radius * 0.72
            self._badge(p, self._anchor(QRectF(centre.x() - k, centre.y() - k, 2 * k, 2 * k), at), number)
        elif kind == "arrow":
            a, b = to(geo[0]), to(geo[1])
            p.drawLine(a, b)
            ang = math.atan2(b.y() - a.y(), b.x() - a.x())
            head = [QPointF(b.x() - 16 * math.cos(ang - s), b.y() - 16 * math.sin(ang - s)) for s in (0.45, -0.45)]
            p.setBrush(RED)
            p.drawPolygon(QPolygonF([b, head[0], head[1]]))
            if number is not None:
                self._badge(p, QPointF((a.x() + b.x()) / 2 + 20, (a.y() + b.y()) / 2), number)
        elif kind == "label":
            point, text = to(geo[0]), geo[1]
            p.setFont(_font(16, True))
            fm = p.fontMetrics()
            w, hgt = fm.horizontalAdvance(text) + 20, fm.height() + 10
            off = {"r": (14, -hgt / 2), "l": (-14 - w, -hgt / 2), "t": (-w / 2, -14 - hgt), "b": (-w / 2, 14)}[at]
            r = QRectF(point.x() + off[0], point.y() + off[1], w, hgt)
            bd = getattr(self, "_bounds", None)
            if bd is not None:  # keep the tag inside its panel
                r.moveLeft(min(max(r.left(), bd.left() + 6), bd.right() - w - 6))
                r.moveTop(min(max(r.top(), bd.top() + 6), bd.bottom() - hgt - 6))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(30, 30, 31, 235))
            p.drawRoundedRect(r, 6, 6)
            p.fillRect(QRectF(r.left(), r.top() + 5, 4, r.height() - 10), RED)
            p.setPen(QColor(245, 243, 240))
            p.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, text)

    @staticmethod
    def _anchor(rect, at):
        if isinstance(at, (QPointF, QPoint)):
            return QPointF(at)
        c = rect.center()
        return {"tl": rect.topLeft(), "tr": rect.topRight(), "bl": rect.bottomLeft(), "br": rect.bottomRight(),
                "r": QPointF(rect.right() + 16, c.y()), "l": QPointF(rect.left() - 16, c.y()),
                "t": QPointF(c.x(), rect.top() - 16), "b": QPointF(c.x(), rect.bottom() + 16)}[at]

    @staticmethod
    def _badge(p, centre, number):
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(RED)
        p.drawEllipse(centre, 14, 14)
        p.setPen(QColor(255, 255, 255))
        p.setFont(_font(16, True))
        p.drawText(QRectF(centre.x() - 14, centre.y() - 14, 28, 28), Qt.AlignCenter, str(number))


def _action_rect(s, toolbar, action, pad=2):
    return s.widget_rect(toolbar.widgetForAction(action), pad)


def _status_rect(s):
    return s.widget_rect(s.h.w.statusBar(), pad=-1)


def _dock(h, title):
    return next(d for d in h.w.findChildren(QDockWidget) if d.windowTitle() == title and d.isVisible())


def _toolbar(h, area):
    return next(t for t in h.w.findChildren(QToolBar) if h.w.toolBarArea(t) == area and t.isVisible())


def overview(h, s):
    """The window: modes and display buttons on top, tools on the left, viewport, outliner, status line."""
    h.load("tests/scenes/teacup.sketch.json")
    h.draw_mode()
    top = s.widget_rect(_toolbar(h, Qt.TopToolBarArea), pad=-2)
    s.box(top, 1, at=QPointF(top.left() + 330, top.center().y()))
    s.box(s.widget_rect(_toolbar(h, Qt.LeftToolBarArea), pad=-2), 2, at=QPointF(24, 800))
    view = s.widget_rect(h.v, pad=-8)
    s.box(view, 3, at=QPointF(view.left() + 40, view.top() + 34))
    out = s.widget_rect(_dock(h, "Outliner"), pad=-2)
    s.box(out, 4, at=QPointF(out.right() - 26, out.top() + 44))
    status = _status_rect(s)
    s.box(status, 5, at=QPointF(status.right() - 30, status.top() - 18))
    s.save("01_overview", "The window", [
        (1, "Modes Draw · Edit · Notes · Shots (Tab, N), display buttons on the right"),
        (2, "Tools of the current mode (pen, brush, eraser …)"),
        (3, "Viewport: Alt or Space + mouse buttons move the camera"),
        (4, "Outliner: planes, stroke objects, surfaces, nulls"),
        (5, "Status line: what is active and which keys work right now")],
        "Mule has four modes: Draw puts lines down, Edit changes them, Notes holds prompts for the AI, Shots shows "
        "timing. Any question about Mule: give the file AI_HANDBOOK.md to your AI and ask it.")


README_SCENE = os.environ.get("MULE_README_SCENE", "")  # the Alpaca Monowheel scene (.mule) – not in the repository


def readme_overview(h, s):
    """The window as on the README page: the Alpaca Monowheel scene (the first project made entirely in Mule) with
    its saved camera, notes and drawing aids hidden. Not part of the introduction (that keeps 01_overview)."""
    if not os.path.isfile(README_SCENE):
        raise FileNotFoundError("set MULE_README_SCENE to the Alpaca Monowheel scene (the example scene's .mule)")
    h.load(README_SCENE)
    for o in (*h.sc.nulls, *h.sc.strokes, *h.sc.surfaces):  # public pictures are English (the file stays as it is)
        o.name = o.name.replace("Alpaka", "Alpaca")
    h.w.outliner.rebuild()
    h.draw_mode()
    h.w.notes_visible_action.setChecked(False)
    h.w.planes_action.setChecked(False)
    h.pump(0.3)
    h.grab()
    top = s.widget_rect(_toolbar(h, Qt.TopToolBarArea), pad=-2)
    s.box(top, 1, at=QPointF(top.left() + 330, top.center().y()))
    s.box(s.widget_rect(_toolbar(h, Qt.LeftToolBarArea), pad=-2), 2, at=QPointF(24, 800))
    view = s.widget_rect(h.v, pad=-8)
    s.box(view, 3, at=QPointF(view.left() + 40, view.top() + 34))
    out = s.widget_rect(_dock(h, "Outliner"), pad=-2)
    s.box(out, 4, at=QPointF(out.right() - 26, out.top() + 44))
    status = _status_rect(s)
    s.box(status, 5, at=QPointF(status.right() - 30, status.top() - 18))
    s.save("readme_overview", "The window", [
        (1, "Modes Draw · Edit · Notes · Shots (Tab, N), display buttons on the right"),
        (2, "Tools of the current mode (pen, brush, eraser …)"),
        (3, "Viewport: Alt or Space + mouse buttons move the camera"),
        (4, "Outliner: planes, stroke objects, surfaces, nulls"),
        (5, "Status line: what is active and which keys work right now")],
        "The Alpaca Monowheel, sketched entirely in Mule. Four modes: Draw puts lines down, Edit changes them, Notes "
        "holds prompts for the AI, Shots shows timing.", index=False)


def _rect_scene(h):
    """Rectangle of four connected lines on the ground, seen from the front at an angle."""
    sc = h.new_scene()
    sc.new_stroke()
    c = [[0, 0, 0], [2, 0, 0], [2, 0, 1.4], [0, 0, 1.4]]
    for a, b in zip(c, c[1:] + c[:1]):
        sc.add_curve(line(a, b, 20), sc.planes[0].id)
    from sketch_machine import network
    network.sync(sc)
    h.v._changed()
    h.camera([1.0, 0.45, 0.7], 5.2, [0.55, 0.55, 0.65])
    return sc


def extrude(h, s):
    """Two steps: lines selected in edge mode – X pressed and the mouse moved up, the walls follow."""
    sc = _rect_scene(h)
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.owner_of(cv).id, cv.id) for cv in sc.curves]
    h.v._changed()
    h.grab()
    crop = QRect(0, 26, 1060, SIZE[1] - 26)
    rail = _toolbar(h, Qt.LeftToolBarArea)
    s.box(_action_rect(s, rail, h.w.component_actions["edge"]), 1, at="r")
    front = s.view_point([1.0, 0.0, 1.4])
    s.ring(front, 2, at="r")
    s.label(s.view_point([2.0, 0.0, 0.7]), "selected lines", "r")
    s.snap("Step 1 · select the lines", crop)
    start = h.scrf([1.0, 0.0, 1.4])
    h.move(start)
    h.key(Qt.Key_X)
    for k in range(1, 13):
        h.move(QPointF(start.x(), start.y() - 11 * k))
    length = float(h.v._extrude["length"]) if h.v._extrude else 0.8
    top = s.view_point([1.0, length, 1.4])
    s.arrow(QPointF(front.x() - 70, front.y() - 6), QPointF(top.x() - 70, top.y() + 6), 3)
    s.ring(top, 4, at="r")
    s.label(s.view_point([2.0, length * 0.5, 0.7]), "walls follow", "r")
    status = _status_rect(s)
    s.box(QRect(status.left(), status.top(), 700, status.height()), 5, at=QPointF(720, status.top() - 16))
    s.snap("Step 2 · press X, move the mouse", crop)
    h.key(Qt.Key_Escape)
    s.save("09_extrude", "Extrude (X)", [
        (1, "Edit mode (Tab), edge mode (key 2)"),
        (2, "Select the lines – click, Shift adds, L: connected"),
        (3, "Press X, move the mouse: that sets the length"),
        (4, "The copy follows; walls appear between the lines"),
        (5, "Status line: X/Y/Z axis · N normal · Ctrl snaps · click confirms · Esc cancels")],
        "Extruding pulls a copy of the selected lines away and builds walls between them – the quickest way from a "
        "drawn outline to a volume.")


CROP = QRect(0, 26, 1060, SIZE[1] - 26)  # left bar and most of the viewport
WIDE = QRect(0, 26, 1240, SIZE[1] - 26)  # left bar and the whole viewport
FULL = QRect(0, 26, SIZE[0], SIZE[1] - 26)  # everything below the menu bar
BLUE = (0.13, 0.33, 0.72)
ORANGE = (0.85, 0.42, 0.15)


def _rail(h):
    return _toolbar(h, Qt.LeftToolBarArea)


def _reset(h):
    """Every picture starts from the same state: pen, Draw mode, no paint/free/multi, default width."""
    from sketch_machine.workspace import PEN_WORLD_DEFAULT
    if h.v.ws.timing_mode:
        h.v.set_timing_mode(False)
    if h.v.select_mode:
        h.v.set_select_mode(False)
    h.v.set_notes_mode(False)
    if h.w.paint_mode_action.isChecked():
        h.w.paint_mode_action.trigger()
    if h.w.free_action.isChecked():
        h.w.free_action.trigger()
    h.v.ws.pen_world = PEN_WORLD_DEFAULT
    h.v.ws.point_scale = 1.0
    h.v.set_draw_tool("pen")
    h.v.set_transform_tool(None)
    h.pump(0.05)


def _press_stroke(h, pts):
    """Mouse down at the first point and along the others – still held (a picture in the middle of a stroke)."""
    from PySide6.QtTest import QTest
    h.move(pts[0])
    QTest.mousePress(h.v, Qt.LeftButton, Qt.NoModifier, pts[0].toPoint())
    h.app.processEvents()
    _drag(h, pts)


def _drag(h, pts):
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.hypot(b.x() - a.x(), b.y() - a.y()) / 4))
        for k in range(1, n + 1):
            h.move(QPointF(a.x() + (b.x() - a.x()) * k / n, a.y() + (b.y() - a.y()) * k / n), Qt.LeftButton)


def _release(h, pt):
    from PySide6.QtTest import QTest
    QTest.mouseRelease(h.v, Qt.LeftButton, Qt.NoModifier, pt.toPoint())
    h.pump(0.05)


def _ground(h, target=(0, 0, 0), dist=6.0, back=(0.0, 0.75, 0.66)):
    sc = h.new_scene()
    h.camera(list(target), dist, list(back))
    return sc


def _wave(x0, x1, z, amp=0.25, n=24):
    return [[x, 0.0, z + amp * math.sin((x - x0) * 2.4)] for x in np.linspace(x0, x1, n)]


def _sync(h):
    from sketch_machine import network
    network.sync(h.sc)
    h.v._changed()
    h.grab()


def _square(sc, x0, z0=0.0, w=1.6, d=1.2):
    c = [[x0, 0, z0], [x0 + w, 0, z0], [x0 + w, 0, z0 + d], [x0, 0, z0 + d]]
    for a, b in zip(c, c[1:] + c[:1]):
        sc.add_curve(line(a, b, 16), sc.planes[0].id)


def pen_brush(h, s):
    """Pen and brush: both draw real lines – pencil grey or in the current colour with a brush texture."""
    _ground(h, (0, 0, 0), 3.6)
    h.v.ws.pen_world = 0.10
    h.stroke_world(_wave(-1.4, 1.4, -0.45, 0.18))
    h.w._use_color(BLUE, remember=True)
    h.v.set_draw_tool("brush")
    h.stroke_world(_wave(-1.4, 1.4, 0.45, 0.18))
    h.grab()
    rail = _rail(h)
    s.box(_action_rect(s, rail, h.w.draw_action), 1, at="r")
    s.box(_action_rect(s, rail, h.w.brush_action), 2, at="r")
    s.box(_action_rect(s, rail, h.w.color_action), 3, at="r")
    s.label(s.view_point([-1.4, 0, -0.45]), "pen: pencil line", "t")
    s.label(s.view_point([-1.4, 0, 0.45]), "brush: line in the colour", "b")
    s.snap("", WIDE)
    s.save("02_pen_brush", "Pen and brush – both draw lines",
           [(1, "Pen (A): grey pencil line for construction – never coloured"),
            (2, "Brush (A again): the same kind of line, in colour with a brush texture"),
            (3, "The current colour (click: colour wheel) – it is the brush colour"),
            (None, "Both are real lines: select, snap, fill, loft, extrude")],
           "Pen and brush both draw lines you can edit and build surfaces from. The only difference is the look: "
           "the pen draws grey pencil, the brush draws in the current colour.")


def paint_mode(h, s):
    """Lines (Draw mode) and paint (Paint mode S): paint lies flat on the surface and cannot be selected."""
    _ground(h, (0, 0, 0.1), 3.8, (0.0, 0.62, 0.78))
    crop = QRect(0, 120, 1000, 640)
    h.w._use_color(BLUE, remember=True)
    h.v.ws.pen_world = 0.09
    h.v.set_draw_tool("brush")
    h.stroke_world(_wave(-1.4, 1.4, -0.75, 0.15))
    s.label(s.view_point([1.4, 0, -0.75]), "brush line", "l")
    s.snap("Draw mode · lines", crop)
    h.w.paint_mode_action.trigger()
    h.w._use_color((0.62, 0.18, 0.55), remember=True)  # not orange: orange is the selection colour
    h.v.ws.pen_world = 0.22
    for k in range(4):
        z = 0.05 + 0.2 * k
        h.stroke_world([[x, 0.0, z + 0.06 * math.sin(x * 4 + k)] for x in np.linspace(-1.2, 1.2, 18)])
    s.box(_action_rect(s, _rail(h), h.w.paint_mode_action), 1, at="r")
    s.label(s.view_point([1.2, 0, 0.35]), "paint", "l")
    s.snap("Paint mode (S) · paint", crop)
    h.w.paint_mode_action.trigger()
    h.edit_mode("edge")
    h.v.edge_selection = [("line", h.sc.owner_of(c).id, c.id) for c in h.sc.curves if not c.paint]
    h.v._changed()
    h.grab()
    s.label(s.view_point([1.4, 0, -0.75]), "line: selected", "l")
    s.label(s.view_point([1.2, 0, 0.35]), "paint: not selectable", "l")
    s.snap("Edit · select everything", crop)
    s.save("03_paint_mode", "Draw mode and Paint mode",
           [(1, "Paint mode (S): pen and brush lay down paint instead of lines"),
            (None, "Lines: editable – they snap, weld and build surfaces"),
            (None, "Paint: flat on the surface, like colour – not selectable, only the eraser cuts it"),
            (None, "Paint follows its surface (lofts, fill surfaces); S again: back to lines")],
           "In Draw mode pen and brush make lines – the construction. In Paint mode they lay colour flat onto the "
           "surface – for look and shading, never for the shape.")


def free_mode(h, s):
    """Free mode (Q): draw without a plane, facing the camera; start docked on a line, the end docks too."""
    sc = _ground(h, (0, 0.8, 0), 6.5, (0.45, 0.42, 0.79))
    sc.new_stroke()
    for x in (-1.5, 1.5):
        sc.add_curve(line([x, 0, 0], [x, 1.5, 0], 16), sc.planes[0].id)
    _sync(h)
    h.w.free_action.trigger()
    h.grab()
    a, b = h.scrf([-1.5, 1.5, 0]), h.scrf([1.5, 1.5, 0])
    mid_y = min(a.y(), b.y()) - 120

    def arc(t):
        return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (mid_y - a.y()) * 4 * t * (1 - t) + (b.y() - a.y()) * t)

    _press_stroke(h, [arc(t) for t in np.linspace(0.0, 0.45, 11)])
    s.box(_action_rect(s, _rail(h), h.w.free_action), 1, at="r")
    s.ring(s.view_point([-1.5, 1.5, 0]), 2, 18, at="l")
    s.label(s.view_point([0.0, 3.0, 0]), "✗ not in empty space", "t")
    s.snap("Step 1 · start on a line", CROP, settle=0.0)
    rest = [arc(t) for t in np.linspace(0.45, 1.0, 12)]
    _drag(h, rest)
    _release(h, rest[-1])
    h.grab()
    s.ring(s.view_point([1.5, 1.5, 0]), 3, 18, at="r")
    s.label(s.view_point([0.0, 2.6, 0]), "plane faces the camera", "t")
    s.snap("Step 2 · the end docks to another line", CROP)
    h.w.free_action.trigger()
    s.save("04_free_mode", "Free mode (Q) – drawing without a plane",
           [(1, "Free (Q): button in the left bar – a green frame shows it is on"),
            (2, "Start the stroke on a line or a surface – never in empty space"),
            (3, "The end docks to a point or line at any depth"),
            (None, "For connections, arcs and frames between things you already drew")],
           "Free mode draws in space without a plane: the stroke lies in an imagined plane through its start point, "
           "facing the camera. It must start on an existing line or surface; its end may dock somewhere else.")


def hold_shape(h, s):
    """Hold still at the end of a stroke: a rough circle becomes a clean circle."""
    _ground(h, (0, 0, 0), 4.2)
    h.v.ws.pen_world = 0.06
    pts = [h.scrf([(1.1 + 0.05 * math.sin(5 * t)) * math.cos(t), 0, (0.8 + 0.04 * math.cos(3 * t)) * math.sin(t)])
           for t in np.linspace(0.2, 2 * math.pi + 0.15, 40)]
    _press_stroke(h, pts)
    s.label(pts[12], "rough circle", "t")
    s.snap("Step 1 · draw roughly", CROP, settle=0.0)
    end = QPointF(pts[-1].x() + 0.3, pts[-1].y())
    h.pump(0.45)
    h.move(end, Qt.LeftButton)
    h.pump(0.1)
    s.ring(pts[-1], 1, 20, at="r")
    s.snap("Step 2 · hold still at the end", CROP)
    _release(h, end)
    s.save("05_hold_shape", "Straight lines and shapes: hold still",
           [(1, "Keep the pointer still for a moment at the end: the stroke becomes a clean shape"),
            (None, "Recognised: straight line, circle, rectangle, arc"),
            (None, "Until you release, the mouse adjusts size or end point; Ctrl: square"),
            (None, "Straight lines snap their angle in steps")],
           "Draw freely; if you hold still for a moment at the end of a stroke, Mule turns it into a straight line or "
           "a clean shape.")


def _space_key(h, key):
    from PySide6.QtTest import QTest
    h.v.setFocus()
    QTest.keyPress(h.v, Qt.Key_Space)
    QTest.keyClick(h.v, key)
    QTest.keyRelease(h.v, Qt.Key_Space)
    h.pump(0.05)


def new_plane(h, s):
    """Space+N on the cup handle: a new plane there – seen from the side it stands in space; then draw on it."""
    h.load("tests/scenes/teacup.sketch.json")
    handle = next(st for st in h.sc.strokes if st.name == "Handle")
    pts = np.vstack([c.points for c in handle.curves])
    allp = np.vstack([c.points for st in h.sc.strokes for c in st.curves])
    centre = (allp.min(0) + allp.max(0)) / 2
    size = float(np.linalg.norm(np.ptp(allp, axis=0)))
    h.camera(centre, size * 1.5, [0.15, 0.35, 0.92])
    target = pts[np.argmax(pts[:, 0])]  # outermost point of the handle
    h.move(h.scrf(target))
    s.ring(s.view_point(target), 1, 22, at="r")
    s.label(s.view_point(target), "cursor on the handle", "b")
    s.snap("Step 1 · point at the handle, Space+N", CROP)
    _space_key(h, Qt.Key_N)
    h.camera(centre, size * 1.6, [0.85, 0.35, 0.4])
    s.label(s.view_point(target), "new plane at the handle", "t")
    s.snap("Step 2 · orbit: the plane stands in space", CROP)
    plane = h.sc.active_plane
    o, u, v = plane.origin, plane.axis_u, plane.axis_v
    k = size * 0.12
    h.stroke_world([o + k * (math.cos(t) * u + 0.6 * math.sin(t) * v) for t in np.linspace(0, 1.7 * math.pi, 22)])
    s.label(s.view_point(o + k * u), "drawn on it", "r")
    s.snap("Step 3 · draw on it", CROP)
    s.save("06_new_plane", "Own planes: Space+N",
           [(1, "Point at a line or surface and press Space+N: a new plane through that point"),
            (None, "The plane faces the camera; orbit to see where it stands in space"),
            (None, "Draw on it like on paper; wheel or [ ]: move it along its normal"),
            (None, "X / Y / Z: back to a ground plane; click a plane to make it the target")],
           "You always draw onto a plane or surface. Space+N creates a new plane exactly where the cursor points – "
           "for example at the handle of the cup – so you can draw details there.")


def draw_on_surface(h, s):
    """Click a surface: it is the target. A line drawn across it becomes a control line (net line) – moving it shapes
    the surface. Paint (S) on the same surface only colours it."""
    from sketch_machine import components, network
    sc = _ground(h, (0, 0.3, 0), 6.0, (0.25, 0.6, 0.76))
    sc.new_stroke()
    size = 1.6

    def arc(a, b, lift, n=31):
        t = np.linspace(0, 1, n)[:, None]
        p = np.asarray(a, float) * (1 - t) + np.asarray(b, float) * t
        p[:, 1] += lift * np.sin(np.pi * t[:, 0])
        return p
    corners = [[-size, 0, -size], [size, 0, -size], [size, 0, size], [-size, 0, size]]
    border = []
    for k, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1])):
        sc.add_curve(arc(a, b, 0.35 if k % 2 == 0 else 0.0), None)
        border.append(sc.curves[-1])
    network.sync(sc)
    for a, b in zip(border, border[1:] + border[:1]):
        network.join(sc, a, len(a.points) - 1, b, 0)
    surf = sc.create_patch(border)
    sc.sync_lofts()
    _sync(h)
    crop = QRect(0, 60, 1060, 780)
    centre = np.array([0.0, 0.25, 0.0])
    h.click(h.scrf(centre))
    h.pump(0.1)
    h.grab()
    s.ring(s.view_point(centre), 1, 26, at="r")
    s.label(s.view_point([size, 0.0, size]), "active surface: tinted, with grid", "r")
    s.snap("Step 1 · click a surface: you draw on it", crop)
    h.stroke_world([[x, 0.3, 0.3] for x in np.linspace(-size * 1.1, size * 1.1, 30)])
    new = h.sc.curves[-1]
    s.ring(s.view_point(new.points[len(new.points) // 3]), 2, 18, at="t")
    s.label(s.view_point(new.points[-1]), "new control line, border to border", "r")
    s.snap("Step 2 · draw a line across it", crop)
    k = network.knot_at(new, new.points[len(new.points) // 2])
    components.ComponentGroup(h.sc, [(new, k)], []).translate(np.array([0.0, 0.7, 0.0]))
    h.sc.sync_lofts()
    h.edit_mode("point")
    h.v.point_selection = [("line", h.sc.owner_of(new).id, new.id, k)]
    _sync(h)
    s.ring(s.view_point(new.points[k]), 3, 18, at="r")
    s.label(s.view_point(new.points[-1]), "the surface follows the line", "r")
    s.snap("Step 3 · move a point of the line", crop)
    h.v.point_selection = []
    h.draw_mode()
    h.w.paint_mode_action.trigger()
    h.w._use_color((0.62, 0.18, 0.55), remember=True)  # not orange: orange is the selection colour
    h.v.ws.pen_world = 0.16
    h.v.set_draw_tool("brush")
    g = surf.grid()
    rows = g if g.shape[0] >= g.shape[1] else g.transpose(1, 0, 2)
    for r in np.linspace(0.3, 0.7, 3):
        row = rows[int(r * (len(rows) - 1))]
        h.stroke([h.scrf(p) for p in row[int(0.15 * len(row)):int(0.85 * len(row))]])
    h.grab()
    s.box(_action_rect(s, _rail(h), h.w.paint_mode_action), 4, at="r")
    s.label(s.view_point(new.points[-1]), "paint: colour only, the shape stays", "r")
    s.snap("Paint mode (S) · colour the surface", crop)
    h.w.paint_mode_action.trigger()
    s.save("07_draw_on_surface", "Drawing on surfaces: lines shape, paint colours",
           [(1, "Click a surface, plane or mesh: it becomes the target (status line: Drawing on …)"),
            (2, "Pen or brush draws on it; a line from border to border becomes a control line of the surface"),
            (3, "Move the line or its points (Edit, point mode): the surface follows its lines"),
            (4, "Paint mode (S): colour lies flat on the surface – look and shading, never the shape"),
            (None, "Lines build the form, paint decorates it")],
           "You can draw directly on surfaces and meshes. Lines drawn on a surface become its control lines and "
           "shape it; paint only colours it.", cols=2)


def edit_gizmo(h, s):
    """Edit mode: select an object, T shows the move gizmo."""
    h.load("tests/scenes/teacup.sketch.json")
    cup = next(st for st in h.sc.strokes if st.name == "Saucer")
    h.edit_mode("edge")
    h.v.edge_selection = [("line", cup.id, c.id) for c in cup.curves]
    h.v._changed()
    h.grab()
    h.v.setFocus()
    h.key(Qt.Key_T)
    h.grab()
    rail = _rail(h)
    for k, tool in enumerate(("translate", "rotate", "scale"), 1):
        s.box(_action_rect(s, rail, h.w.transform_actions[tool]), k, at="r")
    pts = np.vstack([c.points for c in cup.curves])
    s.ring(s.view_point((pts.min(0) + pts.max(0)) / 2), 4, 34, at="r")
    s.snap("", FULL)
    h.v.set_transform_tool(None)
    s.save("08_edit_gizmo", "Edit mode (Tab): select and transform",
           [(1, "Move (T)"), (2, "Rotate (R)"), (3, "Scale (E) – past the pivot: mirror"),
            (4, "The gizmo sits on the selection: drag an arrow, ring or square"),
            (None, "Click selects, Shift adds, Ctrl removes; Ctrl while dragging snaps"),
            (None, "Points (1) · edges (2) · surfaces (3) choose what you select")],
           "Tab switches to Edit mode. Select what you want to change, then T, R or E shows the gizmo to move, "
           "rotate or scale it.")


def _select_lines(h, curves):
    h.edit_mode("edge")
    h.v.edge_selection = [("line", h.sc.owner_of(c).id, c.id) for c in curves]
    h.v._changed()
    h.grab()


def loft(h, s):
    """Loft (Shift+F): cross-sections selected in order become one curved surface."""
    from tests.harness import circle
    sc = _ground(h, (0, 1.2, 0), 6.5, (0.55, 0.5, 0.67))
    sc.new_stroke()
    lines = []
    for pts in (circle([0, 0.0, 0], 0.9, 41), circle([0, 1.2, 0], 0.55, 41), circle([0, 2.4, 0], 1.0, 41)):
        sc.add_curve(np.asarray(pts, float), None)
        lines.append(sc.curves[-1])
    _sync(h)
    _select_lines(h, lines)
    h.v._pick_rank = {c.id: k for k, c in enumerate(lines)}
    for k, y in enumerate((0.0, 1.2, 2.4), 1):
        s.ring(s.view_point([0.95 if k != 2 else 0.6, y, 0]), k, 18, at="r")
    s.snap("Step 1 · select the cross-sections in order", CROP)
    h.v._track_pick_order = lambda: None
    h.v.do_loft()
    del h.v._track_pick_order
    h.v._changed()
    s.label(s.view_point([1.0, 1.2, 0]), "loft through all three", "r")
    s.snap("Step 2 · Shift+F", CROP)
    s.save("10_loft", "Loft (Shift+F)",
           [(1, "Edit mode, edge mode: click the cross-sections one after another"),
            (2, "The click order is the order of the loft"),
            (3, "Shift+F: a curved surface through all of them (Ctrl+Shift+F: ring back to the first)"),
            (None, "Closed sections give a tube, open ones a sheet; the surface follows its lines")],
           "A loft is a curved surface through several cross-sections, like Skin in Houdini: draw the sections, select "
           "them in order, press Shift+F.")


def fill(h, s):
    """F: lines that close an outline become a surface."""
    sc = _ground(h, (0, 0, 0.2), 5.0)
    sc.new_stroke()
    c = [[-1.4, 0, -0.6], [1.2, 0, -0.9], [1.5, 0, 0.8], [-0.9, 0, 1.0]]
    lines = []
    for a, b in zip(c, c[1:] + c[:1]):
        sc.add_curve(line(a, b, 16), sc.planes[0].id)
        lines.append(sc.curves[-1])
    _sync(h)
    _select_lines(h, lines)
    s.label(s.view_point([1.5, 0, 0.8]), "closed outline, selected", "r")
    s.snap("Step 1 · select the outline", CROP)
    h.key(Qt.Key_F)
    s.label(s.view_point([0.2, 0, 0.1]), "surface", "r")
    s.snap("Step 2 · F", CROP)
    s.save("11_fill", "Surface from lines (F)",
           [(None, "Edit mode, edge mode: select lines that close an outline (L selects connected lines)"),
            (None, "F builds a curve surface; an outline bent inwards becomes a fill surface"),
            (None, "The surface follows its lines: move the lines, the surface moves along"),
            (None, "Alt+F forces a smooth curve surface from curved border lines")],
           "Surfaces always come from lines: select lines that close an outline and press F.")


def _polyline(h):
    sc = _ground(h, (0, 0, 0), 3.6)
    st = sc.new_stroke()
    pts = [[-1.4, 0, 0.35], [-0.45, 0, -0.45], [0.45, 0, 0.45], [1.4, 0, -0.35]]
    dense = np.vstack([line(a, b, 14)[:-1] for a, b in zip(pts[:-1], pts[1:])] + [np.array([pts[-1]])])
    sc.add_curve(dense, sc.planes[0].id)
    sc.active_stroke = st
    _sync(h)
    h.edit_mode("point")
    h.click(h.scr([-0.9, 0, -0.05]))  # a click on the line makes its object active: its points show
    h.v.point_selection = []
    h.v.ws.selection = []  # the click may also pick the ground plane – not part of the picture
    h.v.ws.point_scale = 2.2  # points large enough to see in the picture (View → Point size)
    h.v._changed()
    h.grab()
    return sc, pts


def insert_point(h, s):
    """Ctrl+click on a line in point mode inserts a point."""
    sc, pts = _polyline(h)
    crop = QRect(0, 120, 1060, 600)
    s.box(_action_rect(s, _rail(h), h.w.component_actions["point"]), 1, at="r")
    s.label(s.view_point(pts[2]), "points: corners and ends", "t")
    s.snap("Step 1 · point mode (key 1)", crop)
    where = [0.0, 0, 0.0]
    h.click(h.scr(where), Qt.ControlModifier)
    h.grab()
    s.ring(s.view_point(where), 2, 18, at="r")
    s.label(s.view_point(where), "new point, selected", "b")
    s.snap("Step 2 · Ctrl+click on the line", crop)
    s.save("12_insert_point", "Insert a point (Ctrl+click)",
           [(1, "Edit mode, point mode (key 1): line ends and corners show as points"),
            (2, "Ctrl+click on a line: a new point there, selected – drag it to reshape the line"),
            (None, "Ctrl+click on a point deselects it; hold S and drag: slide points along their line")],
           "Points are where you can grab a line. Ctrl+click on a line adds a point exactly there.")


def delete_point(h, s):
    """Del dissolves a point (shape stays), Ctrl+Del deletes it (straight bridge)."""
    crop = QRect(150, 200, 900, 520)
    sc, pts = _polyline(h)
    corner = pts[2]

    def select_corner():
        h.v.point_selection = []
        h.click(h.scr(corner))
        h.grab()

    select_corner()
    s.ring(s.view_point(corner), 1, 18, at="r")
    s.snap("Selected point", crop)
    h.key(Qt.Key_Delete)
    s.label(s.view_point(corner), "point gone, shape stays", "b")
    s.snap("Del · dissolve", crop)
    h.key(Qt.Key_Z, Qt.ControlModifier)
    select_corner()
    h.key(Qt.Key_Delete, Qt.ControlModifier)
    s.label(s.view_point([0.0, 0, 0.0]), "straight bridge", "b")
    s.snap("Ctrl+Del · delete", crop)
    s.save("13_delete_point", "Delete points (point mode)",
           [(1, "Select a point (point mode, key 1)"),
            (None, "Del dissolves: the point is gone, the line keeps its shape"),
            (None, "Shift+Del removes: the line runs smoothly between the neighbours"),
            (None, "Ctrl+Del deletes: the pieces go, a straight line bridges the neighbours")],
           "Three ways to get rid of a point: dissolve it and keep the shape, remove it and smooth the line, or "
           "delete it together with its pieces.")


def symmetry(h, s):
    """Objects → Symmetry: the objects under it are mirrored live."""
    sc = _ground(h, (0, 0.9, 0), 5.5, (0.2, 0.45, 0.87))
    st = sc.new_stroke()
    st.name = "Half"
    prof = [[0.0, 1.8, 0], [0.9, 1.6, 0], [1.3, 0.9, 0], [0.9, 0.2, 0], [0.0, 0.0, 0]]
    sc.add_curve(np.vstack([line(a, b, 10)[:-1] for a, b in zip(prof[:-1], prof[1:])] + [np.array([prof[-1]])]), None)
    _sync(h)
    h.v.ws.selection = [st.id]
    h.v.create_null("symmetry")
    h.v.ws.selection = []
    h.v._changed()
    h.pump(0.2)
    h.grab()
    s.label(s.view_point([1.3, 0.9, 0]), "drawn half", "r")
    s.label(s.view_point([-1.3, 0.9, 0]), "mirrored live", "l")
    out = s.widget_rect(_dock(h, "Outliner"), pad=-2)
    s.box(QRect(out.left(), out.top() + 145, out.width(), 100), 1, at="l")
    s.snap("", FULL)
    s.save("14_symmetry", "Groups and generators: Symmetry",
           [(1, "Objects → Symmetry: a generator null; the selected objects go under it"),
            (None, "Draw one half – the other half appears live and updates while you draw"),
            (None, "Alt+G: plain group (null); Objects → Array: copies on a circle, line or path"),
            (None, "Alt+C (Convert): turns the generator into real lines")],
           "Generators work like in Cinema 4D: put objects under a Symmetry or Array null and Mule shows the copies "
           "live.")


def _reload_board(h, note, change=None):
    """The note panel loads a board when the active note changes. Leaving the note first stores the panel's own state
    into the note; change(board) edits the board after that, then the note is shown again."""
    h.v.ws.active_note = None
    h.w._sync_note_panel()
    h.pump(0.1)
    if change is not None:
        change(note.board)
    h.v.ws.active_note = note.id
    h.w._sync_note_panel()
    h.v._changed()
    h.pump(0.3)


def note_board(h, s):
    """Notes in four steps: double-click makes a note, camera button and board, text, octopus."""
    sc = _ground(h, (0.0, 0.3, 0.6), 7.0, (0.0, 0.8, 0.6))
    seats = []
    for k, x0 in enumerate((-3.2, -0.8, 1.6), 1):
        st = sc.new_stroke()
        st.name = f"Seat {k}"
        _square(sc, x0)
        seats.append(st)
    _sync(h)
    h.v.set_notes_mode(True)
    h.pump(0.1)
    out = h.w.findChild(QDockWidget, "outliner_dock")
    h.w.resizeDocks([out, h.w.note_dock], [400, 400], Qt.Horizontal)  # more room for the viewport
    h.pump(0.1)
    target = [-2.4, 0, 0.0]
    h.dclick(h.scr(target))
    h.pump(0.2)
    from PySide6.QtTest import QTest
    editor = h.v.notes_tool.editor  # the new note waits for its heading in a small text field
    if editor is not None:
        QTest.keyClicks(editor[0], "Seat")
        h.v.notes_tool.finish_edit()
    h.pump(0.1)
    note = sc.notes[-1]
    h.v.ws.active_note = note.id
    h.v._changed()
    h.grab()
    s.ring(s.view_point(target), 1, 20, at="r")
    s.snap("Step 1 · Notes mode (N): double-click on a part", FULL)
    h.v._changed()
    h.grab()  # the note's buttons are placed while drawing
    cam = h.v.notes_tool._screen[note.id]["icons"].get("cam")
    s.ring(QPointF(h.v.mapTo(h.w, QPoint(0, 0))) + QPointF(cam), 2, 16, at="t")
    h.click(cam)
    h.pump(0.3)
    _reload_board(h, note)
    s.box(s.widget_rect(h.w.note_dock, pad=-2), 3, at="l")
    s.snap("Step 2 · camera button: the view goes onto the board", FULL)
    _reload_board(h, note, lambda board: board.setdefault("items", []).append(
        {"kind": "text", "x": 0, "y": -230, "w": 360, "scale": 2.6,
         "text": "This is a seat: soft cushion, rounded front edge"}))
    s.box(s.widget_rect(h.w.note_dock, pad=-2), 4, at="l")
    s.snap("Step 3 · write into the board", FULL)
    h.v.ws.selection = [seats[1].id, seats[2].id]
    h.v.notes_tool.add_selection(note.id, 0)
    h.v.ws.selection = []
    h.v._changed()
    h.grab()
    s.ring(s.view_point([0.0, 0, 0.0]), 5, 20, at="t")
    s.ring(s.view_point([2.4, 0, 0.0]), 5, 20, at="t")
    s.snap("Step 4 · octopus: the note also means similar parts", FULL)
    h.v.set_notes_mode(False)
    s.save("15_note_board", "Notes (N) and the note board",
           [(1, "Double-click in Notes mode: a note with a leader line to that part"),
            (2, "Camera button at the note: a picture of the view goes onto its board"),
            (3, "Bottom right: the board of the active note – pictures, videos, arrows"),
            (4, "Type, paste or drop pictures into it; it is what the AI reads about this part"),
            (5, "Octopus: Shift+drag from the anchor (or right-click → add selection) – the note means these too")],
           "Notes are prompts in space: a short heading points at a part, and its board holds everything the AI "
           "should know about it. The octopus says which similar parts the same note also means.")


def hero_camera(h, s):
    """A screenshot on the note board (bottom right) marked as hero camera: tick, then name."""
    from sketch_machine.note_board import ImageItem
    from sketch_machine.scene import Note
    sc = _ground(h, (0, 0.4, 0.3), 5.5, (0.35, 0.6, 0.72))
    sc.new_stroke()
    _square(sc, -1.0, 0.0, 2.0, 1.2)
    _sync(h)
    note = Note("Seat", np.array([0.6, 1.0, 0.2]))
    sc.notes.append(note)
    h.v.set_notes_mode(True)
    h.v.ws.active_note = note.id
    h.v._changed()
    h.grab()
    h.click(h.v.notes_tool._screen[note.id]["icons"]["cam"])
    _reload_board(h, note)
    view = h.w.note_panel.view
    item = next(it for it in view.scene().items() if isinstance(it, ImageItem))
    view.scene().clearSelection()
    item.setSelected(True)
    view.viewport().update()
    h.pump(0.2)

    def window_rect(r, pad=4, scene=False):
        """Board rect (screen coordinates of the board view, or scene coordinates) → window rect."""
        r = view.mapFromScene(r).boundingRect() if scene else r.toRect()
        tl = view.viewport().mapTo(h.w, r.topLeft())
        return QRect(tl.x() - pad, tl.y() - pad, r.width() + 2 * pad, r.height() + 2 * pad)

    img = window_rect(item.sceneBoundingRect(), 0, scene=True)
    crop = QRect(img.x() - 30, img.y() - 40, img.width() + 60, int(img.height() * 0.7))
    box, name, _k = view._hero_rects(item)
    s.box(window_rect(box), 1, at="l")
    s.snap("Step 1 · click the screenshot: the check box appears", crop)
    view.toggle_hero(item)
    view._end_hero_edit(apply=True)
    item.setSelected(True)
    view.viewport().update()
    h.pump(0.2)
    box, name, _k = view._hero_rects(item)
    s.box(window_rect(name), 2, at="b")
    frame = window_rect(item.sceneBoundingRect(), 0, scene=True)
    s.ring(QPointF(frame.left() + 2, frame.top() + frame.height() * 0.4), 3, 16, at="r")
    s.label(QPointF(frame.left() + 30, frame.top() + frame.height() * 0.4), "turquoise frame", "r")
    s.snap("Step 2 · ticked: name it – turquoise frame", crop)
    h.v.set_notes_mode(False)
    s.save("16_hero_camera", "Hero camera",
           [(1, "Tick “hero camera” at the top right of a screenshot on the board"),
            (2, "Give the camera a name (default Hero 1, Hero 2 …)"),
            (3, "A turquoise frame marks hero pictures"),
            (None, "The brief renders a clean picture and a USD camera from it"),
            (None, "Without hero cameras the brief uses three standard angles")],
           "Hero cameras are the views that matter most. Tick a screenshot on a note board as hero camera, and the AI "
           "looks through exactly this camera while it builds and reviews.")


def brief_dialog(h, s):
    """File → Export Sketch Brief: the task dialog."""
    from sketch_machine.brief_dialog import BriefDialog
    dlg = BriefDialog(h.w, {"task": "Rebuild the chair as a procedural model in Houdini"}, selected=0, name="chair")
    dlg.resize(760, dlg.sizeHint().height())
    dlg.show()
    h.pump(0.3)
    s.box(s.widget_rect(dlg.task, pad=4, base=dlg), 1, at="l")
    s.box(s.widget_rect(dlg.notes, pad=4, base=dlg), 2, at="l")
    s.box(s.widget_rect(dlg.discuss, pad=4, base=dlg), 3, at="l")
    s.box(s.widget_rect(dlg.recipe_row, pad=4, base=dlg), 4, at="l")
    s.box(s.widget_rect(dlg.copy_prompt, pad=4, base=dlg), 5, at="l")
    s.snap("", widget=dlg)
    dlg.reject()
    s.save("17_brief_dialog", "Export Sketch Brief (Ctrl+E)",
           [(1, "The task in one sentence"),
            (2, "Hints that apply only to this export"),
            (3, "Discuss only – nothing gets built"),
            (4, "Brief recipe: the way of working – Mule Default or your own (…)"),
            (5, "Autoprompt: a ready sentence for the AI chat lands on the clipboard"),
            (None, "Then choose a folder; start Claude Code or Codex in that brief folder")],
           "The Sketch Brief is the hand-over to the AI: a folder with pictures, notes, the scene as USD and working "
           "rules. The dialog asks only for what the AI cannot read from the scene.")


def review_mark(h, s):
    """Review: talk your feedback while walking through the scene; the Mark tool sets markers."""
    import tempfile
    import wave
    from sketch_machine import review

    class Silent:
        def __init__(self, path, parent=None):
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\0\0" * 16000)
            self.ok, self.error, self.frames, self.device_name = True, "", 16000, "Test"

        def stop(self):
            pass

    base = tempfile.mkdtemp()
    old = review.reviews_dir, review.AudioWriter
    review.reviews_dir, review.AudioWriter = (lambda: base), Silent
    try:
        h.load("tests/scenes/teacup.sketch.json")
        h.v.set_notes_mode(True)
        session = h.w.review
        cup = next(st for st in h.sc.strokes if st.name == "Handle")
        target = cup.curves[0].points[len(cup.curves[0].points) // 2]
        on = h.scr(target)
        session.cursor = lambda: h.v.mapToGlobal(on)
        session.start()
        h.pump(0.3)
        h.click(on)
        h.pump(0.3)
        w = _toolbar(h, Qt.TopToolBarArea).widgetForAction(h.w.review_mark_action)
        if w is not None:
            s.box(s.widget_rect(w, pad=3), 2, at="b")
        s.ring(s.view_point(target), 1, 26, at="r")
        s.snap("", FULL)
        session.stop(transcribe=False)
    finally:
        review.reviews_dir, review.AudioWriter = old
        h.v.set_notes_mode(False)
    s.save("18_review_mark", "Review: talk your feedback",
           [(1, "While recording, a click sets a numbered marker exactly there"),
            (2, "Mark tool (on at the start) – off: work normally, the recording goes on"),
            (None, "Review → Start Review: voice, camera and pointer are recorded"),
            (None, "Send Review: transcribes and puts a sentence on the clipboard"),
            (None, "Paste it into the AI chat yourself (Ctrl+V) – nothing is sent automatically"),
            (None, "The AI then writes draft notes at the marked parts; you accept them")],
           "Walk through the scene and talk, like in a review session. Mule records your voice and where you looked "
           "and pointed; the AI turns it into draft notes.")


def shots(h, s):
    """Shots: flipbook layer with drawings per frame, onion skin, shot note with camera."""
    from sketch_machine.scene import Note
    h.new_scene()
    h.camera((0, 0, 0), 7.0, (0.15, 0.25, 0.95))
    h.v.set_timing_mode(True)
    h.v.set_draw_tool("brush")
    h.w._use_color(ORANGE, remember=True)
    h.v.ws.pen_world = 0.12
    h.v.new_plane()
    plane = h.sc.active_plane
    o, u, v = plane.origin, plane.axis_u, plane.axis_v

    def ring_at(r, n=40):
        return [o + r * (math.cos(t) * u + math.sin(t) * v) for t in np.linspace(0.3, 0.3 + 1.9 * math.pi, n)]

    h.v.set_frame(1001)
    h.stroke_world(ring_at(0.6))
    s.box(s.widget_rect(h.w.timeline_dock, pad=-2), 1, at="t")
    s.snap("Step 1 · Space+N: flipbook layer, draw at frame 1001", FULL)
    h.v.set_frame(1012)
    h.sc.timing.onion = True
    h.stroke_world(ring_at(1.6, 40))
    h.v._changed()
    s.label(s.view_point(o + 0.6 * u), "onion skin: frame 1001", "b")
    s.snap("Step 2 · frame 1012: draw the next state", FULL)
    note = Note("Shot 1", o + np.array([0, 2.4, 0]),
                board={"items": [{"kind": "text", "x": 0.0, "y": 0.0, "w": 340.0,
                                  "text": "Explosion grows fast, then slows down"}]})
    h.sc.timing.notes.append(note)
    h.v.ws.active_note = note.id
    h.v.new_timing_camera(note)
    h.v._changed()
    h.pump(0.2)
    s.box(s.widget_rect(h.w.timing_dock, pad=-2), 2, at="l")
    s.snap("Step 3 · shot note with camera: what happens in between", FULL)
    h.sc.timing.onion = False
    h.v.set_timing_mode(False)
    s.save("19_shots", "Shots: what happens when",
           [(1, "Timeline: one row per flipbook layer; a drawing holds until the next one"),
            (2, "Shots panel: shot notes with text and camera positions"),
            (None, "Space+N in Shots: a flipbook layer; draw at any frame, O: onion skin"),
            (None, "Nothing is animated – the notes say what happens in between")],
           "Shots shows timing without animating: drawings per frame on flipbook layers, camera positions and notes "
           "about what happens between them.", cols=2)


PICTURES = {"01_overview": overview, "02_pen_brush": pen_brush, "03_paint_mode": paint_mode,
            "04_free_mode": free_mode, "05_hold_shape": hold_shape, "06_new_plane": new_plane,
            "07_draw_on_surface": draw_on_surface, "08_edit_gizmo": edit_gizmo, "09_extrude": extrude, "10_loft": loft, "11_fill": fill,
            "12_insert_point": insert_point, "13_delete_point": delete_point, "14_symmetry": symmetry,
            "15_note_board": note_board, "16_hero_camera": hero_camera, "17_brief_dialog": brief_dialog,
            "18_review_mark": review_mark, "19_shots": shots, "readme_overview": readme_overview}


def main():
    names = sys.argv[1:] or list(PICTURES)
    h = H(size=SIZE)
    for name in names:
        try:
            _reset(h)
            PICTURES[name](h, Shot(h))
        except Exception:
            import traceback
            print("FAILED", name)
            traceback.print_exc()
    sys.stdout.flush()
    os._exit(0)  # no close(): Mule would ask to save the throw-away scene (a dialog on the user's screen)


if __name__ == "__main__":
    main()

"""UI outside the viewport: plain line icons (active in copper) and the color scheme
(anthracite, muted gray, copper as accent – after the artist's reference)."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

# --- Color scheme ---
BG = "#1e1e1f"          # window, bars
PANEL = "#262627"       # outliner, docks
RAISED = "#2f2f31"      # buttons, input fields
LINE = "#3a3a3d"        # fine separator lines
TEXT = "#c9c6c1"
TEXT_DIM = "#8f8b86"
ACCENT = "#d08a5e"      # copper
ACCENT_SOFT = "rgba(208, 138, 94, 0.18)"

ICON_IDLE = QColor(TEXT)
ICON_ON = QColor(ACCENT)
ICON_PX = 48


def _painter(color, width=3.2):
    pix = QPixmap(ICON_PX, ICON_PX)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    return pix, p


def _poly(p, pts, closed=True):
    poly = QPolygonF([QPointF(x, y) for x, y in pts])
    p.drawPolygon(poly) if closed else p.drawPolyline(poly)


def _arrow(p, x0, y0, x1, y1, head=6.0):
    p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    a = math.atan2(y1 - y0, x1 - x0)
    for s in (-1, 1):
        p.drawLine(QPointF(x1, y1), QPointF(x1 - head * math.cos(a + s * 0.5), y1 - head * math.sin(a + s * 0.5)))


def _dot(p, x, y, r, color):
    p.save()
    p.setBrush(color)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


def _draw(name, p, c):
    if name == "pen":
        _poly(p, [(31, 9), (39, 17), (17, 39), (8, 40), (9, 31)])
        p.drawLine(QPointF(27, 13), QPointF(35, 21))
    elif name == "brush":  # brush: handle, ferrule, bristles
        p.drawLine(QPointF(38, 8), QPointF(24, 22))
        _poly(p, [(24, 18), (28, 22), (22, 28), (18, 24)])
        path = QPainterPath(QPointF(18, 24))
        path.cubicTo(QPointF(12, 28), QPointF(10, 36), QPointF(7, 41))
        path.cubicTo(QPointF(14, 40), QPointF(20, 34), QPointF(22, 28))
        p.setBrush(c)
        p.drawPath(path)
        p.setBrush(Qt.NoBrush)
    elif name == "eraser":
        _poly(p, [(9, 29), (25, 13), (39, 27), (23, 43)])
        p.drawLine(QPointF(16, 22), QPointF(30, 36))
        p.drawLine(QPointF(23, 43), QPointF(41, 43))
    elif name == "free":
        _dot(p, 10, 36, 3.6, c)
        path = QPainterPath(QPointF(10, 36))
        path.cubicTo(QPointF(16, 10), QPointF(28, 40), QPointF(39, 11))
        p.drawPath(path)
    elif name == "multi":
        for dy in (0, 9, 18):
            _poly(p, [(12, 12 + dy), (40, 12 + dy), (34, 20 + dy), (6, 20 + dy)])
    elif name == "multi":  # several planes, all active
        p.setPen(QPen(c, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 90))
        for y in (9, 20, 31):
            _poly(p, [(12, y), (40, y), (34, y + 8), (6, y + 8)])
    elif name == "isolate":
        p.setPen(QPen(c, 1.8, Qt.DashLine))
        _poly(p, [(12, 9), (40, 9), (34, 17), (6, 17)])
        _poly(p, [(12, 31), (40, 31), (34, 39), (6, 39)])
        p.setPen(QPen(c, 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 110))
        _poly(p, [(12, 20), (40, 20), (34, 28), (6, 28)])
    elif name == "knot_auto":  # soft and hard: an arc with a point, next to it a corner
        path = QPainterPath(QPointF(5, 34))
        path.cubicTo(QPointF(10, 12), QPointF(22, 12), QPointF(26, 24))
        p.drawPath(path)
        _poly(p, [(26, 24), (34, 10), (43, 34)], closed=False)
        _dot(p, 26, 24, 3.6, c)
    elif name == "knot_soft":  # point on a curve
        path = QPainterPath(QPointF(5, 36))
        path.cubicTo(QPointF(14, 6), QPointF(34, 6), QPointF(43, 36))
        p.drawPath(path)
        _dot(p, 24, 14, 4, c)
    elif name == "knot_hard":  # point on a corner
        _poly(p, [(6, 36), (24, 10), (42, 36)], closed=False)
        _dot(p, 24, 10, 4, c)
    elif name == "swap":  # double arrow: grays <-> last colors
        _arrow(p, 10, 17, 38, 17, 6)
        _arrow(p, 38, 31, 10, 31, 6)
    elif name == "palette":  # color view: color wheel made of four patches
        p.setPen(QPen(c, 2.4))
        for k, col in enumerate(((214, 96, 77), (226, 181, 72), (96, 168, 120), (84, 132, 198))):
            p.setBrush(QColor(*col) if not c.alpha() < 255 else Qt.NoBrush)
            p.drawPie(QRectF(8, 8, 32, 32), k * 90 * 16, 90 * 16)
    elif name == "magnet":
        p.setPen(QPen(c, 7, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(QRectF(13, 9, 22, 22), 0, 180 * 16)
        p.drawLine(QPointF(13, 20), QPointF(13, 33))
        p.drawLine(QPointF(35, 20), QPointF(35, 33))
        p.setPen(QPen(c.darker(160) if c == ICON_ON else c.darker(140), 7, Qt.SolidLine, Qt.FlatCap))
        p.drawLine(QPointF(13, 33), QPointF(13, 41))
        p.drawLine(QPointF(35, 33), QPointF(35, 41))
    elif name == "translate":
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            _arrow(p, 24 + dx * 3, 24 + dy * 3, 24 + dx * 17, 24 + dy * 17)
    elif name == "rotate":
        p.drawArc(QRectF(10, 10, 28, 28), 40 * 16, 290 * 16)
        a = math.radians(40)
        x, y = 24 + 14 * math.cos(a), 24 - 14 * math.sin(a)
        p.drawLine(QPointF(x, y), QPointF(x - 8, y - 2))
        p.drawLine(QPointF(x, y), QPointF(x + 1, y + 8))
    elif name == "scale":
        p.drawRect(QRectF(8, 22, 18, 18))
        p.setPen(QPen(c, 2.2, Qt.DashLine))
        p.drawRect(QRectF(8, 8, 32, 32))
        p.setPen(QPen(c, 3.2, Qt.SolidLine, Qt.RoundCap))
        _arrow(p, 22, 26, 36, 12)
    elif name == "axis":
        _arrow(p, 16, 32, 40, 32, 5)
        _arrow(p, 16, 32, 16, 8, 5)
        _poly(p, [(16, 26), (22, 32), (16, 38), (10, 32)])
    elif name == "view_space":  # frame of the view with axis cross
        p.drawRoundedRect(QRectF(8, 12, 32, 24), 3, 3)
        p.drawLine(QPointF(24, 24), QPointF(34, 24))
        p.drawLine(QPointF(24, 24), QPointF(24, 16))
        _dot(p, 24, 24, 2.5, c)
    elif name == "local":
        _poly(p, [(10, 17), (24, 10), (38, 17), (38, 33), (24, 40), (10, 33)])
        p.drawLine(QPointF(10, 17), QPointF(24, 24))
        p.drawLine(QPointF(38, 17), QPointF(24, 24))
        p.drawLine(QPointF(24, 24), QPointF(24, 40))
    elif name == "point":
        p.setPen(QPen(c, 1.6))
        _poly(p, [(8, 36), (24, 14), (40, 30)], closed=False)
        for x, y, r in ((8, 36, 3), (40, 30, 3), (24, 14, 6.5)):
            _dot(p, x, y, r, c)
    elif name == "edge":
        _dot(p, 8, 36, 3, c)
        _dot(p, 40, 12, 3, c)
        p.setPen(QPen(c, 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(12, 33), QPointF(36, 15))
    elif name == "face":
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 90))
        _poly(p, [(14, 10), (42, 14), (34, 38), (6, 34)])
    elif name == "grid":  # base grid (floor in perspective, without border)
        p.setPen(QPen(c, 1.8, Qt.SolidLine, Qt.RoundCap))
        for k in range(5):
            t = k / 4
            p.drawLine(QPointF(14 + 20 * t, 12), QPointF(2 + 44 * t, 38))      # longitudinal lines toward the vanishing point
        for y, half in ((12, 10), (18.5, 13), (26, 17), (38, 22)):
            p.drawLine(QPointF(24 - half, y), QPointF(24 + half, y))
    elif name == "note":  # note: brackets at top left and bottom right, two lines
        p.setPen(QPen(c, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        _poly(p, [(8, 19), (8, 10), (17, 10)], closed=False)
        _poly(p, [(40, 29), (40, 38), (31, 38)], closed=False)
        p.drawLine(QPointF(14, 20), QPointF(34, 20))
        p.drawLine(QPointF(14, 28), QPointF(28, 28))
    elif name == "planes":
        _poly(p, [(14, 12), (44, 12), (34, 36), (4, 36)])
        p.setPen(QPen(c, 1.6))
        for t in (1 / 3, 2 / 3):
            p.drawLine(QPointF(14 - 10 * t, 12 + 24 * t), QPointF(44 - 10 * t, 12 + 24 * t))
            p.drawLine(QPointF(14 + 30 * t, 12), QPointF(4 + 30 * t, 36))
    elif name == "xray":
        _poly(p, [(10, 16), (30, 16), (30, 36), (10, 36)])
        p.drawLine(QPointF(10, 16), QPointF(18, 9)); p.drawLine(QPointF(30, 16), QPointF(38, 9))
        p.drawLine(QPointF(18, 9), QPointF(38, 9)); p.drawLine(QPointF(38, 9), QPointF(38, 29))
        p.drawLine(QPointF(30, 36), QPointF(38, 29))
        p.setPen(QPen(c, 1.8, Qt.DashLine))
        p.drawLine(QPointF(18, 9), QPointF(18, 29)); p.drawLine(QPointF(18, 29), QPointF(38, 29))
        p.drawLine(QPointF(18, 29), QPointF(10, 36))
    elif name == "wire":  # wireframe: sphere of latitude and longitude circles
        p.drawEllipse(QRectF(8, 8, 32, 32))
        p.drawEllipse(QRectF(17, 8, 14, 32))
        p.drawEllipse(QRectF(8, 17, 32, 14))
    elif name == "paintmode":  # paint mode: paint roller (roller, bracket, handle) above a painted surface
        p.drawRoundedRect(QRectF(9, 8, 26, 10), 3, 3)
        _poly(p, [(35, 13), (40, 13), (40, 23), (24, 23), (24, 30)], closed=False)
        p.setPen(QPen(c, 5.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(24, 31), QPointF(24, 40))
        p.setPen(QPen(c, 2.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(6, 43), QPointF(42, 43))
    elif name in ("eye", "eye_off"):  # eye in the outliner: visible / hidden
        path = QPainterPath(QPointF(6, 24))
        path.quadTo(QPointF(24, 8), QPointF(42, 24))
        path.quadTo(QPointF(24, 40), QPointF(6, 24))
        p.drawPath(path)
        if name == "eye":
            p.drawEllipse(QPointF(24, 24), 5, 5)
        else:
            p.drawLine(QPointF(10, 38), QPointF(38, 10))
    elif name == "layers":  # planes: three stacked diamonds (show/hide lines, color lines, painting)
        for dy in (0, 9, 18):
            _poly(p, [(24, 8 + dy), (40, 15 + dy), (24, 22 + dy), (8, 15 + dy)])
    elif name == "null":  # null: axis cross
        p.drawLine(QPointF(24, 8), QPointF(24, 40))
        p.drawLine(QPointF(8, 24), QPointF(40, 24))
        p.drawLine(QPointF(14, 34), QPointF(34, 14))
    elif name == "mirror":  # symmetry: shape and its mirror image at a dashed axis
        _poly(p, [(20, 12), (20, 36), (8, 30)])
        _poly(p, [(28, 12), (28, 36), (40, 30)])
        p.setPen(QPen(c, 2.0, Qt.DashLine))
        p.drawLine(QPointF(24, 6), QPointF(24, 42))
    elif name == "array":  # array: three identical boxes
        for x in (6, 19, 32):
            _poly(p, [(x, 18), (x + 10, 18), (x + 10, 30), (x, 30)])
    elif name == "mesh":
        _poly(p, [(24, 8), (40, 17), (40, 33), (24, 42), (8, 33), (8, 17)])
        p.setPen(QPen(c, 1.6))
        p.drawLine(QPointF(8, 17), QPointF(40, 33)); p.drawLine(QPointF(40, 17), QPointF(8, 33))
        p.drawLine(QPointF(24, 8), QPointF(24, 42))
    elif name == "pressure":  # pressure: a stroke swelling from the thin to the thick end
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        path = QPainterPath(QPointF(6, 36))
        path.cubicTo(QPointF(16, 30), QPointF(26, 14), QPointF(41, 9))
        path.cubicTo(QPointF(44, 15), QPointF(43, 21), QPointF(40, 24))
        path.cubicTo(QPointF(28, 30), QPointF(18, 36), QPointF(6, 36))
        p.drawPath(path)
    elif name == "smooth":
        path = QPainterPath(QPointF(6, 34))
        path.cubicTo(QPointF(18, 6), QPointF(30, 42), QPointF(42, 14))
        p.drawPath(path)
    elif name == "contrast":
        p.drawEllipse(QPointF(24, 24), 15, 15)
        path = QPainterPath(QPointF(24, 9))
        path.arcTo(QRectF(9, 9, 30, 30), 90, 180)
        path.closeSubpath()
        p.setBrush(c)
        p.drawPath(path)
    elif name == "sun":
        p.drawEllipse(QPointF(24, 24), 8, 8)
        for k in range(8):
            a = k * math.pi / 4
            p.drawLine(QPointF(24 + 13 * math.cos(a), 24 + 13 * math.sin(a)), QPointF(24 + 18 * math.cos(a), 24 + 18 * math.sin(a)))
    elif name == "moon":
        path = QPainterPath()
        path.addEllipse(QPointF(24, 24), 15, 15)
        cut = QPainterPath()
        cut.addEllipse(QPointF(32, 18), 13, 13)
        p.drawPath(path.subtracted(cut))


_ICONS = {}  # (name, colors) -> QIcon: the outliner asks for the eye on every row – repainting it every time cost
# the largest part of its rebuild (harbor: ~17 of 25 ms)


def icon(name):
    """QIcon with gray (off) and copper (on)."""
    key = (name, ICON_IDLE.rgba(), ICON_ON.rgba())
    if key not in _ICONS:
        _ICONS[key] = _make_icon(name)
    return _ICONS[key]


def _make_icon(name):
    ic = QIcon()
    for color, state in ((ICON_IDLE, QIcon.Off), (ICON_ON, QIcon.On)):
        pix, p = _painter(color)
        _draw(name, p, color)
        p.end()
        ic.addPixmap(pix, QIcon.Normal, state)
    return ic


def paint_icon(p, name, color, rect):
    """Draw an icon directly into a painter (e.g. into the viewport overlay), in rect and color color."""
    p.save()
    p.translate(rect.x(), rect.y())
    p.scale(rect.width() / ICON_PX, rect.height() / ICON_PX)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(color, 3.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    _draw(name, p, color)
    p.restore()


def swatch(rgb, current=False):
    """Color swatch (grays / last colors); current: the current color (larger, with ring)."""
    pix = QPixmap(ICON_PX, ICON_PX)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(LINE), 2))
    p.setBrush(QColor(*rgb))
    if current:
        p.setPen(QPen(QColor(ACCENT), 2.5))
        p.drawEllipse(QRectF(5, 5, 38, 38))
    else:
        p.drawRoundedRect(QRectF(8, 8, 32, 32), 6, 6)
    p.end()
    return QIcon(pix)


STYLE = f"""
QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; font-size: 12px; }}
QMenuBar {{ background: {BG}; color: {TEXT}; border-bottom: 1px solid {LINE}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; }}
QMenuBar::item:selected {{ color: {ACCENT}; }}
QMenu {{ background: {PANEL}; color: {TEXT}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 12px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
QToolBar {{ background: {BG}; border: none; spacing: 4px; padding: 4px; }}
QToolBar::separator {{ background: {LINE}; width: 1px; height: 1px; margin: 6px; }}
QToolButton {{ background: transparent; color: {TEXT_DIM}; border: 1px solid transparent; border-radius: 5px; padding: 4px 8px; }}
QToolButton:hover {{ background: {RAISED}; color: {TEXT}; }}
QToolButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; border: 1px solid rgba(208, 138, 94, 0.45); }}
QToolBar#rail QToolButton {{ padding: 5px; }}
QToolBar#modes QToolButton {{ padding: 4px 14px; font-size: 13px; }}
QDockWidget {{ color: {TEXT_DIM}; titlebar-close-icon: none; }}
QDockWidget::title {{ background: {BG}; padding: 6px 8px; border-bottom: 1px solid {LINE}; }}
QTreeWidget, QTreeView {{ background: {PANEL}; alternate-background-color: {PANEL}; border: none; color: {TEXT}; }}
QTreeView::item {{ padding: 3px 0; }}
QTreeView::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QHeaderView::section {{ background: {PANEL}; color: {TEXT_DIM}; border: none; border-bottom: 1px solid {LINE}; border-right: 1px solid {LINE}; padding: 2px 6px; }}
QStatusBar {{ background: {BG}; color: {TEXT_DIM}; border-top: 1px solid {LINE}; }}
QStatusBar::item {{ border: none; }}
QSlider::groove:horizontal {{ height: 3px; background: {LINE}; border-radius: 1px; }}
QSlider::groove:vertical {{ width: 3px; background: {LINE}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 1px; }}
QSlider::add-page:vertical {{ background: {ACCENT}; border-radius: 1px; }}
QSlider:horizontal {{ min-height: 20px; }}
QSlider:vertical {{ min-width: 20px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; }}
QSlider::handle:vertical {{ background: {TEXT}; width: 12px; height: 12px; margin: 0 -5px; border-radius: 6px; }}
QSlider::handle:hover {{ background: {ACCENT}; }}
QDoubleSpinBox, QSpinBox, QLineEdit {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; border-radius: 4px; padding: 2px 4px; selection-background-color: {ACCENT}; }}
QPushButton {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; border-radius: 4px; padding: 5px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QDialog, QMessageBox {{ background: {PANEL}; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {LINE}; padding: 5px; }}
QScrollBar:vertical {{ background: {PANEL}; width: 9px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {PANEL}; height: 9px; }}
QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QAbstractScrollArea::corner {{ background: {PANEL}; }}
QLabel#railCaption {{ color: {TEXT_DIM}; font-size: 10px; }}
"""

"""Color picker for brush and surfaces: color wheel (hue as ring, saturation/brightness in the square) and the recently
used colors, as a small popup at the toolbar."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QConicalGradient, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QToolButton, QVBoxLayout, QWidget

from . import ui
from .i18n import tr

WHEEL = 196  # size of the color wheel in px
RING = 18  # width of the hue ring


def to_qcolor(rgb):
    return QColor.fromRgbF(*(max(0.0, min(1.0, float(c))) for c in rgb))


def from_qcolor(c):
    return (c.redF(), c.greenF(), c.blueF())


class ColorWheel(QWidget):
    """Ring = hue, square inside = saturation (left→right) and brightness (bottom→top)."""
    changed = Signal(tuple)  # RGB 0..1, live while dragging
    released = Signal(tuple)

    def __init__(self, rgb=(0.24, 0.23, 0.22)):
        super().__init__()
        self.setFixedSize(WHEEL, WHEEL)
        c = to_qcolor(rgb)
        self.h = max(c.hsvHueF(), 0.0)
        self.s, self.v = c.hsvSaturationF(), c.valueF()
        self._drag = None

    def set_rgb(self, rgb):
        c = to_qcolor(rgb)
        if c.hsvHueF() >= 0:
            self.h = c.hsvHueF()
        self.s, self.v = c.hsvSaturationF(), c.valueF()
        self.update()

    def rgb(self):
        return from_qcolor(QColor.fromHsvF(self.h % 1.0, self.s, self.v))

    def _square(self):
        r = WHEEL / 2 - RING - 6
        side = r * math.sqrt(2)
        return QRectF(WHEEL / 2 - side / 2, WHEEL / 2 - side / 2, side, side)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center = QPointF(WHEEL / 2, WHEEL / 2)
        grad = QConicalGradient(center, 0)
        for k in range(13):
            grad.setColorAt(k / 12, QColor.fromHsvF((k / 12) % 1.0, 1.0, 1.0))
        p.setPen(QPen(QBrush(grad), RING))
        p.setBrush(Qt.NoBrush)
        r = WHEEL / 2 - RING / 2 - 1
        p.drawEllipse(center, r, r)
        sq = self._square()
        hue = QLinearGradient(sq.topLeft(), sq.topRight())
        hue.setColorAt(0, QColor(255, 255, 255))
        hue.setColorAt(1, QColor.fromHsvF(self.h % 1.0, 1.0, 1.0))
        p.fillRect(sq, hue)
        dark = QLinearGradient(sq.topLeft(), sq.bottomLeft())
        dark.setColorAt(0, QColor(0, 0, 0, 0))
        dark.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(sq, dark)
        # markers
        a = -self.h * 2 * math.pi
        m = center + QPointF(math.cos(a) * r, math.sin(a) * r)
        p.setPen(QPen(QColor(20, 20, 20), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(m, RING / 2 - 2, RING / 2 - 2)
        q = QPointF(sq.left() + self.s * sq.width(), sq.bottom() - self.v * sq.height())
        p.setPen(QPen(QColor(255, 255, 255) if self.v < 0.6 else QColor(20, 20, 20), 2))
        p.drawEllipse(q, 6, 6)
        p.end()

    def _pick(self, pos, start=False):
        center = QPointF(WHEEL / 2, WHEEL / 2)
        d = pos - center
        dist = math.hypot(d.x(), d.y())
        sq = self._square()
        if start:
            self._drag = "square" if sq.adjusted(-4, -4, 4, 4).contains(pos) else (
                "ring" if dist > WHEEL / 2 - RING - 6 else None)
        if self._drag == "ring":
            self.h = (-math.atan2(d.y(), d.x()) / (2 * math.pi)) % 1.0
        elif self._drag == "square":
            self.s = min(max((pos.x() - sq.left()) / sq.width(), 0.0), 1.0)
            self.v = min(max((sq.bottom() - pos.y()) / sq.height(), 0.0), 1.0)
        else:
            return
        self.update()
        self.changed.emit(self.rgb())

    def mousePressEvent(self, e):
        self._pick(e.position(), start=True)

    def mouseMoveEvent(self, e):
        self._pick(e.position())

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self.released.emit(self.rgb())
        self._drag = None


class ColorPopup(QWidget):
    """Popup: color wheel and the last colors. picked(rgb, final). On request (show_at(apply=True), Edit) below it the
    button "Apply": applied(rgb, reset) – Shift+click resets."""
    picked = Signal(tuple, bool)
    applied = Signal(tuple, bool)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setStyleSheet(f"background: {ui.PANEL}; border: 1px solid {ui.LINE};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        self.wheel = ColorWheel()
        self.wheel.changed.connect(lambda rgb: self.picked.emit(rgb, False))
        self.wheel.released.connect(lambda rgb: self.picked.emit(rgb, True))
        lay.addWidget(self.wheel, 0, Qt.AlignHCenter)
        self.row = QHBoxLayout()
        self.row.setSpacing(4)
        lay.addLayout(self.row)
        self.buttons = []
        self.apply_button = QPushButton(tr("Anwenden"))
        self.apply_button.setToolTip(tr("Gewählte Flächen und Pinsellinien in dieser Farbe färben (Bleistiftlinien "
                                        "bleiben) · Shift+Klick: Färbung der Flächen zurücksetzen"))
        self.apply_button.setStyleSheet(
            f"QPushButton {{ background: {ui.PANEL}; border: 1px solid {ui.LINE}; border-radius: 3px; padding: 4px 10px; }}"
            f"QPushButton:hover {{ border: 1px solid {ui.ACCENT}; }}")
        self.apply_button.clicked.connect(lambda: self.applied.emit(
            self.wheel.rgb(), bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)))
        self.apply_button.hide()
        lay.addWidget(self.apply_button)

    def show_at(self, global_pos, rgb, recent, apply=False):
        self.wheel.set_rgb(rgb)
        self.apply_button.setVisible(bool(apply))
        for b in self.buttons:
            b.deleteLater()
        self.buttons = []
        for c in recent:
            b = QToolButton()
            b.setFixedSize(20, 20)
            q = to_qcolor(c)
            b.setStyleSheet(f"QToolButton {{ background: {q.name()}; border: 1px solid {ui.LINE}; border-radius: 3px; }}"
                            f"QToolButton:hover {{ border: 1px solid {ui.ACCENT}; }}")
            b.clicked.connect(lambda _=False, col=tuple(c): (self.wheel.set_rgb(col), self.picked.emit(col, True)))
            self.row.addWidget(b)
            self.buttons.append(b)
        self.adjustSize()
        self.move(global_pos)
        self.show()

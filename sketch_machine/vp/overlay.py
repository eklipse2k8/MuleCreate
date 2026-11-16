"""Overlay drawing with QPainter: gizmos, light buttons, markers, cursor."""
from .common import *  # noqa: F401,F403
from .. import ui
from ..i18n import tr


class OverlayMixin:
    # --- Axis gizmo -----------------------------------------------------
    def _gizmo_center(self):
        return QPointF(self.width() - GIZMO_MARGIN, GIZMO_MARGIN)

    def _gizmo_bubbles(self):
        """List (label, axis, color, screen point, depth, positive), back first."""
        c = self._gizmo_center()
        out = []
        for label, axis, color in AXES:
            for sign in (1, -1):
                a = axis * sign
                p = QPointF(c.x() + GIZMO_RADIUS * (a @ self.cam.right), c.y() - GIZMO_RADIUS * (a @ self.cam.up))
                out.append((label, a, color, p, a @ self.cam.back, sign > 0))
        return sorted(out, key=lambda b: b[4])

    def _gizmo_hit(self, pos):
        for label, axis, _, p, _, positive in reversed(self._gizmo_bubbles()):  # frontmost first
            if (p - pos).manhattanLength() < (13 if positive else 11):
                return axis
        return None

    def _in_gizmo(self, pos):
        return (pos - self._gizmo_center()).manhattanLength() < GIZMO_RADIUS + 22

    def _paint_axis_gizmo(self, p):
        c = self._gizmo_center()
        if self._in_gizmo(self._last_pos or QPointF(-1e4, -1e4)):
            p.setPen(Qt.NoPen)
            p.setBrush(theme.GIZMO_HALO)
            p.drawEllipse(c, GIZMO_RADIUS + 16, GIZMO_RADIUS + 16)
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(8)
        p.setFont(font)
        for label, axis, color, pt, _, positive in self._gizmo_bubbles():
            hovered = self._gizmo_hover is not None and np.allclose(self._gizmo_hover, axis)
            fill = color.lighter(140) if hovered else color
            if positive:
                p.setPen(QPen(color, 2))
                p.drawLine(c, pt)
                p.setPen(Qt.NoPen)
                p.setBrush(fill)
                p.drawEllipse(pt, 9, 9)
                p.setPen(theme.PAPER)
                self._text(p, QRectF(pt.x() - 4, pt.y() - 6, 9, 12), Qt.AlignCenter, label)
            else:
                p.setPen(QPen(fill, 1.5))
                p.setBrush(QColor(fill.red(), fill.green(), fill.blue(), 60 if not hovered else 140))
                p.drawEllipse(pt, 7, 7)

    def _draw_plane_spot(self, p):
        """Drawing plane under the pen tip: a small circle of its grid lights up – one sees spatially
        where one is drawing. Clearer outside the plane's rectangle (at infinity)."""
        if (self.select_mode or self.notes_mode or self.erase_mode or self._free_pen() or self._last_pos is None
                or self.multi_mode or self.scene.active_mesh is not None or not self.planes_visible):
            return
        plane = self.scene.active_plane
        if plane.preset or self._mode != "draw":  # own planes only and only while painting (not while hovering)
            return
        pos = self._tip if self._tip is not None else self._last_pos
        hit = self._ray_plane(pos, plane)[0]
        if hit is None:
            return
        depth = float((hit - self.cam.eye) @ -self.cam.back)
        radius = SPOT_PX * float(self._world_per_px(max(depth, NEAR)))
        step = max(plane.size_u, plane.size_v) / 10
        while radius / step > 6:  # grid fine enough for the circle, but not too dense
            step *= 2
        while radius / step < 2.5:
            step /= 2
        outside = not plane.contains(hit)
        color = QColor(theme.SEA)
        alpha = SPOT_ALPHA_OUTSIDE if outside else SPOT_ALPHA
        u, v = plane.axis_u, plane.axis_v
        local = hit - plane.origin
        cu, cv = float(local @ u), float(local @ v)
        n = int(radius / step) + 1
        for axis, other, c0, c1 in ((u, v, cu, cv), (v, u, cv, cu)):
            base = math.floor(c0 / step)
            for k in range(base - n, base + n + 2):
                off = k * step - c0  # distance of the grid line to the tip
                if abs(off) >= radius:
                    continue
                half = math.sqrt(radius * radius - off * off)
                ts = np.linspace(-half, half, 9)
                pts = hit + axis * off + np.outer(ts, other)
                screen, ok = self.project(pts)
                fade = 1 - abs(off) / radius
                for i in range(len(pts) - 1):
                    if not (ok[i] and ok[i + 1]):
                        continue
                    f = fade * (1 - abs(ts[i] + ts[i + 1]) / (2 * radius))
                    color.setAlpha(int(alpha * f))
                    p.setPen(QPen(color, 1.0))
                    p.drawLine(QPointF(*screen[i]), QPointF(*screen[i + 1]))

    def _draw_active_outline(self, p):
        """Outline of the drawing surface(s) finely over everything (also over strokes on it): one always sees
        what the surface one is drawing on looks like."""
        if not self.planes_visible:
            return
        color = QColor(theme.SEA)
        color.setAlpha(150)
        p.setPen(QPen(color, 1.2))
        p.setBrush(Qt.NoBrush)
        for s in self._drawing_surfaces():
            if isinstance(s, Plane):
                c = s.corners()
                self.draw_polyline(p, np.vstack([c, c[:1]]))
            elif isinstance(s, SurfaceObject):
                for line in s.outlines():
                    self.draw_polyline(p, np.asarray(line, float))

    def _draw_pivot(self, p, target):
        """Own axis as a yellow diamond; always in axis mode, otherwise only if one is set."""
        if not (self.ws.axis_mode or self.has_custom_pivot()):
            return
        screen, ok = self.project(target.pivot()[None])
        if not ok[0]:
            return
        c = QPointF(*screen[0])
        snapped = isinstance(target, PivotHandle) and target.snap is not None
        r = 9 if snapped else 7
        p.setPen(QPen(PIVOT_COLOR, 2))
        p.setBrush(QColor(PIVOT_COLOR.red(), PIVOT_COLOR.green(), PIVOT_COLOR.blue(), 90 if snapped else 30))
        p.drawPolygon(QPolygonF([c + QPointF(0, -r), c + QPointF(r, 0), c + QPointF(0, r), c + QPointF(-r, 0)]))

    def view_name(self):
        """Name of the view as in Houdini: Persp, Top, Front, Right ... or Ortho."""
        if not self.cam.ortho:
            return "Persp"
        for back, name in VIEW_NAMES:
            if self.cam.back @ np.array(back, float) > 0.9999:
                return name
        return "Ortho"

    def _draw_view_label(self, p):
        """View name at top left; with several viewports a frame around the active one."""
        font = QFont(self.font())
        font.setPointSize(9)
        p.setFont(font)
        p.setPen(theme.LABEL_COLOR)
        p.drawText(QRectF(10, 6, 200, 18), Qt.AlignLeft | Qt.AlignVCenter, self.view_name())
        if len([v for v in self.ws.viewports if v.isVisible()]) > 1 and self.ws.current is self:
            p.setPen(QPen(theme.CURRENT_FRAME, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(1, 1, self.width() - 2, self.height() - 2))
        self._draw_close_button(p)

    # --- Light mode: buttons at the right edge (as in Houdini) and sky disc for the sun ---
    def _light_buttons(self):
        """{name: center} of the buttons below the axis gizmo."""
        x = self.width() - GIZMO_MARGIN
        y0 = GIZMO_MARGIN * 2 + 6
        return {"light": QPointF(x, y0), "sun": QPointF(x, y0 + LIGHT_BUTTON * 2 + 6)}

    def _sun_disc(self):
        """(center, radius) of the sky disc at bottom right (only while editing the sun)."""
        return QPointF(self.width() - SUN_DISC - 26, self.height() - SUN_DISC - 46), SUN_DISC  # room for the elevation label

    def _light_hit(self, pos):
        for name, c in self._light_buttons().items():
            if (pos - c).manhattanLength() <= LIGHT_BUTTON * 1.4:
                return name
        if self.ws.sun_edit:
            c, r = self._sun_disc()
            if math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= r + 8:
                return "disc"
        return None

    def set_light(self, on):
        self.ws.light_on = bool(on)
        if not on:
            self.ws.sun_edit = False
        self.notify(tr("Licht an: eine Sonne – Sonne bearbeiten mit dem Knopf darunter") if on else tr("Licht aus"))
        self.toggles_changed.emit()
        self.update()

    def show_light_bands(self, global_pos):
        """Slider of the light steps (right-click on the light icon, View → Light steps …): left 3 steps,
        middle 10, far right smooth. Saved with the scene."""
        menu = QMenu(self)
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(10, 6, 10, 6)
        value = QLabel()
        value.setMinimumWidth(64)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setFixedWidth(160)
        slider.setValue(light_mod.slider_from_bands(self.scene.light_bands))
        slider.setToolTip(tr("Licht in Stufen (Cel-Shading): links 3, Mitte 10, ganz rechts fließend"))

        def show(bands):
            value.setText(tr("{0} Stufen").format(bands) if bands else tr("fließend"))

        def changed(v):
            bands = light_mod.bands_from_slider(v)
            self.scene.light_bands = bands
            self.scene.dirty = True
            show(bands)
            if not self.ws.light_on:
                self.set_light(True)
            for vp in self.ws.viewports:
                vp.update()

        show(self.scene.light_bands)
        slider.valueChanged.connect(changed)
        lay.addWidget(QLabel(tr("Licht-Stufen")))
        lay.addWidget(slider)
        lay.addWidget(value)
        holder = QWidgetAction(menu)
        holder.setDefaultWidget(box)
        menu.addAction(holder)
        menu.exec(global_pos)

    def set_sun_edit(self, on):
        if on and not self.ws.light_on:
            self.ws.light_on = True
        self.ws.sun_edit = bool(on)
        self.toggles_changed.emit()
        self.update()

    def _sun_from_disc(self, pos):
        c, r = self._sun_disc()
        az, el = light_mod.from_disc((pos.x() - c.x()) / r, (pos.y() - c.y()) / r)
        self.scene.sun = (az, el)
        self.scene.dirty = True
        self.status_changed.emit(tr("Sonne: Höhe {0:.0f}°, Richtung {1:.0f}°  |  Mitte = senkrecht von oben, Rand = Horizont").format(el, az))
        self.update()

    def _paint_light_strip(self, p, part):
        """part: \"buttons\" (light, edit sun) or \"disc\" (sky disc)."""
        on = self.ws.light_on
        for name, c in (self._light_buttons().items() if part == "buttons" else []):
            active = on if name == "light" else self.ws.sun_edit
            usable = name == "light" or on
            ring = QColor(theme.TERRACOTTA) if active else QColor(theme.LABEL_COLOR)
            if not usable:
                ring.setAlpha(70)
            p.setPen(QPen(ring, 1.4))
            fill = QColor(theme.PAPER)
            fill.setAlpha(200)
            p.setBrush(fill)
            p.drawEllipse(c, LIGHT_BUTTON, LIGHT_BUTTON)
            if name == "light":  # sun: circle with rays
                p.drawEllipse(c, 3.5, 3.5)
                for k in range(8):
                    a = k * math.pi / 4
                    p.drawLine(c + QPointF(math.cos(a) * 6, math.sin(a) * 6), c + QPointF(math.cos(a) * 8.5, math.sin(a) * 8.5))
            else:  # sky disc with sun point
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, 7, 7)
                dx, dy = light_mod.to_disc(self.scene.sun)
                p.setBrush(ring)
                p.drawEllipse(c + QPointF(dx * 7, dy * 7), 2.4, 2.4)
        if part != "disc" or not self.ws.sun_edit:
            return
        c, r = self._sun_disc()
        bg = QColor(theme.PAPER)
        bg.setAlpha(225)
        p.setPen(QPen(QColor(theme.LABEL_COLOR), 1.2))
        p.setBrush(bg)
        p.drawEllipse(c, r, r)
        for frac in (1 / 3, 2 / 3):  # elevation circles: 60° and 30°
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r * frac, r * frac)
        p.drawLine(c - QPointF(r, 0), c + QPointF(r, 0))
        p.drawLine(c - QPointF(0, r), c + QPointF(0, r))
        font = QFont(self.font())
        font.setPointSize(7)
        p.setFont(font)
        for text, off in (("+X", QPointF(r + 5, 4)), ("-X", QPointF(-r - 18, 4)), ("+Z", QPointF(-7, r + 13)),
                          ("-Z", QPointF(-6, -r - 5))):
            self._text(p, c + off, None, text)
        dx, dy = light_mod.to_disc(self.scene.sun)
        col = light_mod.color(self.scene.sun)
        sun_q = QColor.fromRgbF(*col)
        p.setPen(QPen(QColor(theme.TERRACOTTA), 2))
        p.setBrush(sun_q)
        p.drawEllipse(c + QPointF(dx * r, dy * r), 7, 7)
        p.setPen(QColor(theme.LABEL_COLOR))
        self._text(p, QRectF(c.x() - r - 20, c.y() + r + 17, 2 * r + 40, 16), Qt.AlignCenter,
                   tr("Höhe {0:.0f}°  ·  {1:.0f}°").format(self.scene.sun[1], self.scene.sun[0]))

    def _close_rect(self):
        """X at top right to close – only if there is more than one viewport."""
        if self.area is None or self.area.count() <= 1:
            return None
        return QRectF(self.width() - CLOSE_BUTTON - 6, 6, CLOSE_BUTTON, CLOSE_BUTTON)

    def _over_close(self, pos):
        rect = self._close_rect()
        return rect is not None and pos is not None and rect.adjusted(-3, -3, 3, 3).contains(pos)

    def _draw_close_button(self, p):
        rect = self._close_rect()
        if rect is None:
            return
        hover = self._mode is None and self._over_close(self._last_pos)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.CLOSE_BG_HOVER if hover else theme.CLOSE_BG)
        p.drawRoundedRect(rect, 3, 3)
        p.setPen(QPen(theme.CLOSE_FG_HOVER if hover else theme.CLOSE_FG, 1.6))
        m = 4.5
        p.drawLine(QPointF(rect.left() + m, rect.top() + m), QPointF(rect.right() - m, rect.bottom() - m))
        p.drawLine(QPointF(rect.right() - m, rect.top() + m), QPointF(rect.left() + m, rect.bottom() - m))

    def _draw_snap_marks(self, p):
        """Green point where the pen would snap; in selection mode small rings at open ends."""
        if self._snap_dot is not None:
            screen, ok = self.project(self._snap_dot[None])
            if ok[0]:
                p.setPen(QPen(theme.GRAPHITE, 1))
                p.setBrush(CONNECT_COLOR)
                p.drawEllipse(QPointF(*screen[0]), 4.5, 4.5)
        # points drawn into an image (clean on scaled screens, see _raster)
        if self.select_mode and self.ws.component == "point":
            return self._raster_at(p, QRectF(0, 0, self.width(), self.height()), self._draw_points)
        if self.select_mode and self.ws.component == "edge":  # see connections: shared points, open ends
            return self._raster_at(p, QRectF(0, 0, self.width(), self.height()),
                                   lambda q: (self._draw_net_marks(q, plain=False), self._draw_hardness(q)))

    def _draw_eraser(self, p):
        """Eraser circle at the cursor while D is held."""
        if not self.erase_mode or self._last_pos is None:
            return
        r = self.eraser_px / 2
        p.setPen(QPen(ERASER_COLOR, 1.5))
        p.setBrush(QColor(ERASER_COLOR.red(), ERASER_COLOR.green(), ERASER_COLOR.blue(), 40 if self._mode == "erase" else 18))
        p.drawEllipse(self._last_pos, r, r)

    def _draw_smooth_string(self, p):
        """When drawing with smoothing: circle around the cursor and a string to the pen tip."""
        if self._mode != "draw" or self._straight or self._tip is None or self.smooth <= 0:
            return
        cursor = self._last_pos
        if cursor is None:
            return
        radius = self._smooth_radius()
        p.setPen(QPen(theme.GRAPHITE_SOFT, 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(cursor, radius, radius)
        p.setPen(QPen(theme.GRAPHITE_SOFT, 1, Qt.DashLine))
        p.drawLine(self._tip, cursor)

    def _draw_pen_feedback(self, p):
        """Circle at pen size at the cursor, briefly after adjusting (Ctrl + wheel / Ctrl + RMB)."""
        if self.erase_mode or self._mode != "pensize" and time.monotonic() > self._pen_feedback_until:
            return
        pos = self._press_pos if self._mode == "pensize" else self._last_pos
        if pos is None:
            return
        if self.pen_world_mode:
            # depth from _scale_pen: never query the GPU here while drawing (that would free the context)
            px = self.pen_world / self._world_per_px(self._feedback_depth)
        else:
            px = self.pen_px
        p.setPen(QPen(theme.FEEDBACK_PEN, 1))
        p.setBrush(theme.FEEDBACK_FILL)
        p.drawEllipse(pos, max(px / 2, 1.0), max(px / 2, 1.0))

    def _drawing_surfaces(self):
        """Surfaces being drawn on: in multi mode all selected ones, otherwise the active one."""
        if self._free_pen() or self.select_mode or self.notes_mode:  # free: view plane; selection/notes: no drawing target
            return []
        return self._multi_surfaces() if self.multi_mode else [self.scene.active_surface]

    def draw_polyline(self, p, pts):
        screen, ok = self.project(pts)
        run = []
        for i in range(len(pts)):  # contiguous pieces in front of the camera as one polyline
            if ok[i]:
                run.append(QPointF(screen[i, 0], screen[i, 1]))
            elif run:
                if len(run) > 1:
                    p.drawPolyline(QPolygonF(run))
                run = []
        if len(run) > 1:
            p.drawPolyline(QPolygonF(run))

    def _draw_world_axes(self, p):
        """Axis cross at the origin – part of the drawing aids (off: raw result, no cross)."""
        if not self.planes_visible:
            return
        for _, axis, color in AXES:
            p.setPen(QPen(color, 2))
            self.draw_polyline(p, np.array([np.zeros(3), axis * 1.5]))

    # --- at the bottom of the main viewport: which tools and switches are currently active ---
    def _draw_review_pins(self, p):
        """Review running (review.py): each "Here!" mark as a magenta ring with a number at the hit spot – stays until
        the end of the review, the new one briefly flashes large; without a hit, briefly a gray ring with "?" at the cursor."""
        aim = getattr(self.ws, "review_aim", None)
        if aim is not None and aim.get("vp") is self:  # marking: preview ring at the cursor
            pos = aim["screen"]
            color = QColor(225, 0, 160) if aim["hit"] else QColor(150, 150, 150)
            box = QRectF(pos.x() - 24, pos.y() - 24, 48, 48)

            def ring(g, pos=pos, color=color):
                g.setBrush(Qt.NoBrush)
                g.setPen(QPen(QColor(255, 255, 255, 220), 4))
                g.drawEllipse(pos, 13, 13)
                pen = QPen(color, 2.2, Qt.DashLine)
                g.setPen(pen)
                g.drawEllipse(pos, 13, 13)
                g.setPen(QPen(color, 1.6))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    g.drawLine(QPointF(pos.x() + dx * 17, pos.y() + dy * 17), QPointF(pos.x() + dx * 22, pos.y() + dy * 22))
            self._raster_at(p, box, ring)
        pins = getattr(self.ws, "review_pins", None)
        if not pins:
            return
        import time
        from .. import review
        now = time.monotonic()
        hits = [q for q in pins if q.get("point") is not None]
        where = {}
        if hits:
            xy, ok = self.project(np.array([q["point"] for q in hits], float))
            for q, s, good in zip(hits, xy, ok):
                if good and np.all(np.isfinite(s)):
                    where[id(q)] = QPointF(float(s[0]), float(s[1]))
        for q in pins:
            if q.get("point") is None and q.get("vp") is self and q.get("screen") is not None \
                    and now - q["at"] < review.FLASH_S + 0.6:
                where[id(q)] = q["screen"]
        for q in pins:
            pos = where.get(id(q))
            if pos is None:
                continue
            age = now - q["at"]
            grow = max(0.0, 1.0 - age / review.FLASH_S) if age < review.FLASH_S else 0.0
            r = 9.0 + 22.0 * grow
            miss = q.get("point") is None
            color = QColor(150, 150, 150) if miss else QColor(225, 0, 160)
            label = f"{q['n']}?" if miss else str(q["n"])
            box = QRectF(pos.x() - r - 4, pos.y() - r - 18, 2 * r + 40, 2 * r + 24)

            def paint(g, pos=pos, r=r, color=color, label=label, grow=grow):
                g.setBrush(Qt.NoBrush)
                g.setPen(QPen(QColor(255, 255, 255, 230), 4.5))
                g.drawEllipse(pos, r, r)
                g.setPen(QPen(color, 2.4 if not grow else 3.2))
                g.drawEllipse(pos, r, r)
                g.drawEllipse(pos, 1.6, 1.6)
                f = g.font()
                f.setBold(True)
                g.setFont(f)
                g.setPen(QPen(QColor(255, 255, 255, 230), 3.5))
                self._text(g, QPointF(pos.x() + r + 3, pos.y() - r + 2), 0, label)
                g.setPen(color)
                self._text(g, QPointF(pos.x() + r + 3, pos.y() - r + 2), 0, label)
            self._raster_at(p, box, paint)

    def _raster(self, p, x, y, w, h, draw):
        """Draw into an image (raster painter, screen scaling) and put it into the overlay – the OpenGL painter
        draws fine lines, text and semi-transparency unclean on scaled screens."""
        dpr = max(self.devicePixelRatioF(), 1.0)
        img = QImage(max(1, int(w * dpr)), max(1, int(h * dpr)), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing)
        draw(q)
        q.end()
        p.drawImage(QPointF(round(x), round(y)), img)

    def _active_tool_icons(self):
        ws = self.ws
        if self.notes_mode:
            return ["note"]
        if self.select_mode:
            out = []  # the tool first (highlighted), then the selection mode
            if ws.value_tool:
                out.append({"hardness": "knot_hard", "smooth": "smooth"}[ws.value_tool])
            elif self.gizmo.tool:
                out.append(self.gizmo.tool)
            out.append({"point": "point", "edge": "edge", "face": "face"}[ws.component])
            if ws.axis_mode:
                out.append("axis")
            return out
        out = [{"pen": "pen", "brush": "brush", "eraser": "eraser"}.get(ws.draw_tool, "pen")]
        out += [name for name, on in (("paintmode", ws.paint_mode), ("free", self.free_draw),
                                      ("multi", self.multi_mode), ("magnet", ws.magnet)) if on]
        return out

    def _draw_tool_bar(self, p):
        """Small icons at the bottom center (main viewport only): the tool and the switches currently active."""
        if not self.ws.viewports or self.ws.viewports[0] is not self:
            return
        names = self._active_tool_icons()
        size, gap, pad = 20, 6, 6
        w = len(names) * size + (len(names) - 1) * gap + 2 * pad
        h = size + 2 * pad
        x, y = (self.width() - w) / 2, self.height() - h - 10

        def draw(q):
            bg = QColor(theme.PAPER)
            bg.setAlphaF(0.85)
            q.setPen(QPen(QColor(theme.GRAPHITE.red(), theme.GRAPHITE.green(), theme.GRAPHITE.blue(), 90), 1))
            q.setBrush(bg)
            q.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2, h / 2)
            for i, name in enumerate(names):
                color = theme.TERRACOTTA if i == 0 else theme.GRAPHITE  # the tool itself highlighted
                ui.paint_icon(q, name, color, QRectF(pad + i * (size + gap), pad, size, size))
        self._raster(p, x, y, w, h, draw)

    # axis gizmo, light buttons and sky disc: drawn into an image (see _raster)
    def _draw_axis_gizmo(self, p):
        c, m = self._gizmo_center(), GIZMO_RADIUS + 20
        self._raster_at(p, QRectF(c.x() - m, c.y() - m, 2 * m, 2 * m), self._paint_axis_gizmo)

    def _draw_light_strip(self, p):
        b = self._light_buttons()
        x0, y0 = b["light"].x() - LIGHT_BUTTON - 4, b["light"].y() - LIGHT_BUTTON - 4
        self._raster_at(p, QRectF(x0, y0, 2 * LIGHT_BUTTON + 8, b["sun"].y() - y0 + LIGHT_BUTTON + 4),
                        self._paint_light_buttons)
        if self.ws.sun_edit:
            c, r = self._sun_disc()
            self._raster_at(p, QRectF(c.x() - r - 30, c.y() - r - 22, 2 * r + 60, 2 * r + 60), self._paint_sun_disc)

    def _paint_light_buttons(self, p):
        self._paint_light_strip(p, "buttons")

    def _paint_sun_disc(self, p):
        self._paint_light_strip(p, "disc")

    def _raster_at(self, p, rect, paint):
        """Draw paint(q) with viewport coordinates into an image of size rect and blend it in there."""
        def draw(q):
            q.translate(-rect.x(), -rect.y())
            q.setFont(self.font())
            paint(q)
        self._raster(p, rect.x(), rect.y(), rect.width(), rect.height(), draw)

    @staticmethod
    def _text(p, where, flags, text):
        """Text as a path (grayscale smoothing; ClearType gives color fringes on transparent images). where: point
        (baseline left) or rectangle with alignment flags."""
        font = p.font()
        metrics = QFontMetricsF(font)
        if isinstance(where, QRectF):
            w = metrics.horizontalAdvance(text)
            x = where.x() + (where.width() - w) / 2 if flags & Qt.AlignHCenter else where.x()
            y = where.y() + (where.height() + metrics.ascent() - metrics.descent()) / 2
        else:
            x, y = where.x(), where.y()
        path = QPainterPath()
        path.addText(QPointF(x, y), font, text)
        pen = p.pen()
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(pen.color())
        p.drawPath(path)
        p.restore()


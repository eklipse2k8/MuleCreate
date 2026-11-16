"""Free mode (Q): strokes between points in space."""
from .common import *  # noqa: F401,F403
from ..i18n import tr


MULTI_FRAME = (230, 165, 60)  # frame in multi mode (amber, dashed)


class FreeDrawMixin:
    # --- Free mode (Q): draw without a plane, attached to existing things ---
    def set_magnet(self, on):
        self.ws.magnet = on
        self._snap_dot = None
        self.notify(tr("Magnet an: Strichanfang und -ende rasten an Linien ein") if on
                    else tr("Magnet aus: frei zeichnen, nichts rastet ein"))
        self.toggles_changed.emit()
        self._changed()

    def set_free_draw(self, on):
        self.free_draw = on
        self._free_hover = None
        self.notify(tr("Frei-Modus an: an einer Linie oder auf einer Fläche ansetzen und in der Blickebene weiterzeichnen")
                    if on else tr("Frei-Modus aus: gezeichnet wird wieder auf der aktiven Fläche"))
        self.toggles_changed.emit()
        self._changed()

    def _free_pen(self):
        """Is free mode currently active? Only with pen/brush in draw mode (eraser as always)."""
        return self.free_draw and not self.select_mode and not self.notes_mode and self.ws.draw_tool in ("pen", "brush")

    def _snap_points(self):
        """All points (N,3): line ends, corners and inserted points; cached until _changed."""
        cache = self.ws.points_cache
        if cache is None or cache[0] is not self.scene:
            pts = [c.points[k] for c in self._visible_curves() for k in components.knots(c)]
            cache = self.ws.points_cache = (self.scene, np.array(pts) if pts else np.zeros((0, 3)))
        return cache[1]

    def _free_point_snap(self, pos):
        """Point (end, corner, inserted point) under the cursor, at any depth - the nearest one on
        screen, the frontmost on a tie. Otherwise None."""
        pts = self._snap_points()
        if pos is None or not len(pts):
            return None
        screen, ok = self.project(pts)
        d = np.hypot(screen[:, 0] - pos.x(), screen[:, 1] - pos.y())
        d[~ok | np.isnan(d)] = np.inf
        near = np.flatnonzero(d < FREE_POINT_PX)
        if not len(near):
            return None
        best = near[d[near] <= d[near].min() + TIE_SCREEN_PX]
        return pts[best[np.argmin((pts[best] - self.cam.eye) @ -self.cam.back)]].copy()

    def _free_anchor(self, pos, with_kind=False):
        """Start point in free mode: a point under the cursor (end, corner) takes precedence, otherwise the frontmost
        point of a line or surface. with_kind: (point, on a line?)."""
        point = self._free_point_snap(pos) if self.ws.magnet else None
        if point is not None:
            return (point, True) if with_kind else point
        eye, view = self.cam.eye, -self.cam.back
        best = None
        on_line = False
        curve, point = self._curve_under(pos, PICK_PX)
        if curve is not None:
            best = ((point - eye) @ view, point)
            on_line = True
        surface, hit, _ = self._mesh_under(pos)  # surface (or mesh) under the cursor
        if hit is not None and isinstance(surface, SurfaceObject):
            depth = (hit - eye) @ view
            if best is None or depth < best[0] - 1e-6:
                best, on_line = (depth, hit), False
        point = None if best is None else np.asarray(best[1], float)
        return (point, on_line) if with_kind else point

    def _begin_free(self, anchor):
        """Activate an imaginary plane facing the camera through the start point for this stroke."""
        self._free_saved = (self.scene.active_plane, self.scene.active_mesh, self.ws.multi_mode)
        u, v = self.cam.right.copy(), self.cam.up.copy()
        if getattr(self.ws, "free_upright", False):
            # upright plane (right-click toggle): vertical, turned to the camera - up then really means
            # up (harbor test: pipes drawn at an angle from above otherwise ran into the depth); vertically from above: as before
            flat = np.array([u[0], 0.0, u[2]])
            if abs(float(self.cam.back[1])) < 0.85 and np.linalg.norm(flat) > 0.2:  # steep from above: edge-on, as before
                u, v = flat / np.linalg.norm(flat), np.array([0.0, 1.0, 0.0])
        self.scene.active_plane = Plane("Frei", anchor.copy(), u, v, 1e5, 1e5)
        self.scene.active_mesh = None
        self.ws.multi_mode = False

    def _end_free(self):
        if self._free_saved is not None:
            self.scene.active_plane, self.scene.active_mesh, self.ws.multi_mode = self._free_saved
            self._free_saved = None
        self._free_start = None

    def _free_end_snap(self, pos):
        """End in free mode: line end or line under the cursor, at any depth (frontmost)."""
        if not self.ws.magnet:
            return None, False
        point = self._free_point_snap(pos)  # corners and inserted points become real nodes when snapping
        if point is not None:
            return point, True
        curve, point = self._curve_under(pos, SNAP_PX)
        return (point, True) if curve is not None else (None, False)

    def _free_span(self, points, target):
        """Free stroke with snapped end: lay it on the plane through start and target point that faces
        the camera as well as possible (it contains the start-target connection). Each point moves along its
        view ray - on screen the stroke looks the same, in space it connects both points
        without a kink. If the connection points almost along the view direction, only the end bends toward it."""
        pts = np.array(points, float)
        a, b = pts[0], np.asarray(target, float)
        u = b - a
        length = float(np.linalg.norm(u))
        n = None
        if length > 1e-9:
            u = u / length
            n = self.cam.back - (self.cam.back @ u) * u
            n = n / np.linalg.norm(n) if np.linalg.norm(n) > FREE_SPAN_MIN else None
        new = None
        if n is not None:
            dirs = np.tile(self.cam.back, (len(pts), 1)) if self.cam.ortho else pts - self.cam.eye
            denom = dirs @ n
            if np.all(np.abs(denom) > 1e-9):
                new = pts + (((a - pts) @ n) / denom)[:, None] * dirs
                if not self.cam.ortho and np.any((new - self.cam.eye) @ -self.cam.back <= NEAR):
                    new = None  # plane intersects behind the camera: do not use
        if new is not None:
            new[0] = a
            for i in range(len(pts)):
                points[i] = new[i]
        self._blend_end(points, b)  # remainder (snap radius) or without a plane: bend the end softly

    @staticmethod
    def _blend_end(points, target):
        """Pull the stroke end onto target: the last third bends along softly (tapering off gently)."""
        pts = np.array(points, float)
        arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        span = max(arc[-1] / 3, 1e-9)
        t = np.clip((arc - (arc[-1] - span)) / span, 0, 1)
        w = t * t * (3 - 2 * t)
        offset = target - pts[-1]
        for i in np.flatnonzero(w > 0):
            points[i] = pts[i] + w[i] * offset

    def _draw_free(self, p):
        """Free mode: sea-green frame around the viewport, start point under the cursor as a ring. Multi mode (B):
        dashed amber frame - one should never overlook that it is on (harbor test: mountains accidentally
        recolored along)."""
        if self.multi_mode and not self.select_mode and not self.notes_mode:
            pen = QPen(QColor(*MULTI_FRAME), 3)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            inset = 6.5 if self._free_pen() else 1.5
            p.drawRect(QRectF(inset, inset, self.width() - 2 * inset, self.height() - 2 * inset))
        if not self._free_pen():
            return
        p.setPen(QPen(theme.SEA, 3))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3))
        self._draw_snap_rings(p, self._snap_points() if self.ws.magnet else ())
        if self._mode is None and self._free_hover is not None:
            s, ok = self.project(self._free_hover[None])
            if ok[0]:
                p.setPen(QPen(CONNECT_COLOR, 2))
                p.drawEllipse(QPointF(*s[0]), 6.5, 6.5)

    def _draw_surface_snaps(self, p):
        """Drawing on surfaces/planes (pen/brush, no paint mode): the points on the drawing surface as small rings -
        only these snap the pen (_surface_snap_points)."""
        if (self._free_pen() or self.select_mode or self.notes_mode or not self.ws.magnet or self._painting()
                or self.ws.draw_tool not in ("pen", "brush")):
            return
        if self.gizmo.dragging:
            return  # nobody draws during a gizmo drag: repainting the rings every frame only cost time
        self._draw_snap_rings(p, self._surface_snap_points())

    def _draw_snap_rings(self, p, pts):
        """Existing points as small rings: start/snap onto them."""
        if not 0 < len(pts) <= FREE_POINTS_MAX:
            return
        screen, ok = self.project(pts)
        ring = QColor(CONNECT_COLOR)
        ring.setAlpha(150)
        p.setPen(QPen(ring, 1.2))
        p.setBrush(Qt.NoBrush)
        w, h = self.width(), self.height()
        for (x, y), visible in zip(screen, ok):
            if visible and -5 < x < w + 5 and -5 < y < h + 5:
                p.drawEllipse(QPointF(x, y), 2.6, 2.6)

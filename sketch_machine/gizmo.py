"""Transform gizmo as in Houdini: arrows (T), rings (R), cubes (E), plus two-axis squares
(T, E) and a purple outer ring that always rotates around the view direction (R).

Works on everything that fulfills the transform interface
(pivot, local_axes, translate, rotate, scale, scale_axes), see scene.TransformSet.
"""
import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen, QPolygonF

from .camera import rot_axis

from .theme import AXIS_COLORS, GIZMO_CENTER, HOVER_COLOR, VIEW_RING_COLOR
HANDLE_SCREEN_FRACTION = 0.12  # gizmo length relative to viewport height
HIT_PX = 8
RING_SEGMENTS = 64
VIEW_RING_SCALE = 1.25  # outer ring relative to the axis rings
PLANE_HANDLE = (0.2, 0.48)  # two-axis square: from/to as a fraction of the arrow length

TOOLS = {"translate": "Translate", "rotate": "Rotate", "scale": "Scale"}


def _dist_to_segment(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, QPointF.dotProduct(p - a, ab) / max(QPointF.dotProduct(ab, ab), 1e-9)))
    return (p - (a + ab * t)).manhattanLength()


def _snap(value, step):
    """Round to whole multiples of step (also element-wise for vectors)."""
    return np.round(np.asarray(value) / step) * step if step > 0 else value


def _snap_factor(f, step):
    """Scale factor in steps of step around 1 (e.g. 0.9, 1.0, 1.1 ... and mirrored -0.1, -1.0 ...), never zero."""
    if step <= 0:
        return f
    v = 1 + round((f - 1) / step) * step
    return v if abs(v) > step / 2 else math.copysign(step, f)


class TransformGizmo:
    def __init__(self, viewport):
        self.vp = viewport
        self.hover = None
        self._drag = None
        self.point_snap = None  # (source point at start, target point): V when moving

    # tool and space apply to all viewports together
    @property
    def tool(self):  # translate | rotate | scale | None
        return self.vp.ws.gizmo_tool

    @tool.setter
    def tool(self, value):
        self.vp.ws.gizmo_tool = value

    @property
    def space(self):  # world | local | view
        return self.vp.ws.gizmo_space

    @space.setter
    def space(self, value):
        self.vp.ws.gizmo_space = value

    @property
    def dragging(self):
        return self._drag is not None

    # --- Geometry ---
    def axes(self, target):
        """World, local or camera (Space + M cycles through) – for all tools. Only planes always scale locally:
        their width and height exist only in their own axes."""
        planes_only = tuple(target.scale_axes) == (0, 1)
        if self.space == "local" or (self.tool == "scale" and planes_only):
            return target.local_axes()
        if self.space == "view":
            return self.vp.cam.rot.copy()
        return np.eye(3)

    def _length(self, pivot):
        cam = self.vp.cam
        depth = max((pivot - cam.eye) @ -cam.back, 0.1)
        return self.vp._world_per_px(depth) * self.vp.height() * HANDLE_SCREEN_FRACTION

    def _screen(self, point):
        s, ok = self.vp.project(np.array([point]))
        return QPointF(*s[0]) if ok[0] else None

    def _axis_indices(self, target):
        return target.scale_axes if self.tool == "scale" else (0, 1, 2)

    def _plane_pairs(self, target):
        """Axis pairs for the two-axis squares (XY, XZ, YZ or only the scalable ones)."""
        axes = self._axis_indices(target)
        return [(i, j) for i in axes for j in axes if i < j]

    def _plane_quad(self, pivot, axes, length, i, j):
        a, b = PLANE_HANDLE
        u, v = axes[:, i] * length, axes[:, j] * length
        return [pivot + u * x + v * y for x, y in ((a, a), (b, a), (b, b), (a, b))]

    def _screen_quad(self, corners):
        pts = [self._screen(c) for c in corners]
        return None if any(q is None for q in pts) else QPolygonF(pts)

    def _ring_points(self, pivot, axis, length):
        helper = np.array([1.0, 0, 0]) if abs(axis[0]) < 0.9 else np.array([0, 1.0, 0])
        a = np.cross(axis, helper)
        a /= np.linalg.norm(a)
        b = np.cross(axis, a)
        angles = np.linspace(0, 2 * math.pi, RING_SEGMENTS + 1)
        return pivot + length * (np.outer(np.cos(angles), a) + np.outer(np.sin(angles), b))

    # --- Display ---
    def draw(self, p, target):
        if not self.tool:
            return
        pivot = target.pivot()
        center = self._screen(pivot)
        if center is None:
            return
        axes, length = self.axes(target), self._length(pivot)
        active = self._drag["handle"] if self._drag else self.hover

        if self.tool == "rotate":
            for i in range(3):
                color = HOVER_COLOR if active == ("ring", i) else AXIS_COLORS[i]
                p.setPen(QPen(color, 2.5 if active == ("ring", i) else 1.8))
                self.vp.draw_polyline(p, self._ring_points(pivot, axes[:, i], length))
            hot = active == ("view",)
            p.setPen(QPen(HOVER_COLOR if hot else VIEW_RING_COLOR, 2.5 if hot else 1.8))
            self.vp.draw_polyline(p, self._ring_points(pivot, self.vp.cam.back, length * VIEW_RING_SCALE))
            return

        for i, j in self._plane_pairs(target):
            quad = self._screen_quad(self._plane_quad(pivot, axes, length, i, j))
            if quad is None:
                continue
            k = 3 - i - j  # color of the axis perpendicular to the square (as in Houdini)
            base = HOVER_COLOR if active == ("plane", i, j) else AXIS_COLORS[k]
            p.setPen(QPen(base, 1.2))
            p.setBrush(QColor(base.red(), base.green(), base.blue(), 150 if active == ("plane", i, j) else 70))
            p.drawPolygon(quad)

        for i in self._axis_indices(target):
            end = self._screen(pivot + axes[:, i] * length)
            if end is None:
                continue
            color = HOVER_COLOR if active == ("axis", i) else AXIS_COLORS[i]
            p.setPen(QPen(color, 2.5))
            p.drawLine(center, end)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            direction = end - center
            n = max(math.hypot(direction.x(), direction.y()), 1e-6)
            d = direction / n
            if self.tool == "translate":
                side = QPointF(-d.y(), d.x())
                p.drawPolygon(QPolygonF([end + d * 12, end + side * 5, end - side * 5]))
            else:
                p.drawRect(end.x() - 5, end.y() - 5, 10, 10)

        color = HOVER_COLOR if active == ("center",) else GIZMO_CENTER
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(center.x() - 6, center.y() - 6, 12, 12)

    # --- Hits ---
    def hit(self, pos, target):
        if not self.tool:
            return None
        pivot = target.pivot()
        center = self._screen(pivot)
        if center is None:
            return None
        axes, length = self.axes(target), self._length(pivot)

        if self.tool == "rotate":
            best = None
            rings = [(("ring", i), self._ring_points(pivot, axes[:, i], length)) for i in range(3)]
            rings.append((("view",), self._ring_points(pivot, self.vp.cam.back, length * VIEW_RING_SCALE)))
            for handle, ring in rings:
                pts, ok = self.vp.project(ring)
                for k in range(RING_SEGMENTS):
                    if ok[k] and ok[k + 1]:
                        dist = _dist_to_segment(pos, QPointF(*pts[k]), QPointF(*pts[k + 1]))
                        if dist < HIT_PX and (best is None or dist < best[0]):
                            best = (dist, handle)
            return best[1] if best else None

        if (pos - center).manhattanLength() < HIT_PX + 4:
            return ("center",)
        for i, j in self._plane_pairs(target):
            quad = self._screen_quad(self._plane_quad(pivot, axes, length, i, j))
            if quad is not None and quad.containsPoint(pos, Qt.OddEvenFill):
                return ("plane", i, j)
        best = None
        for i in self._axis_indices(target):
            end = self._screen(pivot + axes[:, i] * length)
            if end is None:
                continue
            dist = _dist_to_segment(pos, center, end)
            if dist < HIT_PX and (best is None or dist < best[0]):
                best = (dist, ("axis", i))
        return best[1] if best else None

    # --- Dragging ---
    def _axis_param(self, pos, origin, axis):
        """Parameter t of the point on the axis (origin + t*axis) that is closest to the mouse ray."""
        eye, d = self.vp.ray(pos)
        w0 = origin - eye
        b = axis @ d
        denom = 1 - b * b
        if denom < 1e-4:
            return None
        return (b * (d @ w0) - (axis @ w0)) / denom

    def _plane_hit(self, pos, point, normal):
        """Intersection point of the mouse ray with the plane through point (or None if nearly parallel)."""
        eye, d = self.vp.ray(pos)
        denom = d @ normal
        if abs(denom) < 1e-6:
            return None
        return eye + ((point - eye) @ normal) / denom * d

    def begin(self, handle, pos, target):
        """Start a drag. What is remembered is the total travel since the start ("total") and how much of it is
        already applied ("applied") – so one can snap with Ctrl, even in the middle of a drag."""
        pivot = target.pivot().copy()
        axes = self.axes(target).copy()
        if hasattr(target, "begin_rigid"):
            target.in_drag = True  # in a gizmo drag only carry surfaces along rigidly (end() releases them again)
        drag = {"handle": handle, "target": target, "pivot": pivot, "axes": axes,
                "center": self._screen(pivot), "last_pos": pos}
        if handle[0] == "axis":
            t = self._axis_param(pos, pivot, axes[:, handle[1]])
            drag["t0"] = t if t is not None else 0.0
            drag["applied"] = 1.0 if self.tool == "scale" else 0.0
        elif handle[0] in ("ring", "view"):
            drag["angle"] = self._screen_angle_for(drag, pos)
            drag["total"] = drag["applied"] = 0.0
            drag["view_axis"] = self.vp.cam.back.copy()  # purple ring: view direction at start
        elif handle[0] == "plane":
            i, j = handle[1], handle[2]
            drag["normal"] = np.cross(axes[:, i], axes[:, j])
            drag["hit0"] = self._plane_hit(pos, pivot, drag["normal"])
            if self.tool == "scale":  # reference: distance along the diagonal of the square
                drag["diag"] = (axes[:, i] + axes[:, j]) / math.sqrt(2)
                drag["d0"] = (drag["hit0"] - pivot) @ drag["diag"] if drag["hit0"] is not None else 0.0
                drag["applied"] = 1.0
            else:
                drag["applied"] = np.zeros(3)
        elif handle == ("center",) and self.tool == "translate":
            drag["hit0"] = self._view_plane_hit(pos, pivot)
            drag["applied"] = np.zeros(3)
        else:  # center when scaling: uniform
            drag["total"] = drag["applied"] = 1.0
        self._drag = drag

    def _screen_angle_for(self, drag, pos):
        c = drag["center"]
        return math.atan2(-(pos.y() - c.y()), pos.x() - c.x())

    def _view_plane_hit(self, pos, pivot):
        eye, d = self.vp.ray(pos)
        n = self.vp.cam.back
        denom = d @ n
        if abs(denom) < 1e-6:
            return None
        return eye + ((pivot - eye) @ n) / denom * d

    def update(self, pos, snap=False):
        """snap (Ctrl held): round the total travel to the snap steps (workspace: snap_move,
        snap_angle in degrees, snap_scale in percent) – relative to the start. As a number: fraction of the
        step (Ctrl+Shift = 0.1, fine steps); False/0: free."""
        drag = self._drag
        target, handle, pivot, axes = drag["target"], drag["handle"], drag["pivot"], drag["axes"]
        ws = self.vp.ws

        if handle[0] == "plane":
            self._update_plane(drag, pos, snap)
        elif self.tool == "translate" and handle[0] == "axis":
            axis = axes[:, handle[1]]
            t = self._axis_param(pos, pivot, axis)
            if self.point_snap is not None:  # V: grabbed point onto the target point (along the axis)
                t = drag["t0"] + (self.point_snap[1] - self.point_snap[0]) @ axis
            if t is not None:
                total = t - drag["t0"]
                if snap and self.point_snap is None:
                    total = _snap(total, ws.snap_move * snap)
                target.translate(axis * (total - drag["applied"]))
                drag["applied"] = total
        elif self.tool == "translate":
            hit = self._view_plane_hit(pos, pivot)
            if self.point_snap is not None and drag["hit0"] is not None:  # V: free onto the target point
                hit = drag["hit0"] + self.point_snap[1] - self.point_snap[0]
                snap = False
            if hit is not None and drag["hit0"] is not None:
                total = hit - drag["hit0"]
                if snap:  # in steps along the gizmo axes
                    total = axes @ _snap(axes.T @ total, ws.snap_move * snap)
                target.translate(total - drag["applied"])
                drag["applied"] = total
        elif self.tool == "rotate":
            angle = self._screen_angle_for(drag, pos)
            delta = (angle - drag["angle"] + math.pi) % (2 * math.pi) - math.pi
            axis = drag["view_axis"] if handle[0] == "view" else axes[:, handle[1]]
            sign = 1.0 if axis @ self.vp.cam.back >= 0 else -1.0
            drag["angle"] = angle
            drag["total"] += delta * sign
            total = _snap(drag["total"], math.radians(ws.snap_angle * snap)) if snap else drag["total"]
            target.rotate(rot_axis(axis, total - drag["applied"]), pivot)  # pivot from the drag start, otherwise it travels along
            drag["applied"] = total
        elif self.tool == "scale" and handle[0] == "axis":
            i = handle[1]
            t = self._axis_param(pos, pivot, axes[:, i])
            if t is not None and abs(drag["t0"]) <= 1e-6:
                drag["t0"] = t  # attached at the pivot: reference only from here
            elif t is not None:
                f = t / drag["t0"]
                if snap:
                    f = _snap_factor(f, ws.snap_scale * snap / 100)
                if abs(f) > 1e-3:  # negative = mirror; skip exactly zero (flattening)
                    factors = np.ones(3)
                    factors[i] = f / drag["applied"]
                    target.scale(factors, axes, pivot)
                    drag["applied"] = f
        elif self.tool == "scale":
            d = pos - drag["last_pos"]
            drag["total"] *= math.exp((d.x() - d.y()) * 0.01)
            f = _snap_factor(drag["total"], ws.snap_scale * snap / 100) if snap else drag["total"]
            target.scale(np.full(3, f / drag["applied"]), axes, pivot)
            drag["applied"] = f
        drag["last_pos"] = pos

    def _update_plane(self, drag, pos, snap):
        """Two-axis square: move in the plane of the two axes or scale both equally."""
        hit = self._plane_hit(pos, drag["pivot"], drag["normal"])
        if hit is None or drag["hit0"] is None:
            return
        ws, axes = self.vp.ws, drag["axes"]
        i, j = drag["handle"][1], drag["handle"][2]
        if self.tool == "translate":
            total = hit - drag["hit0"]
            if self.point_snap is not None:  # V: in the plane of the two axes onto the target point
                total = self.point_snap[1] - self.point_snap[0]
                snap = False
            c = np.array([total @ axes[:, i], total @ axes[:, j]])
            if snap:
                c = _snap(c, ws.snap_move * snap)
            vec = axes[:, i] * c[0] + axes[:, j] * c[1]
            drag["target"].translate(vec - drag["applied"])
            drag["applied"] = vec
        elif abs(drag["d0"]) > 1e-9:
            f = ((hit - drag["pivot"]) @ drag["diag"]) / drag["d0"]
            if snap:
                f = _snap_factor(f, ws.snap_scale * snap / 100)
            if abs(f) > 1e-3:  # negative = mirror
                factors = np.ones(3)
                factors[i] = factors[j] = f / drag["applied"]
                drag["target"].scale(factors, axes, drag["pivot"])
                drag["applied"] = f

    def end(self):
        target = self._drag["target"] if self._drag else None
        if target is not None and hasattr(target, "end_rigid"):
            target.in_drag = False
            target.end_rigid()  # rigidly carried surfaces follow their lines again
        self._drag = None

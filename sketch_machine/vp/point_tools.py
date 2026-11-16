"""Point tools in edit mode: hardness (K), smoothing (J) and sliding points along their line (hold S)."""
from .common import *  # noqa: F401,F403
from ..i18n import tr

VALUE_PX = 200.0  # this many pixels of mouse travel = the whole range 0 … 1 (hardness, smoothing)
VALUE_WHEEL = 0.05  # per mouse wheel notch


class PointToolsMixin:
    # --- Value tool (K hardness, J smoothing): a slider at the cursor ---
    # Mouse left/right (with or without button pressed) sets the value, mouse wheel in small steps, 0–9 = 0 … 0.9,
    # Ctrl snaps to tenths. Releasing the mouse button or click or Enter confirms, right click/Esc cancels.
    def _start_value_tool(self, kind, label, start, apply, done):
        self.scene.checkpoint()
        pos = self._last_pos if self._last_pos is not None else QPointF(self.width() / 2, self.height() / 2)
        self._val = {"kind": kind, "label": label, "start": float(start), "x": pos.x(), "value": float(start),
                     "apply": apply, "done": done, "pressed": False}
        self._mode = "value"
        self._value_set(start)

    def _value_set(self, value):
        v = self._val
        value = min(max(float(value), 0.0), 1.0)
        if self._ctrl:
            value = round(value * 10) / 10
        v["value"] = value
        v["apply"](value)
        self.status_changed.emit(tr("{0} {1:.2f} – Maus links/rechts, Mausrad, 0–9 · Klick/Enter bestätigt, Rechtsklick/Esc bricht ab").format(v['label'], value))
        self._changed()

    def _value_move(self, pos):
        v = self._val
        self._value_set(v["start"] + (pos.x() - v["x"]) / VALUE_PX)

    def _value_nudge(self, delta):
        """Mouse wheel/digit: shift the value without the next mouse move making it jump back."""
        v = self._val
        target = min(max(v["value"] + delta, 0.0), 1.0)
        v["start"] += target - v["value"]
        self._value_set(target)

    def finish_value(self, ok):
        v, self._val = self._val, None
        self._mode = None
        if v is None:
            return
        if not ok:
            self.scene.undo()
            self.scene._redo.clear()
            self.notify(tr("{0}: abgebrochen").format(v['label']))
        else:
            v["done"](v["value"])
        self._changed()

    # --- K / J as tools (on/off): click selects as usual, dragging sets the value of the selection ---
    VALUE_TOOLS = {"hardness": (tr("Härte"), ("point", "edge")), "smooth": (tr("Glätten"), ("edge",))}

    def set_knot_mode(self, mode):
        """Drag points: auto (as the line bends at the point), soft (always soft) or hard (always hard)."""
        self.ws.knot_mode = mode
        self.ws.target_cache = (None, None)  # rebuild transform target
        self.toggles_changed.emit()
        self.notify({"auto": tr("Punkte ziehen: automatisch – auf Rundungen weich, an Ecken hart"),
                     "soft": tr("Punkte ziehen: immer weich"), "hard": tr("Punkte ziehen: immer hart")}[mode])

    def set_value_tool(self, kind):
        """K (hardness) or J (smoothing) on/off. The same key again, Esc or Tab turns it off."""
        if kind is not None and self.ws.value_tool == kind:
            kind = None
        if kind is not None:
            if not self.select_mode:
                self.set_select_mode(True)
            if self.ws.component not in self.VALUE_TOOLS[kind][1]:
                self.set_component("edge")
        self.ws.value_tool = kind
        self.ws.target_cache = (None, None)
        self.toggles_changed.emit()
        if kind is None:
            self.notify(tr("Werkzeug aus"))
        else:
            what = tr("Punkte oder Kanten") if kind == "hardness" else tr("Kanten")
            self.notify(tr("{0}: {1} anklicken, dann ziehen (links/rechts) oder Mausrad – {2}/Esc: aus").format(self.VALUE_TOOLS[kind][0], what, 'K' if kind == 'hardness' else 'J'))
        self._changed()

    def _leave_value_tool(self):
        """Hardness/smoothing off, without hint (another tool was chosen)."""
        if self.ws.value_tool:
            self.ws.value_tool = None
            self.ws.target_cache = (None, None)
            self.toggles_changed.emit()

    def _value_tool_start(self, pos):
        """Dragging with the tool begins: the value of the selection follows the mouse (from the place where it started)."""
        self._mode = None
        self._last_pos = QPointF(pos)
        (self.start_hardness if self.ws.value_tool == "hardness" else self.start_smooth)()
        if self._val is not None:
            self._val["pressed"] = True

    def _value_tool_wheel(self, steps):
        """Mouse wheel with the tool: value of the selection in small steps (notch by notch one undo step)."""
        (self.start_hardness if self.ws.value_tool == "hardness" else self.start_smooth)()
        if self._val is not None:
            self._value_nudge(steps * VALUE_WHEEL)
            self.finish_value(True)

    def _value_key(self, e):
        """Keys during the value tool; True if consumed."""
        k = e.key()
        if k == Qt.Key_Escape:
            self.finish_value(False)
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.finish_value(True)
        elif Qt.Key_0 <= k <= Qt.Key_9:
            self._value_nudge((k - Qt.Key_0) / 10 - self._val["value"])
        else:
            return False
        return True

    def _draw_value_hud(self, p):
        """Small slider next to the cursor: name, number, bar."""
        v = self._val
        if self._last_pos is None or (v is None and not (self.ws.value_tool and self.select_mode)):
            return
        if v is None:  # tool on, not dragging right now: only name and hint
            v = {"label": self.VALUE_TOOLS[self.ws.value_tool][0], "value": None}
        w, h = 140, 38
        x = min(self._last_pos.x() + 18, self.width() - w - 6)
        y = min(self._last_pos.y() + 14, self.height() - h - 6)
        # first into an image (raster painter, matching the screen scaling), then lay it into the image: the OpenGL painter
        # draws text and semi-transparency unclean on scaled screens (looked like a graphics glitch)
        dpr = max(self.devicePixelRatioF(), 1.0)
        img = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing)
        q.setRenderHint(QPainter.TextAntialiasing)
        q.setPen(QPen(theme.GRAPHITE, 1))
        q.setBrush(theme.PAPER)
        q.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 5, 5)
        font = QFont(q.font())
        font.setPointSizeF(9)
        # text as a path: grayscale smoothing instead of ClearType (that gives color fringes on a transparent image)
        metrics = QFontMetricsF(font)
        value = f"{v['value']:.2f}" if v["value"] is not None else ""
        base = 4 + (16 + metrics.ascent() - metrics.descent()) / 2
        path = QPainterPath()
        path.addText(QPointF(9, base), font, v["label"])
        path.addText(QPointF(w - 9 - metrics.horizontalAdvance(value), base), font, value)
        q.setPen(Qt.NoPen)
        q.setBrush(theme.GRAPHITE)
        q.drawPath(path)
        if v["value"] is None:
            hint = QPainterPath()
            small = QFont(font)
            small.setPointSizeF(8)
            hint.addText(QPointF(9, 33), small, tr("← ziehen →"))
            q.setBrush(theme.GRAPHITE)
            q.drawPath(hint)
            q.end()
            p.drawImage(QPointF(round(x), round(y)), img)
            return
        bar = QRectF(9, 24, w - 18, 7)
        q.setPen(Qt.NoPen)
        q.setBrush(theme.TERRACOTTA)
        q.drawRect(QRectF(bar.x(), bar.y(), bar.width() * v["value"], bar.height()))
        q.setPen(QPen(theme.GRAPHITE, 1))
        q.setBrush(Qt.NoBrush)
        q.drawRect(bar)
        q.end()
        p.drawImage(QPointF(round(x), round(y)), img)

    # --- Hardness (K): a shaping tool. Hardness is the angularity of the lines (components.sharpness), nothing is stored:
    # K shapes the lines at the point until they bend as much as set. Point mode: all lines through the point;
    # edge mode: the lines that cross the edge at its points (the edge itself stays) – that is how the edge becomes hard.
    def _hardness_targets(self):
        """{point ID: ids of the lines K does not shape there}: selected points (all lines), points of selected edges
        or lines (without the edge itself)."""
        network.sync(self.scene)
        out = {}

        def add(c, k, exclude):
            pid = network.pid_of(c, k)
            if pid is not None:
                cur = out.get(pid)
                out[pid] = set() if (cur is not None and not cur) or not exclude else (cur or set()) | exclude
        for r, c in self._valid_points():
            add(c, r[3], set())
        for r, c in self._valid_segs():
            for j in (r[3], r[4]):
                add(c, j, {c.id})
        for r in self.edge_selection:
            c = edges.ref_to_curve(self.scene, r)
            if c is not None and not c.paint:
                for k in components.knots(c):
                    add(c, k, {c.id})
        return out

    def _hardness_plan(self):
        """For each continuous line at the target points a pair of edge pieces and how K shapes it -> (pairs, source lines).
        At the point the tangent is blended between soft (direction from neighbor to neighbor: the rounding runs through) and hard
        (each side straight toward the point) – one Hermite offset per side; the point and its
        neighboring points stay put."""
        refs = network.refs_by_pid(self.scene)
        pairs, origs = [], {}
        for pid, exclude in self._hardness_targets().items():
            for pair in components.pairs_at(refs.get(pid, []), exclude):
                far = [c.points[lo] if p_hi else c.points[hi] for c, lo, hi, p_hi in pair]
                through = far[1] - far[0]
                n = float(np.linalg.norm(through))
                if n < 1e-12:
                    continue
                through /= n
                sides, v0 = [], []
                for i, (c, lo, hi, p_hi) in enumerate(pair):
                    p = c.points[hi] if p_hi else c.points[lo]
                    chord = p - far[i] if p_hi else far[i] - p
                    soft = through if (i == 0) == p_hi else -through
                    delta = chord - soft * float(np.linalg.norm(chord))
                    t = np.linspace(0.0, 1.0, hi - lo + 1)[:, None]
                    basis = t ** 3 - t ** 2 if p_hi else t ** 3 - 2 * t ** 2 + t
                    sides.append((c, lo, hi, p_hi, basis * delta))
                    origs.setdefault(id(c), (c, c.points.copy()))
                    # how far the tangent is already blended from soft to hard (limits of the slider)
                    sp = components.side_points((c, lo, hi, p_hi))  # direction at the point, by point index like the
                    cur = 2 * (sp[1] - sp[0]) - 0.5 * (sp[2] - sp[0]) if len(sp) > 2 else sp[-1] - sp[0]  # deformation
                    cur = cur / n_c if (n_c := float(np.linalg.norm(cur))) > 1e-12 else None
                    away_soft = -through if i == 0 else through
                    away_hard = (far[i] - p) / max(float(np.linalg.norm(far[i] - p)), 1e-12)
                    # tangent(v) ~ soft + v (hard - soft): v such that it points in the current direction
                    u = away_hard - away_soft
                    du = np.cross(cur, u) if cur is not None else np.zeros(3)
                    nn = float(du @ du)
                    v0.append(float(np.clip(-(np.cross(cur, away_soft) @ du) / nn, 0, 1)) if nn > 1e-12 else 0.0)
                pairs.append({"sides": sides, "v0": float(np.mean(v0))})
        return pairs, origs

    @staticmethod
    def _pair_kink(pair, w):
        polys = []
        for c, lo, hi, p_hi, disp in pair["sides"]:
            seg = pair["orig"][id(c)][lo:hi + 1] + w * disp
            polys.append(seg[::-1] if p_hi else seg)
        return components.kink_deg(polys[0], polys[1])

    def _pair_offset(self, pair, value):
        """Offset (multiple of the Hermite offset) with which the line bends at the point as sharply as value."""
        lo, hi = -pair["v0"], 1.0 - pair["v0"]
        if value <= 0.0:
            return lo
        sharp = lambda w: components.sharpness(self._pair_kink(pair, w))
        if value >= sharp(hi):
            return hi
        a, b = lo, hi
        for _ in range(24):
            mid = (a + b) / 2
            a, b = (mid, b) if sharp(mid) < value else (a, mid)
        return (a + b) / 2

    def _apply_hardness(self, pairs, origs, value):
        total = {key: np.zeros_like(orig) for key, (_, orig) in origs.items()}
        for pair in pairs:
            pair["orig"] = {key: orig for key, (_, orig) in origs.items()}
            w = self._pair_offset(pair, value)
            for c, lo, hi, p_hi, disp in pair["sides"]:
                total[id(c)][lo:hi + 1] += w * disp
        for key, (c, orig) in origs.items():
            c.points = orig + total[key]

    def _hardness_ready(self):
        if not self.select_mode or self.ws.component not in ("point", "edge"):
            self.notify(tr("Härte: im Edit-Modus Punkte (1) oder Kanten (2) wählen, dann K"))
            return None
        if not self._hardness_targets():
            self.notify(tr("Härte: erst Punkte (1) oder Kanten (2) wählen, dann K"))
            return None
        pairs, origs = self._hardness_plan()
        if not pairs:
            self.notify(tr("Härte: hier läuft keine Linie durch (Linienende, Ecke mehrerer Linien) – K formt durchlaufende Linien"))
            return None
        return pairs, origs

    def start_hardness(self):
        """K: set hardness (angularity) of the selected points/edges (value tool) – shapes the lines at the point."""
        if self._mode is not None:
            return self.notify(tr("Härte: im Edit-Modus Punkte (1) oder Kanten (2) wählen, dann K"))
        plan = self._hardness_ready()
        if plan is None:
            return
        pairs, origs = plan
        start = float(np.mean([components.sharpness(components.pair_kink(
            tuple((c, lo, hi, p_hi) for c, lo, hi, p_hi, _ in pair["sides"]))) for pair in pairs]))
        self._start_value_tool("hardness", tr("Härte"), start, lambda value: self._apply_hardness(pairs, origs, value),
                               lambda value: self.notify(tr("Härte {0:.2f} an {1} Stelle(n)").format(value, len(pairs))))

    def set_hardness(self, value):
        """Shift+K: fully hard, Alt+K: fully soft."""
        plan = self._hardness_ready()
        if plan is None:
            return
        self.scene.checkpoint()
        self._apply_hardness(*plan, value)
        self.notify(tr("{0} Stelle(n) {1}").format(len(plan[0]), 'hart' if value >= 0.5 else 'weich'))
        self._changed()

    # --- Smoothing (J): selected edges; fully smoothed every edge is a straight line between its points ---
    def _smooth_targets(self):
        """[(line, a, b)] of the edges to smooth: selected partial edges, whole selected lines piece by piece between their
        points (the points stay where they are)."""
        out = [(c, r[3], r[4]) for r, c in self._valid_segs()]
        for r in self.edge_selection:
            c = edges.ref_to_curve(self.scene, r)
            if c is not None and not c.paint:
                out += [(c, a, b) for a, b in components.segments(c)]
        return list({(id(c), a, b): (c, a, b) for c, a, b in out}.values())

    def start_smooth(self):
        """J: smooth selected edges (value tool): first small wobbles disappear, fully smoothed every edge is a
        straight line between its two points. The points (and what hangs on them) stay put."""
        if not self.select_mode or self.ws.component != "edge" or self._mode is not None:
            return self.notify(tr("Glätten: im Edit-Modus Kanten (2) wählen, dann J"))
        targets = self._smooth_targets()
        if not targets:
            return self.notify(tr("Glätten: erst Kanten (2) wählen, dann J"))
        originals = {id(c): (c, c.points.copy()) for c, _, _ in targets}

        def apply(value):
            for c, pts in originals.values():
                new = pts.copy()
                for t, a, b in targets:
                    if t is c:
                        new[a:b + 1] = components.smooth_points(pts[a:b + 1], value)
                c.points = new
        self._start_value_tool("smooth", tr("Glätten"), 0.0, apply,
                               lambda value: self.notify(tr("{0} Kante(n) geglättet ({1:.0%})").format(len(targets), value)))

    # --- Sliding (S held, point mode): points move along their line, the line keeps its shape ---
    def _begin_slide(self, pos):
        network.sync(self.scene)
        refs = network.refs_by_pid(self.scene)
        items, seen, skipped = [], set(), 0
        for r, c in self._valid_points():
            pid = network.pid_of(c, r[3])
            if pid in seen:
                continue
            seen.add(pid)
            linked = refs.get(pid, [(c, r[3])]) if pid is not None else [(c, r[3])]
            # slide along a line on which the point lies in the middle (a line end has only one direction)
            along = next(((o, j) for o, j in linked if 0 < j < len(o.points) - 1), None)
            if along is None:
                skipped += 1
                continue
            o, j = along
            ks = components.knots(o)
            i = ks.index(j)
            others = [(q, m) for q, m in linked if q is not o]
            items.append({"curve": o, "k": j, "a": ks[i - 1], "b": ks[i + 1], "pts": o.points.copy(),
                          "wid": o.widths.copy(), "knots": o.knots, "pids": dict(o.pids or {}),
                          "others": [(q, m, q.points.copy()) for q, m in others],
                          "group": components.ComponentGroup(self.scene, [(q, m) for q, m in others], [], weld=False)
                          if others else None})
        if not items:
            return self.notify(tr("Gleiten: nur Punkte mitten auf einer Linie gleiten (Linienenden nicht)"))
        self.scene.checkpoint()
        self._slide = {"start": QPointF(pos), "items": items, "sel": list(self.point_selection)}
        self._mode = "slide"
        if skipped:
            self.notify(tr("Gleiten: {0} Linienende(n) bleiben stehen").format(skipped))

    def _slide_update(self, pos):
        s = self._slide
        d = np.array([pos.x() - s["start"].x(), pos.y() - s["start"].y()])
        for it in s["items"]:
            pts, a, b, k = it["pts"], it["a"], it["b"], it["k"]
            seg = pts[a:b + 1]
            screen, ok = self.project(seg)
            if not ok.all():
                continue
            target = screen[k - a] + d
            p0, p1 = screen[:-1], screen[1:]
            v = p1 - p0
            t = np.clip(np.einsum("ij,ij->i", target - p0, v) / np.maximum(np.einsum("ij,ij->i", v, v), 1e-12), 0, 1)
            dist = np.linalg.norm(p0 + v * t[:, None] - target, axis=1)
            i = int(np.argmin(dist))
            self._slide_place(it, a + i, float(t[i]))
        # selected points point to their new node index (otherwise they would drop out of the selection)
        moved = {(it["curve"].id, it["k"]): it["at"] for it in s["items"] if "at" in it}
        self.point_selection = [(r[0], r[1], r[2], moved.get((r[2], r[3]), r[3])) for r in s["sel"]]
        self._changed()

    def _slide_place(self, it, i, t):
        """Place node it["k"] at position t on the piece i -> i+1 of the original line."""
        c, pts, wid, k = it["curve"], it["pts"], it["wid"], it["k"]
        n0, inner0 = it["knots"]
        if t > 1 - 1e-6 and i + 1 < len(pts) - 1:
            i, t = i + 1, 0.0
        if t < 1e-6:  # exactly on an existing line point
            new_pts, new_wid, at, shift = pts.copy(), wid.copy(), i, lambda j: j
        else:
            q = pts[i] + t * (pts[i + 1] - pts[i])
            new_pts = np.vstack([pts[:i + 1], q, pts[i + 1:]])
            new_wid = np.concatenate([wid[:i + 1], [wid[i] + t * (wid[i + 1] - wid[i])], wid[i + 1:]])
            at, shift = i + 1, (lambda j: j + 1 if j > i else j)
        inner = sorted({shift(j) for j in inner0 if j != k} | {at})
        it["at"] = at
        c.points, c.widths = new_pts, new_wid
        c.knots = (len(new_pts), tuple(j for j in inner if 0 < j < len(new_pts) - 1))
        if it["pids"]:
            c.pids = {(at if j == k else shift(j)): p for j, p in it["pids"].items()}
        for q, m, orig in it["others"]:  # connected lines (e.g. a T-junction) are dragged softly along
            q.points = orig.copy()
        if it["group"] is not None:
            it["group"].translate(new_pts[at] - pts[k])

    def finish_slide(self, ok):
        s, self._slide = self._slide, None
        self._mode = None
        if s is None:
            return
        if not ok:
            self.scene.undo()
            self.scene._redo.clear()
        self._changed()

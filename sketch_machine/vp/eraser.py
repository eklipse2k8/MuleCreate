"""Eraser."""
from .common import *  # noqa: F401,F403


_NORMAL_TREES = {}  # id(net points) -> (points, KD tree of the triangle centers, normals of the usable triangles)


def _normal_tree(mesh):
    """(KD tree, normals) of the triangles with direction of a net – remembered as long as the net stays the same."""
    from scipy.spatial import cKDTree
    hit = _NORMAL_TREES.get(id(mesh[0]))
    if hit is not None and hit[0] is mesh[0]:
        return hit[1], hit[2]
    v, t = np.asarray(mesh[0], float), np.asarray(mesh[1])
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    n = np.cross(b - a, c - a)
    size = np.linalg.norm(n, axis=1)
    ok = np.flatnonzero(size > 1e-9 * max(float(size.max()), 1e-18)) if len(size) else np.zeros(0, int)
    normals = n[ok] / size[ok, None]
    tree = cKDTree((a[ok] + b[ok] + c[ok]) / 3) if len(ok) else None
    if len(_NORMAL_TREES) > 4096:
        for k in list(_NORMAL_TREES)[:2048]:
            del _NORMAL_TREES[k]
    _NORMAL_TREES[id(mesh[0])] = (mesh[0], tree, normals)
    return tree, normals


class EraserMixin:
    @staticmethod
    def _surface_normals_at(surface, points, fallback):
        """Normal of the drawing surface at each point (triangle with the nearest centroid) – all points in one
        go via a KD tree of the triangle centers, remembered per surface shape (before: point by point in Python:
        painting that follows a surface was slow when dragging – harbor test 09.11.)."""
        mesh = surface.fill_mesh()
        if mesh is None or not len(mesh[1]):
            return fallback
        pts = np.asarray(points, float).reshape(-1, 3)
        if not len(pts):
            return fallback
        tree, normals = _normal_tree(mesh)
        if tree is None:
            return fallback
        _d, idx = tree.query(pts)
        return normals[idx].astype(fallback.dtype if hasattr(fallback, "dtype") else float)

    def _erase_reach(self, pos, r, also=()):
        """The eraser does not erase through the whole space: only within a sphere around the frontmost hit under
        the eraser circle (line, surface or mesh), radius = the circle at that depth.
        Each step searches for the hit anew (the eraser stays on what you see); between two
        steps the connection of both spheres applies. No hit: the depth of the last one stays valid.
        also: points the eraser circle currently hits (lines and painting, with their stroke width) – they too
        can be the frontmost hit. Without them painting never counted: if it lay on a plane above the terrain
        (planes do not occlude), the depth of the terrain behind it applied, and the eraser could not reach it
        (harbor test 10.11.).
        Returns a check function (3D points -> allowed) or None as long as there never was a hit."""
        eye, view = self.cam.eye, -self.cam.back
        best = None

        def consider(point):
            nonlocal best
            depth = (point - eye) @ view
            if depth > NEAR and (best is None or depth < best[0]):
                best = (depth, np.asarray(point, float))

        _, hit, _ = self._mesh_under(pos)  # drawing surfaces and meshes (planes do not occlude)
        if hit is not None:
            consider(hit)
        for _, curve, i, t in self._near_segments(pos, None, r, cache="curves"):
            consider(self._segment_point(pos, curve.points[i], curve.points[i + 1], t))
        for point in also:
            consider(point)
        anchor = best[1] if best is not None else self._erase_last
        if anchor is None:
            return None
        prev = self._erase_last if self._erase_last is not None else anchor
        self._erase_last = anchor
        radius = r * float(self._world_per_px(max((anchor - eye) @ view, NEAR)))

        def inside(points):
            ab = anchor - prev
            t = np.clip(((points - prev) @ ab) / max(ab @ ab, 1e-18), 0, 1)
            return np.linalg.norm(prev + t[:, None] * ab - points, axis=1) <= radius
        return inside

    @staticmethod
    def _erase_filter_for(mods):
        """Eraser: Ctrl = lines only (no painting), otherwise both; Ctrl+Shift: delete whole lines."""
        if mods & Qt.ControlModifier and not mods & Qt.ShiftModifier:
            return "lines"
        return None

    @property
    def erase_mode(self):
        """Eraser: tool of drawing mode (D on; A back to the pen)."""
        return not self.select_mode and not self.notes_mode and self.ws.draw_tool == "eraser"

    @erase_mode.setter
    def erase_mode(self, on):
        if on and self.ws.draw_tool != "eraser":
            self.ws.last_draw_tool = self.ws.draw_tool
            self.ws.draw_tool = "eraser"
        elif not on and self.ws.draw_tool == "eraser":
            self.ws.draw_tool = self.ws.last_draw_tool

    def _erase_near(self, lines, a, b, r):
        """Preselection for the eraser: only lines whose bounding sphere (including stroke width) can reach the path a-b
        of the eraser on screen – all checked at once. Before, on every mouse move every line of the
        scene was projected individually (harbor 10.11.: 3,800 lines, 0.4 s per move). When in doubt a line stays in."""
        if len(lines) < 32:
            return lines
        sc = self.scene
        widths = self.__dict__.setdefault("_erase_wmax", {})
        lo, hi, wmax = np.empty((len(lines), 3)), np.empty((len(lines), 3)), np.empty(len(lines))
        for k, (_, c) in enumerate(lines):
            lo[k], hi[k] = sc.curve_bounds(c)
            hit = widths.get(id(c))
            if hit is None or hit[0] is not c.widths:
                if len(widths) > 20000:
                    widths.clear()
                hit = widths[id(c)] = (c.widths, float(np.max(c.widths)) if len(c.widths) else 0.0, c)
            wmax[k] = hit[1]
        center = (lo + hi) / 2
        radius = np.linalg.norm(hi - lo, axis=1) / 2 + wmax / 2
        screen, ok = self.project(center)
        depth = (center - self.cam.eye) @ -self.cam.back
        front = depth - radius  # the nearest point of the sphere: there it is largest on screen
        sure = ok & (front > NEAR) & np.all(np.isfinite(screen), axis=1)
        px = np.where(sure, radius / np.maximum(self._world_per_px(np.maximum(front, NEAR)), 1e-30), np.inf)
        dist = _capsule_dist(np.nan_to_num(screen, nan=0.0), a, b)
        keep = ~sure | (dist <= r + px + 2.0)
        return [lines[k] for k in np.flatnonzero(keep)]

    def _erase_samples(self, curve, a, b, r):
        """Check points of a line for the eraser path a-b: line pieces within reach are
        subdivided to pixel precision. Returns (points, widths, original, hit, screen) or None."""
        pts, wid = curve.points, curve.widths
        screen, ok = self.project(pts)
        if not ok.any():
            return None
        screen = np.nan_to_num(screen, nan=1e9)
        depth = (pts - self.cam.eye) @ -self.cam.back
        reach = r + wid / self._world_per_px(depth) / 2  # stroke width counts too
        d = _capsule_dist(screen, a, b)
        seg_len = np.linalg.norm(np.diff(screen, axis=0), axis=1)
        near = (np.minimum(d[:-1], d[1:]) - seg_len < np.maximum(reach[:-1], reach[1:])) & ok[:-1] & ok[1:]
        if not near.any():
            return None
        P, W, O = [], [], []
        for i in range(len(pts) - 1):
            n = int(min(max(math.ceil(seg_len[i] / ERASE_SAMPLE_PX), 1), ERASE_MAX_SAMPLES)) if near[i] else 1
            t = np.arange(n) / n
            P.append(pts[i] + t[:, None] * (pts[i + 1] - pts[i]))
            W.append(wid[i] + t * (wid[i + 1] - wid[i]))
            O.append(t == 0)
        P, W, O = np.vstack(P + [pts[-1:]]), np.concatenate(W + [wid[-1:]]), np.concatenate(O + [[True]])
        s, sok = self.project(P)
        s = np.nan_to_num(s, nan=1e9)
        sdepth = (P - self.cam.eye) @ -self.cam.back
        hit = sok & (_capsule_dist(s, a, b) < r + W / self._world_per_px(sdepth) / 2)
        return (P, W, O, hit, s) if hit.any() else None

    def _erase_occlusion(self, candidates):
        """Release hit points behind meshes/surfaces again (only what is visible gets erased)."""
        idx = [(k, j) for k, c in enumerate(candidates) for j in np.flatnonzero(c[5])]
        positions = [QPointF(*candidates[k][6][j]) for k, j in idx]
        for (k, j), pos, (mesh, _, m_dist) in zip(idx, positions, self._mesh_samples(positions)):
            if mesh is None:
                continue
            origin, d = self.ray(pos)
            point, width = candidates[k][2][j], candidates[k][3][j]
            if m_dist < (point - origin) @ d - (OCCLUDE_TOL * self.cam.dist + width):
                candidates[k][5][j] = False

    @staticmethod
    def _erase_runs(P, W, O, hit):
        """What remains of a line: [(points, widths)] of the pieces not hit.
        The original points are kept plus the new ends at the cut points."""
        runs, start = [], None
        for i in range(len(P) + 1):
            if i < len(P) and not hit[i]:
                if start is None:
                    start = i
            elif start is not None:
                keep = [j for j in range(start, i) if O[j] or j in (start, i - 1)]
                if len(keep) >= 2 and np.linalg.norm(np.diff(P[keep], axis=0), axis=1).sum() > 1e-9:
                    runs.append((P[keep].copy(), W[keep].copy()))
                start = None
        return runs

    def _erase(self, p0, p1):
        """Drag the eraser from p0 to p1 (screen): cut the hit lines of the stroke objects
        (Shift when starting: delete whole). Drawing surfaces stay
        untouched; lines behind meshes/surfaces only in X-ray mode."""
        a, b = np.array([p0.x(), p0.y()]), np.array([p1.x(), p1.y()])
        r = self.eraser_px / 2
        p = self._current_pressure()  # tablet: the pressure scales the eraser circle like the pen width
        if p is not None:
            r *= float(self._pressure_factor(p, "eraser"))
        candidates = []  # (stroke, curve, points, widths, original, hit, screen)
        lines = [(stroke, curve) for stroke, curve in self._shown_lines(include_paint=True)  # hidden ones determined once
                 if (curve.frame is not None) == bool(self.ws.timing_mode)  # timing erases only flipbook, otherwise never
                 and not (curve.paint and self._erase_filter == "lines")]  # Ctrl: lines only, painting stays
        for stroke, curve in self._erase_near(lines, a, b, r):
            samples = self._erase_samples(curve, a, b, r)
            if samples is not None:
                candidates.append((stroke, curve, *samples))
        if candidates and not self.xray:
            self._erase_occlusion(candidates)
        under = [c[2][c[5]] for c in candidates if c[5].any()]  # what the circle visibly hits
        limit = None if self._penetrate else self._erase_reach(p1, r, np.vstack(under) if under else ())
        if limit is not None:  # only what lies in the sphere around the frontmost hit
            for c in candidates:
                c[5][:] = c[5] & limit(c[2])
        changed = [(c[0], c[1], [] if self._erase_whole else self._erase_runs(*c[2:6]))
                   for c in candidates if c[5].any()]
        if not changed:
            return
        if not self._erase_checkpointed:  # one undo step per erase drag
            self.scene.checkpoint()
            self._erase_checkpointed = True
        if self.ws.timing_mode:  # timing: erasing happens in the drawing of this frame (if missing: copy of the current one)
            changed = self._timing_erase_targets(changed)
        for stroke, curve, runs in changed:
            k = next(i for i, c in enumerate(stroke.curves) if c is curve)
            stroke.curves[k:k + 1] = [inherit(Curve(p, curve.plane_id, w, curve.generated), curve) for p, w in runs]
        if all(curve.paint for _, curve, _ in changed) and not self.ws.timing_mode:
            # only painting is erased: no surface changes because of it – the reconciliation of all surfaces (and the binding of the
            # remaining pieces) waits until release, instead of running on every mouse move
            self.ws.sync_hold = self.scene
        else:
            self.ws.sync_hold = None
        if self.ws.timing_mode:  # shots: erased empty stays an (empty) drawing – otherwise the previous one would apply again
            t = int(self.scene.timing.frame)
            for pid in {c.plane_id for _, c, _ in changed}:
                plane = self.scene.plane_by_id(pid)
                if plane is not None and plane.flipbook and not timing_mod.key_curves(self.scene, pid, t):
                    timing_mod.add_blank_key(plane, t)
            self.ws.flip_cache = None

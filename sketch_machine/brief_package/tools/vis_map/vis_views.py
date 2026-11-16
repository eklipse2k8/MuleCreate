# vis_views.py – component views (rule 7): cameras made from the bounding box of one component, shared by
# vis_export.py (hython) and vis_blender.py (Blender). Pure numpy, Y up, metres.
# Config key "component" (README.md):
#   {"name": "train", "rank": 1, "parts": "<regex on part names, optional>",
#    "views": [{"name": "side", "az": 90, "el": 8, "why": "..."}, ...],     rank 1: 2-3 views, rank 2: 1 view
#    "front": [1, 0, 0], "fill": 0.6, "hfov": 40, "random": {"n": 2, "el": [0, 35], "seed": 1}}
# az: degrees around +Y from the component's front (default +X), counter-clockwise seen from above; el: degrees above
# the horizon. The distance follows the rank: the component (bounding-sphere diameter) fills `fill` of the picture
# width (rank 1: 0.6, rank 2: 0.3). Readable size = threshold px x diameter / (fill x picture width).
# Views are class "component" (count like hero cameras for this component only: A); random views at the same
# distance are class "component_random" (count like the cloud: B), are measured, never shown.
import math, zlib
import numpy as np

FILL = {1: 0.6, 2: 0.3}


def _look_at(eye, tgt, up=(0, 1, 0)):
    e, t, u = np.array(eye, float), np.array(tgt, float), np.array(up, float)
    z = e - t; z /= np.linalg.norm(z)
    if abs(float(np.dot(z, u))) > 0.999:      # straight down/up: any horizontal up vector
        u = np.array((0, 0, 1), float)
    x = np.cross(u, z); x /= np.linalg.norm(x); y = np.cross(z, x)
    M = np.eye(4); M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = x, y, z, e
    return M


def target_points(P, T, I, items, parts_rx=None):
    """points of the target pieces (items 'T:<part>#nnnn'), optionally only parts matching parts_rx"""
    import re
    rx = re.compile(parts_rx) if parts_rx else None
    ok = np.array([it.startswith("T:") and (rx is None or bool(rx.fullmatch(it[2:].split("#")[0]))) for it in items])
    sel = ok[I] if len(I) else np.zeros(0, bool)
    return P[np.unique(T[sel].ravel())] if sel.any() else np.zeros((0, 3), np.float32)


def component_cams(comp, pts, res_x, threshold):
    """-> (cams, info). cams in the cache format of vis_export.py; info for the report and the views file"""
    if len(pts) == 0:
        raise SystemExit("VIS_ERROR component %s: no target geometry matches 'parts'" % comp.get("name"))
    lo, hi = pts.min(0).astype(float), pts.max(0).astype(float)
    ctr = (lo + hi) / 2; R = max(float(np.linalg.norm(hi - lo)) / 2, 1e-3)
    rank = int(comp.get("rank", 1))
    fill = float(comp.get("fill", FILL.get(rank, 0.3)))
    hfov = float(comp.get("hfov", 40.0)); th = math.tan(math.radians(hfov) / 2)
    dist = R / (fill * th)
    f = np.array(comp.get("front", (1, 0, 0)), float); f[1] = 0
    f = f / np.linalg.norm(f) if np.linalg.norm(f) > 1e-9 else np.array((1.0, 0, 0))
    side = np.cross((0, 1, 0), f)              # +90° az (counter-clockwise seen from above, Y up)
    focal = 0.5 / th
    name = comp.get("name", "component")

    def cam(nm, az, el, cls, why=""):
        a, e = math.radians(az), math.radians(el)
        d = (f * math.cos(a) + side * math.sin(a)) * math.cos(e) + np.array((0, 1, 0)) * math.sin(e)
        eye = ctr + d * dist
        eye[1] = max(eye[1], lo[1])            # never below the foot of the component (negative el stops there)
        return {"name": nm, "cls": cls, "M": _look_at(eye, ctr).tolist(), "focal": focal, "aperture": 1.0, "res": None,
                "win": [0, 0], "zoom": 1, "component": name, "az": round(az, 1), "el": round(el, 1), "why": why,
                "eye": [round(v, 3) for v in eye], "target": [round(v, 3) for v in ctr], "hfov": hfov}

    views = comp.get("views") or []
    if not views:
        raise SystemExit("VIS_ERROR component %s: no views (rank 1: 2-3, rank 2: 1; rank 3 gets none)" % name)
    cams = [cam("%s_%s" % (name, v["name"]), float(v.get("az", 0)), float(v.get("el", 0)), "component", v.get("why", ""))
            for v in views]
    rd = comp.get("random") or {}
    rng = np.random.default_rng((zlib.crc32(name.encode()) + int(rd.get("seed", 1))) % 2**32)
    e0, e1 = rd.get("el", [0, 35])
    for k in range(int(rd.get("n", 2))):
        cams.append(cam("%s_r%02d" % (name, k), float(rng.uniform(0, 360)), float(rng.uniform(e0, e1)), "component_random"))
    readable = threshold * 2 * R / (fill * res_x)
    info = {"name": name, "rank": rank, "parts": comp.get("parts") or "", "fill": fill, "hfov": hfov, "diameter_m": round(2 * R, 3), "distance_m": round(dist, 3),
            "readable_m": round(readable, 4), "center": [round(v, 3) for v in ctr],
            "views": [{k: c[k] for k in ("name", "az", "el", "why", "eye", "target", "hfov")} for c in cams if c["cls"] == "component"]}
    return cams, info

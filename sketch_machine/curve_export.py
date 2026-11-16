"""Export only the curves of a scene – as USD (for Houdini, Blender, Maya) or JSON (for scripts and AI chats).

Both show the same: lines and painting with thickness per point, no surfaces, no meshes, no notes. Identifiers as
in the sketch brief; with hidden, hidden items are added and counted on afterwards. Exact duplicate strokes are dropped."""
import json
import math
import os

import numpy as np

from . import brief, generators, network, usd_export
from .camera import Camera
from .vp.common import FOV

FORMAT = "mule-curves"
VERSION = 1
ROUND = 5  # Decimal places: 0.01 mm at 1 unit = 1 m – enough and keeps the file readable


def _key(c):
    """Position of a stroke at ROUND decimal places: same key = exactly the same stroke (-0.0 and 0.0 are equal)."""
    return (np.round(c.points, ROUND) + 0.0).tobytes()


def collect(scene, hidden=False):
    """-> (vis, maps, dropped): what is exported, like brief.index (without surfaces and meshes), and the number of
    dropped duplicate strokes. Visible items keep their brief identifier, hidden ones are counted on afterwards."""
    vis, maps = brief.index(scene)
    strokes, curves, nulls = list(vis["strokes"]), list(vis["curves"]), list(vis["nulls"])
    if hidden:
        known = {st.id for st in strokes}
        strokes += [st for st in scene.strokes if st.id not in known and st.flipbook is None]  # Flipbook: not yet
        known = {c.id for _, c in curves}
        curves += [(st, c) for st in strokes for c in st.curves if c.id not in known and len(c.points) > 1]
        known = {n.id for n in nulls}
        nulls += [n for n in scene.nulls if n.id not in known]
    seen, kept = set(), []
    for st, c in curves:
        key = _key(c)
        if key not in seen:
            seen.add(key)
            kept.append((st, c))
    used = {st.id for st, _ in kept}
    strokes = [st for st in strokes if st.id in used]
    wanted = {o.id for st in strokes for o in scene.ancestors(st)}
    nulls = [n for n in nulls if n.id in wanted]
    lid, sid, hid = dict(maps["lid"]), dict(maps["sid"]), dict(maps["hid"])
    for table, prefix, ids in ((lid, "L", [c.id for _, c in kept]), (sid, "S", [st.id for st in strokes]),
                               (hid, "H", [n.id for n in nulls])):
        for i in ids:
            if i not in table:
                table[i] = f"{prefix}{len(table) + 1}"
    keep = {c.id for _, c in kept}
    maps = {**maps, "fid": {}, "mid": {}, "lid": {i: name for i, name in lid.items() if i in keep},
            "sid": {i: sid[i] for i in used}, "hid": {n.id: hid[n.id] for n in nulls}}
    vis = {"strokes": strokes, "surfaces": [], "meshes": [], "nulls": nulls, "curves": kept}
    return vis, maps, len(curves) - len(kept)


def cameras(scene, fov=FOV):
    """The hero cameras of the scene (screenshots with a flag) in the form of data["cameras"] – without rendering."""
    out, used = [], set()
    for hero in brief.board_heroes(scene):
        view = hero["view"]
        cam = Camera()
        cam.set_state(np.array(view["target"], float), float(view["dist"]), np.array(view["rot"], float))
        key = "hero_" + "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in hero["name"].lower())
        while key in used:
            key += "_"
        used.add(key)
        entry = {"name": hero["name"], "id": key, "image": "", "eye": _r(cam.eye), "target": _r(cam.target),
                 "up": _r(cam.up), "fov_vertical_deg": round(math.degrees(fov), 2),
                 "aspect": round(hero["aspect"] or 1.0, 4)}
        if view.get("ortho"):
            entry["orthographic_height"] = round(2 * float(view["dist"]) * math.tan(fov / 2), 4)
        out.append(entry)
    return out


def _r(values, digits=ROUND):
    return [round(float(x), digits) + 0.0 for x in np.ravel(values)]


def _corners(c):
    """Inner corners/knots of a line as point indices (empty: none)."""
    return [int(k) for k in (c.knots[1] if c.knots else ())]


def as_dict(scene, hidden=False, fov=FOV):
    """The curves as data (what write_json writes). Symmetry/array are factored out as in the USD."""
    vis, maps, dropped = collect(scene, hidden)
    lid, sid = maps["lid"], maps["sid"]
    copies = generators.copies_by_object(scene)
    shown = {c.id for _, c in brief.index(scene)[0]["curves"]}
    objects, points = [], []
    for st in vis["strokes"]:
        curves = []
        for _, ops in copies.get(st.id, [((), ())]):
            for c in st.curves:
                if c.id not in lid:
                    continue
                pieces = generators.apply_polyline(c.points, ops, (c.widths,)) if ops else [(c.points, (c.widths,))]
                for k, (p, (w,)) in enumerate(pieces):
                    if len(p) < 2:
                        continue
                    points.append(p)
                    curves.append({"id": lid[c.id] + (f"_{k + 1}" if len(pieces) > 1 else ""),
                                   "style": c.style, "paint": bool(c.paint), "order": int(c.seq) if c.paint else None,
                                   "hidden": c.id not in shown,
                                   "color": brief._hex(c.color) if c.color is not None else None,
                                   "corners": _corners(c) if not ops else [],
                                   "points": [_r(x) for x in p], "widths": _r(w)})
        objects.append({"id": sid[st.id], "name": st.name, "curves": curves})
    lo, hi = (np.vstack(points).min(0), np.vstack(points).max(0)) if points else (np.zeros(3), np.zeros(3))
    return {"format": FORMAT, "version": VERSION, "units": "1 unit = 1 m", "up_axis": "Y",
            "about": "Curves from Mule, a 3D sketching tool. widths = stroke width per point. paint: painted stroke, "
                     "order = painting order; corners = point indices of corners.",
            "bounds": {"min": _r(lo), "max": _r(hi)}, "dropped_duplicates": dropped,
            "cameras": [{k: v for k, v in c.items() if k not in ("id", "image")} for c in cameras(scene, fov)],
            "objects": objects}


def write_json(scene, path, hidden=False, fov=FOV):
    """Curves as JSON to path: one line per curve, so the file stays readable. -> (curves, duplicates)"""
    data = as_dict(scene, hidden, fov)
    objects = data.pop("objects")
    head = json.dumps(data, ensure_ascii=False, indent=1)[:-2]
    parts = []
    for obj in objects:
        rows = ",\n".join("    " + json.dumps(c, ensure_ascii=False, separators=(",", ":")) for c in obj["curves"])
        parts.append(f'  {{"id":{json.dumps(obj["id"])},"name":{json.dumps(obj["name"], ensure_ascii=False)},'
                     f'"curves":[\n{rows}\n  ]}}')
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(head + ',\n "objects":[\n' + ",\n".join(parts) + "\n ]\n}\n")
    return sum(len(o["curves"]) for o in objects), data["dropped_duplicates"]


def write_usd(scene, path, hidden=False, tubes=False, fov=FOV):
    """Curves as USD to path (.usda text, .usd/.usdc binary), prims as in the scene USD. -> (curves, duplicates)"""
    vis, maps, dropped = collect(scene, hidden)
    ids = {**maps["sid"], **maps["hid"]}
    data = {"_vis": vis, "_maps": maps, "notes": [], "cameras": cameras(scene, fov),
            "hierarchy": [brief._null_entry(scene, n, ids, maps["lid"]) for n in vis["nulls"]]}
    usd_export.write(scene, path, data=data, tubes=tubes)
    return len(vis["curves"]), dropped


def default_path(scene_path, ext):
    """Suggestion for the save dialog: next to the scene, name.curves.json or name_curves.usd."""
    from . import assoc
    base = assoc.strip_ext(os.path.basename(scene_path or "skizze"))
    name = f"{base}.curves.json" if ext == "json" else f"{base}_curves.usd"
    return os.path.join(os.path.dirname(scene_path or os.path.abspath(".")), name)

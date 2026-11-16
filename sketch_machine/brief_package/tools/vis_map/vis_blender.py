# vis_blender.py – the visibility map in Blender only, one command (export + counting + report + pictures).
# The Blender counterpart of vis_export.py (hython): reads a .blend READ-ONLY (never saves), evaluates the geometry
# per motion state (modifiers, geometry nodes, instances), splits the unit's parts into connected pieces, builds the
# camera set (hero cameras of the brief or of the .blend, control cameras, hero-like cloud), writes the neutral cache
# (geo_<state>.npz + scene.json, Y up like the brief) and then runs vis_map.py in the same Blender process.
#   blender -b --factory-startup -P tools/vis_map/vis_blender.py -- review/vis/<unit>_config.json [vis_map options]
#   blender -b --factory-startup -P tools/vis_map/vis_blender.py -- --selftest      (tool check, no project needed)
# Config keys (README.md): blend, objects, target, part_attrib, occluder_attrib, states, brief_json / hero_names,
#   hero_cams, control_cams, cloud, brief_scale, component, res_x, thresholds, threshold_main, cloud_sizes, part_alias, pictures,
#   cache_dir, out_dir, unit.
import bpy, sys, os, json, math, time, zlib, re, runpy, tempfile
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
MESHY = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES"}
# Blender is Z up, the brief (and the Houdini path) Y up: (x, y, z)_blender -> (x, z, -y)
C3 = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)
C4 = np.eye(4); C4[:3, :3] = C3


def look_at(eye, tgt, up=(0, 1, 0)):
    e, t, u = np.array(eye, float), np.array(tgt, float), np.array(up, float)
    z = e - t; z /= np.linalg.norm(z)
    x = np.cross(u, z); x /= np.linalg.norm(x); y = np.cross(z, x)
    M = np.eye(4); M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = x, y, z, e
    return M


def rot(axis, deg):
    a = np.array(axis, float); a /= np.linalg.norm(a); th = math.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K


def islands(nv, tris):
    """connected pieces over shared vertices: label per vertex (hooking + pointer jumping, numpy only)"""
    parent = np.arange(nv)
    if len(tris) == 0:
        return parent
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]]])
    while True:
        a, b = parent[e[:, 0]], parent[e[:, 1]]
        ch = a != b
        if not ch.any():
            return parent
        lo, hi = np.minimum(a[ch], b[ch]), np.maximum(a[ch], b[ch])
        np.minimum.at(parent, hi, lo)
        while True:
            pp = parent[parent]
            if np.array_equal(pp, parent):
                break
            parent = pp


# ---------- scene reading -----------------------------------------------------------------------------
def apply_state(parms):
    sc = bpy.context.scene
    if "frame" in parms:
        sc.frame_set(int(parms["frame"]))
    for path, v in (parms.get("props") or {}).items():   # e.g. 'objects["Rig"]["Fold_In"]' = 0.5 (relative to bpy.data)
        exec("D.%s = V" % path, {"D": bpy.data, "V": v})
    bpy.context.view_layer.update()


def target_test(cfg):
    t = cfg.get("target") or {}
    names = set(t.get("objects") or ())
    if t.get("collection"):
        col = bpy.data.collections.get(t["collection"])
        if col is None:
            raise SystemExit("VIS_ERROR target collection not found: %s" % t["collection"])
        names |= {o.name for o in col.all_objects}
    rx = re.compile(t["regex"]) if t.get("regex") else None
    if not names and rx is None:
        raise SystemExit("VIS_ERROR config needs target: {collection | objects | regex}")
    return lambda name: name in names or bool(rx and rx.fullmatch(name))


def occluder_test(cfg):
    o = cfg.get("objects", "visible")
    if o == "visible":
        return lambda ob: ob.visible_get()
    keep = set(o)
    return lambda ob: ob.name in keep


def face_strings(me, attr):
    a = me.attributes.get(attr) if attr else None
    if a is None or a.domain != "FACE" or a.data_type != "STRING":
        return None
    return np.array([d.value if isinstance(d.value, str) else d.value.decode("utf-8", "replace") for d in a.data],
                    dtype=object)


def collect(cfg, is_target, is_occ, items, prim_counts):
    """one state -> P (Y up, world), T, I (item per triangle)"""
    dg = bpy.context.evaluated_depsgraph_get()
    Ps, Ts, Is, off = [], [], [], 0
    piece_base = {}                                   # part -> next island rank (instances of one part continue)
    for inst in dg.object_instances:
        ob = inst.object
        if ob.type not in MESHY:
            continue
        owner = (inst.parent.original if inst.is_instance and inst.parent else ob.original)
        if not is_occ(owner) and not is_target(owner.name):
            continue
        try:
            me = ob.to_mesh()
        except RuntimeError:
            continue
        if me is None or len(me.polygons) == 0:
            ob.to_mesh_clear(); continue
        me.calc_loop_triangles()
        nv, nt, npoly = len(me.vertices), len(me.loop_triangles), len(me.polygons)
        V = np.empty(nv * 3, np.float32); me.vertices.foreach_get("co", V); V = V.reshape(-1, 3).astype(float)
        T = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get("vertices", T); T = T.reshape(-1, 3)
        TP = np.empty(nt, np.int32); me.loop_triangles.foreach_get("polygon_index", TP)
        tgt = is_target(owner.name)
        oname = owner.name
        raw = face_strings(me, cfg.get("part_attrib") if tgt else cfg.get("occluder_attrib"))
        if raw is None:
            raw = np.full(npoly, oname, dtype=object)
        raw = np.where(raw == "", oname, raw)
        if tgt and cfg.get("islands", True):          # every part split into its connected pieces
            lab = islands(nv, T)
            poly_lab = np.zeros(npoly, np.int64)
            poly_lab[TP] = lab[T[:, 0]]
            rank = np.zeros(npoly, np.int64)
            for p in np.unique(raw):
                m = raw == p
                _, r = np.unique(poly_lab[m], return_inverse=True)
                rank[m] = r + piece_base.get(p, 0)
                piece_base[p] = piece_base.get(p, 0) + int(r.max()) + 1
            raw = np.array(["%s#%04d" % (p, r) for p, r in zip(raw, rank)], dtype=object)
        names = np.array([("T:" if tgt else "O:") + str(v) for v in raw], dtype=object)
        u, inv = np.unique(names, return_inverse=True)
        for k in u:
            if k not in items:
                items.append(k)
        idmap = np.array([items.index(k) for k in u], dtype=np.int32)
        pid = idmap[inv]
        if tgt:
            for k, c in zip(u, np.bincount(inv)):
                prim_counts[k] = prim_counts.get(k, 0) + int(c)
        M = np.array(inst.matrix_world)
        W = V @ M[:3, :3].T + M[:3, 3]
        Ps.append((W @ C3.T).astype(np.float32)); Ts.append(T + off); Is.append(pid[TP]); off += nv
        ob.to_mesh_clear()
    if not Ps:
        raise SystemExit("VIS_ERROR no geometry found (check objects / target)")
    return np.concatenate(Ps), np.concatenate(Ts).astype(np.int32), np.concatenate(Is).astype(np.int32)


def blend_camera(name, sc):
    ob = bpy.data.objects.get(name)
    if ob is None or ob.type != "CAMERA":
        raise SystemExit("VIS_ERROR camera not found: %s" % name)
    d = ob.data
    rx, ry = sc.render.resolution_x * sc.render.pixel_aspect_x, sc.render.resolution_y * sc.render.pixel_aspect_y
    horizontal = d.sensor_fit == "HORIZONTAL" or (d.sensor_fit == "AUTO" and rx >= ry)
    sensor = d.sensor_width if d.sensor_fit != "VERTICAL" else d.sensor_height
    lens = d.lens if horizontal else d.lens * rx / ry   # vis_map fits horizontally
    M = C4 @ np.array(ob.matrix_world)
    M[:3, :3] /= np.linalg.norm(M[:3, :3], axis=0)     # no scale on cameras
    return {"name": ob.name, "cls": "hero", "M": M.tolist(), "focal": lens, "aperture": sensor,
            "res": [sc.render.resolution_x, sc.render.resolution_y], "win": [d.shift_x, d.shift_y * rx / ry], "zoom": 1}


def cameras(cfg):
    sc = bpy.context.scene
    cams = []
    if cfg.get("brief_json"):   # hero cameras of the Mule brief (Y up, the views of views/hero_*.png)
        want = cfg.get("hero_names")
        for bc in json.load(open(cfg["brief_json"], encoding="utf-8")).get("cameras") or []:
            if want and bc["id"] not in want:
                continue
            if bc.get("orthographic_height"):
                print("VIS_WARN skip orthographic hero camera", bc["id"]); continue
            tv = math.tan(math.radians(bc["fov_vertical_deg"]) / 2); bs = float(cfg.get("brief_scale", 1.0))
            cams.append({"name": bc["id"], "cls": "hero", "M": look_at([v * bs for v in bc["eye"]], [v * bs for v in bc["target"]], bc.get("up", (0, 1, 0))).tolist(),
                         "focal": 0.5 / (tv * bc["aspect"]), "aperture": 1.0, "res": [1000, round(1000 / bc["aspect"])],
                         "win": [0, 0], "zoom": 1})
    for n in cfg.get("hero_cams") or []:
        cams.append(blend_camera(n, sc))
    if not cams:
        raise SystemExit("VIS_ERROR no hero camera (brief_json or hero_cams)")
    aspect = cams[0]["res"][1] / cams[0]["res"][0]
    for s in cfg.get("control_cams", []):
        nm, e, t, f = s.split(":")
        e = [float(v) for v in e.split(",")]; t = [float(v) for v in t.split(",")]
        cams.append({"name": nm, "cls": "control", "M": look_at(e, t).tolist(), "focal": 0.5 / math.tan(math.radians(float(f)) / 2),
                     "aperture": 1.0, "res": None, "win": [0, 0], "zoom": 1})
    dg = bpy.context.evaluated_depsgraph_get()
    Ci = C3.T                                          # Y up -> Blender

    def hit(eye, d):
        ok, loc, _n, _i, _o, _m = sc.ray_cast(dg, Vector(Ci @ eye), Vector(Ci @ d))
        return float(np.dot(C3 @ np.array(loc) - eye, d)) if ok else None

    cl = cfg.get("cloud") or {"n": 16, "ang_deg": 15, "dist_frac": 0.2, "seed": 1, "pivot": "median_hit"}
    for h in [c for c in cams if c["cls"] == "hero"]:
        M = np.array(h["M"]); eye = M[:3, 3]; fwd = -M[:3, 2]; right, up = M[:3, 0], M[:3, 1]
        if isinstance(cl.get("pivot"), list):
            piv = np.array(cl["pivot"], float)
        else:   # median hit distance of a 5×5 ray grid over the central half of the frame (as vis_export.py)
            hfov = 2 * math.atan(h["aperture"] / 2 / h["focal"]); dists = []
            for i in np.linspace(-0.25, 0.25, 5):
                for j in np.linspace(-0.25 * aspect, 0.25 * aspect, 5):
                    d = fwd + right * (2 * i * math.tan(hfov / 2)) + up * (2 * j * math.tan(hfov / 2))
                    d /= np.linalg.norm(d); t = hit(eye, d)
                    if t is not None and t > 1e-6:
                        dists.append(t)
            piv = eye + fwd * (np.median(dists) if dists else 10.0)
        h["pivot"] = piv.tolist()
        rng = np.random.default_rng((zlib.crc32(h["name"].encode()) + int(cl["seed"])) % 2**32)
        v0 = eye - piv
        for k in range(int(cl["n"])):
            yaw, pitch = rng.uniform(-cl["ang_deg"], cl["ang_deg"], 2); s = rng.uniform(1 - cl["dist_frac"], 1 + cl["dist_frac"])
            v = rot(up, yaw) @ v0; v = rot(np.cross(v, up), pitch) @ v
            c = dict(h); c.update({"name": "%s_c%02d" % (h["name"], k), "cls": "cloud", "parent": h["name"],
                                   "M": look_at(piv + v * s, piv, up).tolist(), "offset": [round(yaw, 1), round(pitch, 1), round(s, 3)]})
            c.pop("pivot", None); cams.append(c)
    for c in cams:
        c["aspect"] = aspect
    return cams


def export(cfg):
    t0 = time.time()
    blend = cfg.get("blend")
    if blend and os.path.normcase(os.path.abspath(bpy.data.filepath or "")) != os.path.normcase(os.path.abspath(blend)):
        bpy.ops.wm.open_mainfile(filepath=blend, load_ui=False)   # read only: this script never saves
    t_load = time.time() - t0
    CACHE = cfg["cache_dir"]; os.makedirs(CACHE, exist_ok=True)
    is_target, is_occ = target_test(cfg), occluder_test(cfg)
    states = cfg.get("states") or {"rest": {}}
    items, prim_counts, timing, pc_state = [], {}, {}, {}
    cams, comp_info = None, None
    for si, (sname, parms) in enumerate(states.items()):
        ts = time.time()
        apply_state(parms)
        pcs = {}; P, T, I = collect(cfg, is_target, is_occ, items, pcs); pc_state[sname] = pcs
        for k, v in pcs.items():
            prim_counts.setdefault(k, v)
        np.savez(os.path.join(CACHE, "geo_%s.npz" % sname), P=P, T=T, I=I)
        timing[sname] = round(time.time() - ts, 2)
        print("STATE", sname, "points", len(P), "tris", len(T), "s", timing[sname])
        if si == 0:
            cams = cameras(cfg)      # pivots from the first (rest) state, as vis_export.py
            if cfg.get("component"):   # component views from the component's bounding box (rule 7, vis_views.py)
                sys.path.insert(0, HERE); import vis_views
                ccams, comp_info = vis_views.component_cams(cfg["component"], vis_views.target_points(P, T, I, items, cfg["component"].get("parts")),
                                                            int(cfg.get("res_x", 960)), int(cfg.get("threshold_main", 20)))
                for c in ccams:
                    c["aspect"] = cams[0]["aspect"]
                cams += ccams
                os.makedirs(cfg.get("out_dir", CACHE), exist_ok=True)
                json.dump(comp_info, open(os.path.join(cfg.get("out_dir", CACHE), "%s_views.json" % cfg["unit"]), "w"), indent=1)
    json.dump({"items": items, "prim_counts": prim_counts, "prim_counts_state": pc_state, "states": list(states.keys()),
               "cams": cams, "component": comp_info, "timing": {"load_s": round(t_load, 2), "per_state_s": timing, "total_s": round(time.time() - t0, 2)}},
              open(os.path.join(CACHE, "scene.json"), "w"), indent=1)
    print("EXPORT_DONE items", len(items), "cams", len(cams), "total_s", round(time.time() - t0, 1))


def count(cfg_path, extra):
    """vis_map.py in this process, on an empty scene (nothing of the project file can change the ID renders)"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sys.argv = [sys.argv[0], "--", cfg_path, *extra]
    try:
        runpy.run_path(os.path.join(HERE, "vis_map.py"), run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            raise


# ---------- self-test -----------------------------------------------------------------------------------
def selftest():
    """Tool check on a synthetic scene: a box seen by the hero camera must be A, a cube sealed inside a hollow shell
    D, a speck far away S – and one object with two separate pieces must give two pieces."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    tmp = tempfile.mkdtemp(prefix="vis_selftest_")
    col = bpy.data.collections.new("U_TEST"); bpy.context.scene.collection.children.link(col)

    def box(name, size, loc, coll, hollow=False):
        bpy.ops.mesh.primitive_cube_add(size=size, location=loc)
        ob = bpy.context.active_object; ob.name = name
        if hollow:   # inward-facing second shell: closed, no gaps
            m = ob.modifiers.new("solid", "SOLIDIFY"); m.thickness = size * 0.05
        for c in ob.users_collection:
            c.objects.unlink(ob)
        coll.objects.link(ob)
        return ob

    box("seen_box", 1.0, (0, 0, 0.5), col)
    box("shell", 2.0, (4, 0, 1.0), bpy.context.scene.collection, hollow=True)      # occluder
    box("sealed", 0.5, (4, 0, 1.0), col)                                            # inside the shell
    box("speck", 0.02, (2, -2, 0.6), col)                                            # a few pixels only
    bpy.ops.mesh.primitive_cube_add(size=0.6, location=(-1.5, 0, 0.3)); two = bpy.context.active_object
    bpy.ops.mesh.primitive_cube_add(size=0.6, location=(-1.5, 1.2, 0.3)); other = bpy.context.active_object
    with bpy.context.temp_override(active_object=two, selected_editable_objects=[two, other]):
        bpy.ops.object.join()
    two.name = "two_pieces"
    for c in two.users_collection:
        c.objects.unlink(two)
    col.objects.link(two)
    cam = bpy.data.objects.new("hero_test", bpy.data.cameras.new("hero_test"))
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (0, -9, 3)
    cam.rotation_euler = (math.radians(75), 0, 0)
    sc = bpy.context.scene; sc.render.resolution_x, sc.render.resolution_y = 960, 540
    cfg = {"unit": "SELFTEST", "target": {"collection": "U_TEST"}, "objects": "visible", "hero_cams": ["hero_test"],
           "control_cams": [], "cloud": {"n": 4, "ang_deg": 10, "dist_frac": 0.1, "seed": 7, "pivot": "median_hit"},
           "res_x": 480, "thresholds": [20], "threshold_main": 20, "cloud_sizes": [4], "pictures": {"heroes": 1},
           "cache_dir": os.path.join(tmp, "cache"), "out_dir": tmp}
    path = os.path.join(tmp, "config.json"); json.dump(cfg, open(path, "w"), indent=1)
    export(cfg)
    # component views: the speck alone, rank 1 -> it fills the picture and reads (A); the sealed cube is not part of the
    # component and stays D; readable size and views file are written
    cfg2 = dict(cfg, unit="SELFTEST_C", cache_dir=os.path.join(tmp, "cache_c"),
                component={"name": "speck_c", "rank": 1, "parts": "speck", "views": [{"name": "front", "az": 0, "el": 10, "why": "test"}],
                           "random": {"n": 1, "seed": 3}})
    path2 = os.path.join(tmp, "config_c.json"); json.dump(cfg2, open(path2, "w"), indent=1)
    export(cfg2)
    count(path, ["--no_pics"])
    res = json.load(open(os.path.join(tmp, "vis_SELFTEST.json"), encoding="utf-8"))
    tiers = {p: r["tier"] for p, r in res["parts"].items()}
    want = {"seen_box": "A", "sealed": "D", "speck": "S", "two_pieces": "A"}
    bad = {p: (tiers.get(p), t) for p, t in want.items() if tiers.get(p) != t}
    if res["parts"].get("two_pieces", {}).get("pieces") != 2:
        bad["two_pieces/pieces"] = (res["parts"].get("two_pieces", {}).get("pieces"), 2)
    count(path2, ["--no_pics"])
    res2 = json.load(open(os.path.join(tmp, "vis_SELFTEST_C.json"), encoding="utf-8"))
    t2 = {p: r["tier"] for p, r in res2["parts"].items()}
    for p, t in {"speck": "A", "sealed": "D", "seen_box": "A"}.items():
        if t2.get(p) != t:
            bad["component/" + p] = (t2.get(p), t)
    rd = (res2.get("component") or {}).get("readable_m")
    if not rd or rd > 0.01 or not os.path.exists(os.path.join(tmp, "SELFTEST_C_views.json")):
        bad["component/readable_m"] = (rd, "< 0.01 m and views file")
    print("SELFTEST", "PASS" if not bad else "FAIL %s" % bad, "tiers", tiers, "component", t2, "readable_m", rd, "folder", tmp)
    return not bad


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv or argv[0] == "--selftest":
        ok = selftest()
        sys.exit(0 if ok else 1)
    cfg_path = os.path.abspath(argv[0])
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    if "--skip_render" not in argv:
        export(cfg)
    count(cfg_path, argv[1:])

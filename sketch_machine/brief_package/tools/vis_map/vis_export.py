# vis_export.py – Sichtkarte, step 1 (hython, READ-ONLY): scene geometry per motion state + camera set.
# Generic: works on any Houdini scene (hip) or on plain geometry files. Never saves the hip.
#   hython vis_export.py -- <config.json>
# Config keys used here (see README.md):
#   hip                  path of the scene (loaded read-only)          | or geo_files: [paths] (no states)
#   objects              "displayed" (all displayed geo objects) or [list of /obj paths]
#   target_object        /obj path of the unit to classify
#   part_attrib          prim string attribute naming the parts of the target (fallback: object name)
#   occluder_attrib      optional prim string attrib to split occluders (default: one item per object)
#   states               {state_name: {"/obj/node/parm": value, ...}}
#   brief_json           path of the brief's brief.json: its hero cameras are used (optional hero_names: [ids])
#   hero_cams            [camera node paths], in addition or instead  (aspect of the first hero = render aspect)
#   control_cams         ["NAME:ex,ey,ez:tx,ty,tz:hfov", ...]  (world coords of the scene, up +Y)
#   cloud                {n, ang_deg, dist_frac, seed, pivot: "median_hit" | [x,y,z]}
#   brief_scale          optional: the scene is the brief scene scaled by this factor about the origin (brief cameras follow)
#   component            optional component views (vis_views.py, README.md); writes <out_dir>/<unit>_views.json
#   cache_dir            where the per-state npz files go (big, temporary)
# Output: <cache_dir>/geo_<state>.npz (P float32 n×3, T int32 m×3, I int32 m = item id), <cache_dir>/scene.json
import hou, sys, json, os, math, time, zlib
import numpy as np

cfg = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
CACHE = cfg["cache_dir"]; os.makedirs(CACHE, exist_ok=True)
t0 = time.time()
TRI_SNIPPET = "i@_t0 = primpoint(0, @primnum, 0); i@_t1 = primpoint(0, @primnum, 1); i@_t2 = primpoint(0, @primnum, 2);"
_TMP = {}

def _tri_chain():
    """in-memory helper network (stash -> divide -> wrangle) in a temporary /obj container; the hip is never saved"""
    if "w" not in _TMP or _TMP["w"] is None:
        box = hou.node("/obj").createNode("geo", "_vis_tmp"); box.setDisplayFlag(False)
        st = box.createNode("stash"); dv = box.createNode("divide", "tri"); dv.setFirstInput(st)
        w = box.createNode("attribwrangle", "tri_points"); w.setFirstInput(dv)
        w.parm("class").set(1); w.parm("snippet").set(TRI_SNIPPET)
        _TMP.update(st=st, w=w)
    return _TMP["st"], _TMP["w"]

def islands(g):
    """connectivity class per prim (point-connected pieces), via an in-memory connectivity SOP"""
    if "cn" not in _TMP:
        box = hou.node("/obj/_vis_tmp") or _tri_chain()[0].parent()
        s2 = box.createNode("stash", "isl_in"); cn = box.createNode("connectivity", "isl"); cn.setFirstInput(s2); cn.parm("connecttype").set(1)  # 1 = primitive class
        _TMP.update(s2=s2, cn=cn)
    _TMP["s2"].parm("stash").set(g); _TMP["cn"].cook(force=True)
    return np.array(_TMP["cn"].geometry().primIntAttribValues("class"), dtype=np.int64)

def triangulate(g):
    """g (world space) -> P (n,3) float32, T (m,3) int32, src prim index per tri (m) via attribute _src"""
    g.addAttrib(hou.attribType.Prim, "_src", 0)
    g.setPrimIntAttribValues("_src", list(range(len(g.iterPrims()))))
    st, wn = _tri_chain(); st.parm("stash").set(g); wn.cook(force=True)
    w = wn.geometry()
    P = np.frombuffer(w.pointFloatAttribValuesAsString("P"), dtype=np.float32).reshape(-1, 3)
    T = np.stack([np.array(w.primIntAttribValues(a), dtype=np.int32) for a in ("_t0", "_t1", "_t2")], 1)
    S = np.array(w.primIntAttribValues("_src"), dtype=np.int32)
    ok = (T >= 0).all(1)                                  # curves / points / 2-vertex prims are not surfaces
    return P, T[ok], S[ok]

def obj_list():
    if cfg.get("objects", "displayed") == "displayed":
        return [n for n in hou.node("/obj").children() if n.type().name() == "geo" and n.isDisplayFlagSet()
                and n.displayNode() is not None]
    return [hou.node(p) for p in cfg["objects"]]

def collect(items, prim_counts):
    """one state -> merged arrays; items = ordered list of item names (grows); returns P,T,I"""
    Ps, Ts, Is, off = [], [], [], 0
    srcs = []
    if "geo_files" in cfg:
        for f in cfg["geo_files"]:
            g = hou.Geometry(); g.loadFromFile(f); srcs.append((os.path.splitext(os.path.basename(f))[0], g, f == cfg.get("target_file")))
    else:
        for n in obj_list():
            g = hou.Geometry(); g.merge(n.displayNode().geometry()); g.transform(n.worldTransform())
            srcs.append((n.name(), g, n.path() == cfg["target_object"]))
    for oname, g, is_target in srcs:
        if len(g.iterPrims()) == 0: continue
        attr = cfg.get("part_attrib") if is_target else cfg.get("occluder_attrib")
        if attr and g.findPrimAttrib(attr) is not None:
            raw = np.array(g.primStringAttribValues(attr), dtype=object)
            raw = np.where(raw == "", oname, raw)
        else:
            raw = np.full(len(g.iterPrims()), oname, dtype=object)
        if is_target and cfg.get("islands", True):      # split every part into its connected pieces (point-connected)
            cls = islands(g)
            rank = np.zeros(len(raw), dtype=np.int64)
            for p in np.unique(raw):                     # island index = rank of the class inside the part (stable if topology is)
                m = raw == p; _, r = np.unique(cls[m], return_inverse=True); rank[m] = r
            raw = np.array(["%s#%04d" % (p, r) for p, r in zip(raw, rank)], dtype=object)
        names = [("T:" if is_target else "O:") + str(v) for v in raw]
        u, inv = np.unique(np.array(names, dtype=object), return_inverse=True)
        for k in u:
            if k not in items: items.append(k)
        idmap = np.array([items.index(k) for k in u], dtype=np.int32)
        pid = idmap[inv]
        if is_target:
            for k, c in zip(u, np.bincount(inv)): prim_counts[k] = int(c)
        P, T, S = triangulate(g)
        Ps.append(P); Ts.append(T + off); Is.append(pid[S]); off += len(P)
    return np.concatenate(Ps), np.concatenate(Ts), np.concatenate(Is)

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

if "hip" in cfg:
    hou.hipFile.load(cfg["hip"], suppress_save_prompt=True, ignore_load_warnings=True)
t_load = time.time() - t0
states = cfg.get("states") or {"static": {}}
items, prim_counts, timing, rest_geo, pc_state = [], {}, {}, None, {}
for si, (sname, parms) in enumerate(states.items()):
    ts = time.time()
    for p, v in parms.items(): hou.parm(p).set(v)
    pcs = {}; P, T, I = collect(items, pcs); pc_state[sname] = pcs
    for k, v in pcs.items(): prim_counts.setdefault(k, v)
    np.savez(os.path.join(CACHE, "geo_%s.npz" % sname), P=P, T=T, I=I)
    timing[sname] = round(time.time() - ts, 2)
    print("STATE", sname, "points", len(P), "tris", len(T), "s", timing[sname])
    if si == 0: rest_geo = (P, T, I)
    if si == 0:   # merged rest geometry for the pivot rays
        rg = hou.Geometry()
        if "geo_files" in cfg:
            for f in cfg["geo_files"]:
                g = hou.Geometry(); g.loadFromFile(f); rg.merge(g)
        for n in ([] if "geo_files" in cfg else obj_list()):
            g = hou.Geometry(); g.merge(n.displayNode().geometry()); g.transform(n.worldTransform()); rg.merge(g)

# --- cameras -------------------------------------------------------------------------------------------
cams = []
if cfg.get("brief_json"):   # hero cameras of the Mule brief (same views as views/hero_*.png), no camera nodes needed
    want = cfg.get("hero_names")
    for bc in json.load(open(cfg["brief_json"], encoding="utf-8")).get("cameras") or []:
        if want and bc["id"] not in want:
            continue
        if bc.get("orthographic_height"):
            print("SKIP orthographic hero camera", bc["id"]); continue
        tv = math.tan(math.radians(bc["fov_vertical_deg"]) / 2); bs = float(cfg.get("brief_scale", 1.0))
        cams.append({"name": bc["id"], "cls": "hero", "M": look_at([v * bs for v in bc["eye"]], [v * bs for v in bc["target"]], bc.get("up", (0, 1, 0))).tolist(),
                     "focal": 0.5 / (tv * bc["aspect"]), "aperture": 1.0, "res": [1000, round(1000 / bc["aspect"])],
                     "win": [0, 0], "zoom": 1})
for cp in cfg.get("hero_cams") or []:
    c = hou.node(cp)
    M = np.array(c.worldTransform().asTupleOfTuples()).T
    cams.append({"name": c.name(), "cls": "hero", "M": M.tolist(), "focal": c.evalParm("focal"),
                 "aperture": c.evalParm("aperture"), "res": [c.evalParm("resx"), c.evalParm("resy")],
                 "win": [c.evalParm("winx"), c.evalParm("winy")], "zoom": c.evalParm("winsizex")})
aspect = cams[0]["res"][1] / cams[0]["res"][0]
for s in cfg.get("control_cams", []):
    nm, e, t, f = s.split(":")
    e = [float(v) for v in e.split(",")]; t = [float(v) for v in t.split(",")]
    cams.append({"name": nm, "cls": "control", "M": look_at(e, t).tolist(), "focal": 0.5 / math.tan(math.radians(float(f)) / 2),
                 "aperture": 1.0, "res": None, "win": [0, 0], "zoom": 1})
cl = cfg["cloud"]
for h in [c for c in cams if c["cls"] == "hero"]:
    M = np.array(h["M"]); eye = M[:3, 3]; fwd = -M[:3, 2]; right, up = M[:3, 0], M[:3, 1]
    if isinstance(cl.get("pivot"), list):
        piv = np.array(cl["pivot"], float)
    else:                                   # median hit distance of a 5×5 ray grid over the central half of the frame
        hfov = 2 * math.atan(h["aperture"] / 2 / h["focal"]); dists = []
        for i in np.linspace(-0.25, 0.25, 5):
            for j in np.linspace(-0.25 * aspect, 0.25 * aspect, 5):
                d = fwd + right * (2 * i * math.tan(hfov / 2)) + up * (2 * j * math.tan(hfov / 2))
                d /= np.linalg.norm(d); pos, nrm, uvw = hou.Vector3(), hou.Vector3(), hou.Vector3()
                if rg.intersect(hou.Vector3(eye), hou.Vector3(d), pos, nrm, uvw, min_hit=1e-6) >= 0:
                    dists.append(float(np.dot(np.array(pos) - eye, fwd)))
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
comp_info = None
if cfg.get("component"):   # component views from the component's bounding box (rule 7, vis_views.py)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vis_views
    P0, T0, I0 = rest_geo
    ccams, comp_info = vis_views.component_cams(cfg["component"], vis_views.target_points(P0, T0, I0, items, cfg["component"].get("parts")),
                                                int(cfg.get("res_x", 960)), int(cfg.get("threshold_main", 20)))
    cams += ccams
    os.makedirs(cfg.get("out_dir", CACHE), exist_ok=True)
    json.dump(comp_info, open(os.path.join(cfg.get("out_dir", CACHE), "%s_views.json" % cfg["unit"]), "w"), indent=1)
for c in cams:   # common render aspect
    c["aspect"] = aspect
json.dump({"items": items, "prim_counts": prim_counts, "prim_counts_state": pc_state, "states": list(states.keys()), "cams": cams,
           "component": comp_info,
           "timing": {"load_s": round(t_load, 2), "per_state_s": timing, "total_s": round(time.time() - t0, 2)}},
          open(os.path.join(CACHE, "scene.json"), "w"), indent=1)
print("EXPORT_DONE items", len(items), "cams", len(cams), "total_s", round(time.time() - t0, 1))

# vis_map.py – Sichtkarte, step 2 (Blender headless): flat-ID renders per camera and state -> pixel counts ->
# tiers A/B/C/S/D -> report (md + json) -> tier-coloured judging pictures.  Never opens or saves a project .blend.
#   blender -b --factory-startup -P vis_map.py -- <config.json> [--only_states rest] [--max_cams N] [--skip_render]
# Reads <cache_dir>/scene.json + geo_<state>.npz written by vis_export.py (any source that writes this format works).
# Config keys used here: unit, res_x, thresholds, threshold_main, cloud_sizes, part_alias {regex: part},
#   pictures {heroes: n, overview: CAMNAME, overview_hide_occluders: true}, cache_dir, out_dir,
#   component {carrier: regex} (vis_views.py: component views count like hero cameras, random ones like the cloud;
#   both see the component alone, occluders hidden except the carrier).
import bpy, sys, os, json, time, re
import numpy as np
from mathutils import Matrix

argv = sys.argv[sys.argv.index("--") + 1:]
cfg = json.load(open(argv[0], encoding="utf-8"))
opt = {argv[i][2:]: (argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else "1")
       for i in range(1, len(argv)) if argv[i].startswith("--")}
CACHE, OUT, UNIT = cfg["cache_dir"], cfg["out_dir"], cfg["unit"]
os.makedirs(OUT, exist_ok=True)
S = json.load(open(os.path.join(CACHE, "scene.json")))
ITEMS, CAMS = S["items"], S["cams"]
STATES = opt["only_states"].split(",") if "only_states" in opt else S["states"]
if "max_cams" in opt: CAMS = CAMS[:int(opt["max_cams"])]
RX = int(cfg.get("res_x", 960)); RY = int(round(RX * CAMS[0]["aspect"]))
TMP = os.path.join(CACHE, "_id.exr")
CARRIER = re.compile((cfg.get("component") or {}).get("carrier")) if (cfg.get("component") or {}).get("carrier") else None
_CP = (S.get("component") or {}).get("parts")
CPARTS = re.compile(_CP) if _CP else None      # only these target parts are the component; other parts of the unit are hidden in its views
def hidden_alone(it):
    if it.startswith("O:"): return not (CARRIER and CARRIER.fullmatch(it[2:]))
    return bool(CPARTS) and not CPARTS.fullmatch(it[2:].split("#")[0])
GROUP = {"hero": ("hero", "component"), "cloud": ("cloud", "component_random"), "control": ("control",)}
sc = bpy.context.scene
for o in list(bpy.data.objects): bpy.data.objects.remove(o)

# ---------- scene building ----------------------------------------------------------------------------
GEO_BB = []
def build_state(state):
    for o in [o for o in bpy.data.objects if o.type == "MESH"]:
        me = o.data; bpy.data.objects.remove(o); bpy.data.meshes.remove(me)
    z = np.load(os.path.join(CACHE, "geo_%s.npz" % state)); P, T, I = z["P"], z["T"], z["I"]
    GEO_BB[:] = [P.min(0).astype(float), P.max(0).astype(float)]   # extent of this state -> clip range in set_cam
    objs = {}
    order = np.argsort(I, kind="stable"); Is = I[order]; ks, starts = np.unique(Is, return_index=True)
    ends = np.append(starts[1:], len(Is))
    for k, a0, a1 in zip(ks, starts, ends):
        t = T[order[a0:a1]]; u, inv = np.unique(t.ravel(), return_inverse=True)
        V = P[u].astype(np.float32); F = inv.astype(np.int32)
        me = bpy.data.meshes.new("m%d" % k)
        me.vertices.add(len(V)); me.vertices.foreach_set("co", V.ravel())
        me.loops.add(len(F)); me.loops.foreach_set("vertex_index", F)
        me.polygons.add(len(F) // 3); me.polygons.foreach_set("loop_start", np.arange(0, len(F), 3, dtype=np.int32))
        me.update(calc_edges=True)
        ob = bpy.data.objects.new(ITEMS[k], me); sc.collection.objects.link(ob); objs[int(k)] = ob
    return objs

def id_color(k):
    n = k + 1
    return ((n % 256) / 255.0, (n // 256) / 255.0, 0.5, 1.0)

cam_ob = bpy.data.objects.new("visCam", bpy.data.cameras.new("visCam")); sc.collection.objects.link(cam_ob); sc.camera = cam_ob
def set_cam(c):
    d = cam_ob.data; d.sensor_fit = "HORIZONTAL"; d.sensor_width = 36.0
    d.lens = 36.0 * c["focal"] / c["aperture"] / max(c.get("zoom", 1) or 1, 1e-6)
    d.shift_x = c["win"][0]; d.shift_y = c["win"][1] * RY / RX
    # clip range from the scene extent (was a fixed 0.05-5000 m, which cut every camera further than 5 km, e.g. terrain):
    # far = farthest bbox corner of the current state from the eye; near grows with far (depth precision), >= 0.05 m.
    # config "clip": [near, far] overrides; "clip_near_frac" (default 5e-5) sets near = frac * far (km-scale scenes:
    # 1e-3 against z-fighting of nearly coplanar surfaces such as water over lowland).
    if cfg.get("clip"):
        d.clip_start, d.clip_end = float(cfg["clip"][0]), float(cfg["clip"][1])
    else:
        eye = np.array(c["M"], float)[:3, 3]; lo, hi = GEO_BB
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        far = float(np.linalg.norm(corners - eye, axis=1).max()) * 1.02 + 1.0
        d.clip_start, d.clip_end = max(0.05, far * float(cfg.get("clip_near_frac", 5e-5))), far
    cam_ob.matrix_world = Matrix(c["M"])

def setup_id_render():
    r = sc.render; r.engine = "BLENDER_WORKBENCH"; r.resolution_x, r.resolution_y, r.resolution_percentage = RX, RY, 100
    r.film_transparent = True; r.dither_intensity = 0.0
    sh = sc.display.shading; sh.light = "FLAT"; sh.color_type = "OBJECT"
    for a in ("show_cavity", "show_shadows", "show_object_outline", "show_specular_highlight", "show_xray", "show_backface_culling", "use_dof"):
        if hasattr(sh, a): setattr(sh, a, False)
    sc.display.render_aa = "OFF"
    try: sc.view_settings.view_transform = "Raw"
    except Exception: sc.view_settings.view_transform = "Standard"
    im = r.image_settings
    im.file_format = "OPEN_EXR"; im.color_mode = "RGBA"; im.color_depth = "32"
    try: im.exr_codec = "NONE"
    except Exception: pass
    r.filepath = TMP

def render_counts():
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(TMP, check_existing=False)
    a = np.empty(RX * RY * 4, np.float32); img.pixels.foreach_get(a); bpy.data.images.remove(img)
    a = a.reshape(-1, 4); m = a[:, 3] > 0.5
    rr, gg = a[m, 0] * 255.0, a[m, 1] * 255.0
    err = float(max(np.abs(rr - np.round(rr)).max(initial=0), np.abs(gg - np.round(gg)).max(initial=0), np.abs(a[m, 2] - 0.5).max(initial=0) * 255))
    ids = (np.round(rr) + 256 * np.round(gg)).astype(np.int64) - 1
    return np.bincount(ids[(ids >= 0) & (ids < len(ITEMS))], minlength=len(ITEMS)), err

# ---------- 1. ID renders ---------------------------------------------------------------------------
cnt_path = os.path.join(OUT, "vis_counts_%s.json" % UNIT)
tim = {"build_s": {}, "render_s": {}, "n_renders": 0}
if "skip_render" not in opt:
    counts, max_err, t_all = {}, 0.0, time.time()
    setup_id_render()
    for st in STATES:
        tb = time.time(); objs = build_state(st); tim["build_s"][st] = round(time.time() - tb, 2)
        for k, ob in objs.items(): ob.color = id_color(k)
        counts[st] = {}; tr = time.time()
        for c in CAMS:
            alone = c["cls"].startswith("component")      # component views: the component alone on its carrier
            for k, ob in objs.items():
                ob.hide_render = alone and hidden_alone(ITEMS[k])
            set_cam(c); n, e = render_counts(); max_err = max(max_err, e)
            counts[st][c["name"]] = {ITEMS[i]: int(v) for i, v in enumerate(n) if v}
        tim["render_s"][st] = round(time.time() - tr, 2); tim["n_renders"] += len(CAMS)
        print("VIS_STATE", st, "build", tim["build_s"][st], "render", tim["render_s"][st], "cams", len(CAMS), "max_decode_err", round(max_err, 4))
    tim["total_s"] = round(time.time() - t_all, 2); tim["per_render_s"] = round(sum(tim["render_s"].values()) / max(tim["n_renders"], 1), 3)
    tim["max_decode_err_255"] = round(max_err, 4); tim["res"] = [RX, RY]
    json.dump({"timing": tim, "export_timing": S["timing"], "counts": counts}, open(cnt_path, "w"))
D = json.load(open(cnt_path)); counts = D["counts"]; tim = D["timing"]

# ---------- 2. classification -------------------------------------------------------------------------
# Decision unit = one connected piece ("Teilstück", item part#nnnn) when its part has the same pieces and prim counts in
# every state where it exists (stable topology); otherwise the whole part. Parts are grouped by part_alias (regex).
from collections import defaultdict
alias = [(re.compile(k), v) for k, v in cfg.get("part_alias", {}).items()]
def base(it): return it[2:].split("#")[0]
def canon(b):
    for rx, v in alias:
        if rx.fullmatch(b): return v
    return b
PCS = S.get("prim_counts_state", {}); PC = S["prim_counts"]
sig = defaultdict(dict)
for st, d in PCS.items():
    tmp = defaultdict(set)
    for it, c in d.items(): tmp[base(it)].add((it, c))
    for p, s in tmp.items(): sig[p][st] = frozenset(s)
STABLE = {p: len(set(v.values())) == 1 for p, v in sig.items()}
def unit(it): return it[2:] if STABLE.get(base(it), True) else base(it)
ALLST = [s for s in S["states"] if s in counts]; FIRST = ALLST[0]
UPRIM, UFIRST = defaultdict(int), set()
for st in S["states"]:
    seen = set()
    for it, c in PCS.get(st, {}).items():
        u = unit(it); seen.add(u)
        if st == FIRST: UFIRST.add(u)
    for u in seen:
        if u not in UPRIM:
            UPRIM[u] = sum(c for it, c in PCS[st].items() if unit(it) == u)
UNITS = sorted(UPRIM); UPART = {u: canon(u.split("#")[0]) for u in UNITS}
PARTS = sorted(set(UPART.values()))
PPRIM = defaultdict(int); PPIECES = defaultdict(int)
for u in UFIRST: PPRIM[UPART[u]] += UPRIM[u]; PPIECES[UPART[u]] += 1
CLS = {c["name"]: c for c in S["cams"]}
def cloud_idx(n): return int(n.rsplit("_c", 1)[1])
AGG = {}                                     # (state, cam) -> (per unit px, per part px)
for st in ALLST:
    for cn, d in counts[st].items():
        au, ap = defaultdict(int), defaultdict(int)
        for it, v in d.items():
            if it.startswith("T:"):
                u = unit(it); au[u] += v; ap[UPART[u]] += v
        AGG[(st, cn)] = (au, ap)

def maxima(states, cls, cloud_n=None):
    bu, bp = defaultdict(lambda: (0, "", "")), defaultdict(lambda: (0, "", ""))
    for (st, cn), (au, ap) in AGG.items():
        c = CLS[cn]
        if st not in states or c["cls"] not in GROUP.get(cls, (cls,)) or (c["cls"] == "cloud" and cloud_n is not None and cloud_idx(cn) >= cloud_n): continue
        for u, v in au.items():
            if v > bu[u][0]: bu[u] = (v, cn, st)
        for p, v in ap.items():
            if v > bp[p][0]: bp[p] = (v, cn, st)
    return bu, bp

def tiers(thr, cloud_n, states):
    (hu, hp), (bu, bp), (cu, cp) = maxima(states, "hero"), maxima(states, "cloud", cloud_n), maxima(states, "control")
    # S = seen somewhere but below the threshold everywhere (too small to read), D = not one pixel anywhere (rule 7)
    t = lambda h, b, c: "A" if h > thr else "B" if b > thr else "C" if c > thr else "S" if max(h, b, c) > 0 else "D"
    tu = {u: t(hu[u][0], bu[u][0], cu[u][0]) for u in UNITS}
    tp = {p: t(hp[p][0], bp[p][0], cp[p][0]) for p in PARTS}
    return tu, tp, (hu, bu, cu), (hp, bp, cp)

THR, CN = int(cfg["threshold_main"]), max(cfg["cloud_sizes"])
TU, TP, MU, MP = tiers(THR, CN, ALLST)
VAR = {}
for thr in cfg["thresholds"]:
    for cn in cfg["cloud_sizes"]: VAR["thr%d_cloud%d" % (thr, cn)] = tiers(thr, cn, ALLST)[:2]
VAR["thr%d_cloud%d_%s_only" % (THR, CN, FIRST)] = tiers(THR, CN, [FIRST])[:2]
COMP = S.get("component")                    # component views (vis_views.py); None for a unit without them
if COMP:   # blind spots: read only in a random view, in no chosen view and no hero camera -> a view may be missing
    RU, _ = maxima(ALLST, "component_random")
    BLIND = sorted((u for u in UFIRST if RU[u][0] > THR and MU[0][u][0] <= THR), key=lambda u: -RU[u][0])
tot = sum(UPRIM[u] for u in UFIRST)
def piece_sum(tu):
    return {k: {"pieces": sum(1 for u in UFIRST if tu[u] == k), "prims": sum(UPRIM[u] for u in UFIRST if tu[u] == k)} for k in "ABCSD"}
def part_sum(tp):
    return {k: {"parts": sum(1 for p in PARTS if tp[p] == k and PPIECES[p]), "prims": sum(PPRIM[p] for p in PARTS if tp[p] == k)} for k in "ABCSD"}
never = [u for u in UFIRST if MU[0][u][0] == 0 and MU[1][u][0] == 0 and MU[2][u][0] == 0]
res = {"unit": UNIT, "threshold_px": THR, "cloud_n": CN, "res": [RX, RY], "states": ALLST, "first_state": FIRST,
       "total_prims_first_state": tot, "pieces_first_state": len(UFIRST),
       "summary_pieces": piece_sum(TU), "summary_parts": part_sum(TP),
       "never_any_pixel": {"pieces": len(never), "prims": sum(UPRIM[u] for u in never)},
       "variants": {k: {"pieces": piece_sum(v[0]), "parts": part_sum(v[1]),
                        "changed_pieces": sum(1 for u in UFIRST if v[0][u] != TU[u]),
                        "changed_prims": sum(UPRIM[u] for u in UFIRST if v[0][u] != TU[u]),
                        "changed_parts": sum(1 for p in PARTS if PPIECES[p] and v[1][p] != TP[p])} for k, v in VAR.items()},
       "unstable_parts_part_level": sorted(p for p, s in STABLE.items() if not s),
       "parts": {p: {"tier": TP[p], "prims": PPRIM[p], "pieces": PPIECES[p],
                     "px_hero": MP[0][p][0], "hero_at": "%s@%s" % MP[0][p][1:], "px_cloud": MP[1][p][0], "cloud_at": "%s@%s" % MP[1][p][1:],
                     "px_control": MP[2][p][0], "control_at": "%s@%s" % MP[2][p][1:],
                     "piece_prims": {k: sum(UPRIM[u] for u in UFIRST if UPART[u] == p and TU[u] == k) for k in "ABCSD"},
                     "piece_count": {k: sum(1 for u in UFIRST if UPART[u] == p and TU[u] == k) for k in "ABCSD"},
                     "variants": {k: v[1][p] for k, v in VAR.items()}} for p in PARTS},
       "pieces": {u: {"tier": TU[u], "prims": UPRIM[u], "first_state": u in UFIRST, "px": [MU[0][u][0], MU[1][u][0], MU[2][u][0]]} for u in UNITS},
       "timing": tim, "export_timing": D.get("export_timing")}
if COMP:
    res["component"] = COMP; res["blind_spots"] = [{"piece": u, "px_random": RU[u][0], "at": "%s@%s" % RU[u][1:]} for u in BLIND]
json.dump(res, open(os.path.join(OUT, "vis_%s.json" % UNIT), "w"), indent=0)
json.dump({"attribute": "vis_tier", "key": "part attribute + '#' + piece index (primitive connectivity, rank inside the part)",
           "pieces": {u: TU[u] for u in UNITS}, "parts": TP}, open(os.path.join(OUT, "vis_%s_tier_attr.json" % UNIT), "w"), indent=0)

L = ["# Sichtkarte %s (Pilot)" % UNIT, "",
     "Schwelle %d px bei %d×%d, Wolke %d Kameras je Hero (±%s°, ±%d %% Abstand), Zustände: %s. Pixel = Maximum über alle Kameras der Klasse und alle Zustände (Teil-Ebene: Summe aller Teilstücke im selben Bild)." % (
         THR, RX, RY, CN, cfg["cloud"]["ang_deg"], round(100 * cfg["cloud"]["dist_frac"]), ", ".join(ALLST)), "",
     "Stufe je Teil (ganzes Objekt) und je Teilstück (zusammenhängendes Stück, z. B. eine Öse). Prims = Polygone im Zustand %s." % FIRST, "",
     "| Teil | Prims | Stücke | Hero px | (wo) | Wolke px | (wo) | Kontrolle px | (wo) | Stufe Teil | Stücke A/B/C/S/D | Prims A/B/C/S/D (Stücke) | " + " | ".join(VAR) + " |",
     "|---|---:|---:|---:|---|---:|---|---:|---|:-:|---|---|" + "|".join([":-:"] * len(VAR)) + "|"]
for p in sorted(PARTS, key=lambda p: -PPRIM[p]):
    r = res["parts"][p]
    L.append("| %s | %d | %d | %d | %s | %d | %s | %d | %s | **%s** | %s | %s | %s |" % (p, r["prims"], r["pieces"], r["px_hero"], r["hero_at"], r["px_cloud"], r["cloud_at"],
             r["px_control"], r["control_at"], r["tier"], "/".join(str(r["piece_count"][k]) for k in "ABCSD"),
             "/".join(str(r["piece_prims"][k]) for k in "ABCSD"), " | ".join(r["variants"][k] for k in VAR)))
ps, pt = res["summary_pieces"], res["summary_parts"]
cdp = ps["C"]["prims"] + ps["S"]["prims"] + ps["D"]["prims"]; cdt = pt["C"]["prims"] + pt["S"]["prims"] + pt["D"]["prims"]
L += ["", "## Kennzahl", "",
      "| Stufe | Teile | Prims (Teil-Ebene) | Teilstücke | Prims (Stück-Ebene) | Anteil (Stück) |", "|---|---:|---:|---:|---:|---:|"]
for k in "ABCSD":
    L.append("| %s | %d | %d | %d | %d | %.1f %% |" % (k, pt[k]["parts"], pt[k]["prims"], ps[k]["pieces"], ps[k]["prims"], 100.0 * ps[k]["prims"] / max(tot, 1)))
L += ["", "**C + S + D, Stück-Ebene: %d von %d Teilstücken, %d von %d Prims (%.1f %%). Teil-Ebene: %d Prims (%.1f %%).** Nie ein einziges Pixel: %d Stücke / %d Prims." % (
          ps["C"]["pieces"] + ps["S"]["pieces"] + ps["D"]["pieces"], len(UFIRST), cdp, tot, 100.0 * cdp / max(tot, 1), cdt, 100.0 * cdt / max(tot, 1),
          res["never_any_pixel"]["pieces"], res["never_any_pixel"]["prims"]), "",
      "## Stabilität (Varianten gegen Hauptwerte)", "",
      "| Variante | Stück-Prims A/B/C/S/D | C+S+D Prims | Stücke anders | Prims anders | Teile anders |", "|---|---|---:|---:|---:|---:|"]
for k, v in res["variants"].items():
    L.append("| %s | %s | %d | %d | %d | %d |" % (k, "/".join(str(v["pieces"][x]["prims"]) for x in "ABCSD"), v["pieces"]["C"]["prims"] + v["pieces"]["S"]["prims"] + v["pieces"]["D"]["prims"],
             v["changed_pieces"], v["changed_prims"], v["changed_parts"]))
if COMP:
    L += ["", "## Component views – %s, rank %d" % (COMP["name"], COMP["rank"]), "",
          "Fills %d %% of the picture width (diameter %.2f m, distance %.1f m, %d° horizontal). **Readable size: %.3g m** – smaller details do not read here and are not built (rule 7). Views count like hero cameras for this component (A), random views like the cloud (B)." % (
              round(100 * COMP["fill"]), COMP["diameter_m"], COMP["distance_m"], COMP["hfov"], COMP["readable_m"]), "",
          "| View | az | el | Why |", "|---|---:|---:|---|"]
    L += ["| %s | %s | %s | %s |" % (v["name"], v["az"], v["el"], v["why"]) for v in COMP["views"]]
    L += ["", "Blind spots (read only in a random view, in no chosen view or hero camera): " +
          (", ".join("%s (%d px, %s)" % (b["piece"], b["px_random"], b["at"]) for b in res["blind_spots"][:12]) or "none") +
          (" – a view may be missing; propose one to the main chat." if BLIND else "")]
L +=["", "Teile mit wechselnder Topologie zwischen Zuständen (nur Teil-Ebene): " + ", ".join(res["unstable_parts_part_level"]), "",
      "## Laufzeit", "", "Export (hython): %s" % json.dumps(D.get("export_timing")), "", "Render (Blender Workbench): %s" % json.dumps(tim)]
with open(os.path.join(OUT, "%s_vis.md" % UNIT), "w", encoding="utf-8") as fh:   # name the gate hook checks (review/vis/<unit>_vis.md)
    fh.write("\n".join(L) + "\n")
print("VIS_SUMMARY pieces", json.dumps(ps), "parts", json.dumps(pt), "CD_piece_prims", cdp, "of", tot)

# ---------- 3. tier-coloured pictures -------------------------------------------------------------------
if "no_pics" in opt: sys.exit(0)
COL = {"A": (0.10, 0.65, 0.15, 1), "B": (0.95, 0.80, 0.05, 1), "C": (1.0, 0.45, 0.02, 1), "S": (0.60, 0.25, 0.75, 1), "D": (0.85, 0.05, 0.05, 1)}
pc = cfg.get("pictures", {})
def pic_setup():
    r = sc.render; r.film_transparent = False
    sh = sc.display.shading; sh.light = "STUDIO"; sh.color_type = "OBJECT"
    sc.display.render_aa = "8"; sc.view_settings.view_transform = "Standard"
    im = r.image_settings; im.file_format = "PNG"; im.color_mode = "RGB"; im.color_depth = "8"
HIDE_RX = [re.compile(x) for x in pc.get("overview_hide_parts", [])]
def paint(objs, hide_occ=False, hide_parts=False):
    for k, ob in objs.items():
        it = ITEMS[k]
        if it.startswith("T:"): ob.color = COL[TU[unit(it)]]; ob.hide_render = hide_parts and any(r.fullmatch(base(it)) for r in HIDE_RX)
        else: ob.color = (0.55, 0.55, 0.57, 1); ob.hide_render = hide_occ
def shot(c, fn):
    set_cam(c); sc.render.filepath = os.path.join(OUT, fn); bpy.ops.render.render(write_still=True); return fn
pics = []
setup_id_render(); pic_setup()   # same resolution and clean shading flags also with --skip_render
objs = build_state(FIRST); paint(objs)
heroes = sorted([c for c in S["cams"] if c["cls"] == "hero"], key=lambda c: -sum(AGG.get((FIRST, c["name"]), ({}, {}))[1].values()))
for c in heroes[:int(pc.get("heroes", 3))]: pics.append(shot(c, "pic_%s_%s_%s.png" % (UNIT, c["name"], FIRST)))
paint(objs, hide_occ=pc.get("overview_hide_occluders", True), hide_parts=True)
for ov in pc.get("overview", []):   # control cameras by name (the pilot used "CT"); unknown names are skipped
    if ov in CLS: pics.append(shot(CLS[ov], "pic_%s_overview_%s_%s.png" % (UNIT, ov, FIRST)))
    else: print("VIS_WARN overview camera not found:", ov)
bu = [u for u in UNITS if TU[u] == "B"]          # cloud view: where the B pieces with most prims peak
if bu:
    tally = defaultdict(int)
    for u in bu: tally[MU[1][u][1:]] += UPRIM[u]
    cn, st = max(tally, key=tally.get)
    if st != FIRST: objs = build_state(st)
    paint(objs); pics.append(shot(CLS[cn], "pic_%s_cloud_%s_%s.png" % (UNIT, cn, st)))
if COMP:   # one picture per chosen view (the ones QC reads), component alone on its carrier; random views get none
    objs = build_state(FIRST); paint(objs)
    for k, ob in objs.items():
        ob.hide_render = hidden_alone(ITEMS[k])
    for c in [c for c in S["cams"] if c["cls"] == "component"]:
        pics.append(shot(c, "pic_%s_view_%s_%s.png" % (UNIT, c["name"], FIRST)))
print("VIS_PICS", pics)

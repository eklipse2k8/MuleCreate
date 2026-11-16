"""Shots in the export (prototype): shot cameras as USD with time samples and the
"Shots" part of the Sketch Brief (brief.md, brief.json, images from the cameras, boards of the shot notes).

Camera interpolation (export dialog): "step" = stepped, exactly like Mule (each pose holds until one frame before the
next - which takes an extra time sample); "linear" = linear between the poses of a camera (position and
focal length), rotation as a quaternion (cleanly interpolated). Smoothing is done afterwards in Blender/Houdini.
"""
import os
import re

import numpy as np

from . import timing
from .camera import _mat_to_quat

INTERPS = ("step", "linear")
IMAGES_PER_CAMERA = 24  # at most this many images per camera in the brief
SENSOR_H = timing.SENSOR_W / timing.GATE


def has_timing(scene):
    """Does anything happen in Shots at all? Only then is there a Shots part in the brief: a camera, a flipbook drawing
    or a shot note with content on the board. Empty notes and unpainted flipbook planes do not count."""
    t = scene.timing
    if t.cams or any(_note_matters(n) for n in t.all_notes()):
        return True
    planes = {p.id for p in timing.flipbook_planes(scene)}
    return any(c.frame is not None and c.plane_id in planes for s in scene.strokes for c in s.curves)


def _note_matters(n):
    """Shot note with content (something on the board) - empty notes stay out of the brief."""
    return bool(n.board.get("items"))


def note_text(n):
    """Texts on the board of a note (in board order)."""
    return "\n\n".join(it["text"].strip() for it in n.board.get("items", []) if it.get("kind") == "text"
                       and it.get("text", "").strip())


def has_cameras(scene):
    return bool(scene.timing.cameras())


def _slug(text):
    s = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_")
    return s or "x"


def cam_ids(scene):
    """{camera id: prim/file name} - stable in note order, unambiguous (e.g. S1_Kamera_1, G_Kamera_2)."""
    out, used = {}, set()
    tm = scene.timing
    for k, note in enumerate(tm.all_notes()):
        prefix = "G" if note is tm.global_note else f"S{k}"
        for cam in tm.cams_of(note):
            name = f"{prefix}_{_slug(cam.name)}"
            while name in used:
                name += "_"
            used.add(name)
            out[cam.id] = name
    return out


def _eye(pose):
    return np.asarray(pose.target, float) + float(pose.dist) * np.asarray(pose.rot, float)[:, 2]


def _samples(cam, interp, end):
    """[(frame, pose)] of the time samples: stepped, each pose holds until one frame before the next."""
    out = []
    for k, pose in enumerate(cam.poses):
        out.append((pose.frame, pose))
        nxt = cam.poses[k + 1].frame if k + 1 < len(cam.poses) else None
        if interp == "step" and nxt is not None and nxt - 1 > pose.frame:
            out.append((nxt - 1, pose))
    return out


# --- USD ---------------------------------------------------------------------
def usd_header(scene):
    """Lines for the header of the USD layer (time range, fps) - only with timing cameras."""
    if not has_cameras(scene):
        return []
    t = scene.timing
    return [f"    startTimeCode = {t.start}", f"    endTimeCode = {t.end}", f"    timeCodesPerSecond = {t.fps}",
            f"    framesPerSecond = {t.fps}"]


def usd_lines(scene, depth, interp="step"):
    """Scope "shots" with all shot cameras: translate/orient/focalLength as time samples (USD: camera looks along -Z)."""
    tm = scene.timing
    cams = tm.cameras()
    if not cams:
        return []
    interp = interp if interp in INTERPS else "step"
    pad = "    " * depth
    names = cam_ids(scene)
    o = [f'{pad}def Scope "shots" (', f'{pad}    doc = "Mule Shot-Kameras: {interp}"', f"{pad})", f"{pad}{{"]
    for note, cam in cams:
        samples = _samples(cam, interp, tm.end)
        quats, prev = [], None
        for _, pose in samples:
            q = _mat_to_quat(np.asarray(pose.rot, float))
            if prev is not None and float(q @ prev) < 0:  # same hemisphere: interpolation takes the short way
                q = -q
            quats.append(q)
            prev = q

        def ts(values):
            return "{" + ", ".join(f"{f}: {v}" for (f, _), v in zip(samples, values)) + "}"
        eyes = [f"({', '.join(f'{x:.6g}' for x in _eye(p))})" for _, p in samples]
        orient = [f"({', '.join(f'{x:.7g}' for x in q)})" for q in quats]
        focal = [f"{p.mm:.4f}" for _, p in samples]
        o += [f'{pad}    def Camera "{names[cam.id]}"', f"{pad}    {{",
              f"{pad}        double3 xformOp:translate.timeSamples = {ts(eyes)}",
              f"{pad}        quatf xformOp:orient.timeSamples = {ts(orient)}",
              f'{pad}        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:orient"]',
              f"{pad}        float focalLength.timeSamples = {ts(focal)}",
              f"{pad}        float horizontalAperture = {timing.SENSOR_W:.4f}",
              f"{pad}        float verticalAperture = {SENSOR_H:.4f}",
              f'{pad}        string primvars:sketch_name = "{_esc(cam.name)}" (interpolation = "constant")',
              f'{pad}        string primvars:sketch_note = "{_esc(note.title)}" (interpolation = "constant")',
              f'{pad}        string primvars:sketch_interpolation = "{interp}" (interpolation = "constant")',
              f"{pad}    }}"]
    o.append(f"{pad}}}")
    return o


def _esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


# --- Brief -------------------------------------------------------------------
def brief_data(scene, interp="step", images=None, boards=None):
    """Shots for brief.json: range, shot notes with their cameras and poses, flipbook planes and their drawings.
    images: {camera id: [(frame, file)]} from render_images; boards: {note id: file} (board as image)."""
    tm = scene.timing
    names = cam_ids(scene)
    keys = timing.flip_keys(scene)
    planes = {p.id: p for p in timing.flipbook_planes(scene)}
    filled = {}
    for s in scene.strokes:
        for c in s.curves:
            if c.frame is not None and c.plane_id in planes:
                filled.setdefault(c.plane_id, set()).add(int(c.frame))
    images = images or {}

    def cam(c):
        poses = []
        for k, p in enumerate(c.poses):
            nxt = c.poses[k + 1].frame - 1 if k + 1 < len(c.poses) else tm.end
            poses.append({"frame": p.frame, "holds_until": nxt, "focal_mm": round(float(p.mm), 2),
                          "eye": [round(float(x), 4) for x in _eye(p)],
                          "target": [round(float(x), 4) for x in p.target]})
        return {"name": c.name, "usd": f"/sketch/shots/{names[c.id]}", "move": timing.is_move(c),
                "color": [round(float(x), 3) for x in c.rgb], "poses": poses,
                "images": [{"frame": f, "file": path} for f, path in images.get(c.id, [])]}

    boards = boards or {}

    def note(n, nid):
        return {"id": nid, "title": n.title, "text": note_text(n),
                "layers": [p.name for p in timing.note_layers(scene, n)],
                "cameras": [cam(c) for c in tm.cams_of(n)],
                **({"board": boards[n.id]} if n.id in boards else {})}

    return {"frames": [tm.start, tm.end], "fps": tm.fps, "camera_interpolation": interp,
            "global": note(tm.global_note, "SG"),
            "notes": [note(n, f"S{k}") for k, n in enumerate(tm.notes, 1) if _note_matters(n)],
            # only planes with drawings; empty drawings only after the first (before that the plane is empty anyway)
            "layers": [{"name": p.name, "drawings": sorted(filled[pid]),
                        "empty": [f for f in keys.get(pid, []) if f not in filled[pid] and f > min(filled[pid])]}
                       for pid, p in planes.items() if filled.get(pid)]}


def _image_frames(scene, note, cam):
    """Frames for the images of a camera: its poses and the drawing changes of the planes of its note (without
    planes: of all) - shows what happens when. At most IMAGES_PER_CAMERA, thinned out evenly."""
    tm = scene.timing
    lo, hi = tm.start, tm.end
    keys = timing.flip_keys(scene)
    layers = [p.id for p in timing.note_layers(scene, note)] or list(keys)
    frames = {p.frame for p in cam.poses if lo <= p.frame <= hi} | {f for pid in layers for f in keys.get(pid, [])
                                                                  if lo <= f <= hi}
    frames = sorted(frames) or [max(lo, cam.poses[0].frame)]
    if len(frames) > IMAGES_PER_CAMERA:
        idx = np.linspace(0, len(frames) - 1, IMAGES_PER_CAMERA).round().astype(int)
        frames = [frames[i] for i in sorted(set(idx))]
    return frames


def render_images(scene, viewport, folder):
    """Images through each shot camera (fresh, drawing state of the respective frame) into folder/shots/ ->
    ({camera id: [(frame, relative file)]}, [written files])."""
    if viewport is None or not has_cameras(scene):
        return {}, []
    names = cam_ids(scene)
    out_dir = os.path.join(folder, "shots")
    os.makedirs(out_dir, exist_ok=True)
    images, written = {}, []
    for note, cam in scene.timing.cameras():
        for f in _image_frames(scene, note, cam):
            rel = f"shots/{names[cam.id]}_F{f}.jpg"
            with open(os.path.join(folder, rel), "wb") as fh:
                fh.write(viewport.camera_jpeg(cam, f))
            images.setdefault(cam.id, []).append((f, rel))
            written.append(rel)
    return images, written


def render_boards(scene, folder):
    """Boards of the shot notes with content as an image into folder/shots/ (images, painting, text - this is how the AI sees
    the references and annotations) -> ({note id: relative file}, [written files]). Needs a Qt application."""
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        return {}, []
    from .note_board import render_board
    out, written = {}, []
    tm = scene.timing
    for k, n in enumerate(tm.all_notes()):
        if not _note_matters(n):
            continue
        img = render_board(scene, n.board)
        if img is None:
            continue
        rel = f"shots/{'SG' if n is tm.global_note else f'S{k}'}_board.jpg"
        os.makedirs(os.path.join(folder, "shots"), exist_ok=True)
        img.save(os.path.join(folder, rel), "JPG", 88)
        out[n.id] = rel
        written.append(rel)
    return out, written


def markdown(t):
    """"Shots" section for brief.md from brief_data."""
    if not t:
        return []
    interp = {"step": "stepped – each position holds until the next, exactly as the artist saw it in Mule",
              "linear": "linear between the positions of a camera (smooth it as the notes say)"}[t["camera_interpolation"]]
    md = ["## Shots – what happens when",
          f"Frames {t['frames'][0]}–{t['frames'][1]} at {t['fps']} fps. Mule has no keyframe animation: a drawing "
          "holds until the next drawing of its layer, a camera position holds until the next position of that camera – "
          "nothing in between is interpolated. **What should happen in between is written in the shot notes**; the "
          "drawings are rough indications of size, shape and timing, not final shapes. Shot notes belong to flipbook "
          "layers, not to a time range. Cameras run in parallel over the whole range (no edit; a note may ask for one). "
          f"Shot cameras are in `scene.usd` under `/sketch/shots` (camera interpolation: {interp}); full data in "
          "`brief.json` → `shots`."]
    g = t["global"]
    if g["text"]:
        md += ["", "**What the animation is about (global shot note):**", "", "> " + g["text"].replace("\n", "\n> ")]
    for n in ([g] if g["cameras"] or g.get("board") else []) + t["notes"]:
        title = "Global shot note" if n is g else f"{n['id']} – {n['title'] or 'untitled'}"
        md += ["", f"### {title}"]
        if n is not g and n["text"]:
            md += ["> " + n["text"].replace("\n", "\n> ")]
        if n["layers"]:
            md.append("- layers: " + ", ".join(n["layers"]))
        if n.get("board"):
            md.append(f"- board (references, camera pictures, sketches): `{n['board']}`")
        for c in n["cameras"]:
            poses = "; ".join(f"F{p['frame']}–{p['holds_until']}: {p['focal_mm']:.0f} mm, eye {p['eye']}"
                              for p in c["poses"])
            kind = "camera move between its positions" if c["move"] else "static camera"
            md.append(f"- **{c['name']}** (`{c['usd']}`, {kind}): {poses}")
            if c["images"]:
                md.append("  - pictures: " + ", ".join(f"F{i['frame']} `{i['file']}`" for i in c["images"]))
    if t["layers"]:
        md += ["", "**Flipbook layers** (2D drawings on planes in space, changing over time):"]
        for lay in t["layers"]:
            parts = [f"drawings at {', '.join('F%d' % f for f in lay['drawings'])}" if lay["drawings"] else "no drawings"]
            if lay["empty"]:
                parts.append(f"empty from {', '.join('F%d' % f for f in lay['empty'])}")
            md.append(f"- {lay['name']}: " + "; ".join(parts))
    return md + [""]

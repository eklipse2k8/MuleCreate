"""Sketch Brief: Hero-Kameras (eigene oder drei Standardwinkel) als Bilder ohne Beschriftung und USD-Kameras,
Übersichten zusätzlich ohne Beschriftung in views/clean/."""
import json
import os
import tempfile

import numpy as np

from tests.harness import H, expected_failure
from tests.test_brief_inhalt import _scene
from sketch_machine import brief
from sketch_machine.scene import Scene


def _export(sc, h):
    folder = tempfile.mkdtemp()
    files = brief.export(sc, h.v, folder, "k")
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
    return folder, files, md, data


def test_standardwinkel_und_saubere_ansichten(h: H):
    sc = _scene(h)
    folder, files, md, data = _export(sc, h)
    heroes = [c["image"] for c in data["cameras"]]
    assert heroes == [f"views/{n}.png" for n, _ in brief.DEFAULT_HEROES] and all(c["default"] for c in data["cameras"])
    for f in heroes + [f"views/clean/{n}.png" for n, _, _ in brief.VIEWS]:
        assert f in files and os.path.isfile(os.path.join(folder, f)), f
    assert "views/back.png" in files, "Ansicht von hinten"
    from PySide6.QtGui import QImage
    front, persp = (QImage(os.path.join(folder, "views", f"{n}.png")) for n in ("front", "persp"))
    assert front.width() / front.height() > persp.width() / persp.height() + 0.3, "flache Szene: Front zugeschnitten"
    assert front.width() / front.height() <= brief.CROP_MAX_ASPECT + 0.05
    assert "## Hero cameras" in md and "Standard angles – the artist set none" in md
    assert "`views/clean/*.png`" in md and "- `views/clean/" not in md, "saubere Ansichten zusammengefasst"
    project = open(os.path.join(folder, "project.md"), encoding="utf-8").read()
    assert "the artist set none – the brief has standard angles" in project and "Propose hero cameras" in project


def _hero_shot(h, sc, name, ortho=False):
    """Screenshot im Brett der ersten Notiz, als Hero-Kamera markiert (breites Bild 2:1)."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    from sketch_machine.note_board import camera_view
    h.v.cam.set_state(np.array([10.0, 1.0, 1.0]), 30.0, h.v.cam.rot.copy())
    h.v.cam.ortho = ortho
    view = camera_view(h.v)
    h.v.cam.ortho = False
    img, buf = QImage(800, 400, QImage.Format_RGB32), QBuffer()
    img.fill(0x808080)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPG")
    sc.assets["shot.jpg"] = bytes(buf.data())
    sc.notes[0].board = {"items": [{"kind": "image", "x": 0, "y": 0, "scale": 1.0, "file": "shot.jpg", "view": view,
                                    "hero": True, "hero_name": name},
                                   {"kind": "image", "x": 0, "y": 500, "scale": 1.0, "file": "shot.jpg",
                                    "view": view}]}
    return view


def test_screenshot_als_hero_kamera_und_usd_kamera(h: H):
    from pxr import Usd, UsdGeom
    from PySide6.QtGui import QImage
    sc = _scene(h)
    view = _hero_shot(h, sc, "Flügel von vorn")
    base = tempfile.mkdtemp()
    again = Scene.from_dict(sc.to_dict(base), base)
    assert brief.board_heroes(again)[0]["name"] == "Flügel von vorn", "Haken und Name gespeichert"
    folder, files, md, data = _export(sc, h)
    cam = data["cameras"][0]
    assert len(data["cameras"]) == 1, "nur der markierte Screenshot – keine Standardwinkel"
    assert cam["image"] == "views/hero_fluegel_von_vorn.png" and not cam["default"] and cam["from"] == "Flügel"
    assert abs(cam["aspect"] - 2.0) < 0.01, "Seitenverhältnis des Screenshots"
    pic = QImage(os.path.join(folder, cam["image"]))
    assert abs(pic.width() / pic.height() - 2.0) < 0.02, (pic.width(), pic.height())
    assert "screenshots marked as hero camera" in md and "**Flügel von vorn** (from the board of „Flügel“)" in md
    stage = Usd.Stage.Open(os.path.join(folder, "scene.usd"))
    prim = stage.GetPrimAtPath("/sketch/cameras/hero_fluegel_von_vorn")
    assert prim.IsValid() and prim.IsA(UsdGeom.Camera)
    gf = UsdGeom.Camera(prim).GetCamera()
    target, dist, rot = np.array(view["target"]), view["dist"], np.array(view["rot"])
    assert np.allclose(np.array(gf.frustum.GetPosition()), target + dist * rot[:, 2], atol=1e-3)
    assert np.allclose(np.array(gf.frustum.ComputeViewDirection()), -rot[:, 2], atol=1e-3)
    assert abs(gf.GetFieldOfView(gf.FOVVertical) - cam["fov_vertical_deg"]) < 0.05
    assert abs(gf.aspectRatio - 2.0) < 0.01


@expected_failure("Knöpfe am Bild im Brett breiter als ein Viertel – rot seit mindestens v0.99.130, Ursache ungeklärt (12.11.)")
def test_hero_haken_im_brett(h: H):
    """Haken oben rechts am Screenshot: an = Hero-Kamera (Name gleich schreibbar), gespeichert in der Notiz."""
    from PySide6.QtCore import QRectF
    from tests.test_notizen import _close, _open_board
    from sketch_machine.note_board import ImageItem
    note, board = _open_board(h)
    try:
        board.add_snapshot()
        h.pump(0.05)
        shot = next(i for i in board.gscene.items() if isinstance(i, ImageItem))
        view = board.view
        assert view._hero_at(view._hero_rects(shot)[0].center()) is None or not shot.hero
        other = next(n for n in h.sc.notes if n.id != note.id) if len(h.sc.notes) > 1 else None
        if other is None:
            from sketch_machine.scene import Note
            other = Note("Andere", np.zeros(3))
            h.sc.notes.append(other)
        other.board = {"items": [{"kind": "image", "file": "x.jpg", "view": {}, "hero": True, "hero_name": "Hero 1"}]}
        view.toggle_hero(shot)
        assert shot.hero and view._hero_edit is not None, "an: Namensfeld offen"
        assert shot.hero_name == "Hero 2", "Vorgabe wiederholt keinen Namen aus einer anderen Notiz"
        view._hero_edit[1].setText("Hero 1")  # selbst getippt, gibt es schon in der anderen Notiz
        view._end_hero_edit()
        assert shot.hero_name == "Hero 1_1", "doppelter Name bekommt eine Nummer"
        view.edit_hero_name(shot)
        view._hero_edit[1].setText("Cockpit schräg")
        view._end_hero_edit()
        item = next(i for i in note.board["items"] if i.get("kind") == "image")
        assert item["hero"] and item["hero_name"] == "Cockpit schräg"
        shot.setSelected(False)
        view._hover_shot = None
        assert view._hero_at(view._hero_rects(shot)[0].center()) is None, "Haken nur bei Maus oder Auswahl"
        shot.setSelected(True)
        assert view._hero_at(view._hero_rects(shot)[1].center()) == ("name", shot)
        view.scale(0.2, 0.2)  # herausgezoomt: der Haken schrumpft mit dem Bild
        shown = view.mapFromScene(shot.sceneBoundingRect()).boundingRect().width()
        box = view._hero_rects(shot)[0]
        c, r = view._redo_center(shot)
        assert c.x() + r - box.left() <= 0.25 * shown + 1, "↻ und Haken zusammen höchstens ein Viertel der Bildbreite"
        rect = QRectF(view.mapFromScene(shot.sceneBoundingRect()).boundingRect())
        assert rect.contains(box) and rect.contains(c), "am Bild angepinnt"
        view.edit_hero_name(shot)
        h.pump(0.05)
        assert view._hero_edit[1].width() <= 0.3 * shown + 2, "Namensfeld im selben Maßstab"
        view._end_hero_edit()
        view.scale(5, 5)
        view.toggle_hero(shot)
        view._end_hero_edit()
        assert "hero" not in next(i for i in note.board["items"] if i.get("kind") == "image")
    finally:
        _close(h, board)


def test_look_vorstufe(h: H):
    """Paket F: „Look-Vorstufe“ angekreuzt – Abschnitt mit Ablauf (Prompt-OK, Varianten je Hero-Kamera nach gen/,
    nie Orthos, Auswahl vor dem Bauen, Rangfolge) und je Kamera Eingabe- und Ausgabedateien."""
    sc = _scene(h)
    sc.brief_task = {"parts": ["geometry", "look"]}
    folder, files, md, data = _export(sc, h)
    project = open(os.path.join(folder, "project.md"), encoding="utf-8").read()
    task = project[project.index("## Task"):project.index("## First round")]
    assert "**Look images first:** before anything is built" in task
    look = md[md.index("## Look images (before building)"):]
    assert "never orthographic views" in look and "the sketch geometry wins over the notes" in look
    assert "every hero camera above – input `views/<camera>.png` → `gen/<camera>_a.png`" in look
    heroes = md[md.index("## Hero cameras"):md.index("## Look images")]
    for name, _ in brief.DEFAULT_HEROES:
        assert f"`views/{name}.png`" in heroes and f"`{name}` – input" not in look, "Kameras nur einmal gelistet"
    assert "eye [" not in heroes and "looking at" not in heroes, "Kameradaten in scene.usd und brief.json"
    assert all("eye" in c and "fov_vertical_deg" in c for c in data["cameras"])
    assert brief.part_hints({"parts": ["look"]}, "rumpf", images=True) == []
    assert brief.part_hints({"parts": ["look"]}, "rumpf") != []
    sc.brief_task = {"parts": ["geometry"]}
    assert "## Look images" not in _export(sc, h)[2], "ohne Häkchen kein Abschnitt"


def test_doppelte_hero_namen_beim_laden(h: H):
    """Ältere Szenen mit doppelten Hero-Namen: beim Laden durchnummeriert (Brief und set_hero_prompt brauchen
    eindeutige Namen)."""
    sc = _scene(h)
    from sketch_machine.scene import Note
    sc.notes.append(Note("Zweite", np.zeros(3)))
    for note in sc.notes[-2:]:
        note.board = {"items": [{"kind": "image", "file": "x.jpg", "view": {}, "hero": True,
                                 "hero_name": "cockpit main"}]}
    base = tempfile.mkdtemp()
    again = Scene.from_dict(sc.to_dict(base), base)
    names = [i["hero_name"] for n in again.notes for i in n.board.get("items", []) if i.get("hero")]
    assert names == ["cockpit main", "cockpit main_1"], names


def test_export_raeumt_alten_export_auf(h: H):
    """Erneuter Export in denselben Ordner: alte Bilder (views/, notes/) weg, gen/ bleibt; ein Ordner ohne Brief wird
    nicht angefasst."""
    sc = _scene(h)
    folder = tempfile.mkdtemp()
    stray = os.path.join(folder, "views", "fremd.png")
    os.makedirs(os.path.dirname(stray))
    open(stray, "wb").write(b"x")
    brief.export(sc, h.v, folder, "k")
    assert os.path.isfile(stray), "ohne vorherigen Brief wird nichts gelöscht"
    old = os.path.join(folder, "views", "hero_alt.png")
    open(old, "wb").write(b"x")
    os.makedirs(os.path.join(folder, "gen"))
    keep = os.path.join(folder, "gen", "hero_1_high_a.png")
    open(keep, "wb").write(b"x")
    brief.export(sc, h.v, folder, "k")
    assert not os.path.exists(old) and not os.path.exists(stray), "Veraltetes aus dem alten Export ist weg"
    assert os.path.isfile(keep) and os.path.isfile(os.path.join(folder, "views", "front.png"))


def test_color_id_je_hero_kamera(h: H):
    """Color-ID: je Hero-Kamera ein Bild, jedes Mesh flach in eigener Farbe (gleich in allen Kameras), Kopien der
    Symmetrie in der Farbe des Originals, Legende Farbe -> Teil -> Notizen in brief.json."""
    from PySide6.QtGui import QImage
    from tests.test_brief_inhalt import _box
    from sketch_machine.scene import MeshObject
    sc = _scene(h)
    sc.meshes.append(MeshObject("Rumpf", "rumpf.usd", _box([-1, 0, -6], [1, 0.5, -4])))
    sym = sc.new_null("symmetry")
    sc.set_parent([next(n for n in sc.nulls if n.name == "Flügel")], sym)
    h.v._changed()

    def pixels(folder, data):
        out = {}
        for c in data["cameras"]:
            hero, ids = QImage(os.path.join(folder, c["image"])), QImage(os.path.join(folder, c["id_image"]))
            assert (ids.width(), ids.height()) == (hero.width(), hero.height()), "gleiche Größe wie das Hero-Bild"
            ids = ids.convertToFormat(QImage.Format_RGB888)
            arr = np.frombuffer(ids.constBits(), np.uint8).reshape(ids.height(), ids.bytesPerLine())[:, :ids.width() * 3]
            cols, n = np.unique(arr.reshape(-1, 3), axis=0, return_counts=True)
            out[c["id"]] = {"#%02x%02x%02x" % tuple(k): int(m) for k, m in zip(cols, n)}
        return out

    folder, files, md, data = _export(sc, h)
    legend = {e["part"]: e for e in data["id_colors"]}
    assert set(legend) == {"M1", "M2"} and legend["M1"]["color"] != legend["M2"]["color"]
    assert legend["M1"].get("notes") == ["N1"] and "notes" not in legend["M2"], "Notiz zeigt auf den Flügel"
    assert all(f"views/{c['id']}_ids.png" in files and c["id_parts"] == ["M1", "M2"] for c in data["cameras"])
    seen = pixels(folder, data)
    for counts in seen.values():
        assert set(counts) <= {"#000000", legend["M1"]["color"], legend["M2"]["color"]}, "nur Legendenfarben, kein AA"
    assert "**Color-ID**" in md and "· Color-ID `views/" in md
    sym.params["on"] = False  # ohne Kopie: deutlich weniger Flügel im Bild
    h.v._changed()
    folder2, _, _, data2 = _export(sc, h)
    alone = pixels(folder2, data2)
    wing = legend["M1"]["color"]
    # (die Standardwinkel rahmen nur die Originale – die Kopie ist nicht in jedem Winkel im Bild)
    assert any(seen[k][wing] > 1.3 * alone[k][wing] for k in seen), "gespiegelte Kopie in der Farbe des Originals"


def test_mcp_konfig_im_brief_ordner(h: H):
    """Brief-Ordner bekommt die MCP-Einträge des Repos (.mcp.json, .codex/config.toml) – Sketch Machine immer;
    was dort schon steht, bleibt, nur diese Server werden gesetzt."""
    import tomllib
    src, folder = tempfile.mkdtemp(), tempfile.mkdtemp()
    with open(os.path.join(src, ".mcp.json"), "w", encoding="utf-8") as fh:
        json.dump({"mcpServers": {"houdini_code": {"type": "http", "url": "http://127.0.0.1:8771/mcp"}}}, fh)
    os.makedirs(os.path.join(src, ".codex"))
    with open(os.path.join(src, ".codex", "config.toml"), "w", encoding="utf-8") as fh:
        fh.write('[mcp_servers.houdini_code]\nurl = "http://127.0.0.1:8771/mcp"\n')
    with open(os.path.join(folder, ".mcp.json"), "w", encoding="utf-8") as fh:  # schon da: eigener Eintrag
        json.dump({"mcpServers": {"eigen": {"command": "x.exe", "args": ["-v"]},
                                  "sketch_machine": {"type": "http", "url": "http://alt"}}}, fh)
    os.makedirs(os.path.join(folder, ".codex"))
    with open(os.path.join(folder, ".codex", "config.toml"), "w", encoding="utf-8") as fh:
        fh.write('model = "o"\n[mcp_servers.eigen]\ncommand = "x.exe"\nenv = { A = "1" }\n')
    assert brief.write_tool_config(folder, src) == [".mcp.json", ".codex/config.toml"]
    servers = json.load(open(os.path.join(folder, ".mcp.json"), encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"eigen", "houdini_code", "sketch_machine"}
    assert servers["sketch_machine"]["url"] == brief.SKETCH_MCP_URL and servers["eigen"]["args"] == ["-v"]
    toml = tomllib.load(open(os.path.join(folder, ".codex", "config.toml"), "rb"))
    assert toml["model"] == "o" and toml["mcp_servers"]["eigen"]["env"] == {"A": "1"}
    assert toml["mcp_servers"]["houdini_code"]["url"].endswith(":8771/mcp")
    assert toml["mcp_servers"]["sketch_machine"]["url"] == brief.SKETCH_MCP_URL
    from sketch_machine import mcp_server
    assert brief.SKETCH_MCP_URL == f"http://127.0.0.1:{mcp_server.PORT}/mcp"
    _, files, _, _ = _export(_scene(h), h)
    assert ".mcp.json" in files and ".codex/config.toml" in files, "jeder Export schreibt sie"

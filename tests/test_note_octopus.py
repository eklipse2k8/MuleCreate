"""Note octopus: arms from the anchor point of a note to further similar parts – drag (Shift) or add the
selection, visible only on the selected note (curved, magenta), saved, undo, in the Sketch Brief."""
import json
import os
import tempfile

import numpy as np
from PySide6.QtCore import QPointF, Qt

from tests.harness import H, expected_failure
from tests.test_material import _square
from sketch_machine import theme
from sketch_machine.scene import Note, NoteAnchor, NoteMember, Scene


def _octopus_scene(h: H):
    """Three panels side by side, one note points to the first."""
    h.new_scene()
    panels = [_square(h, y=0.0, x0=x0, size=2.0) for x0 in (-4.0, -1.0, 2.0)]
    for k, s in enumerate(panels, 1):
        s.name = f"Panel {k}"
    note = Note("Panel", np.array([-3.0, 1.2, 1.0]))
    note.anchors.append(NoteAnchor(np.array([-3.0, 0.0, 1.0])))
    h.sc.notes.append(note)
    h.v.set_notes_mode(True)
    h.v.ws.active_note = note.id
    h.camera([0.0, 0.0, 1.0], 11, [0.0, 0.9, 0.35])
    h.grab()
    return note, panels


def _magenta(img):
    """Number of pixels in the color of the octopus arms."""
    c = theme.OCTOPUS
    n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            p = img.pixelColor(x, y)
            if abs(p.red() - c.red()) < 40 and abs(p.green() - c.green()) < 40 and abs(p.blue() - c.blue()) < 40:
                n += 1
    return n


def _diff(a, b):
    """Mean color deviation of two images of the same size."""
    def arr(img):
        img = img.convertToFormat(img.Format.Format_RGB32)  # (hold the image until the data is copied)
        raw = np.frombuffer(bytes(img.constBits()), np.uint8)
        return raw.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return float(np.abs(arr(a).astype(int) - arr(b).astype(int)).mean())


def test_drag_arm_with_shift_undo_redo(h: H):
    """Shift+drag from the anchor point to another panel: arm attached (one undo step); without Shift the leader
    line is moved as before, the octopus is not extended."""
    note, panels = _octopus_scene(h)
    try:
        end = h.v.notes_tool._screen[note.id]["anchors"][0][1]
        h.stroke([end, h.scrf([0.0, 0.0, 1.0])], mods=Qt.ShiftModifier)
        assert not note.anchors[0].members, "anchor not clicked yet: Shift selects it first"
        assert h.v.ws.active_anchor == (note.id, 0)
        h.grab()
        h.stroke([end, h.scrf([0.0, 0.0, 1.0])], mods=Qt.ShiftModifier)
        members = note.anchors[0].members
        assert len(members) == 1 and members[0].obj_id == panels[1].id, [m.obj_id for m in members]
        assert members[0].curve_id is None and np.allclose(members[0].point, [0.0, 0.0, 1.0], atol=0.1)
        assert np.allclose(note.anchors[0].point, [-3.0, 0.0, 1.0]), "anchor stays where it was"
        h.grab()
        end = h.v.notes_tool._screen[note.id]["anchors"][0][1]
        h.stroke([end, h.scrf([0.0, 0.0, 1.0])], mods=Qt.ShiftModifier)
        assert len(note.anchors[0].members) == 1, "the same part only once"
        h.sc.undo()
        again = h.sc.notes[0]
        assert not again.anchors[0].members, "Ctrl+Z takes the arm back"
        h.sc.redo()
        assert len(h.sc.notes[0].anchors[0].members) == 1, "Ctrl+Y brings it back"
    finally:
        h.v.set_notes_mode(False)


@expected_failure("Anchor point of the octopus not magenta – red since at least v0.99.130, cause unknown (12.11.)")
def test_arms_only_on_selected_note_curved_magenta(h: H):
    """Arms appear only while the note is selected (Notes mode); the ring at the end is clickable, Del
    removes the arm."""
    note, panels = _octopus_scene(h)
    try:
        note.anchors[0].members += [NoteMember(panels[1].id, None, np.array([0.0, 0.0, 1.0])),
                                    NoteMember(panels[2].id, None, np.array([3.0, 0.0, 1.0]))]
        h.v._changed()
        dot = h.grab()
        assert not h.v.notes_tool._screen[note.id]["members"], "only note selected: no arms yet"
        assert 3 < _magenta(dot) < 60, ("anchor point with octopus magenta with ring", _magenta(dot))
        h.click(h.v.notes_tool._screen[note.id]["anchors"][0][1])
        assert h.v.ws.active_anchor == (note.id, 0)
        shown = h.grab()
        info = h.v.notes_tool._screen[note.id]
        assert len(info["members"]) == 2, info["members"]
        assert _magenta(shown) > _magenta(dot) + 20, "clicked: arms visible in magenta"
        h.v.ws.active_note = None
        h.v._changed()
        hidden = h.grab()
        assert not h.v.notes_tool._screen[note.id]["members"] and _magenta(hidden) < 3, "without a selection no arms"
        h.v.ws.active_note, h.v.ws.active_anchor = note.id, (note.id, 0)
        h.v._changed()
        h.grab()
        (ji, end), = [m for m in h.v.notes_tool._screen[note.id]["members"] if m[0] == (0, 1)]
        h.move(end)
        assert h.v.notes_tool.hover == ("member", note.id, (0, 1)), h.v.notes_tool.hover
        h.key(Qt.Key_Delete)
        assert [m.obj_id for m in h.sc.notes[0].anchors[0].members] == [panels[1].id], "Del on the ring: only this arm"
        assert h.sc.notes, "the note itself stays"
    finally:
        h.v.set_notes_mode(False)


def test_add_selection_to_octopus_and_save(h: H):
    """Selection (surfaces and a line) as arms in one step; end = the spot nearest to the anchor; saved
    and loaded with new ids."""
    note, panels = _octopus_scene(h)
    try:
        line = h.sc.strokes[-1].curves[0]
        h.v.ws.selection = [panels[1].id, panels[2].id]
        h.v.ws.edge_selection = [("line", h.sc.strokes[-1].id, line.id)]
        added = h.v.notes_tool.add_selection(note.id, 0)
        members = note.anchors[0].members
        assert added == 3 and len(members) == 3, [(m.obj_id, m.curve_id) for m in members]
        assert members[0].point[0] < 0.0, "end of the arm: spot of panel 2 nearest to the anchor (left edge)"
        assert members[2].curve_id == line.id and members[2].obj_id == h.sc.strokes[-1].id
        assert h.v.notes_tool.add_selection(note.id, 0) == 0, "nothing twice"
        path = os.path.join(tempfile.mkdtemp(), "krake.sketch.json")
        h.sc.save(path)
        loaded = Scene.load(path)[0]
        got = loaded.notes[0].anchors[0].members
        names = [loaded.object_by_id(m.obj_id).name for m in got]
        assert names == ["Panel 2", "Panel 3", h.sc.strokes[-1].name], names
        assert got[2].curve_id is not None and loaded.curve_by_id(got[2].curve_id) is not None, "line linked anew"
        h.sc.undo()
        assert not h.sc.notes[0].anchors[0].members, "add selection = one undo step"
    finally:
        h.v.ws.selection, h.v.ws.edge_selection = [], []
        h.v.set_notes_mode(False)


def test_brief_names_members_index_and_deleted(h: H):
    """Brief: anchor says "also meant", brief.json has members and the index part -> notes, the note image
    shows the members fainter than the anchor; the pre-check reports deleted members."""
    from sketch_machine import brief
    note, panels = _octopus_scene(h)
    try:
        note.anchors[0].members += [NoteMember(panels[1].id, None, np.array([0.0, 0.0, 1.0])),
                                    NoteMember(panels[2].id, None, np.array([3.0, 0.0, 1.0]))]
        folder = tempfile.mkdtemp()
        brief.export(h.sc, h.v, folder, "krake")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        a = data["notes"][0]["anchors"][0]
        assert a["target"]["name"] == "Panel 1", a.get("target")
        assert [m["name"] for m in a["members"]] == ["Panel 2", "Panel 3"], a.get("members")
        assert "also meant: " in md and "may be incomplete" in md, "anchor names its members"
        assert "„also meant“" in md.split("**Reading notes:**")[1][:2000], "reading aid explains the list"
        index = {e["name"]: e["notes"] for e in data["part_notes"]}
        assert index["Panel 1"] == [{"note": "N1", "anchor": 1, "via": "anchor"}], index
        assert index["Panel 3"] == [{"note": "N1", "anchor": 1, "via": "also meant"}], index
        assert os.path.isfile(os.path.join(folder, "views", "note_N1_1.png"))
        # highlighted fainter than the anchor, but visible
        h.v.set_notes_mode(False)
        h.camera([0.0, 0.0, 1.0], 11, [0.0, 0.9, 0.35])
        plain = h.v.clean_image()
        faint = h.v.clean_image(faint=[panels[2].id])
        strong = h.v.clean_image(select=[panels[2].id])
        assert 0 < _diff(plain, faint) < _diff(plain, strong), (_diff(plain, faint), _diff(plain, strong))
        # deleted: the pre-check reports it, the brief no longer names it
        h.sc.checkpoint()
        h.sc.surfaces.remove(panels[2])
        h.v._changed()
        data = brief.analyse(h.sc)
        points = brief.precheck(h.sc, data)["points"]
        assert any(("Notizkrake" in p and "Gelöschtes" in p) or "deleted" in p.lower() for p in points), points
        assert [m["name"] for m in data["notes"][0]["anchors"][0]["members"]] == ["Panel 2"]
        h.v.set_notes_mode(True)
        h.v.ws.active_note, h.v.ws.active_anchor = h.sc.notes[0].id, (h.sc.notes[0].id, 0)
        h.v._changed()
        h.grab()
        assert len(h.v.notes_tool._screen[note.id]["members"]) == 2, "deleted member stays visible, dashed"
    finally:
        h.v.set_notes_mode(False)


def test_selected_note_lights_up_connected_parts(h: H):
    """Selected note: part at the anchor strong, parts at the arms fainter in magenta; click on an anchor point:
    only its parts; click on the note or Esc: all again; without a selected note nothing."""
    note, panels = _octopus_scene(h)
    try:
        line = h.sc.strokes[-1].curves[0]
        note.anchors.append(NoteAnchor(np.array([0.0, 0.0, 0.5]), line.id, 0.5))
        note.anchors[0].members.append(NoteMember(panels[1].id, None, np.array([0.0, 0.0, 1.0])))
        h.v._changed()
        objs, lines = h.v._note_glow()
        assert objs == {panels[0].id: 1.0, panels[1].id: 0.5} and lines == {line.id: 1.0}, (objs, lines)
        lit = h.grab()
        h.v.ws.active_note = None
        h.v._changed()
        assert h.v._note_glow() == ({}, {}), "without a selected note nothing lights up"
        dark = h.grab()
        assert _diff(lit, dark) > 0.3, _diff(lit, dark)
        h.v.ws.active_note = note.id
        h.v._changed()
        h.grab()
        end = dict(h.v.notes_tool._screen[note.id]["anchors"])[0]
        h.click(end)
        assert h.v.ws.active_anchor == (note.id, 0), h.v.ws.active_anchor
        objs, lines = h.v._note_glow()
        assert objs == {panels[0].id: 1.0, panels[1].id: 0.5} and not lines, "only the parts of the clicked anchor"
        assert note.anchors[0].point[0] == -3.0, "click does not move the anchor"
        h.key(Qt.Key_Escape)
        assert h.v.ws.active_anchor is None and h.v.ws.active_note == note.id, "Esc: back to the whole note"
        assert h.v._note_glow()[1] == {line.id: 1.0}
    finally:
        h.v.set_notes_mode(False)


def test_shift_click_in_the_viewport_and_null_as_group(h: H):
    """Notes mode, note selected (one leader line): Shift+click on a part attaches it to the octopus, again
    removes it; Ctrl+Shift+click takes the null above it (one arm, everything in it lights up). "Add selection" with a
    null: also one arm; the brief names the group including its parts."""
    from sketch_machine import brief
    from sketch_machine.scene import NullObject
    note, panels = _octopus_scene(h)
    try:
        null = NullObject("Panels")
        h.sc.nulls.append(null)
        panels[1].parent = panels[2].parent = null.id
        h.v._changed()
        h.grab()
        h.click(h.scrf([0.0, 0.0, 1.0]), mods=Qt.ShiftModifier)
        assert [m.obj_id for m in note.anchors[0].members] == [panels[1].id], "Shift+click: part added"
        assert h.v.ws.active_note == note.id, "note stays selected"
        h.click(h.scrf([0.0, 0.0, 1.0]), mods=Qt.ShiftModifier)
        assert not note.anchors[0].members, "Shift+click again: removed again"
        h.click(h.scrf([-3.0, 0.0, 1.0]), mods=Qt.ShiftModifier)
        assert not note.anchors[0].members, "the part at the anchor itself is not added again"
        h.click(h.scrf([3.0, 0.0, 1.0]), mods=Qt.ShiftModifier | Qt.ControlModifier)
        assert [m.obj_id for m in note.anchors[0].members] == [null.id], "Ctrl+Shift+click: the whole null"
        objs, _ = h.v._note_glow()
        assert objs.get(panels[1].id) == 0.5 and objs.get(panels[2].id) == 0.5, objs
        data = brief.analyse(h.sc)
        (m,) = data["notes"][0]["anchors"][0]["members"]
        assert m["kind"] == "group" and len(m["parts"]) == 2, m
        index = {e["name"]: e["notes"] for e in data["part_notes"]}
        assert index["Panel 3"] == [{"note": "N1", "anchor": 1, "via": "also meant"}], index
        h.sc.undo()
        h.v.ws.selection = [null.id]
        assert h.v.notes_tool.add_selection(note.id, 0) == 1, "null in the selection: one arm"
        assert h.sc.notes[0].anchors[0].members[0].obj_id == null.id
    finally:
        h.v.ws.selection = []
        h.v.set_notes_mode(False)


def test_arms_occluded_pale(h: H):
    """Arms are occluded by surfaces like leader lines: the occluded piece stays pale in Notes mode."""
    note, panels = _octopus_scene(h)
    try:
        note.anchors[0].members.append(NoteMember(panels[2].id, None, np.array([3.0, 0.0, 1.0])))
        h.v.ws.active_anchor = (note.id, 0)
        h.v._changed()
        h.grab()
        seen = h.v.notes_tool.occlusion["_arms"][(note.id, 0, 0)]
        assert seen.all(), "free: fully visible"
        wall = _square(h, y=0.6, x0=-0.5, size=2.0)  # above the arm (camera looks from above)
        h.v.ws.active_note, h.v.ws.active_anchor = note.id, (note.id, 0)
        h.v._changed()
        h.grab()
        seen = h.v.notes_tool.occlusion["_arms"][(note.id, 0, 0)]
        assert seen.any() and not seen.all(), ("partly occluded", seen)
        assert len(h.v.notes_tool._screen[note.id]["members"]) == 1, "the arm stays clickable"
    finally:
        h.v.set_notes_mode(False)


def test_second_click_off_and_octopus_without_sign(h: H):
    """Clicking the clicked anchor point again hides the arms; if the note's sign lies behind
    the camera (close to the parts), the anchor point and arms of the clicked anchor stay visible; an arm whose
    end lies behind the camera does not disappear entirely."""
    note, panels = _octopus_scene(h)
    try:
        note.anchors[0].members.append(NoteMember(panels[1].id, None, np.array([0.0, 0.0, 1.0])))
        h.v._changed()
        h.grab()
        end = h.v.notes_tool._screen[note.id]["anchors"][0][1]
        h.click(end)
        h.grab()
        assert h.v.ws.active_anchor == (note.id, 0) and len(h.v.notes_tool._screen[note.id]["members"]) == 1
        h.click(end)
        h.grab()
        assert h.v.ws.active_anchor is None and not h.v.notes_tool._screen[note.id]["members"], "second click: off"
        assert h.v.ws.active_note == note.id, "the note stays selected"
        h.click(end)
        note.pos = h.v.cam.eye + h.v.cam.back * 2.0  # sign behind the camera
        h.v._changed()
        h.grab()
        info = h.v.notes_tool._screen.get(note.id)
        assert info is not None and len(info["members"]) == 1 and info["anchors"], info
        assert h.v.notes_tool.hit(info["anchors"][0][1])[0] == "anchor", "anchor point stays clickable"
        cam = h.v.cam
        samples = h.v.notes_tool.arm_samples(np.array([-3.0, 0.0, 1.0]), cam.eye + cam.back * 1.0)
        q, qok = h.v.project(samples)
        assert qok.sum() >= 2 and not qok[-1], "end behind the camera, start in front"
    finally:
        h.v.set_notes_mode(False)


def test_front_surface_beats_line_behind(h: H):
    """Shift+click (octopus) and new leader line on a surface with a line running behind it: the visible
    surface is hit, not the line behind. A line in front of the surface stays hittable."""
    from sketch_machine import network
    note, panels = _octopus_scene(h)
    try:
        sc = h.sc
        sc.new_stroke()
        sc.add_curve(np.linspace([-0.5, -1.0, 1.0], [2.5, -1.0, 1.0], 20), None)  # below panel 2
        behind = sc.curves[-1]
        sc.new_stroke()
        sc.add_curve(np.linspace([-0.5, 1.0, 0.4], [2.5, 1.0, 0.4], 20), None)  # above panel 2
        front = sc.curves[-1]
        network.sync(sc)
        for s in sc.strokes:
            s.parent = None
        h.v._changed()
        h.grab()
        tool = h.v.notes_tool
        pos = h.scrf([1.0, -1.0, 1.0])  # screen spot of the rear line – panel 2 lies in front of it
        assert h.v._curve_under(pos)[0] is behind, "without occlusion one would hit the line"
        target = tool._member_target(pos)
        assert target is not None and target.curve_id is None and target.obj_id == panels[1].id, target
        assert abs(target.point[1]) < 0.05, "the point lies on the surface"
        anchor = tool._anchor_target(pos)
        assert anchor.curve_id is None and abs(anchor.point[1]) < 0.05, "leader line: the surface too"
        target = tool._member_target(h.scrf([1.0, 1.0, 0.4]))
        assert target is not None and target.curve_id == front.id, "line in front stays hittable"
    finally:
        h.v.set_notes_mode(False)

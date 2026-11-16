"""MCP server: JSON-RPC over HTTP (initialize, tools/list, tools/call), tools in the main thread - read scene, view,
export, clarified points (stay in the scene and in every export), prompt on the hero camera."""
import base64
import json
import os
import tempfile
import threading
import time
import urllib.request

from tests.harness import H
from tests.test_brief_content import _scene
from tests.test_brief_cameras import _hero_shot
from sketch_machine import brief, mcp_server
from sketch_machine.scene import Scene


def _post(h, server, msg):
    """Request from a side thread (like Claude), the main thread works off the tools."""
    box = {}

    def run():
        req = urllib.request.Request(f"http://127.0.0.1:{server.port}/mcp", json.dumps(msg).encode(),
                                     {"Content-Type": "application/json",
                                      "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            box["status"], box["body"] = resp.status, json.loads(body) if body else None

    t = threading.Thread(target=run)
    t.start()
    end = time.monotonic() + 120
    while t.is_alive() and time.monotonic() < end:
        h.app.processEvents()
        time.sleep(0.005)
    t.join(1)
    return box


def _call(h, server, name, **args):
    r = _post(h, server, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name,
                                                                                       "arguments": args}})
    return r["body"]["result"]


def test_protocol_and_tools(h: H):
    _scene(h)
    h.w.last_brief = None  # the tests share the main window
    server = mcp_server.Server(h.w, port=0).start()
    try:
        r = _post(h, server, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                         "clientInfo": {"name": "t", "version": "1"}}})
        assert r["body"]["result"]["protocolVersion"] == "2025-06-18" and "tools" in r["body"]["result"]["capabilities"]
        assert _post(h, server, {"jsonrpc": "2.0", "method": "notifications/initialized"})["status"] == 202
        tools = _post(h, server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["body"]["result"]["tools"]
        assert [t["name"] for t in tools] == ["scene_brief", "render_view", "note_images", "video_frames", "image_captions",
                                              "set_image_captions", "export_brief", "write_clarified",
                                              "set_hero_prompt", "dictate_note", "review_read", "review_moment",
                                              "review_note", "review_notes", "insert_images", "edit_note"]
        text = _call(h, server, "scene_brief")["content"][0]["text"]
        assert "## Overview" in text and "Hero cameras: none" in text and "Last brief export: (none" in text
        img = _call(h, server, "render_view", view="persp")["content"][0]
        assert img["type"] == "image" and base64.b64decode(img["data"])[:4] == b"\x89PNG"
        bad = _call(h, server, "render_view", view="doesnotexist")
        assert bad["isError"] and "unknown view" in bad["content"][0]["text"]
        assert "## Views" not in text and "note_images" in text, "live: no empty view list, pointer to the tools"
        assert "board is empty" in _call(h, server, "note_images", note="N1")["content"][0]["text"]
        h.sc.notes[0].board = {"items": [{"kind": "text", "x": 0, "y": 0, "w": 200, "text": "Wing foldable"}]}
        r = _call(h, server, "note_images", note="wing")
        assert [c["type"] for c in r["content"]] == ["text", "image"] and r["content"][0]["text"].startswith("N1")
        r = _call(h, server, "note_images", note="N1", sections=True)["content"]
        assert [c["type"] for c in r] == ["text", "image", "text", "image"] and "`notes/board_N1_1.png`" in r[2]["text"], \
            "section images as in the export"
        assert "exist only in an exported brief folder" in text, "without an export the old hint stays"
        assert _call(h, server, "note_images", note="Nonexistent")["isError"]
    finally:
        server.stop()


def test_export_clarified_and_hero_prompt(h: H):
    sc = _scene(h)
    _hero_shot(h, sc, "Cockpit")
    sc.brief_task = {"parts": ["geometry", "look"]}
    server = mcp_server.Server(h.w, port=0).start()
    try:
        folder = os.path.join(tempfile.mkdtemp(), "k_brief")
        assert "Exported to" in _call(h, server, "export_brief", folder=folder)["content"][0]["text"]
        assert h.w.last_brief == folder and os.path.isfile(os.path.join(folder, "brief.md"))
        head = _call(h, server, "scene_brief")["content"][0]["text"].split("\n\n")[0]
        assert f"are the files of that export – open them in {folder}" in head, "blind test Glider 003: location of the pictures"
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        project = open(os.path.join(folder, "project.md"), encoding="utf-8").read()
        assert "the hero pictures `views/hero_*.png` (1)" in project, "number of pictures of the first round"
        live = _call(h, server, "scene_brief")["content"][0]["text"]
        assert "# Project document" in live and "Live from Mule (no export folder)" in live, "live with project part"
        r = _call(h, server, "write_clarified", summary="A wing.",
                  answers=[{"question": "Foldable?", "answer": "Yes"}, {"question": "Colour?", "answer": ""}])
        assert not r["isError"] and sc.brief_clarified["answers"] == [{"question": "Foldable?", "answer": "Yes"}]
        assert "- Foldable? → Yes" in open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        _call(h, server, "write_clarified", answers=[{"question": "foldable? ", "answer": "No, rigid"},
                                                     {"question": "Colour?", "answer": "Red"}])
        assert sc.brief_clarified == {"summary": "A wing.", "answers": [
            {"question": "foldable?", "answer": "No, rigid"}, {"question": "Colour?", "answer": "Red"}],
            "history": [{"question": "Foldable?", "answer": "Yes"}]}, \
            "added: same question replaced (old answer into the history), new one added, summary stays"
        _call(h, server, "write_clarified", answers=[], drop=["Colour?"])
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "No, rigid" in md and "Colour?" not in md and "- Foldable? → Yes" not in md
        hist = open(os.path.join(folder, "clarified_history.md"), encoding="utf-8").read()
        assert "- Foldable? → Yes" in hist and "- Colour? → Red" in hist, "what was taken out is in the history"
        assert not _call(h, server, "set_hero_prompt", hero="Cockpit", prompt="Glider, sunset, glossy")["isError"]
        assert _call(h, server, "set_hero_prompt", hero="Nonexistent", prompt="x")["isError"]
        _call(h, server, "export_brief", folder=folder)
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert md.count("## Clarified with the artist before export") == 1 and "No, rigid" in md, \
            "clarified points come back with every export"
        assert "prompt approved by the artist (use it, no need to ask again): Glider, sunset, glossy" in md
        base = tempfile.mkdtemp()
        again = Scene.from_dict(sc.to_dict(base), base)
        assert again.brief_clarified == sc.brief_clarified
        assert "Glider, sunset, glossy" in json.dumps(again.notes[0].board)
        assert "set_hero_prompt" in h.w.claude_prompt(folder) and folder in h.w.claude_prompt(folder)
    finally:
        server.stop()


def test_image_captions(h: H):
    """image_captions: reference images without a caption (screenshots excluded) with file name and image, page by page;
    set_image_captions stores, the brief shows them."""
    from tests.test_notes import _png
    sc = _scene(h)
    _hero_shot(h, sc, "Cockpit")
    items = sc.notes[0].board["items"]
    for k in range(9):
        sc.assets[f"ref{k}.png"] = _png(40, 30, 0x101010 * k)
        items.append({"kind": "image", "x": 600, "y": 100 * k, "scale": 1.0, "file": f"ref{k}.png"})
    server = mcp_server.Server(h.w, port=0).start()
    try:
        r = _call(h, server, "image_captions")["content"]
        assert r[0]["text"].startswith("Pictures 1–8 of 9 (call again with start=8")
        assert r[1]["text"].startswith("`notes/ref0.png` – on N1") and r[2]["type"] == "image"
        assert "shot.jpg" not in json.dumps(r), "screenshots need no caption"
        r = _call(h, server, "image_captions", start=8)["content"]
        assert r[0]["text"] == "Pictures 9–9 of 9:" and "ref8.png" in r[1]["text"]
        r = _call(h, server, "set_image_captions", captions=[{"file": "notes/ref0.png", "caption": "Pockets on the net"},
                                                             {"file": "nix.png", "caption": "x"}])
        assert "1 caption(s) stored" in r["content"][0]["text"] and "nix.png" in r["content"][0]["text"]
        assert "8 of 8" in _call(h, server, "image_captions")["content"][0]["text"]
        r = _call(h, server, "image_captions", note="N1", all=True)["content"]
        assert "of 10" in r[0]["text"] and "caption „Pockets on the net“" in json.dumps(r, ensure_ascii=False)
        assert "`notes/ref0.png` – „Pockets on the net“" in _call(h, server, "scene_brief")["content"][0]["text"]
        part = next(iter(brief.index(sc)[1]["sid"].values()))  # parts by id as in the brief
        r = _call(h, server, "set_image_captions", captions=[{"file": "notes/ref0.png", "caption": "Pockets on the net",
                                                              "parts": [part, "M99"]}])
        assert "Unknown or hidden part ids, left out: M99" in r["content"][0]["text"]
        r = _call(h, server, "image_captions", note="N1", all=True)["content"]
        assert f"caption „Pockets on the net“ → parts {part}" in json.dumps(r, ensure_ascii=False)
        assert f"„Pockets on the net“ → parts {part}" in _call(h, server, "scene_brief")["content"][0]["text"]
        assert _call(h, server, "image_captions", note="Nonexistent")["isError"]
    finally:
        server.stop()


def test_dictated_note(h: H):
    """dictate_note: cleaned-up text as a text block on the board (default: project note), with an arrow to an image
    that the brief reads like a painted arrow; covers nothing; one undo step; an open board shows it at once."""
    from PySide6.QtWidgets import QGraphicsScene
    from tests.test_notes import _png, _open_board, _close
    from sketch_machine import board_links
    from sketch_machine.note_board import StrokeItem, TextBlock, _populate
    sc = _scene(h)
    sc.assets["ref.png"] = _png(200, 100, 0x406080)
    sc.notes[0].board = {"items": [{"kind": "image", "x": 0, "y": 0, "scale": 1.0, "file": "ref.png"},
                                   {"kind": "text", "x": 280, "y": 0, "w": 200, "text": "Already there"}]}
    server = mcp_server.Server(h.w, port=0).start()
    try:
        r = _call(h, server, "dictate_note", text="Project: everything in grey")
        assert not r["isError"] and "project" in r["content"][0]["text"]
        assert sc.global_note.board["items"][-1]["text"] == "Project: everything in grey"
        r = _call(h, server, "dictate_note", note="N1", text="Hinge left\n- made of brass",
                  images=[{"file": "notes/ref.png", "at": [0.2, 0.5]}, {"file": "doesnotexist.png"}])
        assert not r["isError"] and "1 arrow" in r["content"][0]["text"] and "doesnotexist.png" in r["content"][0]["text"]
        g = QGraphicsScene()
        _populate(g, sc, sc.notes[0].board)
        texts = [i for i in g.items() if isinstance(i, TextBlock)]
        new = next(t for t in texts if t.toPlainText().startswith("Hinge"))
        old = next(t for t in texts if t.toPlainText() == "Already there")
        assert not new.sceneBoundingRect().intersects(old.sceneBoundingRect()), "covers nothing"
        links = [board_links.stroke_link(g, s) for s in g.items() if isinstance(s, StrokeItem)]
        links = [l for l in links if l is not None]
        assert len(links) == 1 and links[0]["kind"] == "link" and links[0]["source"] is new, links
        assert abs(links[0]["uv"][0] - 0.2) < 0.02 and abs(links[0]["uv"][1] - 0.5) < 0.02, links[0]["uv"]
        g.clear()
        h.sc.undo()
        assert not any(i.get("text", "").startswith("Hinge") for i in sc.notes[0].board["items"]), "one undo step"
        assert not any(i["kind"] == "stroke" for i in sc.notes[0].board["items"])
        note, board = _open_board(h)  # open board: enter it there (otherwise it would overwrite the note)
        try:
            r = _call(h, server, "dictate_note", text="Entered while open")
            assert not r["isError"] and "Entered while open" in [t.toPlainText() for t in board.gscene.items()
                                                                  if isinstance(t, TextBlock)]
            assert note.board["items"][-1]["text"] == "Entered while open", "by default: the open board"
        finally:
            _close(h, board)
        assert _call(h, server, "dictate_note", text="  ")["isError"]
    finally:
        server.stop()


def test_edit_note(h: H):
    """edit_note: replace a piece of text (unambiguous, otherwise error), heading, empty block disappears; one
    undo step; an open board shows it at once."""
    from tests.test_notes import _open_board, _close
    from sketch_machine.note_board import TextBlock
    sc = _scene(h)
    sc.notes[0].board = {"items": [{"kind": "text", "x": 0, "y": 0, "w": 200, "text": "Hinge left, made of brass"},
                                   {"kind": "text", "x": 0, "y": 90, "w": 200, "text": "Handle made of brass"},
                                   {"kind": "text", "x": 0, "y": 180, "w": 200, "text": "get rid of this"}]}
    server = mcp_server.Server(h.w, port=0).start()
    try:
        r = _call(h, server, "edit_note", note="N1", old="brass", new="steel")
        assert r["isError"] and "2 times" in r["content"][0]["text"], "ambiguous"
        assert _call(h, server, "edit_note", note="N1", old="doesnotexist", new="x")["isError"]
        r = _call(h, server, "edit_note", note="N1", old="left, made of brass", new="right, made of steel",
                  title="Flap")
        assert not r["isError"], r
        texts = [i["text"] for i in sc.notes[0].board["items"] if i["kind"] == "text"]
        assert texts == ["Hinge right, made of steel", "Handle made of brass", "get rid of this"], texts
        assert sc.notes[0].title == "Flap"
        h.sc.undo()
        assert sc.notes[0].board["items"][0]["text"] == "Hinge left, made of brass", "one undo step"
        assert _call(h, server, "edit_note", old="x")["isError"], "without an open board: name the note"
        note, board = _open_board(h)
        try:
            assert not _call(h, server, "dictate_note", text="Noted completely wrong")["isError"]
            r = _call(h, server, "edit_note", old="Noted completely wrong", new="")
            assert not r["isError"], r
            shown = [t.toPlainText() for t in board.gscene.items() if isinstance(t, TextBlock)]
            assert "Noted completely wrong" not in shown, shown
            assert not any("wrong" in i.get("text", "") for i in (note.board or {}).get("items", [])), "in the note too"
        finally:
            _close(h, board)
    finally:
        server.stop()

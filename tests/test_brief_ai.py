"""Clarified points with the artist (MCP write_clarified): clarified points land in the brief after the head, a second
write replaces them, merging adds instead of replacing."""
import json
import os
import tempfile


from tests.harness import H
from tests.test_brief_content import _scene
from sketch_machine import brief, brief_ai

RESULT = {"summary": "A glider with folding wings.\nSecond line.",
          "questions": [{"question": "Does the wing fold around the leading edge?", "why": "Changes the hinge.",
                         "ids": ["M1"]},
                        {"question": "What colour is the canopy?", "why": "Look.", "ids": []},
                        {"question": "How long is the landing gear?", "why": "Dimension missing.", "ids": []}],
          "contradictions": ["N1 says red, the painting is blue."]}


def _folder(h):
    sc = _scene(h)
    sc.brief_task = {"task": "Build wing"}
    folder = tempfile.mkdtemp()
    brief.export(sc, h.v, folder, "ki")
    return folder


def test_clarified_points_in_the_brief(h: H):
    folder = _folder(h)
    answers = [(RESULT["questions"][0]["question"], "Yes, around the leading edge"),
               (RESULT["questions"][1]["question"], "decide"), (RESULT["questions"][2]["question"], None)]
    assert brief_ai.write_clarified(folder, RESULT["summary"], answers)
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    sec = md.index(brief_ai.SECTION)
    assert md.index("`project.md`") < sec < md.index(brief.READ_SECTION), "after the head, before the reference material"
    assert not os.path.isfile(os.path.join(folder, brief.CORE_FILE)), "build brief (package v4) has no old core"
    assert "> A glider with folding wings.\n> Second line." in md
    assert "- Does the wing fold around the leading edge? → Yes, around the leading edge" in md
    assert "What colour is the canopy? → the artist leaves this to you" in md
    assert "landing gear" not in md, "ignored question is missing"
    data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
    assert len(data["clarified"]["answers"]) == 2
    brief_ai.write_clarified(folder, "New.", [])
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    assert md.count(brief_ai.SECTION) == 1 and "> New." in md and "leading edge" not in md, "second check replaces"
    assert brief.READ_SECTION in md and "## Overview" in md


def test_merging_clarified_and_removing_entirely(h: H):
    old = {"summary": "S", "answers": [{"question": "A?", "answer": "1"}]}
    was = [{"question": "A?", "answer": "1"}]
    assert brief_ai.merge_clarified(old, "", [("a? ", "2")]) == {
        "summary": "S", "answers": [{"question": "a?", "answer": "2"}], "history": was}, "replaced goes into the history"
    assert brief_ai.merge_clarified(old, "", [("A?", "1")]) == old, "same answer: no history"
    assert brief_ai.merge_clarified(old, "", [], drop=["A?"]) == {"summary": "S", "answers": [], "history": was}
    assert brief_ai.merge_clarified(old, "T", []) == {"summary": "T", "answers": was, "history": [
        {"question": "Earlier summary", "answer": "S"}]}
    assert brief_ai.merge_clarified({"answers": [], "history": was}, "", [("B?", "x")])["history"] == was
    assert brief_ai.merge_clarified({}, "", [], drop=["A?"]) == {}, "nothing: empty"
    folder = _folder(h)
    # history: only a reference in the core, in full in clarified_history.md
    brief_ai.write_clarified(folder, "S", [("B?", "2")], history=[("B?", "1"), ("Old correction?", "Edge rounder")])
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    hist = open(os.path.join(folder, brief_ai.HISTORY_FILE), encoding="utf-8").read()
    assert "- B? → 2" in md and "Edge rounder" not in md and "`clarified_history.md` (2)" in md
    assert "- B? → 1" in hist and "- Old correction? → Edge rounder" in hist
    assert len(json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))["clarified"]["history"]) == 2
    brief_ai.write_clarified(folder, "S", [("A?", "1")])
    assert not brief_ai.write_clarified(folder, "", [])
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    assert brief_ai.SECTION not in md and brief.READ_SECTION in md, "without content the section is dropped"
    assert "clarified" not in json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
    assert not os.path.isfile(os.path.join(folder, brief_ai.HISTORY_FILE)), "without history the file is dropped"

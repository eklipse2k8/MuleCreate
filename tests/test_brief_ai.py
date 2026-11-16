"""Geklärtes mit dem Künstler (MCP write_clarified): geklärte Punkte landen nach dem Kopf im Brief, ein zweites
Schreiben ersetzt sie, Zusammenführen ergänzt statt zu ersetzen."""
import json
import os
import tempfile


from tests.harness import H
from tests.test_brief_inhalt import _scene
from sketch_machine import brief, brief_ai

RESULT = {"summary": "Ein Segelflugzeug mit klappbaren Flügeln.\nZweite Zeile.",
          "questions": [{"question": "Klappt der Flügel um die Vorderkante?", "why": "Ändert das Gelenk.",
                         "ids": ["M1"]},
                        {"question": "Welche Farbe hat die Haube?", "why": "Look.", "ids": []},
                        {"question": "Wie lang ist das Fahrwerk?", "why": "Maß fehlt.", "ids": []}],
          "contradictions": ["N1 sagt rot, die Malerei ist blau."]}


def _folder(h):
    sc = _scene(h)
    sc.brief_task = {"task": "Flügel bauen"}
    folder = tempfile.mkdtemp()
    brief.export(sc, h.v, folder, "ki")
    return folder


def test_geklaerte_punkte_im_brief(h: H):
    folder = _folder(h)
    answers = [(RESULT["questions"][0]["question"], "Ja, um die Vorderkante"),
               (RESULT["questions"][1]["question"], "decide"), (RESULT["questions"][2]["question"], None)]
    assert brief_ai.write_clarified(folder, RESULT["summary"], answers)
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    sec = md.index(brief_ai.SECTION)
    assert md.index("`project.md`") < sec < md.index(brief.READ_SECTION), "nach dem Kopf, vor dem Nachschlagematerial"
    assert not os.path.isfile(os.path.join(folder, brief.CORE_FILE)), "Bau-Brief (Paket v4) hat keinen alten Kern"
    assert "> Ein Segelflugzeug mit klappbaren Flügeln.\n> Zweite Zeile." in md
    assert "- Klappt der Flügel um die Vorderkante? → Ja, um die Vorderkante" in md
    assert "Welche Farbe hat die Haube? → the artist leaves this to you" in md
    assert "Fahrwerk" not in md, "ignorierte Frage fehlt"
    data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
    assert len(data["clarified"]["answers"]) == 2
    brief_ai.write_clarified(folder, "Neu.", [])
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    assert md.count(brief_ai.SECTION) == 1 and "> Neu." in md and "Vorderkante" not in md, "zweiter Check ersetzt"
    assert brief.READ_SECTION in md and "## Overview" in md


def test_geklaertes_zusammenfuehren_und_ganz_entfernen(h: H):
    old = {"summary": "S", "answers": [{"question": "A?", "answer": "1"}]}
    was = [{"question": "A?", "answer": "1"}]
    assert brief_ai.merge_clarified(old, "", [("a? ", "2")]) == {
        "summary": "S", "answers": [{"question": "a?", "answer": "2"}], "history": was}, "Ersetztes in den Verlauf"
    assert brief_ai.merge_clarified(old, "", [("A?", "1")]) == old, "gleiche Antwort: kein Verlauf"
    assert brief_ai.merge_clarified(old, "", [], drop=["A?"]) == {"summary": "S", "answers": [], "history": was}
    assert brief_ai.merge_clarified(old, "T", []) == {"summary": "T", "answers": was, "history": [
        {"question": "Earlier summary", "answer": "S"}]}
    assert brief_ai.merge_clarified({"answers": [], "history": was}, "", [("B?", "x")])["history"] == was
    assert brief_ai.merge_clarified({}, "", [], drop=["A?"]) == {}, "nichts: leer"
    folder = _folder(h)
    # Verlauf: nur ein Verweis im Kern, ganz in clarified_history.md
    brief_ai.write_clarified(folder, "S", [("B?", "2")], history=[("B?", "1"), ("Alte Korrektur?", "Kante runder")])
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    hist = open(os.path.join(folder, brief_ai.HISTORY_FILE), encoding="utf-8").read()
    assert "- B? → 2" in md and "Kante runder" not in md and "`clarified_history.md` (2)" in md
    assert "- B? → 1" in hist and "- Alte Korrektur? → Kante runder" in hist
    assert len(json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))["clarified"]["history"]) == 2
    brief_ai.write_clarified(folder, "S", [("A?", "1")])
    assert not brief_ai.write_clarified(folder, "", [])
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    assert brief_ai.SECTION not in md and brief.READ_SECTION in md, "ohne Inhalt fällt der Abschnitt weg"
    assert "clarified" not in json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
    assert not os.path.isfile(os.path.join(folder, brief_ai.HISTORY_FILE)), "ohne Verlauf fällt die Datei weg"

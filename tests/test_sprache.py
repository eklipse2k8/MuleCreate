"""Sprache der Oberfläche: jeder tr()-Text hat eine englische Fassung, das Programm läuft auf Englisch ohne sichtbares Deutsch."""
import ast
import json
import os
import pathlib
import re
import subprocess
import sys

from tests.harness import H

ROOT = pathlib.Path(__file__).resolve().parent.parent
# wechselnde Fachbegriffe, die auf Englisch gleich heißen, stehen hier nicht: gesucht wird nur eindeutig Deutsches
GERMAN = re.compile(r"[äöüÄÖÜß]|\b(und|oder|nicht|Fläche|Flächen|Linie|Linien|Notiz|Notizen|Strg|Entf|Auswahl|Zeichnen|"
                    r"Ansicht|Datei|Hilfe|Löschen|Speichern|wählen|Ebene|Stift|Pinsel|Radierer)\b")
SCAN = r"""
import json, os, sys
sys.path.insert(0, os.getcwd())
from tests.harness import H
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget
h = H()
board = None
from tests.test_notizen import _open_board
note, board = _open_board(h)
found = set()
for w in h.app.allWidgets():
    for get in ("text", "toolTip", "windowTitle", "placeholderText", "title"):
        fn = getattr(w, get, None)
        if callable(fn):
            try:
                value = fn()
            except TypeError:
                continue
            if isinstance(value, str) and value:
                found.add(value)
    for a in w.actions():
        found.update(x for x in (a.text(), a.toolTip()) if x)
sys.stdout.write("@@" + json.dumps(sorted(found), ensure_ascii=False))
sys.stdout.flush()
os._exit(0)
"""


def test_jeder_text_hat_eine_englische_fassung(h: H):
    from sketch_machine.i18n_en import EN
    missing = []
    for path in (ROOT / "sketch_machine").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args \
                    and isinstance(node.args[0], ast.Constant):
                text = node.args[0].value
                if text not in EN:
                    missing.append(f"{path.name}:{node.lineno} {text[:60]}")
                elif set(re.findall(r"\{\d+", EN[text])) - set(re.findall(r"\{\d+", text)):
                    missing.append(f"{path.name}:{node.lineno} Platzhalter: {text[:60]}")
    assert not missing, "\n".join(missing[:30])


def test_auf_englisch_keine_deutsche_oberflaeche(h: H):
    env = dict(os.environ, MULE_LANG="en", PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-c", SCAN], cwd=ROOT, env=env, capture_output=True, encoding="utf-8", timeout=120)
    assert "@@" in done.stdout, done.stderr[-1500:]
    texts = json.loads(done.stdout.split("@@", 1)[1])
    assert len(texts) > 80, f"zu wenig Texte gefunden: {len(texts)}"
    german = [t for t in texts if GERMAN.search(t)]
    assert not german, "\n".join(x[:130] for x in german)


def test_standard_bleibt_deutsch(h: H):
    from sketch_machine import i18n
    if not os.environ.get("MULE_LANG"):
        assert i18n.LANG == "de"
        assert i18n.tr("Zeichnen") == "Zeichnen"
    assert i18n.EN["Zeichnen"] == "Draw"


def test_handbuch_gibt_es_zeile_fuer_zeile_auf_englisch(h: H):
    from sketch_machine import manual, manual_en
    assert len(manual.TABS) == len(manual_en.TABS)
    for (de, html_de), (en, html_en) in zip(manual.TABS, manual_en.TABS):
        for tag in ("<tr>", "<h2>"):
            assert html_de.count(tag) == html_en.count(tag), f"{de}/{en}: {tag} {html_de.count(tag)} != {html_en.count(tag)}"
        plain = re.sub(r"<[^>]+>", " ", html_en).replace("Sprache / Language", "")
        assert not GERMAN.search(plain), f"{en}: {GERMAN.search(plain)}"


def test_handbuch_oeffnet_beim_modus_auf_englisch(h: H):
    code = ("import os, sys; sys.path.insert(0, os.getcwd())\nfrom tests.harness import H\nh = H()\n"
            "from sketch_machine.manual import ManualWindow\nw = ManualWindow()\nfrom sketch_machine.i18n import tr\n"
            "w.open_at(tr('Notizen'))\nsys.stdout.write('@@' + w.tabs.tabText(w.tabs.currentIndex()) + '|' + w.windowTitle())\n"
            "sys.stdout.flush()\nos._exit(0)\n")
    env = dict(os.environ, MULE_LANG="en", PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, encoding="utf-8", timeout=120)
    assert "@@Notes|Mule Create – Manual" in done.stdout, done.stdout[-200:] + done.stderr[-800:]


def test_sprachmenue_waehlt_genau_eine_sprache(h: H):
    """Rückmeldung aus dem Studio: English anklicken setzte einen zweiten Haken, das Wegklicken von Deutsch speicherte
    wieder Deutsch. Jetzt genau ein Haken; was zuletzt gewählt wurde, gilt beim nächsten Start."""
    from sketch_machine import app as app_module, i18n
    window = h.v.window()
    view = next(a.menu() for a in window.menuBar().actions() if a.menu() and a.menu().actions()
                and any(x.menu() and x.menu().title() == "Sprache / Language" for x in a.menu().actions()))
    menu = next(x.menu() for x in view.actions() if x.menu() and x.menu().title() == "Sprache / Language")
    german, english = menu.actions()
    shown = []
    original = app_module.QMessageBox.information
    app_module.QMessageBox.information = lambda *a: shown.append(a)
    try:
        i18n.set_language("de")
        german.setChecked(True)
        english.trigger()
        assert english.isChecked() and not german.isChecked(), "genau ein Haken"
        assert i18n.saved_language() == "en" and len(shown) == 1, "gespeichert, Hinweis auf den Neustart"
        german.trigger()
        assert german.isChecked() and not english.isChecked()
        assert i18n.saved_language() == "de"
        english.trigger()
        assert i18n.saved_language() == "en", "die zuletzt gewählte gilt"
        if not os.environ.get("MULE_LANG"):
            assert i18n._load() == "en", "beim nächsten Start Englisch"
    finally:
        app_module.QMessageBox.information = original
        i18n.set_language("de")

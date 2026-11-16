"""AI handbook (AI_HANDBOOK.md) must not fall behind the program: every MCP tool and every key combination of the
in-app manual is named there, and nothing private or unfinished is left in it."""
import ast
import pathlib
import re

LEVEL = "core"

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOK = ROOT / "AI_HANDBOOK.md"


def _tool_names():
    """Names in mcp_server.TOOLS, read from the source (no import: the server pulls in Qt)."""
    tree = ast.parse((ROOT / "sketch_machine" / "mcp_server.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "TOOLS" for t in node.targets):
            return [ast.literal_eval(k_v[1]) for d in node.value.elts
                    for k_v in zip(d.keys, d.values) if ast.literal_eval(k_v[0]) == "name"]
    raise AssertionError("TOOLS not found in mcp_server.py")


def _text():
    return BOOK.read_text(encoding="utf-8")


def _flat(s):
    """`Ctrl + Shift + E`, `Ctrl+Shift+E` and `Ctrl`+`E` all become ctrl+shift+e."""
    return re.sub(r"[\s`]*\+[\s`]*", "+", s.lower())


def _combos():
    """Key combinations of the in-app manual: [Ctrl]+[E] → ctrl+e. Single keys are left out (too short to search)."""
    src = (ROOT / "sketch_machine" / "manual_en.py").read_text(encoding="utf-8")
    found = set()
    for m in re.finditer(r"\[[^\]\[]+\](?:\s*\+\s*\[[^\]\[]+\])+", src):
        keys = re.findall(r"\[([^\]]+)\]", m.group(0))
        if any(k in ("LMB", "MMB", "RMB") for k in keys):
            continue  # mouse gestures are described in words
        found.add("+".join(k.lower() for k in keys))
    return sorted(found)


def test_every_mcp_tool_is_in_the_handbook(h=None):
    text = _text()
    missing = [n for n in _tool_names() if f"`{n}`" not in text]
    assert not missing, f"MCP tools missing in AI_HANDBOOK.md (write them as `name`): {missing}"


def test_every_key_combination_is_in_the_handbook(h=None):
    text = _flat(_text())
    def named(c):
        return re.search(r"(?<![\w+])" + re.escape(c) + r"(?![\w+])", text)
    # the manual shortens "[Ctrl]+[C] · [V] · [D] · [Shift]+[D]": a later combo in the row keeps the Ctrl
    missing = [c for c in _combos() if not named(c) and not named("ctrl+" + c)]
    assert not missing, f"key combinations from manual_en.py missing in AI_HANDBOOK.md: {missing}"


def test_handbook_without_private_or_open_leftovers(h=None):
    text = _text()
    for pat, why in ((r"<!--\s*OPEN", "open-points block of a draft"), (r"\bFelix\b", "personal name"),
                     (r"[A-Za-z]:[\\/]+Users[\\/]", "absolute path of a machine")):
        assert not re.search(pat, text), f"AI_HANDBOOK.md contains a {why}"


def test_glossary_is_current(h=None):
    import importlib.util
    spec = importlib.util.spec_from_file_location("handbook_glossary", ROOT / "packaging" / "handbook_glossary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.glossary() in _text(), "UI glossary is out of date: run packaging/handbook_glossary.py"


def test_public_bible_only_technology_and_tools(h=None):
    """The public export cuts the bible by the workflow entries (the package handles those); every title in the list
    must still exist, otherwise the export aborts."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("public_export", ROOT / "packaging" / "public_export.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = (ROOT / "bible" / "sketch_machine_bible.md").read_text(encoding="utf-8")
    out = mod.public_bible(text)
    titles = [line[4:].strip() for line in out.splitlines() if line.startswith("### ")]
    assert not set(titles) & set(mod.BIBLE_PROCESS), "workflow entries are out"
    assert len(titles) >= 20 and "## Protocol" in out and mod.BIBLE_NOTE in out


def test_introduction_is_current(h=None):
    """Introduction (docs/INTRODUCTION.md, introduction.html, block at the top of the handbook) matches the pictures."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("handbook_intro", ROOT / "packaging" / "handbook_intro.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pics = mod.pictures()
    assert len(pics) >= 18, len(pics)
    for p in pics:
        assert (ROOT / "docs" / "handbook" / p["file"]).is_file(), f"Picture missing: {p['file']}"
    assert mod.handbook_block(pics) in _text(), "Block at the top of the handbook is outdated: packaging/handbook_intro.py"
    intro = (ROOT / "docs" / "INTRODUCTION.md").read_text(encoding="utf-8")
    assert intro == mod.introduction_md(pics), "docs/INTRODUCTION.md is outdated: packaging/handbook_intro.py"
    assert _text().index("View the introduction") < _text().index("## How to use this handbook"), "at the very top"

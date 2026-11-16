"""Test package as GitHub release: builds from the commit, not from the working folder, checks and uploads.
Run from the repo root: .venv/Scripts/python.exe packaging/release.py
Prerequisite: the current commit has its version tag and is pushed. Only what passes the self-test is uploaded.
With --alpha "Alpha 1": draft only (not public, not "latest"), with source package, ANLEITUNG and CHANGELOG.
With --public "Alpha 2": in the PUBLIC checkout (after packaging/public_sync.py): the same files as --alpha, published
as a pre-release with the public release text (PUBLIC_NOTES)."""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORK = os.path.join(ROOT, "dist", "_release")
LINUX_FILES = ("README.md", "LIESMICH.md", "AI_HANDBOOK.md", "docs", "LICENSE", "CONTRIBUTING.md", "ANLEITUNG.md", "GUIDE.md", "CHANGELOG.md", "bible", "packaging", "requirements.txt", "requirements-build.txt", "sketch_machine", "start.sh")  # Mule only, no tests and no Houdini MCP
DOCS = ("ANLEITUNG.md", "GUIDE.md", "AI_HANDBOOK.md", "CHANGELOG.md")  # sit in the Windows package next to Mule.exe
# Source package: everything tracked except measurement scripts (they point to private scenes) and the studio guide
SOURCE_EXCLUDE = ("bench", "packaging/LIESMICH_Studio.txt")
PUBLIC = sys.argv[sys.argv.index("--public") + 1] if "--public" in sys.argv else None
if PUBLIC:  # the public repository is English only: no German guide, an English file name for the source
    DOCS = tuple(d for d in DOCS if d != "ANLEITUNG.md")
SOURCE_ZIP = "Mule_Source.zip" if PUBLIC else "Mule_Quellcode.zip"
ALPHA = PUBLIC or (sys.argv[sys.argv.index("--alpha") + 1] if "--alpha" in sys.argv else None)
PUBLIC_NOTES = """<img src="https://raw.githubusercontent.com/felixbfx/MuleCreate/main/sketch_machine/assets/mule_icon.png" alt="Mule Create logo" width="96" align="right">

**Mule Create {name}** – sketch in 3D space with lines, add notes, pictures and spoken feedback, and export a Sketch Brief from which an AI (Claude Code, Codex, …) builds the object in Houdini or Blender. This is an alpha: expect bugs, and scene files may change between versions.

**Downloads**
- **Windows:** `Mule_Windows.zip` – unzip into a folder of its own and start `Mule.exe` in the `Mule` folder. No Python needed. The program is not signed yet: on the first start Windows SmartScreen warns – click "More info", then "Run anyway". The package passed its self-test in English and German.
- **Source / Linux:** `Mule_Source.zip` – run `./start.sh` (Linux) or `start.bat` (Windows). Linux is hardly tested.
- **Guides:** `GUIDE.md`, `CHANGELOG.md`; the introduction in pictures is in `docs/` and in the program (Help menu).
- **`AI_HANDBOOK.md`:** the complete reference, written for AI assistants. Give it to your AI and ask your questions about Mule.
- **Brief recipes:** [how Mule's own way of working is built, and why](https://github.com/felixbfx/MuleCreate/blob/main/docs/mule_default_recipe.md) · [swap it or write your own](https://github.com/felixbfx/MuleCreate/blob/main/docs/recipes.md).
- **Example scene:** [Example_Alpaca_Monowheel.zip](https://github.com/felixbfx/MuleCreate/releases/download/v0.99.255/Example_Alpaca_Monowheel.zip) – sketch and finished model (USD, with and without cargo) in one scene, free to use under CC BY 4.0.

Needs a graphics card with OpenGL 3.3. Bugs and ideas: please open an issue. Contact: mulecreate@gmail.com.

Mule Create is free software under the GNU GPL v3.0. The name "Mule Create" and the Mule logo are reserved.

**Changes**

{changes}"""


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, encoding="utf-8").stdout.strip()


def version():
    """Version tag of the current commit; aborts if the commit is not on GitHub."""
    tags = [t for t in git("tag", "--points-at", "HEAD").split() if t.startswith("v")]
    if not tags:
        sys.exit("The current commit has no version tag.")
    if not git("branch", "-r", "--contains", "HEAD"):
        sys.exit("The current commit has not been pushed yet.")
    if not git("ls-remote", "--tags", "origin", tags[0]):
        sys.exit(f"The tag {tags[0]} has not been pushed yet.")
    if subprocess.run(["gh", "release", "view", tags[0]], cwd=ROOT, capture_output=True).returncode == 0:
        sys.exit(f"The release {tags[0]} already exists.")
    return tags[0]


def export_source():
    """Exactly the state of the commit: uncommitted changes (e.g. to the bible) do not go into the package."""
    shutil.rmtree(WORK, ignore_errors=True)
    source = os.path.join(WORK, "quelle")
    os.makedirs(source)
    archive = os.path.join(WORK, "quelle.tar")
    git("archive", "--format=tar", "-o", archive, "HEAD")
    with tarfile.open(archive) as tar:
        tar.extractall(source, filter="data")
    return source


def build(source):
    subprocess.run([sys.executable, "-m", "PyInstaller", os.path.join(source, "packaging", "mule.spec"), "--noconfirm",
                    "--distpath", os.path.join(WORK, "dist"), "--workpath", os.path.join(WORK, "build")],
                   cwd=source, check=True)
    return os.path.join(WORK, "dist", "Mule")


def selftest(program):
    """In both languages, outside the project: the package has to run on its own."""
    for lang in ("de", "en"):
        result = os.path.join(WORK, f"selftest_{lang}.json")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"} | {"MULE_LANG": lang}
        exe = os.path.join(program, "Mule.exe" if os.name == "nt" else "Mule")
        code = subprocess.run([exe, "--selftest", result], cwd=WORK, env=env, timeout=300).returncode
        with open(result, encoding="utf-8") as fh:
            report = json.load(fh)
        if code != 0 or not report.get("ok"):
            sys.exit(f"Self-test {lang} failed (exit {code}): {result}")
        print(f"Self-test {lang}: {len(report['checks'])} ok", flush=True)


def pack(program, tag):
    out = os.path.join(WORK, "paket")
    os.makedirs(out)
    source = os.path.join(WORK, "quelle")
    # the public repo has no German guides (ANLEITUNG.md, LIESMICH.md, since v0.99.257): take what this repo has
    present = [n for n in DOCS if os.path.isfile(os.path.join(source, n))]
    for name in present + ["CONTRIBUTING.md"]:
        shutil.copy2(os.path.join(source, name), os.path.join(program, name))
    if os.path.isdir(os.path.join(source, "docs")):  # introduction with its pictures, next to the guides
        shutil.copytree(os.path.join(source, "docs"), os.path.join(program, "docs"), dirs_exist_ok=True)
    windows = shutil.make_archive(os.path.join(out, "Mule_Windows"), "zip", os.path.dirname(program), "Mule")
    if ALPHA:  # Source code instead of the Linux extract, plus guide and changelog as separate files
        linux = os.path.join(out, SOURCE_ZIP)
        git("archive", "--format=zip", "--prefix=Mule/", "-o", linux, "HEAD", "--", ".",
            *(f":(exclude){p}" for p in SOURCE_EXCLUDE))
        docs = [os.path.join(out, name) for name in present]
        for name, dst in zip(present, docs):
            shutil.copy2(os.path.join(source, name), dst)
        print(f"{tag}: Windows {os.path.getsize(windows) / 1e6:.0f} MB, Quellcode {os.path.getsize(linux) / 1e6:.1f} MB", flush=True)
        return [windows, linux, *docs]
    linux = os.path.join(out, "Mule_Linux.tar.gz")
    git("archive", "--format=tar.gz", "--prefix=Mule/", "-o", linux, "HEAD",
        *(p for p in LINUX_FILES if os.path.exists(os.path.join(source, p))))
    readme = os.path.join(out, "LIESMICH.txt")
    shutil.copy2(os.path.join(ROOT, "packaging", "LIESMICH_Studio.txt"), readme)
    print(f"{tag}: Windows {os.path.getsize(windows) / 1e6:.0f} MB, Linux {os.path.getsize(linux) / 1e6:.1f} MB", flush=True)
    return [windows, linux, readme]


def this_release_changes(path):
    """The newest section of CHANGELOG.md (the one at the top), without its heading."""
    text = open(path, encoding="utf-8").read()
    sections = text.split("\n## ")[1:]
    return sections[0].split("\n", 1)[1].strip() if sections else ""


def publish(tag, files):
    if PUBLIC:
        if os.path.exists(os.path.join(ROOT, "packaging", "LIESMICH_Studio.txt")):
            sys.exit("--public only in the public checkout (after packaging/public_sync.py), not in the private repo.")
        changes = this_release_changes(os.path.join(WORK, "quelle", "CHANGELOG.md"))
        for attempt in range(3):  # GitHub occasionally answers uploads with a 502
            # a regular release marked latest (2026-11-17): the README's one-click link
            # .../releases/latest/download/Mule_Windows.zip always gets the newest – "Alpha" is in the name
            done = subprocess.run(["gh", "release", "create", tag, *files, "--verify-tag", "--latest",
                                   "--title", f"Mule Create {PUBLIC} ({tag})",
                                   "--notes", PUBLIC_NOTES.format(name=PUBLIC, changes=changes)], cwd=ROOT)
            if done.returncode == 0:
                return
            time.sleep(30)
        sys.exit("Upload failed three times; check GitHub for a half-created release.")
    if ALPHA:
        changes = open(os.path.join(WORK, "quelle", "CHANGELOG.md"), encoding="utf-8").read().split("\n", 2)[2]
        notes = ("Draft, internal only – not public. Windows: unpack Mule_Windows.zip, start Mule.exe "
                 "(tested in the package). Source code for Linux and for rebuilding: Mule_Quellcode.zip. "
                 "Everything else is in GUIDE.md (German: ANLEITUNG.md); questions for your own AI: AI_HANDBOOK.md.\n\n"
                 + changes)
        done = subprocess.run(["gh", "release", "create", tag, *files, "--verify-tag", "--draft", "--latest=false",
                               "--title", f"Mule Create {ALPHA} ({tag})", "--notes", notes], cwd=ROOT)
        if done.returncode != 0:
            sys.exit("Upload failed; check GitHub for a half-created draft.")
        return
    notes = ("Test package, tested in the package itself (Windows). Linux: source code with start.sh, untested.\n\n"
             + git("log", "-1", "--format=%s"))
    for attempt in range(3):  # GitHub occasionally answers uploads with a 502
        done = subprocess.run(["gh", "release", "create", tag, *files, "--verify-tag", "--latest",
                               "--title", f"Mule Create {tag}", "--notes", notes], cwd=ROOT)
        if done.returncode == 0:
            return
        time.sleep(30)
    sys.exit("Upload failed three times; check GitHub for a half-created draft.")


if __name__ == "__main__":
    if PUBLIC and os.path.exists(os.path.join(ROOT, "packaging", "LIESMICH_Studio.txt")):
        sys.exit("--public only in the public checkout (after packaging/public_sync.py), not in the private repo.")
    tag = version()
    program = build(export_source())
    selftest(program)
    publish(tag, pack(program, tag))

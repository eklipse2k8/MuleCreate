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
ALPHA = PUBLIC or (sys.argv[sys.argv.index("--alpha") + 1] if "--alpha" in sys.argv else None)
PUBLIC_NOTES = """**Mule Create {name}** – sketch in 3D space with lines, add notes, pictures and spoken feedback, and export a Sketch Brief from which an AI (Claude Code, Codex, …) builds the object in Houdini or Blender. This is an alpha: expect bugs, and scene files may change between versions.

**Downloads**
- **Windows:** `Mule_Windows.zip` – unzip into a folder of its own and start `Mule.exe` in the `Mule` folder. No Python needed. The program is not signed yet: on the first start Windows SmartScreen warns – click "More info", then "Run anyway". The package passed its self-test in English and German.
- **Source / Linux:** `Mule_Quellcode.zip` – run `./start.sh` (Linux) or `start.bat` (Windows). Linux is hardly tested.
- **Guides:** `GUIDE.md` (English), `ANLEITUNG.md` (German), `CHANGELOG.md`.
- **`AI_HANDBOOK.md`:** the complete reference, written for AI assistants. Give it to your AI and ask your questions about Mule.

Needs a graphics card with OpenGL 3.3. Bugs and ideas: please open an issue. Contact: mulecreate@gmail.com.

---

**Deutsch:** Windows: `Mule_Windows.zip` entpacken und im Ordner `Mule` die `Mule.exe` starten (bei der SmartScreen-Warnung „Weitere Informationen“ → „Trotzdem ausführen“). Anleitung: `ANLEITUNG.md`. Fragen zu Mule beantwortet deine KI mit `AI_HANDBOOK.md`. Fehler und Ideen bitte als Issue.

Mule Create is free software under the GNU GPL v3.0. The name "Mule Create" and the Mule logo are reserved.

**Changes**

{changes}"""


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, encoding="utf-8").stdout.strip()


def version():
    """Version tag of the current commit; aborts if the commit is not on GitHub."""
    tags = [t for t in git("tag", "--points-at", "HEAD").split() if t.startswith("v")]
    if not tags:
        sys.exit("Der aktuelle Commit hat keinen Versions-Tag.")
    if not git("branch", "-r", "--contains", "HEAD"):
        sys.exit("Der aktuelle Commit ist noch nicht gepusht.")
    if not git("ls-remote", "--tags", "origin", tags[0]):
        sys.exit(f"Der Tag {tags[0]} ist noch nicht gepusht.")
    if subprocess.run(["gh", "release", "view", tags[0]], cwd=ROOT, capture_output=True).returncode == 0:
        sys.exit(f"Das Release {tags[0]} gibt es schon.")
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
            sys.exit(f"Selbsttest {lang} nicht bestanden (Exit {code}): {result}")
        print(f"Selbsttest {lang}: {len(report['checks'])} ok", flush=True)


def pack(program, tag):
    out = os.path.join(WORK, "paket")
    os.makedirs(out)
    source = os.path.join(WORK, "quelle")
    for name in DOCS + ("CONTRIBUTING.md",):
        shutil.copy2(os.path.join(source, name), os.path.join(program, name))
    if os.path.isdir(os.path.join(source, "docs")):  # introduction with its pictures, next to the guides
        shutil.copytree(os.path.join(source, "docs"), os.path.join(program, "docs"), dirs_exist_ok=True)
    windows = shutil.make_archive(os.path.join(out, "Mule_Windows"), "zip", os.path.dirname(program), "Mule")
    linux = os.path.join(out, "Mule_Linux.tar.gz")
    git("archive", "--format=tar.gz", "--prefix=Mule/", "-o", linux, "HEAD", *LINUX_FILES)
    if ALPHA:  # Source code instead of the Linux extract, plus guide and changelog as separate files
        os.remove(linux)
        linux = os.path.join(out, "Mule_Quellcode.zip")
        git("archive", "--format=zip", "--prefix=Mule/", "-o", linux, "HEAD", "--", ".",
            *(f":(exclude){p}" for p in SOURCE_EXCLUDE))
        docs = [os.path.join(out, name) for name in DOCS]
        for name, dst in zip(DOCS, docs):
            shutil.copy2(os.path.join(source, name), dst)
        print(f"{tag}: Windows {os.path.getsize(windows) / 1e6:.0f} MB, Quellcode {os.path.getsize(linux) / 1e6:.1f} MB", flush=True)
        return [windows, linux, *docs]
    readme = os.path.join(out, "LIESMICH.txt")
    shutil.copy2(os.path.join(ROOT, "packaging", "LIESMICH_Studio.txt"), readme)
    print(f"{tag}: Windows {os.path.getsize(windows) / 1e6:.0f} MB, Linux {os.path.getsize(linux) / 1e6:.1f} MB", flush=True)
    return [windows, linux, readme]


def publish(tag, files):
    if PUBLIC:
        if os.path.exists(os.path.join(ROOT, "packaging", "LIESMICH_Studio.txt")):
            sys.exit("--public only in the public checkout (after packaging/public_sync.py), not in the private repo.")
        changes = open(os.path.join(WORK, "quelle", "CHANGELOG.md"), encoding="utf-8").read().split("\n", 2)[2]
        for attempt in range(3):  # GitHub occasionally answers uploads with a 502
            done = subprocess.run(["gh", "release", "create", tag, *files, "--verify-tag", "--prerelease",
                                   "--title", f"Mule Create {PUBLIC} ({tag})",
                                   "--notes", PUBLIC_NOTES.format(name=PUBLIC, changes=changes)], cwd=ROOT)
            if done.returncode == 0:
                return
            time.sleep(30)
        sys.exit("Hochladen dreimal fehlgeschlagen; auf GitHub nach einem halben Release sehen.")
    if ALPHA:
        changes = open(os.path.join(WORK, "quelle", "CHANGELOG.md"), encoding="utf-8").read().split("\n", 2)[2]
        notes = ("Entwurf, nur intern – nicht öffentlich. Windows: Mule_Windows.zip entpacken, Mule.exe starten "
                 "(im Paket geprüft). Quellcode für Linux und zum Nachbauen: Mule_Quellcode.zip. "
                 "Alles Weitere in ANLEITUNG.md (English: GUIDE.md); Fragen an die eigene KI: AI_HANDBOOK.md.\n\n"
                 + changes)
        done = subprocess.run(["gh", "release", "create", tag, *files, "--verify-tag", "--draft", "--latest=false",
                               "--title", f"Mule Create {ALPHA} ({tag})", "--notes", notes], cwd=ROOT)
        if done.returncode != 0:
            sys.exit("Hochladen fehlgeschlagen; auf GitHub nach einem halben Entwurf sehen.")
        return
    notes = ("Testpaket, im Paket selbst geprüft (Windows). Linux: Quellcode mit start.sh, ungeprüft.\n\n"
             + git("log", "-1", "--format=%s"))
    for attempt in range(3):  # GitHub occasionally answers uploads with a 502
        done = subprocess.run(["gh", "release", "create", tag, *files, "--verify-tag", "--latest",
                               "--title", f"Mule Create {tag}", "--notes", notes], cwd=ROOT)
        if done.returncode == 0:
            return
        time.sleep(30)
    sys.exit("Hochladen dreimal fehlgeschlagen; auf GitHub nach einem halben Entwurf sehen.")


if __name__ == "__main__":
    if PUBLIC and os.path.exists(os.path.join(ROOT, "packaging", "LIESMICH_Studio.txt")):
        sys.exit("--public only in the public checkout (after packaging/public_sync.py), not in the private repo.")
    tag = version()
    program = build(export_source())
    selftest(program)
    publish(tag, pack(program, tag))

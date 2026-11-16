"""Clean state for the public repo: exports the current commit WITHOUT git history into a new folder and
makes the first commit there with a freely chosen author address. Uploads nothing and creates no repo on GitHub.

Call in the repo root (example):
    .venv/Scripts/python.exe packaging/public_export.py TARGETFOLDER --name "Your Name" --email new@address.example

What is included: only tracked files of the current commit (uncommitted things like scenes, Feedback/, .mcp.json,
_lokal_vor_sync/ stay out), without EXCLUDE. Afterwards the script looks for private traces (old e-mail, absolute
paths of this machine) and aborts if it finds any. The new folder gets name/email as local
git setting, so later commits carry the new address too.

Afterwards by hand: create an empty repo on GitHub, then in the target folder
    git remote add origin https://github.com/<konto>/<repo>.git
    git push -u origin main

Only for the very first state. Later updates of an existing public repo: packaging/public_sync.py.
"""
import argparse
import os
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Tracked, but not public: measurement scripts point to private scenes, the studio guide is internal
# Developer-only files and German documents: the public repository is English only (the German UI stays – it is a
# language of the program, not a document)
EXCLUDE = ("bench", "packaging/LIESMICH_Studio.txt", "bible/konzept_timing.md", "ANLEITUNG.md", "LIESMICH.md",
           "sketch_machine/brief_package/LIESMICH.md", "sketch_machine/brief_package/_claude/AENDERUNGEN_HOOKS.md",
           "sketch_machine/brief_package/tools/vis_map/PILOT_README_de.md")
BIBLE = os.path.join("bible", "sketch_machine_bible.md")
# Workflow bible in the public repo: technique and tool entries only. Entries about the build process (agents, reviewers,
# gates, the artist's intent) are superseded by the brief package (rules, roles, hooks) and stay in the private bible.
BIBLE_PROCESS = (
    "Strict reviewer that measures, and is told what the builder claims",
    "Fixed control cameras per unit, next to the hero cameras",
    "Connection checks written by the same script prove little",
    "Measure the reviewer against the artist's marks first",
    "Cleaning up can remove the appeal: compare with the previous version and the target",
    "Reviewer and role agent can agree and still be wrong about intent",
    "A sketch from the artist's own camera beats a description",
    "Compare side by side before correcting a drawn line",
    "Long autonomous runs drift away from the unit process – make every unit pass a gate with artefacts",
)
BIBLE_NOTE = ("This public copy starts with technique and tool entries. How a build runs (roles, reviews, gates) is set "
              "by the way-of-working package in each brief, not here.")
# Must not appear in the export (case-insensitive)
PRIVATE = (r"felix\.barthel96", r"web\.de", r"[a-z]:[/\\]+users[/\\]+felix", r"/home/fel[i]x")


def git(*args, cwd=ROOT, env=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, encoding="utf-8",
                          env=env).stdout.strip()


def export(target):
    """Tracked files of HEAD to target (without EXCLUDE)."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "stand.tar")
        git("archive", "--format=tar", "-o", archive, "HEAD", "--", ".", *(f":(exclude){p}" for p in EXCLUDE))
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter="data")


def public_bible(text):
    """Bible without the process entries (BIBLE_PROCESS), with a note under the title. Every title must exist.
    An already public bible (in the public repo itself) stays as it is."""
    if BIBLE_NOTE in text:
        return text
    head, sep, entries = text.partition("\n## Entries\n")
    parts = entries.split("\n### ")
    keep, found = [parts[0]], set()
    for part in parts[1:]:
        title = part.split("\n", 1)[0].strip()
        if title in BIBLE_PROCESS:
            found.add(title)
        else:
            keep.append(part)
    missing = set(BIBLE_PROCESS) - found
    if missing:
        raise SystemExit(f"Bible: entries not found (renamed?): {sorted(missing)}")
    title, rest = head.split("\n", 1)
    return title + "\n\n" + BIBLE_NOTE + "\n" + rest + sep + "\n### ".join(keep)


def private_hits(target):
    pattern = re.compile("|".join(PRIVATE), re.IGNORECASE)
    hits = []
    for base, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            path = os.path.join(base, f)
            try:
                with open(path, encoding="utf-8") as fh:
                    for no, line in enumerate(fh, 1):
                        if pattern.search(line):
                            hits.append(f"{os.path.relpath(path, target)}:{no}: {line.strip()[:120]}")
            except (UnicodeDecodeError, OSError):
                continue  # images, videos, binary files
    return hits


def clean_copy(target):
    """The public state of HEAD in target (existing, empty folder): export, public bible. Returns private hits."""
    export(target)
    path = os.path.join(target, BIBLE)
    with open(path, encoding="utf-8") as fh:
        text = public_bible(fh.read())
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return private_hits(target)


def head_version():
    """(short hash, version tag or None) of HEAD in this repo."""
    tags = [t for t in git("tag", "--points-at", "HEAD").split() if t.startswith("v")]
    return git("rev-parse", "--short", "HEAD"), (tags[0] if tags else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="new, empty folder (outside this repo)")
    ap.add_argument("--name", required=True, help="author name for the first commit")
    ap.add_argument("--email", required=True, help="author address for the first commit (the new, public one)")
    ap.add_argument("--message", default="Mule Create – first public version", help="text of the first commit")
    a = ap.parse_args()

    target = os.path.abspath(a.target)
    if os.path.commonpath([target, ROOT]) == ROOT:
        sys.exit("The target folder must not be inside the Mule repo.")
    if os.path.exists(target) and os.listdir(target):
        sys.exit(f"{target} is not empty.")
    if re.search("|".join(PRIVATE), a.email, re.IGNORECASE):
        sys.exit("That is the old address – give a new one for the public repo.")
    head, tag = head_version()
    tags = [tag] if tag else []

    os.makedirs(target, exist_ok=True)
    hits = clean_copy(target)
    if hits:
        print("Private traces found – nothing committed, please fix them in the Mule repo first:")
        print("\n".join(hits[:50]))
        sys.exit(1)

    git("init", "-b", "main", cwd=target)
    git("config", "user.name", a.name, cwd=target)
    git("config", "user.email", a.email, cwd=target)
    git("add", ".", cwd=target)  # wanted here: the folder contains only the clean export
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    git("commit", "-q", "-m", a.message, cwd=target, env=env)
    files = len(git("ls-files", cwd=target).splitlines())
    print(f"Done: {target}\n  {files} files from {head} {' '.join(tags)}, one commit by {a.name} <{a.email}>, "
          f"no remote.\n  Continue by hand: git remote add origin <URL> && git push -u origin main")


if __name__ == "__main__":
    main()

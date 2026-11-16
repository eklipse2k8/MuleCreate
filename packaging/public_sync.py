"""Update of the public repo: puts the public state of this repo's HEAD (as packaging/public_export.py builds it:
without EXCLUDE, public bible, checked for private traces) as one normal new commit into the existing public
checkout, with the version tag of HEAD. The public history stays; nothing of this repo's history goes along.

Call in the repo root (example):
    .venv/Scripts/python.exe packaging/public_sync.py                 # checkout ../MuleCreate, commit, no push
    .venv/Scripts/python.exe packaging/public_sync.py --push          # also push main and the tag
    .venv/Scripts/python.exe packaging/public_sync.py --checkout D:/somewhere/MuleCreate

Safety: HEAD must carry a version tag, the public checkout must be clean, on main and not behind origin, and the
new state must have no private traces – otherwise nothing is changed. Ignored files there (dist/, .venv/) stay.
The commit uses the checkout's own git name and address (set by public_export.py).

Release afterwards, in the public checkout (with this repo's Python, it has PyInstaller):
    <this repo>/.venv/Scripts/python.exe packaging/release.py --public "Alpha 2"
"""
import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import public_export as pe  # noqa: E402

DEFAULT_CHECKOUT = os.path.join(os.path.dirname(pe.ROOT), "MuleCreate")


def _public_git(checkout, *args):
    return pe.git(*args, cwd=checkout)


def check_checkout(checkout, fetch=True):
    """Reasons why the public checkout cannot be updated now ([] = fine)."""
    if not os.path.isdir(os.path.join(checkout, ".git")):
        return [f"{checkout} is not a git checkout (first state: public_export.py)"]
    problems = []
    if os.path.commonpath([os.path.abspath(checkout), pe.ROOT]) == pe.ROOT:
        problems.append("the public checkout must not lie inside this repo")
    if _public_git(checkout, "rev-parse", "--abbrev-ref", "HEAD") != "main":
        problems.append("the public checkout is not on main")
    if _public_git(checkout, "status", "--porcelain"):
        problems.append("the public checkout has uncommitted changes")
    if fetch and _public_git(checkout, "remote"):
        _public_git(checkout, "fetch", "-q", "origin")
        behind = _public_git(checkout, "rev-list", "--count", "HEAD..origin/main")
        if behind != "0":
            problems.append(f"the public checkout is {behind} commit(s) behind origin/main – pull first")
    return problems


def sync(checkout, message=None, push=False, fetch=True, tag=None):
    """New public commit from this repo's HEAD. Returns (status, text): "unchanged" | "committed" | "pushed".
    tag: only for tests – otherwise the version tag of HEAD."""
    head, head_tag = pe.head_version()
    tag = tag or head_tag
    if not tag:
        raise SystemExit("HEAD of this repo has no version tag – commit and tag first.")
    problems = check_checkout(checkout, fetch)
    if problems:
        raise SystemExit("Public checkout not ready: " + "; ".join(problems))
    if tag in _public_git(checkout, "tag").split():
        raise SystemExit(f"The public repo already has the tag {tag}.")
    with tempfile.TemporaryDirectory() as tmp:
        hits = pe.clean_copy(tmp)
        if hits:
            raise SystemExit("Private traces – nothing changed, fix them in this repo first:\n" + "\n".join(hits[:50]))
        for rel in _public_git(checkout, "ls-files", "-z").split("\0"):  # tracked files only: ignored ones stay
            if rel:
                os.remove(os.path.join(checkout, rel))
        for base, dirs, files in os.walk(checkout, topdown=False):  # folders that are empty now
            if ".git" in base.split(os.sep):
                continue
            if base != checkout and not os.listdir(base):
                os.rmdir(base)
        shutil.copytree(tmp, checkout, dirs_exist_ok=True)
    _public_git(checkout, "add", "-A")
    if not _public_git(checkout, "status", "--porcelain"):
        return "unchanged", f"No changes against the public repo ({tag} = current public state)."
    stat = _public_git(checkout, "diff", "--cached", "--shortstat")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    pe.git("commit", "-q", "-m", message or f"Mule Create {tag}", cwd=checkout, env=env)
    _public_git(checkout, "tag", tag)
    if not push:
        return "committed", f"Committed {tag} ({stat.strip()}), not pushed: git push origin main {tag}"
    _public_git(checkout, "push", "-q", "origin", "main")
    _public_git(checkout, "push", "-q", "origin", tag)
    return "pushed", f"Pushed {tag} ({stat.strip()})."


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkout", default=DEFAULT_CHECKOUT, help="public checkout (default: ../MuleCreate)")
    ap.add_argument("--message", help="commit message (default: Mule Create <tag>)")
    ap.add_argument("--push", action="store_true", help="push main and the tag afterwards")
    a = ap.parse_args()
    status, text = sync(os.path.abspath(a.checkout), a.message, a.push)
    print(text)


if __name__ == "__main__":
    main()

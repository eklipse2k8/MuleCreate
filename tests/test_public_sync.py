"""Update of the public repo (packaging/public_sync.py) on throwaway repos: an identical state changes nothing, a
differing state becomes a new commit with a tag, ignored files stay, a dirty checkout is rejected.
Nothing is pushed."""
import os
import subprocess
import sys
import tempfile

LEVEL = "core"

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "packaging"))
import public_export as pe  # noqa: E402
import public_sync as ps  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, encoding="utf-8").stdout.strip()


def _public(tmp):
    """Like the first public_export.py: clean copy, one commit, no remote."""
    pub = os.path.join(tmp, "pub")
    os.makedirs(pub)
    assert not pe.clean_copy(pub), "no private traces in the state"
    _git(pub, "init", "-q", "-b", "main")
    _git(pub, "config", "user.name", "Test")
    _git(pub, "config", "user.email", "test@example.invalid")
    _git(pub, "config", "core.autocrlf", "false")
    _git(pub, "add", ".")
    _git(pub, "commit", "-q", "-m", "first")
    return pub


def test_identical_state_changes_nothing(h=None):
    with tempfile.TemporaryDirectory() as tmp:
        pub = _public(tmp)
        assert ps.check_checkout(pub, fetch=False) == []
        status, _ = ps.sync(pub, fetch=False, tag="v0.0.0-test")
        assert status == "unchanged"
        assert _git(pub, "rev-list", "--count", "HEAD") == "1" and not _git(pub, "tag")


def test_differing_state_becomes_new_commit_with_tag(h=None):
    with tempfile.TemporaryDirectory() as tmp:
        pub = _public(tmp)
        os.remove(os.path.join(pub, "README.md"))  # gone in public, must come back
        with open(os.path.join(pub, "stray.txt"), "w") as fh:  # only in public, must go
            fh.write("old")
        _git(pub, "add", "-A")
        _git(pub, "commit", "-q", "-m", "drift")
        os.makedirs(os.path.join(pub, "dist", "_release"))  # ignored (.gitignore): stays
        with open(os.path.join(pub, "dist", "_release", "keep.txt"), "w") as fh:
            fh.write("build")
        status, text = ps.sync(pub, fetch=False, tag="v0.0.0-test")
        assert status == "committed", text
        assert os.path.isfile(os.path.join(pub, "README.md")) and not os.path.exists(os.path.join(pub, "stray.txt"))
        assert os.path.isfile(os.path.join(pub, "dist", "_release", "keep.txt")), "ignored files stay"
        assert _git(pub, "tag") == "v0.0.0-test" and _git(pub, "rev-list", "--count", "HEAD") == "3"
        assert not _git(pub, "status", "--porcelain"), "clean afterwards"
        assert ps.sync(pub, fetch=False, tag="v0.0.1-test")[0] == "unchanged", "twice in a row: nothing new"


def test_dirty_checkout_is_rejected(h=None):
    with tempfile.TemporaryDirectory() as tmp:
        pub = _public(tmp)
        with open(os.path.join(pub, "README.md"), "a") as fh:
            fh.write("\nlocal edit\n")
        assert any("uncommitted" in p for p in ps.check_checkout(pub, fetch=False))
        try:
            ps.sync(pub, fetch=False, tag="v0.0.0-test")
            raise AssertionError("must abort")
        except SystemExit as exc:
            assert "not ready" in str(exc)
        assert "local edit" in open(os.path.join(pub, "README.md")).read(), "nothing touched"


def test_existing_tag_is_rejected(h=None):
    with tempfile.TemporaryDirectory() as tmp:
        pub = _public(tmp)
        _git(pub, "tag", "v0.0.0-test")
        try:
            ps.sync(pub, fetch=False, tag="v0.0.0-test")
            raise AssertionError("must abort")
        except SystemExit as exc:
            assert "already has the tag" in str(exc)

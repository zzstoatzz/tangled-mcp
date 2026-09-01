"""synthesized patches must be real patches: git am applies them cleanly."""

import subprocess
from pathlib import Path

import pytest

from tangled_mcp.patch import synthesize


def _git(repo: Path, *args: str, input: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "keep.txt").write_text("unchanged\n")
    (tmp_path / "edit.txt").write_text("line one\nline two\nline three\n")
    (tmp_path / "gone.txt").write_text("delete me\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def test_git_am_applies_synthesized_patch(repo: Path):
    patch = synthesize(
        "the works",
        "someone.example",
        [
            (
                "edit.txt",
                "line one\nline two\nline three\n",
                "line one\nline 2\nline three\n",
            ),
            ("fresh.txt", None, "brand new\n"),
            ("gone.txt", "delete me\n", None),
        ],
    )
    _git(repo, "am", input=patch)

    assert (repo / "edit.txt").read_text() == "line one\nline 2\nline three\n"
    assert (repo / "fresh.txt").read_text() == "brand new\n"
    assert not (repo / "gone.txt").exists()
    log = _git(repo, "log", "-1", "--format=%s|%an")
    assert log.strip() == "the works|someone.example"


def test_git_am_handles_missing_trailing_newline(repo: Path):
    patch = synthesize(
        "no trailing newline",
        "someone.example",
        [("edit.txt", "line one\nline two\nline three\n", "line one\nno end")],
    )
    _git(repo, "am", input=patch)
    assert (repo / "edit.txt").read_text() == "line one\nno end"


def test_apply_to_file_round_trips_a_synthesized_patch():
    from tangled_mcp.patch import apply_to_file, synthesize

    old = "# phi\n\nlong file\nline three\n"
    new = "toast\n"
    patch = synthesize("t", "phi", [("personalities/phi.md", old, new)])
    assert apply_to_file(patch, "personalities/phi.md", old) == new
    assert apply_to_file(patch, "other.md", old) is None


def test_apply_to_file_handles_no_trailing_newline_and_new_files():
    from tangled_mcp.patch import apply_to_file, synthesize

    patch = synthesize(
        "t", "phi", [("a.md", "x\ny\n", "x\nz"), ("b.md", None, "new\n")]
    )
    assert apply_to_file(patch, "a.md", "x\ny\n") == "x\nz"
    assert apply_to_file(patch, "b.md", "") == "new\n"


def test_apply_to_file_keeps_the_newline_of_a_sections_last_line():
    """a hunk that ends on a blank context line is " \\n"; slicing the
    section at the next `diff --git` used to drop that newline, so the
    line read as " " and never matched the file (phi hit this reviewing
    a real pull)."""
    from tangled_mcp.patch import apply_to_file, synthesize

    old = "x\n\n\n"
    new = "y\n\n\n"
    patch = synthesize("t", "phi", [("a.txt", old, new), ("b.txt", None, "n\n")])
    assert apply_to_file(patch, "a.txt", old) == new


def test_apply_to_file_applies_every_commit_of_a_series(repo: Path):
    """a round can be a multi-commit format-patch; the file as the round
    leaves it is every commit's diff of that path applied in order, not
    just the first."""
    from tangled_mcp.patch import apply_to_file

    (repo / "f.txt").write_text("one\ntwo\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "f.txt").write_text("one\nTWO\n")
    _git(repo, "commit", "-q", "-am", "first")
    (repo / "f.txt").write_text("ONE\nTWO\n")
    _git(repo, "commit", "-q", "-am", "second")
    series = _git(repo, "format-patch", f"{base}..HEAD", "--stdout")
    assert series.count("diff --git a/f.txt") == 2

    assert apply_to_file(series, "f.txt", "one\ntwo\n") == "ONE\nTWO\n"

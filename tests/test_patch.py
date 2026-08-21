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

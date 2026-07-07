"""synthesize a git-am-compatible patch from whole-file edits.

lets clone-less callers open pulls: they say what each file should
become, we produce the format-patch the knot expects.
"""

import difflib
import hashlib
from datetime import datetime, timezone
from email.utils import format_datetime


def _blob_sha(content: str | None) -> str:
    if content is None:
        return "0" * 7
    data = content.encode()
    return hashlib.sha1(b"blob %d\x00%s" % (len(data), data)).hexdigest()[:7]


def _content_lines(old: str, new: str, a: str, b: str) -> list[str]:
    out = []
    for line in difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=a,
        tofile=b,
        lineterm="\n",
    ):
        if line.endswith("\n"):
            out.append(line)
        else:
            out.append(line + "\n")
            out.append("\\ No newline at end of file\n")
    return out


def _file_section(path: str, old: str | None, new: str | None) -> str:
    lines = [f"diff --git a/{path} b/{path}\n"]
    index = f"index {_blob_sha(old)}..{_blob_sha(new)}"
    if old is None:
        lines.append("new file mode 100644\n")
        lines.append(f"{index}\n")
        lines.extend(_content_lines("", new or "", "/dev/null", f"b/{path}"))
    elif new is None:
        lines.append("deleted file mode 100644\n")
        lines.append(f"{index}\n")
        lines.extend(_content_lines(old, "", f"a/{path}", "/dev/null"))
    else:
        lines.append(f"{index} 100644\n")
        lines.extend(_content_lines(old, new, f"a/{path}", f"b/{path}"))
    return "".join(lines)


def synthesize(
    title: str, author_handle: str, files: list[tuple[str, str | None, str | None]]
) -> str:
    """build a single-commit format-patch from (path, old, new) triples.

    old=None means the file is new; new=None means it's deleted.
    """
    sections = "".join(_file_section(path, old, new) for path, old, new in files)
    commit_sha = hashlib.sha1(sections.encode()).hexdigest()
    date = format_datetime(datetime.now(timezone.utc))
    return (
        f"From {commit_sha} Mon Sep 17 00:00:00 2001\n"
        f"From: {author_handle} <noreply@{author_handle}>\n"
        f"Date: {date}\n"
        f"Subject: [PATCH] {title}\n"
        "\n"
        "---\n"
        f"{sections}"
        "-- \n"
        "tangled-mcp\n"
    )

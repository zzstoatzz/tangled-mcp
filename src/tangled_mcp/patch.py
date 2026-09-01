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


def apply_to_file(patch_text: str, path: str, base: str) -> str | None:
    """the content of *path* after *patch_text* is applied to *base*.

    returns None when the patch does not touch the path. handles the
    unified hunks git format-patch emits (including our own synthesized
    ones); a hunk whose context does not match raises ValueError rather
    than guessing.
    """
    marker = f"diff --git a/{path} b/{path}\n"
    sections = []
    start = patch_text.find(marker)
    while start >= 0:
        end = patch_text.find("\ndiff --git ", start + 1)
        # keep the newline that ends the section's last line: a hunk that
        # ends on a blank context line is " \n", and without it the line
        # reads as " " and never matches the file
        sections.append(patch_text[start : end + 1 if end >= 0 else len(patch_text)])
        start = patch_text.find(marker, start + 1)
    if not sections:
        return None
    content: str | None = base
    for section in sections:
        content = _apply_section(section, path, content or "")
    return content


def _apply_section(section: str, path: str, base: str) -> str:
    """one file section (one commit's diff of *path*) applied to *base*."""
    if "deleted file mode" in section.split("@@", 1)[0]:
        return ""
    old_lines = base.splitlines(keepends=True)
    out: list[str] = []
    cursor = 0
    lines = section.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("@@"):
            i += 1
            continue
        header = line.split("@@")[1].strip()
        old_start = int(header.split(" ")[0].lstrip("-").split(",")[0])
        target = max(old_start - 1, 0)
        out.extend(old_lines[cursor:target])
        cursor = target
        i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            hl = lines[i]
            if hl == "-- \n":
                break  # format-patch signature, not a removal
            if hl.startswith("\\"):
                if out and out[-1].endswith("\n"):
                    out[-1] = out[-1][:-1]
                i += 1
                continue
            tag, body = hl[0], hl[1:]
            if tag == " ":
                if cursor >= len(old_lines) or old_lines[cursor] != body:
                    raise ValueError(
                        f"patch context mismatch at {path} line {cursor + 1}"
                    )
                out.append(body)
                cursor += 1
            elif tag == "-":
                if cursor >= len(old_lines) or old_lines[cursor] != body:
                    raise ValueError(
                        f"patch removal mismatch at {path} line {cursor + 1}"
                    )
                cursor += 1
            elif tag == "+":
                out.append(body)
            else:
                break
            i += 1
    out.extend(old_lines[cursor:])
    return "".join(out)

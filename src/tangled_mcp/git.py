"""one commit from whole-file edits, pushed to a knot over smart HTTP.

the knot serves `https://<knot>/<repo did>` to git: fetches are public, and a
push authenticates with a service token (`lxm` org.tangled.git.receivePack,
`aud` the knot's did:web) as the basic-auth password. a depth-1 fetch of the branch tip is
enough to build the new tree; the pack sent back holds only the new objects.
"""

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass

from dulwich.client import HttpGitClient
from dulwich.object_store import commit_tree_changes, tree_lookup_path
from dulwich.objects import Blob, Commit
from dulwich.repo import MemoryRepo

FILE_MODE = 0o100644
PUSH_NSID = "org.tangled.git.receivePack"


@dataclass
class FileEdit:
    path: str
    content: str | None  # None deletes the file


@dataclass
class Pushed:
    parent: str
    head: str


def _ref(branch: str) -> bytes:
    return f"refs/heads/{branch}".encode()


def _fetch_tip(url: str, branch: str) -> tuple[MemoryRepo, bytes]:
    repo = MemoryRepo()
    wanted = _ref(branch)
    found: dict[str, bytes] = {}

    def determine_wants(refs, depth=None):
        if wanted not in refs:
            raise ValueError(f"branch '{branch}' does not exist")
        found["tip"] = refs[wanted]
        return [refs[wanted]]

    HttpGitClient(url).fetch("", repo, determine_wants=determine_wants, depth=1)
    return repo, found["tip"]


def _current(repo: MemoryRepo, tree: bytes, path: str) -> bytes | None:
    try:
        _, sha = tree_lookup_path(repo.object_store.__getitem__, tree, path.encode())
    except KeyError:
        return None
    return repo.object_store[sha].as_raw_string()


def _commit(
    url: str,
    from_branch: str,
    edits: Sequence[FileEdit],
    message: str,
    author: str,
) -> tuple[MemoryRepo, Pushed]:
    repo, parent = _fetch_tip(url, from_branch)
    tip = repo.object_store[parent]
    assert isinstance(tip, Commit)
    tree = tip.tree
    changes: list[tuple[bytes, int | None, bytes | None]] = []
    for edit in edits:
        old = _current(repo, tree, edit.path)
        if edit.content is None:
            if old is None:
                raise ValueError(f"cannot delete '{edit.path}': not in {from_branch}")
            changes.append((edit.path.encode(), None, None))
            continue
        new = edit.content.encode()
        if old == new:
            raise ValueError(f"'{edit.path}' already has that content")
        blob = Blob.from_string(new)
        repo.object_store.add_object(blob)
        changes.append((edit.path.encode(), FILE_MODE, blob.id))
    if not changes:
        raise ValueError("no edits")

    commit = Commit()
    commit.tree = commit_tree_changes(repo.object_store, tree, changes)
    commit.parents = [parent]
    commit.author = commit.committer = author.encode()
    commit.author_time = commit.commit_time = int(time.time())
    commit.author_timezone = commit.commit_timezone = 0
    commit.message = message.encode()
    repo.object_store.add_object(commit)
    return repo, Pushed(parent=parent.decode(), head=commit.id.decode())


def _push(url: str, token: str, repo: MemoryRepo, branch: str, pushed: Pushed) -> None:
    # the remote advertises refs this depth-1 fetch never saw; only the tip
    # we built on is shared, so it alone bounds the pack
    def pack(have, want, *, ofs_delta=False, progress=None):
        shared = {h for h in have if h in repo.object_store}
        return repo.generate_pack_data(
            shared, want, shallow={pushed.parent.encode()}, ofs_delta=ofs_delta
        )

    client = HttpGitClient(url, username="x-token", password=token)
    result = client.send_pack(
        "",
        update_refs=lambda refs: {**refs, _ref(branch): pushed.head.encode()},
        generate_pack_data=pack,
    )
    errors = {ref: err for ref, err in (result.ref_status or {}).items() if err}
    if errors:
        raise RuntimeError(f"push rejected: {errors}")


async def commit_and_push(
    url: str,
    token: str,
    from_branch: str,
    to_branch: str,
    edits: Sequence[FileEdit],
    message: str,
    author: str,
) -> Pushed:
    """commit `edits` on top of `from_branch`'s tip and push it as `to_branch`"""

    def run() -> Pushed:
        repo, pushed = _commit(url, from_branch, edits, message, author)
        _push(url, token, repo, to_branch, pushed)
        return pushed

    return await asyncio.to_thread(run)

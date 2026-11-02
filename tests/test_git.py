"""a real fetch and push over smart HTTP, against dulwich's own git server."""

import threading
from collections.abc import Iterator
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import pytest
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from dulwich.server import DictBackend
from dulwich.web import make_wsgi_chain

from tangled_mcp import git


class _Quiet(WSGIRequestHandler):
    def log_message(self, *args: object) -> None: ...


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Repo, list[str]]]:
    repo = Repo.init_bare(str(tmp_path / "bot.git"), mkdir=True)
    blob = Blob.from_string(b"old\n")
    tree = Tree()
    tree.add(b"phi.md", 0o100644, blob.id)
    commit = Commit()
    commit.tree = tree.id
    commit.author = commit.committer = b"op <op@example>"
    commit.author_time = commit.commit_time = 0
    commit.author_timezone = commit.commit_timezone = 0
    commit.message = b"init"
    for obj in (blob, tree, commit):
        repo.object_store.add_object(obj)
    repo.refs[b"refs/heads/main"] = commit.id

    auth: list[str] = []
    app = make_wsgi_chain(DictBackend({"/": repo}))

    def recording(environ, start_response):
        auth.append(environ.get("HTTP_AUTHORIZATION", ""))
        return app(environ, start_response)

    server: WSGIServer = make_server("127.0.0.1", 0, recording, handler_class=_Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", repo, auth
    server.shutdown()


async def test_edits_land_as_one_commit_on_a_new_branch(served):
    url, repo, auth = served
    main = repo.refs[b"refs/heads/main"]
    pushed = await git.commit_and_push(
        url,
        "service-token",
        "main",
        "phi/change",
        [git.FileEdit("phi.md", "new\n"), git.FileEdit("docs/new.md", "hello\n")],
        "a title",
        "phi <noreply@phi>",
    )
    assert pushed.parent == main.decode()
    assert repo.refs[b"refs/heads/phi/change"] == pushed.head.encode()
    assert repo.refs[b"refs/heads/main"] == main  # the target is untouched
    head = repo[pushed.head.encode()]
    assert isinstance(head, Commit)
    assert head.parents == [main] and head.message == b"a title"
    tree = repo[head.tree]
    assert isinstance(tree, Tree)
    assert repo[tree[b"phi.md"][1]].as_raw_string() == b"new\n"
    import base64

    sent = base64.b64encode(b"x-token:service-token").decode()
    assert f"Basic {sent}" in auth  # the push carried the token


async def test_a_second_round_stacks_on_the_branch(served):
    url, repo, _ = served
    first = await git.commit_and_push(
        url, "t", "main", "phi/c", [git.FileEdit("phi.md", "one\n")], "r0", "phi <p>"
    )
    second = await git.commit_and_push(
        url, "t", "phi/c", "phi/c", [git.FileEdit("phi.md", "two\n")], "r1", "phi <p>"
    )
    assert second.parent == first.head
    assert repo.refs[b"refs/heads/phi/c"] == second.head.encode()


async def test_unchanged_and_missing_files_are_refused(served):
    url, _, _ = served
    with pytest.raises(ValueError, match="already has that content"):
        await git.commit_and_push(
            url, "t", "main", "b", [git.FileEdit("phi.md", "old\n")], "m", "a <a>"
        )
    with pytest.raises(ValueError, match="cannot delete"):
        await git.commit_and_push(
            url, "t", "main", "b", [git.FileEdit("gone.md", None)], "m", "a <a>"
        )
    with pytest.raises(ValueError, match="does not exist"):
        await git.commit_and_push(
            url, "t", "nope", "b", [git.FileEdit("phi.md", "x\n")], "m", "a <a>"
        )

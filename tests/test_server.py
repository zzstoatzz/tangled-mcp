from typing import Any

import pytest

from tangled_mcp import bobbin
from tangled_mcp.records import tid
from tangled_mcp.server import _issue_view, _pull_view, _resolve_labels, tangled_mcp

REPO_RECORD = {
    "uri": "at://did:plc:owner/sh.tangled.repo/myrepo",
    "value": {
        "$type": "sh.tangled.repo",
        "knot": "knot1.tangled.sh",
        "repoDid": "did:plc:repodid",
        "labels": ["at://did:plc:x/sh.tangled.label.definition/bug"],
    },
}

LEGACY_RECORD = {
    "uri": "at://did:plc:owner/sh.tangled.repo/3m2ur2jrcfh22",
    "value": {
        "$type": "sh.tangled.repo",
        "name": "legacy-repo",
        "knot": "knot1.tangled.sh",
        "repoDid": "did:plc:legacydid",
    },
}


async def test_tools_registered():
    tools = await tangled_mcp.list_tools()
    assert {
        "search",
        "list_repos",
        "get_repo",
        "list_branches",
        "list_tags",
        "list_files",
        "read_file",
        "commit_log",
        "compare",
        "list_issues",
        "get_issue",
        "list_pulls",
        "get_pull",
        "list_pipelines",
        "create_issue",
        "create_pull",
        "update_issue",
        "set_issue_state",
        "set_pull_state",
        "comment_on_issue",
        "comment_on_pull",
        "delete_issue",
    } <= {tool.name for tool in tools}


async def test_resolve_repo_new_style(monkeypatch: pytest.MonkeyPatch):
    async def fake_query(nsid: str, **params: Any) -> dict[str, Any]:
        assert nsid == "sh.tangled.repo.getRepo"
        assert params["repo"] == "at://did:plc:owner/sh.tangled.repo/myrepo"
        return REPO_RECORD

    monkeypatch.setattr(bobbin, "query", fake_query)
    monkeypatch.setattr(bobbin, "resolve_handle", _const("did:plc:owner"))

    repo = await bobbin.resolve_repo("owner.example/myrepo")
    assert repo.name == "myrepo"
    assert repo.repo_did == "did:plc:repodid"
    assert repo.knot == "knot1.tangled.sh"


async def test_resolve_repo_legacy_fallback(monkeypatch: pytest.MonkeyPatch):
    async def fake_query(nsid: str, **params: Any) -> dict[str, Any]:
        if nsid == "sh.tangled.repo.getRepo":
            raise bobbin.BobbinError("not found")
        assert nsid == "sh.tangled.repo.listRepos"
        return {"items": [LEGACY_RECORD], "cursor": None}

    monkeypatch.setattr(bobbin, "query", fake_query)
    monkeypatch.setattr(bobbin, "resolve_handle", _const("did:plc:owner"))

    repo = await bobbin.resolve_repo("@owner.example/legacy-repo")
    assert repo.name == "legacy-repo"
    assert repo.uri.endswith("/3m2ur2jrcfh22")
    assert repo.repo_did == "did:plc:legacydid"


async def test_resolve_repo_not_found(monkeypatch: pytest.MonkeyPatch):
    async def fake_query(nsid: str, **params: Any) -> dict[str, Any]:
        if nsid == "sh.tangled.repo.getRepo":
            raise bobbin.BobbinError("not found")
        return {"items": [], "cursor": None}

    monkeypatch.setattr(bobbin, "query", fake_query)
    monkeypatch.setattr(bobbin, "resolve_handle", _const("did:plc:owner"))

    with pytest.raises(ValueError, match="not found"):
        await bobbin.resolve_repo("owner.example/nope")


async def test_resolve_repo_accepts_at_uri(monkeypatch: pytest.MonkeyPatch):
    async def fake_query(nsid: str, **params: Any) -> dict[str, Any]:
        assert nsid == "sh.tangled.repo.getRepo"
        return REPO_RECORD

    monkeypatch.setattr(bobbin, "query", fake_query)
    repo = await bobbin.resolve_repo("at://did:plc:owner/sh.tangled.repo/myrepo")
    assert repo.name == "myrepo"
    assert repo.owner_did == "did:plc:owner"


async def test_resolve_repo_accepts_repo_did(monkeypatch: pytest.MonkeyPatch):
    async def fake_query(nsid: str, **params: Any) -> dict[str, Any]:
        assert nsid == "sh.tangled.repo.getRepoByRepoDid"
        assert params["repoDid"] == "did:plc:repodid"
        return REPO_RECORD

    monkeypatch.setattr(bobbin, "query", fake_query)
    repo = await bobbin.resolve_repo("did:plc:repodid")
    assert repo.name == "myrepo"


async def test_resolve_repo_did_owner_uses_lookup_path(
    monkeypatch: pytest.MonkeyPatch,
):
    # 'did:plc:owner/myrepo' must take the owner/repo path, not getRepoByRepoDid
    async def fake_query(nsid: str, **params: Any) -> dict[str, Any]:
        assert nsid == "sh.tangled.repo.getRepo"
        return REPO_RECORD

    monkeypatch.setattr(bobbin, "query", fake_query)
    monkeypatch.setattr(bobbin, "resolve_handle", _const("did:plc:owner"))
    repo = await bobbin.resolve_repo("did:plc:owner/myrepo")
    assert repo.name == "myrepo"


async def test_resolve_repo_rejects_bad_format():
    with pytest.raises(ValueError, match="owner/repo"):
        await bobbin.resolve_repo("just-a-name")


def test_issue_view():
    view = _issue_view(
        {
            "uri": "at://did:plc:author/sh.tangled.repo.issue/3mabc",
            "value": {"title": "t", "body": "b", "createdAt": "2026-01-01T00:00:00Z"},
            "state": "open",
            "commentCount": 2,
        }
    )
    assert view == {
        "uri": "at://did:plc:author/sh.tangled.repo.issue/3mabc",
        "title": "t",
        "body": "b",
        "state": "open",
        "comment_count": 2,
        "created_at": "2026-01-01T00:00:00Z",
        "author": "did:plc:author",
    }


def test_pull_view():
    view = _pull_view(
        {
            "uri": "at://did:plc:author/sh.tangled.repo.pull/3mxyz",
            "value": {
                "title": "t",
                "target": {"branch": "main", "repo": "did:plc:repodid"},
                "source": {"branch": "feature"},
            },
            "status": "open",
        }
    )
    assert view["target_branch"] == "main"
    assert view["source_branch"] == "feature"
    assert view["state"] == "open"


def test_resolve_labels():
    repo_labels = [
        "at://did:plc:x/sh.tangled.label.definition/bug",
        "at://did:plc:x/sh.tangled.label.definition/good-first-issue",
    ]
    assert _resolve_labels(["Bug"], repo_labels) == [repo_labels[0]]
    with pytest.raises(ValueError, match="invalid labels"):
        _resolve_labels(["nope"], repo_labels)


def test_tid_shape_and_sortability():
    a, b = tid(), tid()
    assert len(a) == len(b) == 13
    assert a[:10] <= b[:10]  # timestamp prefix is base32-sortable


def _const(value: str):
    async def fake(*args: Any, **kwargs: Any) -> str:
        return value

    return fake


def test_resolve_credentials_headers_win_and_never_mix(monkeypatch: Any):
    from tangled_mcp import records
    from tangled_mcp.settings import settings

    monkeypatch.setattr(settings, "tangled_handle", "env.handle")
    monkeypatch.setattr(settings, "tangled_password", "env-pass")
    # no headers → env credentials
    monkeypatch.setattr(records, "get_http_headers", lambda: {})
    creds = records.resolve_credentials()
    assert (creds.handle, creds.password) == ("env.handle", "env-pass")

    # header identity is used whole — env password must NOT fill the gap
    monkeypatch.setattr(
        records, "get_http_headers", lambda: {"x-tangled-handle": "phi.handle"}
    )
    creds = records.resolve_credentials()
    assert creds.handle == "phi.handle"
    assert creds.password is None

    # complete header identity
    monkeypatch.setattr(
        records,
        "get_http_headers",
        lambda: {
            "x-tangled-handle": "phi.handle",
            "x-tangled-password": "phi-pass",
        },
    )
    creds = records.resolve_credentials()
    assert (creds.handle, creds.password) == ("phi.handle", "phi-pass")


async def test_discover_pds_routes_by_did_method(monkeypatch: Any):
    from tangled_mcp import records

    requested: list[str] = []

    class FakeResponse:
        def json(self) -> dict[str, Any]:
            return {
                "service": [
                    {
                        "type": "AtprotoPersonalDataServer",
                        "serviceEndpoint": "https://pds.example",
                    }
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: Any) -> None: ...
        async def get(self, url: str) -> FakeResponse:
            requested.append(url)
            return FakeResponse()

    monkeypatch.setattr(records.httpx, "AsyncClient", FakeClient)

    assert await records.discover_pds("did:plc:abc123") == "https://pds.example"
    assert requested[-1] == "https://plc.directory/did:plc:abc123"

    assert await records.discover_pds("did:web:pds.example") == "https://pds.example"
    assert requested[-1] == "https://pds.example/.well-known/did.json"


async def test_create_pull_record_shape(monkeypatch: Any):
    import gzip

    from tangled_mcp import records, server
    from tangled_mcp.bobbin import Repo

    async def fake_resolve(identifier: str) -> Repo:
        return Repo(
            owner_did="did:plc:owner",
            name="myrepo",
            uri="at://did:plc:owner/sh.tangled.repo/myrepo",
            knot="knot1.tangled.sh",
            repo_did="did:plc:repodid",
            labels=[],
            description=None,
        )

    async def fake_query(nsid: str, **params: Any) -> dict[str, Any]:
        assert nsid == "sh.tangled.repo.getDefaultBranch"
        return {"name": "main"}

    async def fake_repo_query(r: Repo, nsid: str, **params: Any) -> dict[str, Any]:
        from tangled_mcp.bobbin import BobbinError

        raise BobbinError(f"{nsid} not on this fake knot", status=404)

    monkeypatch.setattr(server.bobbin, "repo_query", fake_repo_query)

    uploaded: dict[str, Any] = {}
    put: dict[str, Any] = {}

    class FakeSession:
        did = "did:plc:me"

        class client:
            @staticmethod
            async def aclose() -> None: ...

        async def upload_blob(self, data: bytes, mime_type: str) -> dict[str, Any]:
            uploaded["data"] = data
            uploaded["mime_type"] = mime_type
            return {"$type": "blob", "ref": {"$link": "bafyfake"}}

        async def put_record(
            self, collection: str, rkey: str, record: dict[str, Any]
        ) -> dict[str, Any]:
            put["collection"] = collection
            put["record"] = record
            return {"uri": f"at://did:plc:me/{collection}/{rkey}"}

    monkeypatch.setattr(server.bobbin, "resolve_repo", fake_resolve)
    monkeypatch.setattr(server.bobbin, "query", fake_query)

    async def fake_login() -> Any:
        return FakeSession()

    monkeypatch.setattr(records, "login", fake_login)

    result = await server.create_pull(
        repo="owner.example/myrepo",
        title="fix things",
        patch="From abc123 Mon Sep 17 00:00:00 2001\n...",
        body="why not",
    )

    assert uploaded["mime_type"] == "application/gzip"
    assert gzip.decompress(uploaded["data"]).startswith(b"From abc123")
    record = put["record"]
    assert put["collection"] == "sh.tangled.repo.pull"
    assert record["target"] == {"repo": "did:plc:repodid", "branch": "main"}
    assert record["rounds"][0]["patchBlob"]["ref"]["$link"] == "bafyfake"
    assert result["uri"].startswith("at://did:plc:me/sh.tangled.repo.pull/")
    assert result["url"].endswith("/pulls")


async def test_create_pull_edits_diff_against_the_knot_and_fail_loud(monkeypatch: Any):
    """2026-08-21: phi's pull request against personalities/phi.md arrived as
    a new-file patch (--- /dev/null) and would not apply: the base read went
    to bobbin, failed, and the failure was read as "file does not exist".
    The base now comes from the repo's knot, and only a 404 means new."""
    from tangled_mcp import records, server
    from tangled_mcp.bobbin import BobbinError, Repo

    repo = Repo(
        owner_did="did:plc:owner",
        name="bot",
        uri="at://did:plc:owner/sh.tangled.repo/bot",
        knot="knot1.tangled.sh",
        repo_did="did:plc:repodid",
        labels=[],
        description=None,
    )

    async def fake_resolve(identifier: str) -> Repo:
        return repo

    async def fake_query(nsid: str, **params: Any) -> dict[str, Any]:
        return {"name": "main"}

    captured: dict[str, Any] = {}

    class FakeSession:
        did = "did:plc:me"

        class client:
            @staticmethod
            async def aclose() -> None: ...

        async def upload_blob(self, data: bytes, mime_type: str) -> dict[str, Any]:
            import gzip

            captured["patch"] = gzip.decompress(data).decode()
            return {"$type": "blob", "ref": {"$link": "bafyfake"}}

        async def put_record(
            self, collection: str, rkey: str, record: dict[str, Any]
        ) -> dict[str, Any]:
            return {"uri": f"at://did:plc:me/{collection}/{rkey}"}

    async def fake_login() -> Any:
        return FakeSession()

    monkeypatch.setattr(server.bobbin, "resolve_repo", fake_resolve)
    monkeypatch.setattr(server.bobbin, "query", fake_query)
    monkeypatch.setattr(records, "login", fake_login)
    monkeypatch.setattr(
        records, "resolve_credentials", lambda: type("C", (), {"handle": "phi"})()
    )

    # existing file on the knot → a modification, not a creation
    async def knot_has_file(r: Repo, nsid: str, **params: Any) -> dict[str, Any]:
        assert r is repo
        if nsid == "sh.tangled.repo.getDefaultBranch":
            return {"name": "main"}
        assert nsid == "sh.tangled.repo.blob"
        assert params == {"path": "personalities/phi.md", "ref": "main"}
        return {"content": "old text\n"}

    monkeypatch.setattr(server.bobbin, "repo_query", knot_has_file)
    await server.create_pull(
        repo="zzstoatzz.io/bot",
        title="t",
        edits=[server.Edit(path="personalities/phi.md", content="new text\n")],
    )
    assert "--- /dev/null" not in captured["patch"]
    assert "-old text" in captured["patch"] and "+new text" in captured["patch"]

    # a non-404 failure is an error, never "new file"
    async def knot_rate_limited(r: Repo, nsid: str, **params: Any) -> dict[str, Any]:
        if nsid == "sh.tangled.repo.getDefaultBranch":
            return {"name": "main"}
        raise BobbinError("blob failed (429) slow down", status=429)

    monkeypatch.setattr(server.bobbin, "repo_query", knot_rate_limited)
    import pytest

    with pytest.raises(ValueError, match="could not read current"):
        await server.create_pull(
            repo="zzstoatzz.io/bot",
            title="t",
            edits=[server.Edit(path="personalities/phi.md", content="x")],
        )

    # a real 404 is a new file
    async def knot_not_found(r: Repo, nsid: str, **params: Any) -> dict[str, Any]:
        if nsid == "sh.tangled.repo.getDefaultBranch":
            return {"name": "main"}
        raise BobbinError("blob failed (404) not found", status=404)

    monkeypatch.setattr(server.bobbin, "repo_query", knot_not_found)
    await server.create_pull(
        repo="zzstoatzz.io/bot",
        title="t",
        edits=[server.Edit(path="docs/new.md", content="hello\n")],
    )
    assert "--- /dev/null" in captured["patch"]


async def test_default_branch_survives_bobbin_rate_limit(monkeypatch: Any):
    from tangled_mcp import server
    from tangled_mcp.bobbin import BobbinError, Repo

    repo = Repo(
        owner_did="d",
        name="bot",
        uri="at://d/sh.tangled.repo/bot",
        knot="knot1.tangled.sh",
        repo_did="did:plc:r",
        labels=[],
        description=None,
    )

    async def knot_silent(r: Repo, nsid: str, **params: Any) -> dict[str, Any]:
        raise BobbinError("nope", status=404)

    async def bobbin_429(nsid: str, **params: Any) -> dict[str, Any]:
        raise BobbinError("getDefaultBranch failed (429)", status=429)

    monkeypatch.setattr(server.bobbin, "repo_query", knot_silent)
    monkeypatch.setattr(server.bobbin, "query", bobbin_429)
    assert await server._default_branch(repo) == "main"


async def test_comment_on_pull_record_shape(monkeypatch: Any):
    from tangled_mcp import records, server

    put: dict[str, Any] = {}

    class FakeSession:
        class client:
            @staticmethod
            async def aclose() -> None: ...

        async def put_record(
            self, collection: str, rkey: str, record: dict[str, Any]
        ) -> dict[str, Any]:
            put["collection"] = collection
            put["record"] = record
            return {"uri": f"at://did:plc:me/{collection}/{rkey}"}

    async def fake_login() -> Any:
        return FakeSession()

    monkeypatch.setattr(records, "login", fake_login)
    pull = "at://did:plc:phi/sh.tangled.repo.pull/3abc"
    result = await server.comment_on_pull(pull=pull, body="2/10")
    assert put["collection"] == "sh.tangled.repo.pull.comment"
    assert put["record"]["pull"] == pull and put["record"]["body"] == "2/10"
    assert put["record"]["$type"] == "sh.tangled.repo.pull.comment"
    assert result["uri"].startswith("at://did:plc:me/sh.tangled.repo.pull.comment/")

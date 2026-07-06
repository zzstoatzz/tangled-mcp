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
    tools = await tangled_mcp.get_tools()
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
        "list_pipelines",
        "create_issue",
        "update_issue",
        "set_issue_state",
        "comment_on_issue",
        "delete_issue",
    } <= set(tools)


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
    monkeypatch.setattr(settings, "tangled_pds_url", "https://env.pds")

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
    assert creds.pds_url is None

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

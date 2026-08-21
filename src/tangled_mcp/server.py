"""tangled MCP server

reads go through bobbin (api.tangled.org, no auth); writes are atproto
records put directly on the user's PDS.
"""

import gzip
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from tangled_mcp import bobbin, records
from tangled_mcp.patch import synthesize as synthesize_patch
from tangled_mcp.settings import APPVIEW_URL

tangled_mcp = FastMCP("tangled MCP server")

RepoParam = Annotated[
    str,
    Field(
        description="repository as 'owner/repo' (owner may be a handle or DID), "
        "a repo record at-uri (as returned by search), or a bare repo DID"
    ),
]
IssueParam = Annotated[
    str,
    Field(
        description="issue at-uri (at://did/sh.tangled.repo.issue/rkey) or bare rkey"
    ),
]
Limit = Annotated[int, Field(ge=1, le=100)]


def _issue_view(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("value") or {}
    return {
        "uri": item["uri"],
        "title": value.get("title"),
        "body": value.get("body"),
        "state": item.get("state"),
        "comment_count": item.get("commentCount"),
        "created_at": value.get("createdAt"),
        "author": item["uri"].removeprefix("at://").split("/")[0],
    }


def _pull_view(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("value") or {}
    target, source = value.get("target") or {}, value.get("source") or {}
    return {
        "uri": item["uri"],
        "title": value.get("title"),
        "state": item.get("status") or item.get("state"),
        "target_branch": target.get("branch"),
        "source_branch": source.get("branch"),
        "created_at": value.get("createdAt"),
        "author": item["uri"].removeprefix("at://").split("/")[0],
    }


async def _issue_uri(issue: str) -> str:
    if issue.startswith("at://"):
        return issue
    handle = records.resolve_credentials().handle
    if not handle:
        raise ValueError("bare rkey requires credentials; pass a full at-uri")
    did = await bobbin.resolve_handle(handle)
    return f"at://{did}/{records.ISSUE}/{issue}"


# --- discovery ---------------------------------------------------------------


@tangled_mcp.tool
async def search(
    query: Annotated[str, Field(description="full-text search query")],
    limit: Limit = 20,
) -> list[dict[str, Any]]:
    """search tangled (repos, issues, pulls, strings) via full-text index"""
    body = await bobbin.query("sh.tangled.search.query", q=query, limit=limit)
    return [_search_hit(hit) for hit in body.get("hits") or []]


def _search_hit(hit: dict[str, Any]) -> dict[str, Any]:
    value = hit.get("value") or {}
    rkey = hit["uri"].rsplit("/", 1)[-1]
    title = value.get("name") or value.get("title")
    if not title and hit.get("nsid") == "sh.tangled.repo":
        title = rkey  # new-style repo records carry their name in the rkey
    snippet = value.get("description") or value.get("body") or value.get("contents")
    return {
        "uri": hit["uri"],
        "type": hit.get("nsid"),
        "title": title,
        "snippet": (snippet or "")[:200] or None,
    }


@tangled_mcp.tool
async def get_record(
    uri: Annotated[str, Field(description="at-uri of any public atproto record")],
) -> dict[str, Any]:
    """fetch the full record behind any at-uri (e.g. a string/paste, comment,
    or anything surfaced by search) directly from its owner's PDS"""
    body = await bobbin.get_record(uri)
    return body.get("value") or {}


@tangled_mcp.tool
async def list_repos(
    owner: Annotated[str, Field(description="handle or DID")],
    limit: Limit = 50,
) -> list[dict[str, Any]]:
    """list repositories owned by a user"""
    did = await bobbin.resolve_handle(owner.lstrip("@"))
    body = await bobbin.query("sh.tangled.repo.listRepos", subject=did, limit=limit)
    out = []
    for item in body.get("items") or []:
        value = item.get("value") or {}
        name = value.get("name") or item["uri"].rsplit("/", 1)[-1]
        out.append(
            {
                "name": name,
                "uri": item["uri"],
                "knot": value.get("knot"),
                "description": value.get("description"),
                "url": f"{APPVIEW_URL}/@{owner.lstrip('@')}/{name}",
            }
        )
    return out


@tangled_mcp.tool
async def get_repo(repo: RepoParam) -> dict[str, Any]:
    """get repository metadata: knot, default branch, languages, labels"""
    r = await bobbin.resolve_repo(repo)
    default_branch = await bobbin.query("sh.tangled.repo.getDefaultBranch", repo=r.uri)
    languages = await bobbin.query("sh.tangled.repo.languages", repo=r.uri)
    return {
        "name": r.name,
        "uri": r.uri,
        "repo_did": r.repo_did,
        "knot": r.knot,
        "description": r.description,
        "default_branch": default_branch.get("name"),
        "languages": {
            lang["name"]: lang["percentage"]
            for lang in languages.get("languages") or []
        },
        "labels": [uri.rsplit("/", 1)[-1] for uri in r.labels],
    }


# --- git reads ---------------------------------------------------------------


@tangled_mcp.tool
async def list_branches(repo: RepoParam, limit: Limit = 50) -> list[dict[str, Any]]:
    """list branches with their head commits"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.repo_query(r, "sh.tangled.repo.branches", limit=limit)
    return [
        {
            "name": b["reference"]["name"],
            "sha": b["reference"]["hash"],
            "message": ((b.get("commit") or {}).get("Message") or "").split("\n")[0],
        }
        for b in body.get("branches") or []
    ]


@tangled_mcp.tool
async def list_tags(repo: RepoParam, limit: Limit = 50) -> list[dict[str, Any]]:
    """list tags"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.repo_query(r, "sh.tangled.repo.tags", limit=limit)
    return [
        {"name": t.get("name"), "sha": t.get("hash"), "message": t.get("message")}
        for t in body.get("tags") or []
    ]


@tangled_mcp.tool
async def list_files(
    repo: RepoParam,
    path: Annotated[
        str | None, Field(description="directory path, root if omitted")
    ] = None,
    ref: Annotated[str | None, Field(description="branch, tag, or sha")] = None,
) -> list[dict[str, Any]]:
    """list files in a repository directory"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.repo_query(r, "sh.tangled.repo.tree", path=path, ref=ref)
    return [
        {
            "name": f["name"],
            "is_dir": f.get("mode", "").startswith("004"),
            "size": f.get("size"),
        }
        for f in body.get("files") or []
    ]


@tangled_mcp.tool
async def read_file(
    repo: RepoParam,
    path: Annotated[str, Field(description="file path within the repo")],
    ref: Annotated[str | None, Field(description="branch, tag, or sha")] = None,
) -> str:
    """read a file's contents from a repository"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.repo_query(r, "sh.tangled.repo.blob", path=path, ref=ref)
    return body.get("content") or ""


@tangled_mcp.tool
async def commit_log(
    repo: RepoParam,
    ref: Annotated[str | None, Field(description="branch, tag, or sha")] = None,
    limit: Limit = 20,
) -> list[dict[str, Any]]:
    """list recent commits"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.repo_query(r, "sh.tangled.repo.log", ref=ref, limit=limit)
    return [
        {
            "sha": c.get("this"),
            "message": (c.get("message") or "").split("\n")[0],
            "author": (c.get("author") or {}).get("Name"),
            "when": (c.get("author") or {}).get("When"),
        }
        for c in body.get("commits") or []
    ]


@tangled_mcp.tool
async def compare(
    repo: RepoParam,
    rev1: Annotated[str, Field(description="base revision (branch, tag, or sha)")],
    rev2: Annotated[str, Field(description="head revision (branch, tag, or sha)")],
) -> dict[str, Any]:
    """compare two revisions (diff summary)"""
    r = await bobbin.resolve_repo(repo)
    return await bobbin.repo_query(r, "sh.tangled.repo.compare", rev1=rev1, rev2=rev2)


# --- issues & pulls ----------------------------------------------------------


@tangled_mcp.tool
async def list_issues(
    repo: RepoParam,
    state: Annotated[
        Literal["open", "closed"] | None, Field(description="filter by state")
    ] = None,
    limit: Limit = 20,
) -> list[dict[str, Any]]:
    """list issues on a repository"""
    r = await bobbin.resolve_repo(repo)
    if not r.repo_did:
        raise ValueError(f"repo '{repo}' has no repoDid; issues unavailable")
    body = await bobbin.query(
        "sh.tangled.repo.listIssues", subject=r.repo_did, state=state, limit=limit
    )
    return [_issue_view(item) for item in body.get("items") or []]


@tangled_mcp.tool
async def get_issue(issue: IssueParam) -> dict[str, Any]:
    """get a single issue"""
    uri = await _issue_uri(issue)
    body = await bobbin.query("sh.tangled.repo.getIssue", issue=uri)
    return _issue_view(body)


@tangled_mcp.tool
async def list_pulls(
    repo: RepoParam,
    status: Annotated[
        Literal["open", "closed", "merged"] | None,
        Field(description="filter by status"),
    ] = None,
    limit: Limit = 20,
) -> list[dict[str, Any]]:
    """list pull requests on a repository"""
    r = await bobbin.resolve_repo(repo)
    if not r.repo_did:
        raise ValueError(f"repo '{repo}' has no repoDid; pulls unavailable")
    body = await bobbin.query(
        "sh.tangled.repo.listPulls", subject=r.repo_did, status=status, limit=limit
    )
    return [_pull_view(item) for item in body.get("items") or []]


@tangled_mcp.tool
async def get_pull(
    pull: Annotated[
        str,
        Field(description="pull request at-uri (at://did/sh.tangled.repo.pull/rkey)"),
    ],
) -> dict[str, Any]:
    """get a pull request with its current state.

    state is derived from the newest sh.tangled.repo.pull.status record on
    the author's PDS — the source of truth — so it's live even when the
    appview/bobbin indexes lag.
    """
    record = await bobbin.get_record(pull)
    value = record.get("value") or {}
    author = pull.removeprefix("at://").split("/")[0]

    statuses = [
        s.get("value") or {}
        for s in await bobbin.list_records(author, records.PULL_STATUS)
        if (s.get("value") or {}).get("pull") == pull
    ]
    latest = max(statuses, key=lambda s: s.get("createdAt") or "", default=None)
    state = (latest["status"].rsplit(".", 1)[-1]) if latest else "open"

    target = value.get("target") or {}
    return {
        "uri": pull,
        "title": value.get("title"),
        "body": value.get("body"),
        "state": state,
        "state_changed_at": latest.get("createdAt") if latest else None,
        "target_branch": target.get("branch"),
        "target_repo": target.get("repo"),
        "rounds": len(value.get("rounds") or []),
        "created_at": value.get("createdAt"),
        "author": author,
    }


@tangled_mcp.tool
async def list_pipelines(repo: RepoParam, limit: Limit = 10) -> list[dict[str, Any]]:
    """list CI pipelines for a repository"""
    r = await bobbin.resolve_repo(repo)
    if not r.repo_did:
        raise ValueError(f"repo '{repo}' has no repoDid; pipelines unavailable")
    body = await bobbin.query(
        "sh.tangled.pipeline.listPipelines", subject=r.repo_did, limit=limit
    )
    return body.get("items") or []


# --- writes (require TANGLED_HANDLE / TANGLED_PASSWORD) -----------------------


@tangled_mcp.tool
async def create_issue(
    repo: RepoParam,
    title: Annotated[str, Field(description="issue title")],
    body: Annotated[str | None, Field(description="issue body (markdown)")] = None,
    labels: Annotated[
        list[str] | None,
        Field(description="label names from the repo's label set (see get_repo)"),
    ] = None,
) -> dict[str, str]:
    """create an issue on a repository"""
    r = await bobbin.resolve_repo(repo)
    if not r.repo_did:
        raise ValueError(f"repo '{repo}' has no repoDid; cannot create issues")
    label_uris = _resolve_labels(labels, r.labels) if labels else []

    session = await records.login()
    try:
        rkey = records.tid()
        record: dict[str, Any] = {
            "$type": records.ISSUE,
            "repo": r.repo_did,
            "title": title,
            "createdAt": records.now(),
        }
        if body:
            record["body"] = body
        result = await session.put_record(records.ISSUE, rkey, record)
        if label_uris:
            await _put_label_op(session, result["uri"], add=label_uris)
        return {
            "uri": result["uri"],
            # the appview assigns sequential issue numbers we can't know here
            "url": f"{APPVIEW_URL}/{repo.lstrip('@')}/issues",
        }
    finally:
        await session.client.aclose()


class Edit(BaseModel):
    """desired end-state of one file. content=None deletes it."""

    path: str
    content: str | None = None


async def _default_branch(r: bobbin.Repo) -> str:
    """the repo's default branch, from the knot first. bobbin rate-limits
    unauthenticated callers (phi hit 429 here on 2026-08-21 with a finished
    pull request in hand); the knot serves git data without limits, and
    "main" is the right answer when neither will say."""
    for attempt in (
        lambda: bobbin.repo_query(r, "sh.tangled.repo.getDefaultBranch"),
        lambda: bobbin.query("sh.tangled.repo.getDefaultBranch", repo=r.uri),
    ):
        try:
            body = await attempt()
        except bobbin.BobbinError:
            continue
        if name := body.get("name"):
            return name
    return "main"


@tangled_mcp.tool
async def create_pull(
    repo: RepoParam,
    title: Annotated[str, Field(description="pull request title")],
    patch: Annotated[
        str | None,
        Field(
            description="git format-patch output (`git format-patch <base> --stdout`) "
            "containing the commits to propose"
        ),
    ] = None,
    edits: Annotated[
        list[Edit] | None,
        Field(
            description="alternative to `patch` for callers without a clone: "
            "full desired content per file (content=null deletes the file); "
            "the server diffs against the target branch and synthesizes the patch"
        ),
    ] = None,
    target_branch: Annotated[
        str | None,
        Field(description="branch to merge into (repo default branch if omitted)"),
    ] = None,
    body: Annotated[
        str | None, Field(description="pull request description (markdown)")
    ] = None,
) -> dict[str, str]:
    """open a patch-based pull request on a repository.

    the changeset — a format-patch you provide, or one synthesized from
    `edits` — is gzipped and uploaded as a blob on your PDS, then referenced
    from a sh.tangled.repo.pull record — no push access to the target needed.
    """
    if (patch is None) == (edits is None):
        raise ValueError("provide exactly one of `patch` or `edits`")
    r = await bobbin.resolve_repo(repo)
    if not r.repo_did:
        raise ValueError(f"repo '{repo}' has no repoDid; cannot create pulls")
    if not target_branch:
        target_branch = await _default_branch(r)

    if edits is not None:
        files = []
        for e in edits:
            # the knot is the authority for git data (see repo_query). until
            # 2026-08-21 this asked bobbin and treated any failure as "new
            # file", so a rate-limit or a legacy-rkey 404 produced a
            # /dev/null patch for a file that exists — unmergeable, and
            # silent about why. only a real not-found means new.
            try:
                base = await bobbin.repo_query(
                    r, "sh.tangled.repo.blob", path=e.path, ref=target_branch
                )
                old = base.get("content") or ""
            except bobbin.BobbinError as err:
                if err.status != 404:
                    raise ValueError(
                        f"could not read current '{e.path}' on {target_branch}: {err}"
                    ) from err
                old = None
            if old is None and e.content is None:
                raise ValueError(f"cannot delete '{e.path}': not in {target_branch}")
            if old == e.content:
                raise ValueError(f"'{e.path}' already has that content")
            files.append((e.path, old, e.content))
        author = records.resolve_credentials().handle or "unknown"
        patch = synthesize_patch(title, author, files)
    assert patch is not None

    session = await records.login()
    try:
        blob = await session.upload_blob(
            gzip.compress(patch.encode()), "application/gzip"
        )
        rkey = records.tid()
        record: dict[str, Any] = {
            "$type": records.PULL,
            "title": title,
            "target": {"repo": r.repo_did, "branch": target_branch},
            "rounds": [{"patchBlob": blob, "createdAt": records.now()}],
            "createdAt": records.now(),
        }
        if body:
            record["body"] = body
        result = await session.put_record(records.PULL, rkey, record)
        return {
            "uri": result["uri"],
            # the appview assigns sequential pull numbers we can't know here
            "url": f"{APPVIEW_URL}/{repo.lstrip('@')}/pulls",
        }
    finally:
        await session.client.aclose()


@tangled_mcp.tool
async def update_issue(
    issue: IssueParam,
    title: Annotated[
        str | None, Field(description="new title (unchanged if omitted)")
    ] = None,
    body: Annotated[
        str | None, Field(description="new body (unchanged if omitted)")
    ] = None,
) -> dict[str, str]:
    """update an issue you authored"""
    uri = await _issue_uri(issue)
    rkey = uri.rsplit("/", 1)[-1]
    session = await records.login()
    try:
        existing = await session.get_record(records.ISSUE, rkey)
        record = existing["value"]
        if title is not None:
            record["title"] = title
        if body is not None:
            record["body"] = body
        result = await session.put_record(records.ISSUE, rkey, record)
        return {"uri": result["uri"]}
    finally:
        await session.client.aclose()


@tangled_mcp.tool
async def set_issue_state(
    issue: IssueParam,
    state: Annotated[Literal["open", "closed"], Field(description="new state")],
) -> dict[str, str]:
    """close or reopen an issue"""
    uri = await _issue_uri(issue)
    session = await records.login()
    try:
        record = {
            "$type": records.ISSUE_STATE,
            "issue": uri,
            "state": records.STATE_OPEN if state == "open" else records.STATE_CLOSED,
            "createdAt": records.now(),
        }
        result = await session.put_record(records.ISSUE_STATE, records.tid(), record)
        return {"uri": result["uri"], "state": state}
    finally:
        await session.client.aclose()


@tangled_mcp.tool
async def set_pull_state(
    pull: Annotated[
        str,
        Field(description="pull request at-uri (at://did/sh.tangled.repo.pull/rkey)"),
    ],
    state: Annotated[
        Literal["open", "closed", "merged"], Field(description="new state")
    ],
) -> dict[str, str]:
    """close, reopen, or mark merged a pull request you authored"""
    status = {
        "open": records.PULL_OPEN,
        "closed": records.PULL_CLOSED,
        "merged": records.PULL_MERGED,
    }[state]
    session = await records.login()
    try:
        record = {
            "$type": records.PULL_STATUS,
            "pull": pull,
            "status": status,
            "createdAt": records.now(),
        }
        result = await session.put_record(records.PULL_STATUS, records.tid(), record)
        return {"uri": result["uri"], "state": state}
    finally:
        await session.client.aclose()


@tangled_mcp.tool
async def comment_on_issue(
    issue: IssueParam,
    body: Annotated[str, Field(description="comment body (markdown)")],
) -> dict[str, str]:
    """comment on an issue"""
    uri = await _issue_uri(issue)
    session = await records.login()
    try:
        record = {
            "$type": records.ISSUE_COMMENT,
            "issue": uri,
            "body": body,
            "createdAt": records.now(),
        }
        result = await session.put_record(records.ISSUE_COMMENT, records.tid(), record)
        return {"uri": result["uri"]}
    finally:
        await session.client.aclose()


@tangled_mcp.tool
async def delete_issue(issue: IssueParam) -> dict[str, str]:
    """delete an issue you authored"""
    uri = await _issue_uri(issue)
    session = await records.login()
    try:
        await session.delete_record(records.ISSUE, uri.rsplit("/", 1)[-1])
        return {"deleted": uri}
    finally:
        await session.client.aclose()


def _resolve_labels(names: list[str], repo_label_uris: list[str]) -> list[str]:
    """map label names to the repo's subscribed label definition at-uris"""
    by_name = {uri.rsplit("/", 1)[-1].lower(): uri for uri in repo_label_uris}
    missing = [n for n in names if n.lower() not in by_name]
    if missing:
        raise ValueError(f"invalid labels: {missing}; available: {sorted(by_name)}")
    return [by_name[n.lower()] for n in names]


async def _put_label_op(
    session: records.Session,
    subject: str,
    add: list[str] | None = None,
    delete: list[str] | None = None,
) -> None:
    record = {
        "$type": records.LABEL_OP,
        "subject": subject,
        "add": [{"key": uri, "value": ""} for uri in add or []],
        "delete": [{"key": uri, "value": ""} for uri in delete or []],
        "performedAt": records.now(),
    }
    await session.put_record(records.LABEL_OP, records.tid(), record)

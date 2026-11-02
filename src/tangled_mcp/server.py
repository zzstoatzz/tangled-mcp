"""tangled MCP server

reads go through bobbin (api.tangled.org) and the repo's knot, no auth.
writes go to the repo's knot with a service-auth token from the caller's PDS.
"""

import gzip
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from tangled_mcp import bobbin, records
from tangled_mcp.patch import apply_to_file
from tangled_mcp.patch import synthesize as synthesize_patch
from tangled_mcp.settings import APPVIEW_URL

tangled_mcp = FastMCP("tangled MCP server")

RepoParam = Annotated[
    str,
    Field(
        description="repository as 'owner/repo' (owner may be a handle or DID), "
        "a bare repo DID, or a repo at-uri (as returned by search)"
    ),
]
IssueParam = Annotated[
    str,
    Field(
        description="issue at-uri (at://<repo did>/org.tangled.track.ticket/<number>) "
        "or 'owner/repo#<number>'"
    ),
]
PullParam = Annotated[
    str,
    Field(
        description="pull request at-uri (at://<repo did>/org.tangled.track.ticket/"
        "<number>), 'owner/repo#<number>', or a legacy sh.tangled.repo.pull at-uri"
    ),
]
Limit = Annotated[int, Field(ge=1, le=100)]

PULL_PATCH_ONLY = (
    "tangled no longer accepts patch-only pull requests: a pull is a branch "
    "pushed to a tangled repository (yours or a fork) plus a patch the knot "
    "fetches from it. this server cannot push git, so opening or revising a pull "
    "from edits is unavailable; comment the proposed change on an issue instead."
)


def _text(markup: Any) -> str | None:
    if isinstance(markup, dict):
        return markup.get("text")
    return markup


def _rkey(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _ticket_view(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("value") or item
    view = {
        "uri": item["uri"],
        "number": int(_rkey(item["uri"])),
        "title": _text(value.get("title")),
        "body": _text(value.get("body")),
        "state": item.get("state") or value.get("state"),
        "comment_count": item.get("commentCount"),
        "created_at": value.get("createdAt"),
        "author": _author(item),
    }
    if value.get("targetBranch"):
        view["target_branch"] = value["targetBranch"]
    return view


def _author(item: dict[str, Any]) -> str | None:
    author = item.get("author")
    if isinstance(author, dict):
        return author.get("handle") or author.get("did")
    return author or (item.get("value") or {}).get(records.EDITOR_FIELD)


async def _ticket(ref: str) -> tuple[bobbin.Repo, str]:
    """an issue or pull reference as (repo, ticket number)"""
    if ref.startswith("at://"):
        did, collection, rkey = ref.removeprefix("at://").split("/", 2)
        if collection != records.TICKET:
            raise ValueError(
                f"not a ticket uri: {ref}. issues and pulls are "
                f"{records.TICKET} records on the repository since tangled's "
                "org.tangled migration; find the current uri with list_issues "
                "or list_pulls"
            )
        return await bobbin.resolve_repo(did), rkey
    repo, sep, number = ref.rpartition("#")
    if not sep or not number.isdigit():
        raise ValueError(f"expected a ticket at-uri or 'owner/repo#<number>': {ref}")
    return await bobbin.resolve_repo(repo), number


def _ticket_uri(r: bobbin.Repo, number: str) -> str:
    return f"at://{r.repo_did}/{records.TICKET}/{number}"


def _repo_url(r: bobbin.Repo) -> str:
    return f"{APPVIEW_URL}/{r.owner_did}/{r.name}"


# --- discovery ---------------------------------------------------------------


@tangled_mcp.tool
async def search(
    query: Annotated[str, Field(description="full-text search query")],
    limit: Limit = 20,
) -> list[dict[str, Any]]:
    """search tangled (repos, issues, pulls, strings) via full-text index"""
    body = await bobbin.query("org.tangled.search.query", q=query, limit=limit)
    return [_search_hit(hit) for hit in body.get("hits") or []]


def _search_hit(hit: dict[str, Any]) -> dict[str, Any]:
    value = hit.get("value") or {}
    title = _text(value.get("title")) or (value.get("declaration") or {}).get("name")
    snippet = (
        value.get("description") or _text(value.get("body")) or value.get("contents")
    )
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
    or anything surfaced by search) from where its DID lives"""
    body = await bobbin.get_record(uri)
    return body.get("value") or {}


@tangled_mcp.tool
async def list_repos(
    owner: Annotated[str, Field(description="handle or DID")],
    limit: Limit = 50,
) -> list[dict[str, Any]]:
    """list repositories owned by a user"""
    handle = owner.lstrip("@")
    did = await bobbin.resolve_handle(handle)
    body = await bobbin.query("org.tangled.repo.listRepos", subject=did, limit=limit)
    out = []
    for item in body.get("items") or []:
        value = item.get("value") or {}
        name = (value.get("declaration") or {}).get("name")
        out.append(
            {
                "name": name,
                "repo_did": item["uri"].removeprefix("at://").split("/")[0],
                "description": value.get("description"),
                "url": f"{APPVIEW_URL}/{handle}/{name}",
            }
        )
    return out


@tangled_mcp.tool
async def get_repo(repo: RepoParam) -> dict[str, Any]:
    """get repository metadata: knot, default branch, languages, labels"""
    r = await bobbin.resolve_repo(repo)
    languages = await bobbin.git_query(r, "org.tangled.git.listLanguages")
    labels = await bobbin.list_records(r.repo_did, records.LABEL_DEFINITION)
    return {
        "name": r.name,
        "owner": r.owner_did,
        "repo_did": r.repo_did,
        "knot": r.knot,
        "description": r.description,
        "default_branch": r.default_branch,
        "languages": {
            lang["name"]: lang["percentage"]
            for lang in languages.get("languages") or []
        },
        "labels": [(lbl.get("value") or {}).get("name") for lbl in labels],
        "url": _repo_url(r),
    }


# --- git reads ---------------------------------------------------------------


def _first_line(message: str | None) -> str:
    return (message or "").split("\n")[0]


@tangled_mcp.tool
async def list_branches(repo: RepoParam, limit: Limit = 50) -> list[dict[str, Any]]:
    """list branches with their head commits"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.git_query(r, "org.tangled.git.listBranches", limit=limit)
    return [
        {"name": b["name"], "sha": b["oid"], "message": _first_line(b.get("message"))}
        for b in body.get("branches") or []
    ]


@tangled_mcp.tool
async def list_tags(repo: RepoParam, limit: Limit = 50) -> list[dict[str, Any]]:
    """list tags"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.git_query(r, "org.tangled.git.listTags", limit=limit)
    return [
        {"name": t["name"], "sha": t.get("oid"), "message": t.get("message")}
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
    body = await bobbin.git_query(r, "org.tangled.git.getTree", path=path, ref=ref)
    return [
        {
            "name": f["name"],
            "is_dir": f.get("mode", "").startswith("004"),
            "size": f.get("size"),
        }
        for f in body.get("entries") or []
    ]


@tangled_mcp.tool
async def read_file(
    repo: RepoParam,
    path: Annotated[str, Field(description="file path within the repo")],
    ref: Annotated[str | None, Field(description="branch, tag, or sha")] = None,
) -> str:
    """read a file's contents from a repository"""
    r = await bobbin.resolve_repo(repo)
    return (await bobbin.git_blob(r, path, ref)).decode(errors="replace")


@tangled_mcp.tool
async def commit_log(
    repo: RepoParam,
    ref: Annotated[str | None, Field(description="branch, tag, or sha")] = None,
    limit: Limit = 20,
) -> list[dict[str, Any]]:
    """list recent commits"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.git_query(
        r,
        "org.tangled.git.listCommits",
        ref=ref or r.default_branch or "HEAD",
        limit=limit,
    )
    return [
        {
            "sha": c.get("hash"),
            "message": _first_line(c.get("message")),
            "author": (c.get("author") or {}).get("name"),
            "when": (c.get("author") or {}).get("when"),
        }
        for c in body.get("commits") or []
    ]


def _changed_files(diff: dict[str, Any]) -> list[dict[str, str | None]]:
    return [
        {
            "old_path": (d.get("lhsSrc") or {}).get("path"),
            "new_path": (d.get("rhsSrc") or {}).get("path"),
        }
        for d in diff.get("diffs") or []
    ]


@tangled_mcp.tool
async def compare(
    repo: RepoParam,
    rev1: Annotated[str, Field(description="base revision (branch, tag, or sha)")],
    rev2: Annotated[str, Field(description="head revision (branch, tag, or sha)")],
) -> dict[str, Any]:
    """compare two revisions: diff stats and the files that changed"""
    r = await bobbin.resolve_repo(repo)
    diff = await bobbin.git_query(r, "org.tangled.git.getDiff", base=rev1, head=rev2)
    return {"stats": diff.get("stats"), "files": _changed_files(diff)}


# --- issues & pulls ----------------------------------------------------------


@tangled_mcp.tool
async def list_issues(
    repo: RepoParam,
    state: Annotated[
        Literal["open", "closed", "completed"] | None,
        Field(description="filter by state"),
    ] = None,
    limit: Limit = 20,
) -> list[dict[str, Any]]:
    """list issues on a repository"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.query(
        "org.tangled.repo.listIssues", subject=r.repo_did, state=state, limit=limit
    )
    return [_ticket_view(item) for item in body.get("items") or []]


@tangled_mcp.tool
async def get_issue(issue: IssueParam) -> dict[str, Any]:
    """get a single issue"""
    r, number = await _ticket(issue)
    body = await bobbin.query(
        "org.tangled.track.getTicketView", uri=_ticket_uri(r, number)
    )
    return _ticket_view(body)


@tangled_mcp.tool
async def list_pulls(
    repo: RepoParam,
    status: Annotated[
        Literal["open", "closed", "completed"] | None,
        Field(description="filter by status; a merged pull is completed"),
    ] = None,
    limit: Limit = 20,
) -> list[dict[str, Any]]:
    """list pull requests on a repository"""
    r = await bobbin.resolve_repo(repo)
    body = await bobbin.query(
        "org.tangled.repo.listPulls", subject=r.repo_did, status=status, limit=limit
    )
    return [_ticket_view(item) for item in body.get("items") or []]


@dataclass
class Revision:
    """a pull's latest round. `cid` identifies it for stale-review checks:
    the patch record's cid, or the legacy pull record's for a pull whose
    rounds predate tangled's org.tangled migration."""

    repo: bobbin.Repo
    number: str | None
    rounds: int
    cid: str
    patch: dict[str, Any] | None = None
    legacy: dict[str, Any] | None = None


def _is_legacy(pull: str) -> bool:
    return pull.startswith("at://") and f"/{records.LEGACY_PULL}/" in pull


async def _rounds(r: bobbin.Repo, number: str) -> list[dict[str, Any]]:
    """a pull's patch records, oldest first"""
    patches = await bobbin.list_records(r.repo_did, records.PATCH)
    mine = [p for p in patches if (p.get("value") or {}).get("ticket") == number]
    return sorted(mine, key=lambda p: (p.get("value") or {}).get("createdAt") or "")


async def _legacy_for(r: bobbin.Repo, view: dict[str, Any]) -> dict[str, Any] | None:
    """the legacy pull record a migrated ticket came from: same author, same
    target repo, same title. the migration kept no link, and a match that is
    not unique is treated as none."""
    author = (view.get("author") or {}).get("did")
    title = _text(view.get("title"))
    if not author or not title:
        return None
    legacy = await bobbin.list_records(author, records.LEGACY_PULL)
    matches = [
        rec
        for rec in legacy
        if ((rec.get("value") or {}).get("target") or {}).get("repo") == r.repo_did
        and (rec.get("value") or {}).get("title") == title
    ]
    return matches[0] if len(matches) == 1 else None


async def _revision(pull: str) -> tuple[Revision, dict[str, Any] | None]:
    """the pull's latest round, and its ticket view when it has one"""
    if _is_legacy(pull):
        record = await bobbin.get_record(pull)
        target = (record.get("value") or {}).get("target") or {}
        r = await bobbin.resolve_repo(target.get("repo") or "")
        rounds = len((record.get("value") or {}).get("rounds") or [])
        return Revision(r, None, rounds, record["cid"], legacy=record), None
    r, number = await _ticket(pull)
    view = await bobbin.query(
        "org.tangled.track.getTicketView", uri=_ticket_uri(r, number)
    )
    if rounds := await _rounds(r, number):
        latest = rounds[-1]
        return Revision(r, number, len(rounds), latest["cid"], patch=latest), view
    if legacy := await _legacy_for(r, view):
        rounds_n = len((legacy.get("value") or {}).get("rounds") or [])
        return Revision(r, number, rounds_n, legacy["cid"], legacy=legacy), view
    raise ValueError(f"{pull} has no patch rounds")


@tangled_mcp.tool
async def get_pull(pull: PullParam) -> dict[str, Any]:
    """get a pull request: its ticket, state, and patch rounds.

    `cid` names the latest round. pass it as expected_cid to get_pull_patch
    and comment_on_pull so a review stays tied to the revision it read.
    """
    rev, view = await _revision(pull)
    if view is None:
        assert rev.legacy is not None
        value = rev.legacy.get("value") or {}
        base: dict[str, Any] = {
            "uri": pull,
            "title": value.get("title"),
            "body": value.get("body"),
            "target_branch": (value.get("target") or {}).get("branch"),
            "created_at": value.get("createdAt"),
            "author": pull.removeprefix("at://").split("/")[0],
        }
    else:
        base = _ticket_view(view)
        base["url"] = f"{_repo_url(rev.repo)}/pulls/{rev.number}"
    out = {**base, "rounds": rev.rounds, "cid": rev.cid}
    if rev.patch:
        value = rev.patch["value"]
        out["base"] = value["base"]["oid"]
        out["head"] = value["head"]["oid"]
        out["source"] = value.get("source")
    if rev.legacy:
        out["legacy_pull"] = rev.legacy["uri"]
    return out


@tangled_mcp.tool
async def list_pipelines(repo: RepoParam, limit: Limit = 10) -> list[dict[str, Any]]:
    """list CI pipelines for a repository, from the spindle that runs them"""
    r = await bobbin.resolve_repo(repo)
    if not r.spindle:
        raise ValueError(f"repo '{repo}' has no spindle; it runs no CI")
    host = r.spindle.removeprefix("did:web:")
    response = await bobbin._client.get(
        f"https://{host}/xrpc/org.tangled.ci.queryPipelines",
        params={"repo": r.repo_did, "limit": limit},
    )
    if not response.is_success:
        raise bobbin.BobbinError(
            f"queryPipelines on {host} failed ({response.status_code})",
            status=response.status_code,
        )
    return [
        {
            "id": p.get("id"),
            "commit": p.get("commit"),
            "created_at": p.get("createdAt"),
            "trigger": (p.get("trigger") or {}).get("$type"),
            "workflows": [
                {"name": w.get("name"), "status": w.get("status")}
                for w in p.get("workflows") or []
            ],
        }
        for p in response.json().get("pipelines") or []
    ]


# --- writes (require TANGLED_HANDLE / TANGLED_PASSWORD) -----------------------


async def _label_tokens(r: bobbin.Repo, names: list[str]) -> list[dict[str, str]]:
    """label names to tokens naming the repo's label definitions"""
    defs = await bobbin.list_records(r.repo_did, records.LABEL_DEFINITION)
    by_name = {
        ((d.get("value") or {}).get("name") or "").lower(): _rkey(d["uri"])
        for d in defs
    }
    missing = [n for n in names if n.lower() not in by_name]
    if missing:
        raise ValueError(f"invalid labels: {missing}; available: {sorted(by_name)}")
    return [{"$type": records.LABEL_TOKEN, "key": by_name[n.lower()]} for n in names]


@tangled_mcp.tool
async def create_issue(
    repo: RepoParam,
    title: Annotated[str, Field(description="issue title")],
    body: Annotated[str | None, Field(description="issue body (markdown)")] = None,
    labels: Annotated[
        list[str] | None,
        Field(description="label names from the repo's label set (see get_repo)"),
    ] = None,
) -> dict[str, Any]:
    """create an issue on a repository"""
    r = await bobbin.resolve_repo(repo)
    record: dict[str, Any] = {
        "$type": records.TICKET,
        "title": records.inline(title),
        "state": "open",
        "createdAt": records.now(),
    }
    if body:
        record["body"] = records.markdown(body)
    if labels:
        record["tangledLabels"] = await _label_tokens(r, labels)
    session = await records.login()
    try:
        result = await session.knot_write(
            r, "com.atproto.repo.createRecord", collection=records.TICKET, record=record
        )
    finally:
        await session.client.aclose()
    return {**result, "url": f"{_repo_url(r)}/issues/{_rkey(result['uri'])}"}


async def _edit_ticket(
    ref: str, change: dict[str, Any]
) -> tuple[bobbin.Repo, dict[str, Any]]:
    r, number = await _ticket(ref)
    current = await bobbin.get_record(_ticket_uri(r, number))
    record = {**records.editable(current["value"]), **change}
    session = await records.login()
    try:
        result = await session.knot_write(
            r,
            "com.atproto.repo.putRecord",
            collection=records.TICKET,
            rkey=number,
            swapRecord=current["cid"],
            record=record,
        )
    finally:
        await session.client.aclose()
    return r, result


@tangled_mcp.tool
async def update_issue(
    issue: IssueParam,
    title: Annotated[
        str | None, Field(description="new title (unchanged if omitted)")
    ] = None,
    body: Annotated[
        str | None, Field(description="new body (unchanged if omitted)")
    ] = None,
) -> dict[str, Any]:
    """update an issue's title or body"""
    change: dict[str, Any] = {}
    if title is not None:
        change["title"] = records.inline(title)
    if body is not None:
        change["body"] = records.markdown(body)
    if not change:
        raise ValueError("pass a new title or body")
    _, result = await _edit_ticket(issue, change)
    return result


@tangled_mcp.tool
async def set_issue_state(
    issue: IssueParam,
    state: Annotated[
        Literal["open", "closed", "completed"], Field(description="new state")
    ],
) -> dict[str, Any]:
    """close, complete, or reopen an issue (its author or a maintainer)"""
    _, result = await _edit_ticket(issue, {"state": state})
    return {**result, "state": state}


@tangled_mcp.tool
async def set_pull_state(
    pull: PullParam,
    state: Annotated[Literal["open", "closed"], Field(description="new state")],
) -> dict[str, Any]:
    """close or reopen a pull request (its author or a maintainer)"""
    _, result = await _edit_ticket(pull, {"state": state})
    return {**result, "state": state}


class Edit(BaseModel):
    """desired end-state of one file. content=None deletes it."""

    path: str
    content: str | None = None


@tangled_mcp.tool
async def create_pull(
    repo: RepoParam,
    title: Annotated[str, Field(description="pull request title")],
    patch: Annotated[str | None, Field(description="git format-patch output")] = None,
    edits: Annotated[
        list[Edit] | None,
        Field(description="full desired content per file (content=null deletes)"),
    ] = None,
    target_branch: Annotated[
        str | None, Field(description="branch to merge into")
    ] = None,
    body: Annotated[
        str | None, Field(description="pull request description (markdown)")
    ] = None,
) -> dict[str, str]:
    """open a pull request. unavailable: tangled now opens pulls only from a
    branch pushed to a tangled repository, and this server cannot push."""
    raise ValueError(PULL_PATCH_ONLY)


@tangled_mcp.tool
async def update_pull(
    pull: PullParam,
    edits: Annotated[
        list[Edit],
        Field(description="full desired content per file (content=null deletes)"),
    ],
    note: Annotated[str | None, Field(description="what this round changes")] = None,
) -> dict[str, Any]:
    """push a new round onto a pull request. unavailable for the same reason
    as create_pull: a round is a pushed commit, and this server cannot push."""
    raise ValueError(PULL_PATCH_ONLY)


async def _legacy_patch(record: dict[str, Any]) -> str:
    """a legacy pull record's latest round as patch text, from its blob"""
    rounds = (record.get("value") or {}).get("rounds") or []
    if not rounds:
        raise ValueError("pull request has no rounds")
    ref = (rounds[-1].get("patchBlob") or {}).get("ref") or {}
    cid = ref.get("$link") if isinstance(ref, dict) else None
    if not cid:
        raise ValueError("latest round has no patch blob")
    author = record["uri"].removeprefix("at://").split("/")[0]
    pds = await records.discover_pds(author)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{pds}/xrpc/com.atproto.sync.getBlob",
            params={"did": author, "cid": cid},
        )
        response.raise_for_status()
        data = response.content
    try:
        return gzip.decompress(data).decode()
    except (OSError, EOFError):
        return data.decode()


async def _blob_or_none(r: bobbin.Repo, path: str | None, ref: str) -> str | None:
    if not path:
        return None
    try:
        return (await bobbin.git_blob(r, path, ref)).decode(errors="replace")
    except bobbin.BobbinError as err:
        if err.status == 404:
            return None
        raise


def _check_revision(rev: Revision, expected_cid: str | None) -> None:
    if expected_cid is not None and rev.cid != expected_cid:
        raise ValueError("Pull changed; fetch and review the new revision")


@tangled_mcp.tool
async def get_pull_patch(
    pull: PullParam,
    expected_cid: Annotated[
        str | None,
        Field(
            description="cid from get_pull, captured before review; reject if changed"
        ),
    ] = None,
) -> str:
    """the pull request's latest round as git format-patch text: the whole
    change against its base, every file. read this to review a pull;
    get_pull_file is for one file's resulting content."""
    rev, view = await _revision(pull)
    _check_revision(rev, expected_cid)
    if rev.legacy:
        return await _legacy_patch(rev.legacy)
    assert rev.patch is not None and view is not None
    value = rev.patch["value"]
    base, head = value["base"]["oid"], value["head"]["oid"]
    diff = await bobbin.git_query(
        rev.repo, "org.tangled.git.getDiff", base=base, head=head
    )
    files = []
    for d in diff.get("diffs") or []:
        lhs, rhs = d.get("lhsSrc") or {}, d.get("rhsSrc") or {}
        if lhs.get("isBinary") or rhs.get("isBinary"):
            continue
        old = await _blob_or_none(rev.repo, lhs.get("path"), base)
        new = await _blob_or_none(rev.repo, rhs.get("path"), head)
        files.append((rhs.get("path") or lhs.get("path"), old, new))
    title = _text(view.get("title")) or "pull"
    return synthesize_patch(title, _author(view) or "", files)


@tangled_mcp.tool
async def get_pull_file(
    pull: PullParam,
    path: Annotated[str, Field(description="file path within the repo")],
) -> str:
    """a file as the pull request's latest round leaves it. revise or review
    from this, not from read_file on the target branch: the branch does not
    have the pull's changes yet."""
    rev, _ = await _revision(pull)
    if rev.legacy:
        target = (rev.legacy.get("value") or {}).get("target") or {}
        branch = target.get("branch") or rev.repo.default_branch or "main"
        base = await _blob_or_none(rev.repo, path, branch) or ""
        content = apply_to_file(await _legacy_patch(rev.legacy), path, base)
        return base if content is None else content
    assert rev.patch is not None
    content = await _blob_or_none(rev.repo, path, rev.patch["value"]["head"]["oid"])
    if content is None:
        raise ValueError(f"'{path}' does not exist in the pull's latest round")
    return content


@tangled_mcp.tool
async def comment_on_issue(
    issue: IssueParam,
    body: Annotated[str, Field(description="comment body (markdown)")],
) -> dict[str, Any]:
    """comment on an issue"""
    r, number = await _ticket(issue)
    ticket = await bobbin.get_record(_ticket_uri(r, number))
    return await _comment(r, {"uri": ticket["uri"], "cid": ticket["cid"]}, body)


async def _comment(
    r: bobbin.Repo, subject: dict[str, str], body: str
) -> dict[str, Any]:
    record = {
        "$type": records.COMMENT,
        "subject": subject,
        "body": records.markdown(body),
        "createdAt": records.now(),
    }
    session = await records.login()
    try:
        return await session.knot_write(
            r,
            "com.atproto.repo.createRecord",
            collection=records.COMMENT,
            record=record,
        )
    finally:
        await session.client.aclose()


@tangled_mcp.tool
async def comment_on_pull(
    pull: PullParam,
    body: Annotated[str, Field(description="comment body (markdown)")],
    expected_cid: Annotated[
        str | None,
        Field(
            description="cid from get_pull of the round reviewed; rejects stale reviews"
        ),
    ] = None,
) -> dict[str, Any]:
    """comment on a pull request. the comment points at the latest round when
    it has a patch record, so a review stays attached to the revision it read."""
    if (
        re.search(r"VERDICT:\s*(approve|request-changes|escalate)", body, re.IGNORECASE)
        and not expected_cid
    ):
        raise ValueError("Review verdicts require the CID of the revision reviewed")
    rev, _ = await _revision(pull)
    _check_revision(rev, expected_cid)
    if rev.number is None:
        raise ValueError(
            "comments go on the pull's ticket; pass its ticket uri (find it with "
            "list_pulls) instead of the legacy pull record"
        )
    if rev.patch:
        subject = {"uri": rev.patch["uri"], "cid": rev.patch["cid"]}
    else:
        ticket = await bobbin.get_record(_ticket_uri(rev.repo, rev.number))
        subject = {"uri": ticket["uri"], "cid": ticket["cid"]}
    return await _comment(rev.repo, subject, body)


@tangled_mcp.tool
async def delete_issue(issue: IssueParam) -> dict[str, str]:
    """delete an issue you authored"""
    r, number = await _ticket(issue)
    current = await bobbin.get_record(_ticket_uri(r, number))
    session = await records.login()
    try:
        await session.knot(
            r,
            "com.atproto.repo.deleteRecord",
            collection=records.TICKET,
            rkey=number,
            swapRecord=current["cid"],
        )
    finally:
        await session.client.aclose()
    return {"deleted": current["uri"]}

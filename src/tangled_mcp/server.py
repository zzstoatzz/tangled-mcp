"""tangled MCP server - provides tools and resources for tangled git platform"""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from tangled_mcp import _tangled
from tangled_mcp.types import (
    CreateIssueResult,
    CreatePullResult,
    DeleteIssueResult,
    ListBranchesResult,
    ListIssuesResult,
    ListPullsResult,
    UpdateIssueResult,
    UpdatePullResult,
)

tangled_mcp = FastMCP("tangled MCP server")


# resources - read-only operations
@tangled_mcp.resource("tangled://status")
def tangled_status() -> dict[str, str | bool]:
    """check the status of the tangled connection"""
    client = _tangled._get_authenticated_client()

    # verify can get tangled service token
    try:
        _tangled.get_service_token()
        can_access_tangled = True
    except Exception:
        can_access_tangled = False

    if not client.me:
        raise RuntimeError("client not authenticated")

    return {
        "handle": client.me.handle,
        "did": client.me.did,
        "pds_authenticated": True,
        "tangled_accessible": can_access_tangled,
    }


# tools - actions that query or modify state
@tangled_mcp.tool
def list_repo_branches(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
    limit: Annotated[
        int, Field(ge=1, le=100, description="maximum number of branches to return")
    ] = 50,
    cursor: Annotated[str | None, Field(description="pagination cursor")] = None,
) -> ListBranchesResult:
    """list branches for a repository

    Args:
        repo: repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')
        limit: maximum number of branches to return (1-100)
        cursor: optional pagination cursor

    Returns:
        list of branches with optional cursor for pagination
    """
    # resolve owner/repo to (knot, did/repo)
    knot, repo_id = _tangled.resolve_repo_identifier(repo)
    response = _tangled.list_branches(knot, repo_id, limit, cursor)

    return ListBranchesResult.from_api_response(response)


@tangled_mcp.tool
def create_repo_issue(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
    title: Annotated[str, Field(description="issue title")],
    body: Annotated[str | None, Field(description="issue body/description")] = None,
    labels: Annotated[
        list[str] | None,
        Field(
            description="optional list of label names (e.g., ['good-first-issue', 'bug']) "
            "to apply to the issue"
        ),
    ] = None,
) -> CreateIssueResult:
    """create an issue on a repository

    Args:
        repo: repository identifier in 'owner/repo' format
        title: issue title
        body: optional issue body/description
        labels: optional list of label names to apply

    Returns:
        CreateIssueResult with url (clickable link) and issue_id
    """
    # resolve owner/repo to (knot, did/repo)
    knot, repo_id = _tangled.resolve_repo_identifier(repo)
    # create_issue doesn't need knot (uses atproto putRecord, not XRPC)
    response = _tangled.create_issue(repo_id, title, body, labels)

    return CreateIssueResult(repo=repo, issue_id=response["issueId"])


@tangled_mcp.tool
def update_repo_issue(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
    issue_id: Annotated[int, Field(description="issue number (e.g., 1, 2, 3...)")],
    title: Annotated[str | None, Field(description="new issue title")] = None,
    body: Annotated[str | None, Field(description="new issue body/description")] = None,
    labels: Annotated[
        list[str] | None,
        Field(
            description="list of label names to SET (replaces all existing labels). "
            "use empty list [] to remove all labels"
        ),
    ] = None,
) -> UpdateIssueResult:
    """update an existing issue on a repository

    Args:
        repo: repository identifier in 'owner/repo' format
        issue_id: issue number to update
        title: optional new title (if None, keeps existing)
        body: optional new body (if None, keeps existing)
        labels: optional list of label names to SET (replaces existing)

    Returns:
        UpdateIssueResult with url (clickable link) and issue_id
    """
    # resolve owner/repo to (knot, did/repo)
    knot, repo_id = _tangled.resolve_repo_identifier(repo)
    # update_issue doesn't need knot (uses atproto putRecord, not XRPC)
    _tangled.update_issue(repo_id, issue_id, title, body, labels)

    return UpdateIssueResult(repo=repo, issue_id=issue_id)


@tangled_mcp.tool
def delete_repo_issue(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
    issue_id: Annotated[
        int, Field(description="issue number to delete (e.g., 1, 2, 3...)")
    ],
) -> DeleteIssueResult:
    """delete an issue from a repository

    Args:
        repo: repository identifier in 'owner/repo' format
        issue_id: issue number to delete

    Returns:
        DeleteIssueResult with issue_id of deleted issue
    """
    # resolve owner/repo to (knot, did/repo)
    _, repo_id = _tangled.resolve_repo_identifier(repo)
    # delete_issue doesn't need knot (uses atproto deleteRecord, not XRPC)
    _tangled.delete_issue(repo_id, issue_id)

    return DeleteIssueResult(issue_id=issue_id)


@tangled_mcp.tool
def list_repo_issues(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
    limit: Annotated[
        int, Field(ge=1, le=100, description="maximum number of issues to return")
    ] = 20,
    cursor: Annotated[str | None, Field(description="pagination cursor")] = None,
) -> ListIssuesResult:
    """list issues for a repository

    Args:
        repo: repository identifier in 'owner/repo' format
        limit: maximum number of issues to return (1-100)
        cursor: optional pagination cursor

    Returns:
        ListIssuesResult with list of issues and optional cursor
    """
    # resolve owner/repo to (knot, did/repo)
    _, repo_id = _tangled.resolve_repo_identifier(repo)
    # list_repo_issues doesn't need knot (queries atproto records, not XRPC)
    response = _tangled.list_repo_issues(repo_id, limit, cursor)

    return ListIssuesResult.from_api_response(response)


@tangled_mcp.tool
def list_repo_labels(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
) -> list[str]:
    """list available labels for a repository

    Args:
        repo: repository identifier in 'owner/repo' format

    Returns:
        list of available label names for the repository
    """
    # resolve owner/repo to (knot, did/repo)
    _, repo_id = _tangled.resolve_repo_identifier(repo)
    # list_repo_labels doesn't need knot (queries atproto records, not XRPC)
    return _tangled.list_repo_labels(repo_id)


@tangled_mcp.tool
def create_repo_pull(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
    title: Annotated[str, Field(description="pull request title")],
    base: Annotated[str, Field(description="target branch (e.g., 'main')")],
    head: Annotated[str, Field(description="source branch (e.g., 'feature-branch')")],
    patch: Annotated[str, Field(description="git diff content")],
    body: Annotated[str | None, Field(description="pull request description")] = None,
    source_sha: Annotated[
        str | None, Field(description="40-character commit hash")
    ] = None,
    labels: Annotated[
        list[str] | None,
        Field(
            description="optional list of label names (e.g., ['enhancement', 'needs-review']) "
            "to apply to the pull request"
        ),
    ] = None,
) -> CreatePullResult:
    """create a pull request on a repository

    Args:
        repo: repository identifier in 'owner/repo' format
        title: pull request title
        base: target branch
        head: source branch
        patch: git diff content
        body: optional pull request description
        source_sha: optional 40-character commit hash
        labels: optional list of label names to apply

    Returns:
        CreatePullResult with url (clickable link) and pull_id
    """
    # resolve owner/repo to (knot, did/repo)
    _, repo_id = _tangled.resolve_repo_identifier(repo)
    # create_repo_pull doesn't need knot (uses atproto putRecord, not XRPC)
    response = _tangled.create_repo_pull(
        repo_id, title, base, head, patch, body, source_sha, labels
    )

    return CreatePullResult(repo=repo, pull_id=response["pullId"])


@tangled_mcp.tool
def list_repo_pulls(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="maximum number of pull requests to return"),
    ] = 50,
    cursor: Annotated[str | None, Field(description="pagination cursor")] = None,
) -> ListPullsResult:
    """list pull requests for a repository

    Args:
        repo: repository identifier in 'owner/repo' format
        limit: maximum number of pull requests to return (1-100)
        cursor: optional pagination cursor

    Returns:
        ListPullsResult with list of pull requests and optional cursor
    """
    # resolve owner/repo to (knot, did/repo)
    _, repo_id = _tangled.resolve_repo_identifier(repo)
    # list_repo_pulls doesn't need knot (queries atproto records, not XRPC)
    response = _tangled.list_repo_pulls(repo_id, limit, cursor)

    return ListPullsResult.from_api_response(response)


@tangled_mcp.tool
def get_repo_pull(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
    pull_id: Annotated[
        int, Field(description="pull request number (e.g., 1, 2, 3...)")
    ],
) -> dict:
    """get detailed information about a specific pull request

    Args:
        repo: repository identifier in 'owner/repo' format
        pull_id: pull request number

    Returns:
        dict with pull request details including title, body, base, head, patch, labels
    """
    # resolve owner/repo to (knot, did/repo)
    _, repo_id = _tangled.resolve_repo_identifier(repo)
    # get_repo_pull doesn't need knot (queries atproto records, not XRPC)
    return _tangled.get_repo_pull(repo_id, pull_id)


@tangled_mcp.tool
def update_repo_pull(
    repo: Annotated[
        str,
        Field(
            description="repository identifier in 'owner/repo' format (e.g., 'zzstoatzz/tangled-mcp')"
        ),
    ],
    pull_id: Annotated[
        int, Field(description="pull request number (e.g., 1, 2, 3...)")
    ],
    title: Annotated[str | None, Field(description="new pull request title")] = None,
    body: Annotated[
        str | None, Field(description="new pull request description")
    ] = None,
    base: Annotated[str | None, Field(description="new target branch")] = None,
    labels: Annotated[
        list[str] | None,
        Field(
            description="list of label names to SET (replaces all existing labels). "
            "use empty list [] to remove all labels"
        ),
    ] = None,
) -> UpdatePullResult:
    """update an existing pull request on a repository

    Args:
        repo: repository identifier in 'owner/repo' format
        pull_id: pull request number to update
        title: optional new title (if None, keeps existing)
        body: optional new body (if None, keeps existing)
        base: optional new target branch (if None, keeps existing)
        labels: optional list of label names to SET (replaces existing)

    Returns:
        UpdatePullResult with url (clickable link) and pull_id
    """
    # resolve owner/repo to (knot, did/repo)
    _, repo_id = _tangled.resolve_repo_identifier(repo)
    # update_repo_pull doesn't need knot (uses atproto putRecord, not XRPC)
    _tangled.update_repo_pull(repo_id, pull_id, title, body, base, labels)

    return UpdatePullResult(repo=repo, pull_id=pull_id)

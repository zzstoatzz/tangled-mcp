"""tangled MCP server - provides tools and resources for tangled git platform"""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from tangled_mcp import _tangled
from tangled_mcp.types import BranchInfo, ListBranchesResult

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

    # parse response into BranchInfo objects
    branches = []
    if "branches" in response:
        for branch_data in response["branches"]:
            ref = branch_data.get("reference", {})
            branches.append(
                BranchInfo(
                    name=ref.get("name", ""),
                    sha=ref.get("hash", ""),
                )
            )

    return ListBranchesResult(branches=branches, cursor=response.get("cursor"))


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
) -> dict[str, str]:
    """create an issue on a repository

    Args:
        repo: repository identifier in 'owner/repo' format
        title: issue title
        body: optional issue body/description

    Returns:
        dict with uri and cid of created issue
    """
    # resolve owner/repo to (knot, did/repo)
    knot, repo_id = _tangled.resolve_repo_identifier(repo)
    # create_issue doesn't need knot (uses atproto putRecord, not XRPC)
    response = _tangled.create_issue(repo_id, title, body)
    return {"uri": response["uri"], "cid": response["cid"]}


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
    ] = 50,
    cursor: Annotated[str | None, Field(description="pagination cursor")] = None,
) -> dict[str, Any]:
    """list issues for a repository

    Args:
        repo: repository identifier in 'owner/repo' format
        limit: maximum number of issues to return (1-100)
        cursor: optional pagination cursor

    Returns:
        dict with list of issues and optional cursor
    """
    # resolve owner/repo to (knot, did/repo)
    knot, repo_id = _tangled.resolve_repo_identifier(repo)
    # list_repo_issues doesn't need knot (queries atproto records, not XRPC)
    response = _tangled.list_repo_issues(repo_id, limit, cursor)

    return {
        "issues": response["issues"],
        "cursor": response.get("cursor"),
    }

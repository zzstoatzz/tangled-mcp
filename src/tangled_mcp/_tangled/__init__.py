"""tangled API client"""

from tangled_mcp._tangled._client import (
    _get_authenticated_client,
    get_service_token,
    list_branches,
    resolve_repo_identifier,
)
from tangled_mcp._tangled._issues import (
    create_issue,
    delete_issue,
    list_repo_issues,
    list_repo_labels,
    update_issue,
)
from tangled_mcp._tangled._pulls import (
    create_repo_pull,
    get_repo_pull,
    list_repo_pulls,
    update_repo_pull,
)

__all__ = [
    "_get_authenticated_client",
    "get_service_token",
    "list_branches",
    "create_issue",
    "update_issue",
    "delete_issue",
    "list_repo_issues",
    "list_repo_labels",
    "create_repo_pull",
    "list_repo_pulls",
    "get_repo_pull",
    "update_repo_pull",
    "resolve_repo_identifier",
]

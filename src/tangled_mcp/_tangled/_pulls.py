"""pull request operations for tangled"""

from typing import Any

from atproto import models

from tangled_mcp._tangled._client import _get_authenticated_client


def list_repo_pulls(repo_id: str, limit: int = 50) -> dict[str, Any]:
    """list pull requests created by the authenticated user for a repository

    note: this only returns PRs that the authenticated user created.
    tangled stores PRs in the creator's repo, so we can only see our own PRs.

    Args:
        repo_id: repository identifier in "did/repo" format
        limit: maximum number of pulls to return

    Returns:
        dict containing pulls list
    """
    client = _get_authenticated_client()

    if not client.me:
        raise RuntimeError("client not authenticated")

    # parse repo_id to get owner_did and repo_name
    if "/" not in repo_id:
        raise ValueError(f"invalid repo_id format: {repo_id}")

    owner_did, repo_name = repo_id.split("/", 1)

    # get the repo AT-URI by querying the repo collection
    records = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=owner_did,
            collection="sh.tangled.repo",
            limit=100,
        )
    )

    repo_at_uri = None
    for record in records.records:
        if (name := getattr(record.value, "name", None)) is not None and name == repo_name:
            repo_at_uri = record.uri
            break

    if not repo_at_uri:
        raise ValueError(f"repo not found: {repo_id}")

    # list pull records from the authenticated user's collection
    response = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.pull",
            limit=limit,
        )
    )

    # filter pulls by target repo and convert to dict format
    pulls = []
    for record in response.records:
        value = record.value
        target = getattr(value, "target", None)
        if not target:
            continue

        target_repo = getattr(target, "repo", None)
        if target_repo != repo_at_uri:
            continue

        source = getattr(value, "source", {})
        pulls.append(
            {
                "uri": record.uri,
                "cid": record.cid,
                "title": getattr(value, "title", ""),
                "source": {
                    "sha": getattr(source, "sha", ""),
                    "branch": getattr(source, "branch", ""),
                    "repo": getattr(source, "repo", None),
                },
                "target": {
                    "repo": target_repo,
                    "branch": getattr(target, "branch", ""),
                },
                "createdAt": getattr(value, "createdAt", ""),
            }
        )

    return {"pulls": pulls}

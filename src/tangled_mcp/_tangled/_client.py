"""tangled XRPC client implementation"""

from datetime import datetime, timezone
from typing import Any

import httpx
from atproto import Client, models

from tangled_mcp.settings import TANGLED_APPVIEW_URL, TANGLED_DID, settings


def resolve_repo_identifier(owner_slash_repo: str) -> tuple[str, str]:
    """resolve owner/repo format to (knot, did/repo) for tangled XRPC

    Args:
        owner_slash_repo: repository identifier in "owner/repo" or "@owner/repo" format
                         (e.g., "zzstoatzz.io/tangled-mcp" or "@zzstoatzz.io/tangled-mcp")

    Returns:
        tuple of (knot_url, repo_identifier) where:
        - knot_url: hostname of knot hosting the repo (e.g., "knot1.tangled.sh")
        - repo_identifier: "did/repo" format (e.g., "did:plc:.../tangled-mcp")

    Raises:
        ValueError: if format is invalid, handle cannot be resolved, or repo not found
    """
    if "/" not in owner_slash_repo:
        raise ValueError(
            f"invalid repo format: '{owner_slash_repo}'. expected 'owner/repo'"
        )

    owner, repo_name = owner_slash_repo.split("/", 1)
    client = _get_authenticated_client()

    # resolve owner (handle or DID) to DID
    if owner.startswith("did:"):
        owner_did = owner
    else:
        # strip @ prefix if present
        owner = owner.lstrip("@")
        # resolve handle to DID
        try:
            response = client.com.atproto.identity.resolve_handle(
                params={"handle": owner}
            )
            owner_did = response.did
        except Exception as e:
            raise ValueError(f"failed to resolve handle '{owner}': {e}") from e

    # query owner's repo collection to find repo and get knot
    try:
        records = client.com.atproto.repo.list_records(
            models.ComAtprotoRepoListRecords.Params(
                repo=owner_did,
                collection="sh.tangled.repo",  # correct collection name
                limit=100,
            )
        )
    except Exception as e:
        raise ValueError(f"failed to list repos for '{owner}': {e}") from e

    # find repo with matching name and extract knot
    for record in records.records:
        if hasattr(record.value, "name") and record.value.name == repo_name:
            knot = getattr(record.value, "knot", None)
            if not knot:
                raise ValueError(f"repo '{repo_name}' has no knot information")
            return (knot, f"{owner_did}/{repo_name}")

    raise ValueError(f"repo '{repo_name}' not found for owner '{owner}'")


def _get_authenticated_client() -> Client:
    """get authenticated AT Protocol client

    Returns:
        authenticated client connected to user's PDS
    """
    if settings.tangled_pds_url:
        client = Client(base_url=settings.tangled_pds_url)
    else:
        client = Client()  # auto-discover from handle

    client.login(settings.tangled_handle, settings.tangled_password)
    return client


def get_service_token() -> str:
    """get service auth token for tangled

    auth flow:
    1. authenticate to user's PDS (auto-discovered from handle or specified)
    2. call com.atproto.server.getServiceAuth to get token for tangled
    3. use that token for tangled XRPC calls
    """
    client = _get_authenticated_client()

    # get service auth token for tangled
    # without lxm, token expires in 60 seconds max
    response = client.com.atproto.server.get_service_auth(
        params={
            "aud": TANGLED_DID,
            # no lxm = general token, 60 sec max
            # could specify lxm for longer tokens per method
        }
    )

    return response.token


def make_tangled_request(
    method: str,
    params: dict[str, Any] | None = None,
    knot: str | None = None,
) -> dict[str, Any]:
    """make an XRPC request to tangled's knot

    Args:
        method: XRPC method (e.g., 'sh.tangled.repo.branches')
        params: query parameters for the request
        knot: optional knot hostname (if not provided, must be in params["repo"])

    Returns:
        response data from tangled
    """
    token = get_service_token()

    # if knot not provided, extract from repo identifier
    if not knot and params and "repo" in params:
        raise ValueError("knot must be provided or repo must be resolved first")

    url = f"https://{knot}/xrpc/{method}"

    response = httpx.get(
        url,
        params=params or {},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )

    response.raise_for_status()
    return response.json()


def list_branches(
    knot: str, repo: str, limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    """list branches for a repository

    Args:
        knot: knot hostname (e.g., 'knot1.tangled.sh')
        repo: repository identifier in "did/repo" format (e.g., 'did:plc:.../repoName')
        limit: maximum number of branches to return
        cursor: pagination cursor

    Returns:
        dict containing branches and optional cursor
    """
    params = {"repo": repo, "limit": limit}
    if cursor:
        params["cursor"] = cursor

    return make_tangled_request("sh.tangled.repo.branches", params, knot=knot)


def create_issue(repo: str, title: str, body: str | None = None) -> dict[str, Any]:
    """create an issue on a repository

    Args:
        repo: repository AT-URI (e.g., 'at://did:plc:.../sh.tangled.repo.repo/...')
        title: issue title
        body: optional issue body/description

    Returns:
        dict with uri and cid of created issue record
    """
    client = _get_authenticated_client()

    if not client.me:
        raise RuntimeError("client not authenticated")

    # generate timestamp ID for rkey
    tid = int(datetime.now(timezone.utc).timestamp() * 1000000)
    rkey = str(tid)

    # create issue record
    record = {
        "$type": "sh.tangled.repo.issue",
        "repo": repo,
        "title": title,
        "body": body,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # use putRecord to create the issue
    response = client.com.atproto.repo.put_record(
        models.ComAtprotoRepoPutRecord.Data(
            repo=client.me.did,
            collection="sh.tangled.repo.issue",
            rkey=rkey,
            record=record,
        )
    )

    return {"uri": response.uri, "cid": response.cid}


def list_repo_issues(
    repo: str, limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    """list issues for a repository

    Args:
        repo: repository AT-URI
        limit: maximum number of issues to return
        cursor: pagination cursor

    Returns:
        dict containing issues and optional cursor
    """
    client = _get_authenticated_client()

    if not client.me:
        raise RuntimeError("client not authenticated")

    # list records from the issue collection
    response = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.issue",
            limit=limit,
            cursor=cursor,
        )
    )

    # filter issues by repo
    issues = []
    for record in response.records:
        if hasattr(record.value, "repo") and record.value.repo == repo:
            issues.append(
                {
                    "uri": record.uri,
                    "cid": record.cid,
                    "title": getattr(record.value, "title", ""),
                    "body": getattr(record.value, "body", None),
                    "createdAt": getattr(record.value, "created_at", ""),
                }
            )

    return {"issues": issues, "cursor": response.cursor}

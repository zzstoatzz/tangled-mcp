"""tangled XRPC client - core auth, repo resolution, and branch operations"""

from typing import Any

import httpx
from atproto import Client, models

from tangled_mcp.settings import TANGLED_DID, settings


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
        if (name := getattr(record.value, "name", None)) and name == repo_name:
            knot = getattr(record.value, "knot", None)
            if not knot:
                raise ValueError(f"repo '{repo_name}' has no knot information")
            return (knot, f"{owner_did}/{repo_name}")

    raise ValueError(f"repo '{repo_name}' not found for owner '{owner}'")


def _get_authenticated_client() -> Client:
    """get authenticated AT Protocol client

    Returns:
        authenticated client connected to user's PDS

    Raises:
        RuntimeError: if authentication fails (check handle/password)
    """
    if settings.tangled_pds_url:
        client = Client(base_url=settings.tangled_pds_url)
    else:
        client = Client()  # auto-discover from handle

    try:
        client.login(settings.tangled_handle, settings.tangled_password)
    except Exception as e:
        raise RuntimeError(
            f"failed to authenticate with handle '{settings.tangled_handle}'. "
            f"verify TANGLED_HANDLE and TANGLED_PASSWORD are correct. "
            f"error: {e}"
        ) from e

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


# issue operations have been moved to _issues.py

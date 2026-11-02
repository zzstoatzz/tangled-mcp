"""read client for tangled's public XRPC surfaces.

bobbin (api.tangled.org) is the read-only index: repos, tickets, comments,
search. git data (trees, blobs, commits, diffs) is served by the knot that
hosts the repository, keyed by the repository's own DID. neither needs auth.
see docs/bobbin-api.md for the endpoint map and data-model notes.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from tangled_mcp.settings import BOBBIN_URL

_client = httpx.AsyncClient(timeout=15.0)

MANIFEST = "org.tangled.repo.manifest"
LEGACY_REPO = "sh.tangled.repo"


class BobbinError(RuntimeError):
    """an xrpc read failed. `status` is the HTTP status when there was one,
    so callers can tell not-found from everything else."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _failure(where: str, response: httpx.Response) -> BobbinError:
    try:
        payload = response.json()
        message = f"{payload.get('error', 'error')}: {payload.get('message', '')}"
    except Exception:
        message = response.text[:200]
    return BobbinError(
        f"{where} failed ({response.status_code}) {message}",
        status=response.status_code,
    )


async def query(nsid: str, **params: Any) -> dict[str, Any]:
    """GET /xrpc/<nsid> against bobbin, raising a clean error on failure"""
    clean = {k: v for k, v in params.items() if v is not None}
    response = await _client.get(f"{BOBBIN_URL}/xrpc/{nsid}", params=clean)
    if response.is_success:
        return response.json()
    raise _failure(nsid, response)


async def resolve_handle(handle: str) -> str:
    """resolve an atproto handle to a DID"""
    if handle.startswith("did:"):
        return handle
    response = await _client.get(
        "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle",
        params={"handle": handle},
    )
    if not response.is_success:
        raise BobbinError(f"could not resolve handle '{handle}'")
    return response.json()["did"]


async def resolve_pds(did: str) -> str:
    """resolve a DID to its PDS endpoint (supports did:plc and did:web).

    a repository DID's PDS is the knot that hosts it, so this also finds
    where tickets, patches, and comments live.
    """
    if did.startswith("did:plc:"):
        response = await _client.get(f"https://plc.directory/{did}")
    elif did.startswith("did:web:"):
        host = did.removeprefix("did:web:")
        response = await _client.get(f"https://{host}/.well-known/did.json")
    else:
        raise BobbinError(f"unsupported DID method: {did}")
    if not response.is_success:
        raise BobbinError(f"could not resolve DID document for {did}")
    doc = response.json()
    for service in doc.get("service") or []:
        if service.get("type") == "AtprotoPersonalDataServer":
            return service["serviceEndpoint"]
    raise BobbinError(f"no PDS in DID document for {did}")


async def list_records(
    did: str, collection: str, max_pages: int = 5
) -> list[dict[str, Any]]:
    """page a collection straight off a repo's PDS (or knot, for a repo DID)"""
    pds = await resolve_pds(did)
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(max_pages):
        params: dict[str, Any] = {"repo": did, "collection": collection, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = await _client.get(
            f"{pds}/xrpc/com.atproto.repo.listRecords", params=params
        )
        if not response.is_success:
            raise _failure(f"listRecords {collection}", response)
        body = response.json()
        out.extend(body.get("records") or [])
        cursor = body.get("cursor")
        if not cursor:
            break
    return out


async def get_record(uri: str) -> dict[str, Any]:
    """fetch any public atproto record by at-uri from where its DID lives"""
    parts = uri.removeprefix("at://").split("/")
    if len(parts) != 3:
        raise ValueError(f"invalid at-uri: '{uri}'")
    did, collection, rkey = parts
    pds = await resolve_pds(did)
    response = await _client.get(
        f"{pds}/xrpc/com.atproto.repo.getRecord",
        params={"repo": did, "collection": collection, "rkey": rkey},
    )
    if not response.is_success:
        raise BobbinError(f"record not found: {uri}", status=response.status_code)
    return response.json()


@dataclass
class Repo:
    owner_did: str
    name: str
    repo_did: str
    knot: str
    default_branch: str | None
    description: str | None
    spindle: str | None = None

    @property
    def uri(self) -> str:
        """the repository's manifest, on the repo DID's own account"""
        return f"at://{self.repo_did}/{MANIFEST}/self"


def _repo_from_view(body: dict[str, Any]) -> Repo:
    value = body.get("value") or {}
    declaration = value.get("declaration") or {}
    return Repo(
        owner_did=declaration.get("owner") or "",
        name=declaration.get("name") or "",
        repo_did=body["uri"].removeprefix("at://").split("/")[0],
        knot=body.get("knot") or "",
        default_branch=body.get("defaultBranch"),
        description=value.get("description"),
        spindle=value.get("spindle"),
    )


async def resolve_repo(identifier: str) -> Repo:
    """resolve a repo identifier to a hydrated Repo.

    accepts 'owner/repo' (handle or DID owner), a bare repo DID, the repo's
    manifest at-uri, or a legacy sh.tangled.repo at-uri (owner/rkey=name).
    """
    if identifier.startswith("at://"):
        did, collection, rkey = (identifier.removeprefix("at://").split("/") + [""])[:3]
        if collection == LEGACY_REPO:
            return await _by_name(did, rkey)
        return await _by_repo_did(did)
    if identifier.startswith("did:") and "/" not in identifier:
        return await _by_repo_did(identifier)
    if "/" not in identifier:
        raise ValueError(
            f"invalid repo identifier: '{identifier}', expected 'owner/repo', "
            "an at-uri, or a repo DID"
        )
    owner, name = identifier.lstrip("@").split("/", 1)
    return await _by_name(await resolve_handle(owner), name)


async def _by_name(owner_did: str, name: str) -> Repo:
    try:
        body = await query("org.tangled.repo.getRepoByName", owner=owner_did, name=name)
    except BobbinError as err:
        if err.status in (400, 404):
            raise ValueError(
                f"repo '{name}' not found for owner '{owner_did}'"
            ) from err
        raise
    return _repo_from_view(body)


async def _by_repo_did(repo_did: str) -> Repo:
    return _repo_from_view(
        await query("org.tangled.repo.getRepoByRepoDid", repoDid=repo_did)
    )


async def _knot_get(r: Repo, nsid: str, **params: Any) -> httpx.Response:
    if not r.knot:
        raise BobbinError(f"repo '{r.name}' has no knot")
    clean = {k: v for k, v in params.items() if v is not None}
    response = await _client.get(
        f"https://{r.knot}/xrpc/{nsid}", params={"repo": r.repo_did, **clean}
    )
    if response.is_success:
        return response
    raise _failure(f"{nsid} on knot {r.knot}", response)


async def git_query(r: Repo, nsid: str, **params: Any) -> dict[str, Any]:
    """an org.tangled.git.* query on the repo's knot, by repo DID"""
    return (await _knot_get(r, nsid, **params)).json()


async def git_blob(r: Repo, path: str, ref: str | None = None) -> bytes:
    """a file's raw bytes at `ref`. a missing path raises with status 404."""
    response = await _knot_get(r, "org.tangled.git.getBlob", path=path, ref=ref)
    return response.content

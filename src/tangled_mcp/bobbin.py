"""read client for bobbin, tangled's public XRPC API (api.tangled.org).

bobbin is read-only and unauthenticated. see docs/bobbin-api.md for the
endpoint map and data-model notes.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from tangled_mcp.settings import BOBBIN_URL

_client = httpx.AsyncClient(timeout=15.0)


class BobbinError(RuntimeError):
    pass


async def query(nsid: str, **params: Any) -> dict[str, Any]:
    """GET /xrpc/<nsid> against bobbin, raising a clean error on failure"""
    clean = {k: v for k, v in params.items() if v is not None}
    response = await _client.get(f"{BOBBIN_URL}/xrpc/{nsid}", params=clean)
    if response.is_success:
        return response.json()
    try:
        payload = response.json()
        message = f"{payload.get('error', 'error')}: {payload.get('message', '')}"
    except Exception:
        message = response.text[:200]
    raise BobbinError(f"{nsid} failed ({response.status_code}) {message}")


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
    """resolve a DID to its PDS endpoint (supports did:plc and did:web)"""
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
    """page a collection straight off a repo's PDS"""
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
            raise BobbinError(
                f"listRecords {collection} failed ({response.status_code})"
            )
        body = response.json()
        out.extend(body.get("records") or [])
        cursor = body.get("cursor")
        if not cursor:
            break
    return out


async def get_record(uri: str) -> dict[str, Any]:
    """fetch any public atproto record by at-uri from its owner's PDS"""
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
        raise BobbinError(f"record not found: {uri}")
    return response.json()


@dataclass
class Repo:
    owner_did: str
    name: str
    uri: str  # at-uri of the sh.tangled.repo record
    knot: str
    repo_did: str | None
    labels: list[str]  # label definition at-uris the repo subscribes to
    description: str | None


def _repo_from_record(owner_did: str, uri: str, value: dict[str, Any]) -> Repo:
    # new-style records use the repo name as rkey and have name=None;
    # legacy records have a TID rkey and carry a name field
    rkey = uri.rsplit("/", 1)[-1]
    return Repo(
        owner_did=owner_did,
        name=value.get("name") or rkey,
        uri=uri,
        knot=value["knot"],
        repo_did=value.get("repoDid"),
        labels=value.get("labels") or [],
        description=value.get("description"),
    )


async def resolve_repo(identifier: str) -> Repo:
    """resolve a repo identifier to a hydrated Repo.

    accepts 'owner/repo' (handle or DID owner), a repo record at-uri, or a
    bare repo DID.
    """
    if identifier.startswith("at://"):
        body = await query("sh.tangled.repo.getRepo", repo=identifier)
        owner_did = identifier.removeprefix("at://").split("/")[0]
        return _repo_from_record(owner_did, body["uri"], body["value"])
    if identifier.startswith("did:") and "/" not in identifier:
        body = await query("sh.tangled.repo.getRepoByRepoDid", repoDid=identifier)
        owner_did = body["uri"].removeprefix("at://").split("/")[0]
        return _repo_from_record(owner_did, body["uri"], body["value"])
    if "/" not in identifier:
        raise ValueError(
            f"invalid repo identifier: '{identifier}', expected 'owner/repo', "
            "an at-uri, or a repo DID"
        )
    owner, name = identifier.lstrip("@").split("/", 1)
    owner_did = await resolve_handle(owner)

    # fast path: new-style records are keyed by name
    uri = f"at://{owner_did}/sh.tangled.repo/{name}"
    try:
        body = await query("sh.tangled.repo.getRepo", repo=uri)
        return _repo_from_record(owner_did, body["uri"], body["value"])
    except BobbinError:
        pass

    # legacy path: TID rkey with a name field; page through the owner's repos
    cursor = None
    while True:
        page = await query(
            "sh.tangled.repo.listRepos", subject=owner_did, limit=100, cursor=cursor
        )
        for item in page.get("items") or []:
            value = item.get("value") or {}
            if value.get("name") == name or item["uri"].rsplit("/", 1)[-1] == name:
                return _repo_from_record(owner_did, item["uri"], value)
        cursor = page.get("cursor")
        if not cursor or not page.get("items"):
            raise ValueError(f"repo '{name}' not found for owner '{owner}'")


async def repo_query(r: Repo, nsid: str, **params: Any) -> dict[str, Any]:
    """query a repo's git data via bobbin, falling back to the repo's knot.

    bobbin 404s tree/blob/log/branches/tags for legacy-rkey repos
    ("repository not found on this knot") even when the repo's knot serves
    them fine when asked by repoDid — observed 2026-08-12 on
    zzstoatzz.io/bot. bobbin stays the primary path; on a 404 the knot
    named by the repo record is asked directly.
    """
    try:
        return await query(nsid, repo=r.uri, **params)
    except BobbinError as e:
        if "(404)" not in str(e) or not (r.knot and r.repo_did):
            raise
    clean = {k: v for k, v in params.items() if v is not None}
    response = await _client.get(
        f"https://{r.knot}/xrpc/{nsid}", params={"repo": r.repo_did, **clean}
    )
    if response.is_success:
        return response.json()
    raise BobbinError(
        f"{nsid} failed on knot {r.knot} ({response.status_code}) "
        f"{response.text[:200]}"
    )

"""authenticated writes.

tickets, comments, and patches live in the repository DID's account on its
knot. you write them by calling the knot's com.atproto.repo.* methods with a
service-auth token your own PDS mints (audience: the repo DID). the knot
checks your permission and stamps `x-tngl-editor`; an
org.tangled.graph.attestation on your own PDS then claims the write as yours.
"""

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastmcp.server.dependencies import get_http_headers

from tangled_mcp.bobbin import Repo, resolve_handle
from tangled_mcp.settings import PLC_URL, settings

TICKET = "org.tangled.track.ticket"
PATCH = "org.tangled.review.patch"
COMMENT = "org.tangled.feed.comment"
LABEL_DEFINITION = "org.tangled.label.definition"
ATTESTATION = "org.tangled.graph.attestation"
MARKDOWN = "org.tangled.markup.markdown"
INLINE = "org.tangled.markup.markdown#inline"
LABEL_TOKEN = "org.tangled.label.defs#labelToken"

# legacy pull records stay on their authors' PDSes; pulls opened before the
# org.tangled migration have tickets but no patch records, so their rounds
# are still read from here.
LEGACY_PULL = "sh.tangled.repo.pull"

EDITOR_FIELD = "x-tngl-editor"
CHANGE_FIELD = "x-tngl-change"

_B32 = "234567abcdefghijklmnopqrstuvwxyz"


def tid() -> str:
    """generate an atproto TID (sortable base32 timestamp rkey)"""
    n = (time.time_ns() // 1000) << 10 | int.from_bytes(os.urandom(2), "big") % 1024
    return "".join(_B32[(n >> (60 - 5 * i)) & 31] for i in range(13))


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def markdown(text: str) -> dict[str, str]:
    return {"$type": MARKDOWN, "text": text}


def inline(text: str) -> dict[str, str]:
    return {"$type": INLINE, "text": text}


def editable(value: dict[str, Any]) -> dict[str, Any]:
    """a stored record as a putRecord body: the knot stamps the editor itself"""
    return {k: v for k, v in value.items() if k != EDITOR_FIELD}


@dataclass
class Session:
    client: httpx.AsyncClient
    did: str
    pds: str

    async def _xrpc(self, method: str, nsid: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.request(
            method, f"{self.pds}/xrpc/{nsid}", **kwargs
        )
        if not response.is_success:
            raise RuntimeError(
                f"{nsid} failed ({response.status_code}) {_detail(response)}"
            )
        return response.json()

    async def put_record(
        self, collection: str, rkey: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._xrpc(
            "POST",
            "com.atproto.repo.putRecord",
            json={
                "repo": self.did,
                "collection": collection,
                "rkey": rkey,
                "record": record,
            },
        )

    async def service_token(self, aud: str, lxm: str) -> str:
        body = await self._xrpc(
            "GET", "com.atproto.server.getServiceAuth", params={"aud": aud, "lxm": lxm}
        )
        return body["token"]

    async def knot(self, r: Repo, nsid: str, **input: Any) -> dict[str, Any]:
        """call a procedure on the repo's knot as this account"""
        token = await self.service_token(r.repo_did, nsid)
        response = await self.client.post(
            f"https://{r.knot}/xrpc/{nsid}",
            json={"repo": r.repo_did, **input},
            headers={"Authorization": f"Bearer {token}"},
        )
        if not response.is_success:
            raise RuntimeError(
                f"{nsid} on {r.knot} failed ({response.status_code}) {_detail(response)}"
            )
        return response.json()

    async def attest(self, written: dict[str, Any]) -> dict[str, Any]:
        """claim a knot-written record as this account's, with its change id"""
        record: dict[str, Any] = {
            "$type": ATTESTATION,
            "subject": {"uri": written["uri"], "cid": written["cid"]},
            "createdAt": now(),
        }
        if change := written.get(CHANGE_FIELD):
            record["change"] = change
        return await self.put_record(ATTESTATION, tid(), record)

    async def knot_write(self, r: Repo, nsid: str, **input: Any) -> dict[str, Any]:
        """a knot write plus its attestation. the write has landed even when
        the attestation fails, so that failure is reported, not raised."""
        written = await self.knot(r, nsid, **input)
        result = {"uri": written["uri"], "cid": written["cid"]}
        try:
            await self.attest(written)
        except RuntimeError as err:
            result["attestation_error"] = str(err)
        return result


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        return f"{payload.get('error')}: {payload.get('message')}"
    except Exception:
        return response.text[:200]


@dataclass
class Credentials:
    handle: str | None
    password: str | None


def resolve_credentials() -> Credentials:
    """per-request headers win over env, and are never mixed with it.

    multi-tenant deployments (e.g. FastMCP Cloud) can carry credentials per
    request via x-tangled-handle / x-tangled-password; a header identity must
    be complete on its own so one tenant's handle can't pair with the
    server's env password.
    """
    headers = get_http_headers()
    handle = headers.get("x-tangled-handle")
    if handle:
        return Credentials(
            handle=handle,
            password=headers.get("x-tangled-password"),
        )
    return Credentials(
        handle=settings.tangled_handle,
        password=settings.tangled_password,
    )


async def discover_pds(did: str) -> str:
    """resolve a DID document and return its PDS endpoint."""
    if did.startswith("did:web:"):
        doc_url = f"https://{did.removeprefix('did:web:')}/.well-known/did.json"
    else:
        doc_url = f"{PLC_URL}/{did}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        doc = (await client.get(doc_url)).json()
    try:
        return next(
            s["serviceEndpoint"]
            for s in doc.get("service", [])
            if s.get("type") == "AtprotoPersonalDataServer"
        )
    except StopIteration:
        raise RuntimeError(f"no PDS endpoint in DID document for {did}") from None


async def login() -> Session:
    """authenticate against the user's PDS with app-password credentials"""
    creds = resolve_credentials()
    if not creds.handle or not creds.password:
        raise RuntimeError(
            "write tools require credentials: x-tangled-handle/x-tangled-password "
            "headers or TANGLED_HANDLE/TANGLED_PASSWORD env"
        )
    did = await resolve_handle(creds.handle)
    pds = await discover_pds(did)

    client = httpx.AsyncClient(timeout=15.0)
    response = await client.post(
        f"{pds}/xrpc/com.atproto.server.createSession",
        json={"identifier": creds.handle, "password": creds.password},
    )
    if not response.is_success:
        await client.aclose()
        raise RuntimeError(f"auth failed for '{creds.handle}'")
    body = response.json()
    client.headers["Authorization"] = f"Bearer {body['accessJwt']}"
    return Session(client=client, did=body["did"], pds=pds)

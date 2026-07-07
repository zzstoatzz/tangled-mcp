"""authenticated writes: atproto records on the user's PDS.

tangled has no write API — mutations are just records in your own repo
(sh.tangled.repo.issue, .issue.state, .issue.comment, sh.tangled.label.op).
"""

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastmcp.server.dependencies import get_http_headers

from tangled_mcp.bobbin import resolve_handle
from tangled_mcp.settings import PLC_URL, settings

ISSUE = "sh.tangled.repo.issue"
PULL = "sh.tangled.repo.pull"
ISSUE_STATE = "sh.tangled.repo.issue.state"
ISSUE_COMMENT = "sh.tangled.repo.issue.comment"
LABEL_OP = "sh.tangled.label.op"

STATE_OPEN = "sh.tangled.repo.issue.state.open"
STATE_CLOSED = "sh.tangled.repo.issue.state.closed"

_B32 = "234567abcdefghijklmnopqrstuvwxyz"


def tid() -> str:
    """generate an atproto TID (sortable base32 timestamp rkey)"""
    n = (time.time_ns() // 1000) << 10 | int.from_bytes(os.urandom(2), "big") % 1024
    return "".join(_B32[(n >> (60 - 5 * i)) & 31] for i in range(13))


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
            try:
                payload = response.json()
                detail = f"{payload.get('error')}: {payload.get('message')}"
            except Exception:
                detail = response.text[:200]
            raise RuntimeError(f"{nsid} failed ({response.status_code}) {detail}")
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

    async def get_record(self, collection: str, rkey: str) -> dict[str, Any]:
        return await self._xrpc(
            "GET",
            "com.atproto.repo.getRecord",
            params={"repo": self.did, "collection": collection, "rkey": rkey},
        )

    async def upload_blob(self, data: bytes, mime_type: str) -> dict[str, Any]:
        response = await self.client.post(
            f"{self.pds}/xrpc/com.atproto.repo.uploadBlob",
            content=data,
            headers={"Content-Type": mime_type},
        )
        if not response.is_success:
            raise RuntimeError(
                f"uploadBlob failed ({response.status_code}) {response.text[:200]}"
            )
        return response.json()["blob"]

    async def delete_record(self, collection: str, rkey: str) -> None:
        await self._xrpc(
            "POST",
            "com.atproto.repo.deleteRecord",
            json={"repo": self.did, "collection": collection, "rkey": rkey},
        )

    def uri(self, collection: str, rkey: str) -> str:
        return f"at://{self.did}/{collection}/{rkey}"


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

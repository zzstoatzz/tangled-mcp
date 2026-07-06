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

from tangled_mcp.bobbin import resolve_handle
from tangled_mcp.settings import PLC_URL, settings

ISSUE = "sh.tangled.repo.issue"
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

    async def delete_record(self, collection: str, rkey: str) -> None:
        await self._xrpc(
            "POST",
            "com.atproto.repo.deleteRecord",
            json={"repo": self.did, "collection": collection, "rkey": rkey},
        )

    def uri(self, collection: str, rkey: str) -> str:
        return f"at://{self.did}/{collection}/{rkey}"


async def login() -> Session:
    """authenticate against the user's PDS with app-password credentials"""
    if not settings.tangled_handle or not settings.tangled_password:
        raise RuntimeError(
            "write tools require TANGLED_HANDLE and TANGLED_PASSWORD to be set"
        )
    did = await resolve_handle(settings.tangled_handle)

    pds = settings.tangled_pds_url
    if not pds:
        async with httpx.AsyncClient(timeout=15.0) as client:
            doc = (await client.get(f"{PLC_URL}/{did}")).json()
        pds = next(
            s["serviceEndpoint"]
            for s in doc.get("service", [])
            if s.get("type") == "AtprotoPersonalDataServer"
        )

    client = httpx.AsyncClient(timeout=15.0)
    response = await client.post(
        f"{pds}/xrpc/com.atproto.server.createSession",
        json={"identifier": settings.tangled_handle, "password": settings.tangled_password},
    )
    if not response.is_success:
        await client.aclose()
        raise RuntimeError(f"auth failed for '{settings.tangled_handle}'")
    body = response.json()
    client.headers["Authorization"] = f"Bearer {body['accessJwt']}"
    return Session(client=client, did=body["did"], pds=pds)

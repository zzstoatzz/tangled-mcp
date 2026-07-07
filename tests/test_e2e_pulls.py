"""end-to-end: open real pull requests on tangled, both input variants.

these hit the live appview and write real records to the PDS behind
TANGLED_HANDLE/TANGLED_PASSWORD, then close what they opened. they skip
without credentials and don't run in `just test` — run with `just e2e`.

each test asserts the full loop: record created → appview ingests it
(the pulls index renders the title) → status record closes it.
"""

import asyncio
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from tangled_mcp import bobbin
from tangled_mcp.server import Edit, create_pull, set_pull_state

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (os.environ.get("TANGLED_HANDLE") and os.environ.get("TANGLED_PASSWORD")),
        reason="e2e needs TANGLED_HANDLE/TANGLED_PASSWORD",
    ),
]

REPO = os.environ.get("TANGLED_E2E_REPO", "zzstoatzz.io/tangled-mcp")
INGEST_TIMEOUT = 180


async def _wait_for_ingestion(title: str) -> None:
    url = f"https://tangled.org/{REPO}/pulls"
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        deadline = time.monotonic() + INGEST_TIMEOUT
        while time.monotonic() < deadline:
            response = await client.get(url)
            if title in response.text:
                return
            await asyncio.sleep(10)
    pytest.fail(f"appview did not ingest '{title}' within {INGEST_TIMEOUT}s")


async def _open_verify_close(kwargs: dict) -> None:
    result = await create_pull.fn(repo=REPO, **kwargs)
    record = await bobbin.get_record(result["uri"])
    assert record["value"]["title"] == kwargs["title"]
    await _wait_for_ingestion(kwargs["title"])
    closed = await set_pull_state.fn(pull=result["uri"], state="closed")
    assert closed["state"] == "closed"


async def test_patch_variant():
    """patch produced by real git in a scratch clone of this repo"""
    title = f"e2e patch variant {int(time.time())}"
    project = Path(__file__).parent.parent
    scratch = Path(
        subprocess.run(
            ["mktemp", "-d"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    subprocess.run(
        ["git", "clone", "-q", "--depth=1", str(project), str(scratch / "r")],
        check=True,
    )
    repo = scratch / "r"
    (repo / "README.md").open("a").write(f"\n<!-- {title} -->\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-aqm", title], check=True)
    patch = subprocess.run(
        ["git", "-C", str(repo), "format-patch", "HEAD~1", "--stdout"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    await _open_verify_close({"title": title, "patch": patch})


async def test_edits_variant():
    """whole-file edits, no clone: server synthesizes the patch"""
    title = f"e2e edits variant {int(time.time())}"
    r = await bobbin.resolve_repo(REPO)
    base = await bobbin.query("sh.tangled.repo.blob", repo=r.uri, path="README.md")
    content = (base.get("content") or "") + f"\n<!-- {title} -->\n"

    await _open_verify_close(
        {"title": title, "edits": [Edit(path="README.md", content=content)]}
    )

"""deploy this repository to its Prefect Horizon project from a source archive.

tangled CI runs this on every push to main. it packs the checkout, uploads
the archive, creates a version from the archive's digest, deploys the ready
version to the production target, and confirms the target serves that digest.
no git host is involved: Horizon builds the bytes CI uploaded.

requires HORIZON_API_KEY in the environment (a spindle secret in CI). the key
is never printed. stdlib only so CI needs nothing beyond python.

    uv run python scripts/horizon_deploy.py            # build + deploy
    uv run python scripts/horizon_deploy.py --no-deploy  # build only
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://horizon.prefect.io/api/v0"
ORG = "ead2665d-917e-495b-94cf-29e4918382c3"
PROJECT = "dbb1e068-5119-403c-b460-e94d311918bd"
SERVING_URL = "https://nate-tangled-mcp.fastmcp.app/mcp"
ENTRYPOINT = "src/tangled_mcp/server.py:tangled_mcp"
DEPENDENCY_PATH = "pyproject.toml"

EXCLUDE = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".agents",
    ".pi",
    ".claude",
    ".ruff_cache",
}
POLL_SECONDS = 5
BUILD_TIMEOUT = 15 * 60
DEPLOY_TIMEOUT = 10 * 60


def api(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "authorization": f"Bearer {os.environ['HORIZON_API_KEY']}",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:600]
        raise SystemExit(f"{method} {path} -> HTTP {err.code}: {detail}") from None


def pack(source: Path) -> bytes:
    """gzipped tar of the source tree, excluding credentials and build state."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(source.rglob("*")):
            rel = path.relative_to(source)
            if any(part in EXCLUDE for part in rel.parts):
                continue
            if rel.name == ".env" or rel.name.startswith(".env."):
                continue
            if path.is_file():
                tar.add(path, arcname=str(rel), recursive=False)
    return buf.getvalue()


def upload(archive: bytes) -> str:
    digest = hashlib.sha256(archive).hexdigest()
    grant = api(
        "POST",
        f"/organizations/{ORG}/projects/{PROJECT}/uploads/url",
        {"sizeBytes": len(archive), "checksumSha256": digest},
    )
    signed = grant.get("upload") or {}
    if not signed.get("url"):
        raise SystemExit(f"upload grant had no url; keys: {sorted(grant)}")
    # send exactly the headers Horizon returned; the checksum header is part
    # of the S3 signature
    req = urllib.request.Request(
        signed["url"], data=archive, method="PUT", headers=signed.get("headers") or {}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        if resp.status not in (200, 201, 204):
            raise SystemExit(f"upload returned HTTP {resp.status}")
    print(f"uploaded {len(archive)} bytes, sha256 {digest}")
    return digest


def wait(path: str, done: set[str], timeout: int) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        obj = api("GET", path)
        status = obj.get("status")
        if status != last:
            print(f"  {path.rsplit('/', 2)[-2]} {obj.get('id', '')[:8]}: {status}")
            last = status
        if status in done:
            return obj
        time.sleep(POLL_SECONDS)
    raise SystemExit(f"timed out waiting on {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=".")
    parser.add_argument(
        "--no-deploy", action="store_true", help="build the version, do not deploy it"
    )
    args = parser.parse_args()
    if "HORIZON_API_KEY" not in os.environ:
        raise SystemExit("HORIZON_API_KEY is not set")

    digest = upload(pack(Path(args.source).resolve()))
    version = api(
        "POST",
        f"/organizations/{ORG}/projects/{PROJECT}/versions",
        {
            "source": {"kind": "archive", "checksumSha256": digest},
            "build": {"entrypoint": ENTRYPOINT, "dependencyPath": DEPENDENCY_PATH},
        },
    )
    version = wait(
        f"/organizations/{ORG}/projects/{PROJECT}/versions/{version['id']}",
        {"ready", "failed"},
        BUILD_TIMEOUT,
    )
    if version["status"] != "ready":
        print(f"build failed: {version.get('error')}", file=sys.stderr)
        return 1
    if args.no_deploy:
        print(f"version {version['id']} is ready; not deployed (--no-deploy)")
        return 0

    targets = api("GET", f"/organizations/{ORG}/projects/{PROJECT}/targets")["items"]
    target = next(t for t in targets if t["slug"] == "production")
    deployment = api(
        "POST",
        f"/organizations/{ORG}/projects/{PROJECT}/deployments",
        {"targetId": target["id"], "versionId": version["id"]},
    )
    deployment = wait(
        f"/organizations/{ORG}/projects/{PROJECT}/deployments/{deployment['id']}",
        {"succeeded", "failed", "superseded"},
        DEPLOY_TIMEOUT,
    )
    if deployment["status"] != "succeeded":
        print(
            f"deployment {deployment['status']}: {deployment.get('error')}",
            file=sys.stderr,
        )
        return 1

    target = api(
        "GET", f"/organizations/{ORG}/projects/{PROJECT}/targets/{target['id']}"
    )
    live = api(
        "GET",
        f"/organizations/{ORG}/projects/{PROJECT}/deployments/{target['currentDeploymentId']}",
    )
    live_version = api(
        "GET", f"/organizations/{ORG}/projects/{PROJECT}/versions/{live['versionId']}"
    )
    served = (
        (live_version.get("resolved") or {}).get("source", {}).get("checksumSha256")
    )
    if served != digest:
        print(f"target serves {served}, expected {digest}", file=sys.stderr)
        return 1
    print(f"{target.get('servingUrl', SERVING_URL)} serves archive {digest[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

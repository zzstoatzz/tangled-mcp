# tangled-mcp notes

## dependencies
- `uv add` only (NEVER `uv pip`)
- pure httpx — no atproto SDK (writes are two raw XRPC calls to the PDS)

## deployment
- **primary**: https://github.com/zzstoatzz/tangled-mcp (FastMCP Cloud)
- **mirror**: tangled.sh:zzstoatzz.io/tangled-mcp (dogfooding)
- `git push origin main` → both remotes

## architecture (v2, bobbin era)
- **all reads** go through bobbin, tangled's public read-only XRPC API at
  `https://api.tangled.org` — no auth. full endpoint map: `docs/bobbin-api.md`
- **writes** are atproto records put on the user's PDS via
  `com.atproto.repo.putRecord` (issues, issue states, comments, label ops)
- `owner/repo` resolution (`bobbin.resolve_repo`):
  1. handle → DID (public.api.bsky.app resolveHandle)
  2. fast path: `getRepo?repo=at://did/sh.tangled.repo/<name>` (new records use name as rkey)
  3. legacy fallback: page `listRepos`, match `value.name` (TID-rkey records)
- repos have their own DIDs (`repoDid`); issue/PR/pipeline lists are keyed by
  repo DID (`subject=`), not owner DID
- issue records are TID-keyed; no sequential issueId. open/closed is derived
  from separate `sh.tangled.repo.issue.state` records
- git ops (tree, blob, log, diff, branches...) are proxied by bobbin to the
  hosting knot — pass the repo record at-uri as `repo=`

## dev
- justfile: `setup`, `test`, `check`, `push`
- versioning: uv-dynamic-versioning (git tags)
- type checking: ty + ruff (I, UP)
- remember that `tree` is your friend, better than `ls` and a dream
- **use `jq` for JSON parsing** (not python pipes)
  - example: `curl -s https://pypi.org/pypi/tangled-mcp/json | jq -r '.info.version'`
- **never use `sleep`** - poll/check with actual tools instead

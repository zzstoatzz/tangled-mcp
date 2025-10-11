# tangled-mcp notes

## dependencies
- `uv add` only (NEVER `uv pip`)
- atproto from PR #605 (service auth)
- pydantic warning filtered (upstream atproto issue #625)

## deployment
- **primary**: https://github.com/zzstoatzz/tangled-mcp (FastMCP Cloud)
- **mirror**: tangled.sh:zzstoatzz.io/tangled-mcp (dogfooding)
- `git push origin main` → both remotes

## tools
- all accept `owner/repo` or `@owner/repo` format (e.g., `zzstoatzz/tangled-mcp`)
- server-side resolution:
  1. handle → DID (via atproto identity resolution)
  2. query `sh.tangled.repo` collection on owner's PDS
  3. extract knot hostname and repo name from record
  4. call knot's XRPC endpoint (e.g., `https://knot1.tangled.sh/xrpc/...`)

## dev
- justfile: `setup`, `test`, `check`, `push`
- versioning: uv-dynamic-versioning (git tags)
- type checking: ty + ruff (I, UP)
- remember that `tree` is your friend, better than `ls` and a dream
- **use `jq` for JSON parsing** (not python pipes)
  - example: `curl -s https://pypi.org/pypi/tangled-mcp/json | jq -r '.info.version'`
- **never use `sleep`** - poll/check with actual tools instead

## architecture notes
- repos stored as atproto records in collection `sh.tangled.repo` (NOT `sh.tangled.repo.repo`)
- each repo record contains `knot` field indicating hosting server
- appview (tangled.org) uses web routes, NOT XRPC
- knots (e.g., knot1.tangled.sh) expose XRPC endpoints for git operations

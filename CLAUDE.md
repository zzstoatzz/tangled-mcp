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
- all accept `owner/repo` format (e.g., `zzstoatzz/tangled-mcp`)
- server-side resolution: handle → DID → repo AT-URI

## dev
- justfile: `setup`, `test`, `check`, `push`
- versioning: uv-dynamic-versioning (git tags)
- type checking: ty + ruff (I, UP)

# tangled-mcp project notes

## dependencies
- `uv add` only - NEVER `uv pip`
- atproto from PR #605 (service auth support)

## architecture
- auth: PDS login → `getServiceAuth` → tangled XRPC
- `TANGLED_APPVIEW_URL` + `TANGLED_DID` are constants (not user-configurable)
- `TANGLED_PDS_URL` optional (auto-discovery from handle unless custom PDS)

## code quality
- ruff: import sorting (I), pyupgrade (UP)
- ty: type checking configured
- pre-commit: ruff only
- justfile: setup, test, check

## testing
- use in-memory transport (pass FastMCP directly to Client)
- pytest asyncio_mode = "auto" (never add `@pytest.mark.asyncio`)

## anti-patterns
- don't expose service URLs as user settings
- don't use deferred imports (unless absolutely necessary)

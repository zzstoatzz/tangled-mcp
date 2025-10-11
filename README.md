# tangled-mcp

MCP server for [Tangled](https://tangled.org) - a git collaboration platform built on AT Protocol.

> **note**: this repository is mirrored to [GitHub](https://github.com/zzstoatzz/tangled-mcp) for deployment via [FastMCP Cloud](https://fastmcp.cloud).

## installation

```bash
git clone https://tangled.org/zzstoatzz/tangled-mcp
cd tangled-mcp
just setup
```

> [!IMPORTANT]
> requires [`uv`](https://docs.astral.sh/uv/) and [`just`](https://github.com/casey/just)

## configuration

create `.env` file:

```bash
TANGLED_HANDLE=your.handle
TANGLED_PASSWORD=your-app-password
# optional: only needed if using custom PDS (leave blank for auto-discovery)
TANGLED_PDS_URL=
```

## usage

```bash
uv run tangled-mcp
```

## resources

- `tangled://status` - connection status (PDS auth + tangled accessibility)

## tools

all tools accept repositories in `owner/repo` format (e.g., `zzstoatzz/tangled-mcp`). handles (with or without `@` prefix) and DIDs are both supported for the owner.

### repositories
- `list_repo_branches(repo, limit, cursor)` - list branches for a repository

### issues
- `create_repo_issue(repo, title, body)` - create an issue on a repository
- `list_repo_issues(repo, limit, cursor)` - list issues for a repository

## development

```bash
just test   # run tests
just check  # run pre-commit checks
```

---

mcp-name: io.github.zzstoatzz/tangled-mcp

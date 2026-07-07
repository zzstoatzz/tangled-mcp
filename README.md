# tangled-mcp

MCP server for [Tangled](https://tangled.org) - a git collaboration platform built on AT Protocol.

reads go through [bobbin](https://docs.tangled.org/bobbin.html), tangled's public XRPC API (`api.tangled.org`) — **no credentials needed**. writes (issues, comments, labels) are atproto records put directly on your PDS and require an app password.

> **note**: this repository is mirrored to [GitHub](https://github.com/zzstoatzz/tangled-mcp) for deployment via [FastMCP Cloud](https://fastmcp.cloud).

## hosted server

a hosted instance runs at **`https://nate-tangled-mcp.fastmcp.app/mcp`** — no install needed:

```bash
claude mcp add --transport http tangled https://nate-tangled-mcp.fastmcp.app/mcp
```

for write access, pass credentials per request via headers:

```bash
claude mcp add --transport http tangled https://nate-tangled-mcp.fastmcp.app/mcp \
  --header "x-tangled-handle: your.handle" \
  --header "x-tangled-password: your-app-password"
```

your PDS is auto-discovered from your handle — self-hosted PDS works with no extra config.

## installation

```bash
git clone https://tangled.org/zzstoatzz/tangled-mcp
cd tangled-mcp
just setup
```

> [!IMPORTANT]
> requires [`uv`](https://docs.astral.sh/uv/) and [`just`](https://github.com/casey/just)

## configuration

credentials are optional — only write tools need them. hosted/multi-tenant deployments can send them per request via `x-tangled-handle` / `x-tangled-password` headers, which take precedence over env. for local use, create `.env`:

```bash
TANGLED_HANDLE=your.handle
TANGLED_PASSWORD=your-app-password
```

## usage

<details>
<summary>MCP client installation instructions</summary>

### claude code

```bash
# read-only (no credentials)
claude mcp add tangled -- uvx tangled-mcp

# with write access
claude mcp add tangled \
  -e TANGLED_HANDLE=your.handle \
  -e TANGLED_PASSWORD=your-app-password \
  -- uvx tangled-mcp
```

### cursor

add to your cursor settings (`~/.cursor/mcp.json` or `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "tangled": {
      "command": "uvx",
      "args": ["tangled-mcp"],
      "env": {
        "TANGLED_HANDLE": "your.handle",
        "TANGLED_PASSWORD": "your-app-password"
      }
    }
  }
}
```

### codex cli

```bash
codex mcp add tangled \
  --env TANGLED_HANDLE=your.handle \
  --env TANGLED_PASSWORD=your-app-password \
  -- uvx tangled-mcp
```

### other clients

for clients that support MCP server configuration, use:
- **command**: `uvx`
- **args**: `["tangled-mcp"]`
- **environment variables** (optional, for writes): `TANGLED_HANDLE`, `TANGLED_PASSWORD`

</details>

### development usage

```bash
uv run tangled-mcp
```

## tools

repositories are `owner/repo` (e.g. `zzstoatzz.io/tangled-mcp`); handles (with or without `@`) and DIDs both work for the owner. issues are identified by at-uri.

### discovery (no auth)
- `search(query, limit)` - full-text search across repos, issues, and strings
- `list_repos(owner, limit)` - list a user's repositories
- `get_repo(repo)` - metadata: knot, default branch, languages, labels
- `get_record(uri)` - fetch the full record behind any at-uri (strings/pastes, comments, ...)

### git (no auth)
- `list_branches(repo, limit)` / `list_tags(repo, limit)`
- `list_files(repo, path, ref)` - browse the tree
- `read_file(repo, path, ref)` - file contents
- `commit_log(repo, ref, limit)` - recent commits
- `compare(repo, rev1, rev2)` - diff two revisions

### issues & pulls (no auth)
- `list_issues(repo, state, limit)` - filterable by open/closed
- `get_issue(issue)`
- `list_pulls(repo, status, limit)` - filterable by open/closed/merged
- `list_pipelines(repo, limit)` - CI pipeline runs

### writes (require credentials)
- `create_pull(repo, title, patch, target_branch, body)` - patch-based PR (`git format-patch` output)
- `create_issue(repo, title, body, labels)`
- `update_issue(issue, title, body)`
- `set_issue_state(issue, state)` - close/reopen
- `set_pull_state(pull, state)` - close/reopen a PR
- `comment_on_issue(issue, body)`
- `delete_issue(issue)`

## development

```bash
just test   # run tests
just check  # run pre-commit checks
```

see [docs/bobbin-api.md](docs/bobbin-api.md) for notes on tangled's public API.

---

mcp-name: io.github.zzstoatzz/tangled-mcp

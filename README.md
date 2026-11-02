# tangled-mcp

MCP server for [Tangled](https://tangled.org) - a git collaboration platform built on AT Protocol.

reads go through bobbin, tangled's public index (`api.tangled.org`), and the knot that hosts each repository — **no credentials needed**. writes (issues, comments, states) go to the repository's knot with a service-auth token your PDS mints, and require an app password.

> **note**: pushes to `main` deploy the hosted server through tangled CI, which uploads the source to [Prefect Horizon](https://horizon.prefect.io) (`scripts/horizon_deploy.py`). the [GitHub mirror](https://github.com/zzstoatzz/tangled-mcp) only publishes releases to PyPI and the MCP registry on `v*` tags.

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

repositories are `owner/repo` (e.g. `zzstoatzz.io/tangled-mcp`); handles (with or without `@`) and DIDs both work for the owner, and a bare repo DID works too. issues and pulls are tickets: pass `owner/repo#<number>` or the ticket at-uri.

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
- `list_issues(repo, state, limit)` - filterable by open/closed/completed
- `get_issue(issue)`
- `list_pulls(repo, status, limit)` - filterable by open/closed/completed (merged)
- `get_pull(pull)` - a PR's ticket and its latest patch round; `cid` names the round
- `get_pull_patch(pull, expected_cid)` - the latest round as format-patch text
- `get_pull_file(pull, path)` - one file as the latest round leaves it
- `list_pipelines(repo, limit)` - CI pipeline runs, from the repo's spindle

pulls opened before tangled's `org.tangled` migration have no patch records; their rounds are read from the author's legacy `sh.tangled.repo.pull` record, matched by author, target repo, and title.

### writes (require credentials)
- `create_issue(repo, title, body, labels)`
- `update_issue(issue, title, body)`
- `set_issue_state(issue, state)` - close/complete/reopen
- `set_pull_state(pull, state)` - close/reopen a PR
- `comment_on_issue(issue, body)` / `comment_on_pull(pull, body, expected_cid)`
- `delete_issue(issue)`

`create_pull` and `update_pull` are unavailable: tangled now opens a pull only from a branch pushed to a tangled repository, and this server cannot push git.

## development

```bash
just test   # run tests
just check  # run pre-commit checks
```

see [docs/bobbin-api.md](docs/bobbin-api.md) for where each read and write goes.

---

mcp-name: io.github.zzstoatzz/tangled-mcp

# pull requests: design exploration

**⚠️ CRITICAL: THIS DESIGN CANNOT BE IMPLEMENTED ⚠️**

**Date discovered**: 2025-10-11
**Reason**: Pull requests in tangled use a fundamentally different architecture than issues.

## Why PR support via atproto records doesn't work

After implementing this design and testing, we discovered that **tangled's appview does not ingest pull records from the firehose**. Here's the architectural difference:

### Issues (✅ Works):
1. **Jetstream subscription**: `appview/state/state.go:109` subscribes to `sh.tangled.repo.issue`
2. **Firehose ingester**: `appview/ingester.go:79-80` has `ingestIssue()` function
3. **Pattern**: atproto record is source of truth → firehose keeps database synchronized
4. **Result**: MCP tools work! Create issue via atproto → appears on tangled.org

### Pulls (❌ Broken):
1. **No jetstream subscription**: `tangled.RepoPullNSID` is **missing** from subscription list
2. **No firehose ingester**: No `ingestPull()` function exists in `appview/ingester.go`
3. **Pattern**: Database is source of truth → atproto record is decorative
4. **Web UI flow** (`appview/pulls/pulls.go:1196`):
   - Creates DB entry FIRST via `db.NewPull()`
   - THEN creates atproto record as "announcement"
5. **Result**: MCP-created PRs are **orphan records** that exist on PDS but never appear on tangled.org

### Why this design exists

Looking at the code (`appview/pulls/pulls.go`), pulls have:
- **Submissions array**: Multiple rounds of patches (DB-only concept)
- **Size concerns**: Patches can be megabytes (expensive in atproto)
- **Complexity**: Appview manages pull state in its database with features not in atproto schema
- **Pragmatism**: They wanted to ship pulls quickly, made DB the source of truth

### Evidence

```bash
# Issues are subscribed in jetstream
grep -n "RepoIssueNSID" sandbox/tangled-core/appview/state/state.go
# 109:			tangled.RepoIssueNSID,

# Pulls are NOT subscribed
grep -n "RepoPullNSID" sandbox/tangled-core/appview/state/state.go
# (no results)

# Issues have an ingester
grep -A 2 "RepoIssueNSID:" sandbox/tangled-core/appview/ingester.go
# case tangled.RepoIssueNSID:
#     err = i.ingestIssue(ctx, e)

# Pulls do NOT have an ingester
grep "RepoPullNSID:" sandbox/tangled-core/appview/ingester.go
# (no results)
```

### Conclusion

**Pull request support cannot be added to tangled-mcp** without changes to tangled-core (adding firehose consumer). The design below is architecturally sound but incompatible with tangled's current implementation.

---

## design principle: gh CLI parity

**goal**: tangled-mcp pull request tools should be a subset of `gh pr` commands with matching semantics

- users familiar with `gh` should feel at home
- parameters should match where possible
- we implement what tangled's atproto schema supports
- we don't try to exceed gh's surface area

## gh pr commands (reference)

### general commands (gh)
- `gh pr create` - create a PR with title, body, labels, draft state
- `gh pr list` - list PRs with filters (state, labels, author, base, head)
- `gh pr view` - show details of a single PR
- `gh pr close` - close a PR
- `gh pr reopen` - reopen a closed PR
- `gh pr edit` - edit title, body, labels, base branch
- `gh pr merge` - merge a PR

### what we can support (tangled MCP)

| gh command | tangled tool | notes |
|------------|--------------|-------|
| `gh pr create` | `create_repo_pull` | ✅ title, body, base, head, labels, draft |
| `gh pr list` | `list_repo_pulls` | ✅ state, labels, limit filtering |
| `gh pr view` | `get_repo_pull` | ✅ full details of one PR |
| `gh pr close` | `close_repo_pull` | ✅ via status update |
| `gh pr reopen` | `reopen_repo_pull` | ✅ via status update |
| `gh pr edit` | `update_repo_pull` | ✅ title, body, labels |
| `gh pr merge` | `merge_repo_pull` | ✅ via status update (logical, not git merge) |
| `gh pr comment` | ❌ not v1 | need `sh.tangled.repo.pull.comment` support |
| `gh pr diff` | ❌ not v1 | could show `patch` field |
| `gh pr checks` | ❌ not supported | no CI concept in tangled |
| `gh pr review` | ❌ not v1 | need review records |

## current state

### what we have (issues)
- **collection**: `sh.tangled.repo.issue` (stored on user's PDS)
- **extra fields**: `issueId` (sequential), `owner` (creator DID)
- **labels**: separate `sh.tangled.label.op` records, applied/removed via ops
- **operations**: create, update, delete, list, list_labels
- **no state tracking**: we don't use `sh.tangled.repo.issue.status` yet
- **no comments**: we don't use `sh.tangled.repo.issue.comment` yet

### what we have (branches)
- **knot XRPC**: `sh.tangled.repo.listBranches` query via knot
- **read-only**: no branch creation/deletion yet
- **operations**: list only

## pull request schema (from lexicons)

### core record: `sh.tangled.repo.pull`
```typescript
{
  target: {
    repo: string (at-uri),      // where it's merging to
    branch: string
  },
  source: {
    branch: string,              // where it's coming from
    sha: string (40 chars),      // commit hash
    repo?: string (at-uri)       // optional: for cross-repo pulls
  },
  title: string,
  body?: string,
  patch: string,                 // git diff format
  createdAt: datetime
}
```

### state tracking: `sh.tangled.repo.pull.status`
```typescript
{
  pull: string (at-uri),         // reference to pull record
  status: "open" | "closed" | "merged"
}
```

### comments: `sh.tangled.repo.pull.comment`
```typescript
{
  pull: string (at-uri),
  body: string,
  createdAt: datetime
}
```

## design questions

### 1. sequential IDs (pullId)
**question**: should pulls have `pullId` like issues have `issueId`?

**considerations**:
- human-friendly references: "PR #42" vs AT-URI
- need to maintain counter per-repo (same pattern as issues)
- easier for users to reference in comments/descriptions
- tangled.org URLs probably expect this: `tangled.org/@owner/repo/pulls/42`

**recommendation**: yes, add `pullId` field following issue pattern

### 2. resources vs tools
**current**: 1 resource (`tangled://status`), 6 tools

**question**: should we expose repos/issues/pulls as MCP resources?

**resources are for**:
- read-only data
- things that change over time
- content the LLM should "know about" contextually
- example: `tangled://repo/{owner}/{repo}/issues` → feed LLM current issues

**tools are for**:
- actions (create, update, delete)
- queries with parameters
- returning specific structured data

**potential resources**:
- `tangled://repo/{owner}/{repo}` → repo metadata, default branch, description
- `tangled://repo/{owner}/{repo}/issues` → current open issues
- `tangled://repo/{owner}/{repo}/pulls` → current open pulls
- `tangled://repo/{owner}/{repo}/branches` → all branches

**recommendation**:
- keep tools for actions (create/update/delete)
- add resources for "current state" views
- resources update when queried (not live/streaming)

### 3. patch generation
**question**: where does the `patch` field come from?

**options**:
a) **client generates**: user provides git diff output
   - pros: simple, no server-side git ops
   - cons: user burden, error-prone

b) **knot XRPC**: new endpoint `sh.tangled.repo.generatePatch`
   - pros: server generates correct diff
   - cons: requires knot changes

c) **hybrid**: accept both user-provided patch OR branch refs
   - if patch provided: use it
   - if only branches: call knot to generate
   - pros: flexible
   - cons: more complex

**recommendation**: start with (a), add (b) later as knot capability

### 4. cross-repo pulls (forks)
**question**: how to handle `source.repo` different from `target.repo`?

**use case**: fork workflow
- user forks `owner-a/repo` to `owner-b/repo`
- makes changes on fork
- opens pull from `owner-b/repo:feature` → `owner-a/repo:main`

**challenges**:
- need to resolve both repos (source and target)
- patch generation across repos
- permissions: who can create pulls?

**recommendation**:
- v1: same-repo pulls only (`source.repo` optional, defaults to target)
- v2: add cross-repo support once we understand patterns

### 5. state management
**question**: do we track state separately or in-record?

**issues**: currently don't use `sh.tangled.repo.issue.status`
**pulls**: lexicon has `sh.tangled.repo.pull.status`

**pattern from labels**:
- labels are separate ops
- ops can be applied/reverted
- current state = sum of all ops

**state is simpler**:
- open → closed → merged (mostly linear)
- probably doesn't need full ops history
- could just update a field on pull record OR use status records

**recommendation**:
- use `sh.tangled.repo.pull.status` records (follow lexicon)
- easier to track state changes over time
- consistent with label pattern
- can query "all status changes for pull X"

**draft state**: gh treats draft as a separate boolean, but tangled's lexicon shows:
- `sh.tangled.repo.pull.status.open`
- `sh.tangled.repo.pull.status.closed`
- `sh.tangled.repo.pull.status.merged`

**solution**: we could:
- (a) add custom `draft` field to pull record (not in lexicon, might break)
- (b) treat draft as metadata in status record
- (c) add `sh.tangled.repo.pull.status.draft` as custom state

**recommendation**: (c) - add draft as a custom state value
- fits existing pattern
- `draft` → `open` transition when ready
- backwards compatible (lexicon uses `knownValues` not enum)

### 6. interconnections
**entities that reference each other**:
- issues mention pulls: "closes #42"
- pulls mention issues: "fixes #123"
- both have labels, comments
- pulls reference commits/branches

**question**: how to expose these relationships?

**options**:
a) **inline**: include referenced entities in responses
   - `list_repo_pulls` returns issues it closes
   - bloats responses

b) **separate queries**: tools to fetch relationships
   - `get_pull_related_issues(pull_id)`
   - `get_issue_related_pulls(issue_id)`
   - more API calls but cleaner

c) **resources**: expose as graphs
   - `tangled://repo/{owner}/{repo}/graph` → all entities + edges
   - LLM can traverse
   - ambitious

**recommendation**: start with (b), consider (c) as resources mature

### 7. comments
**question**: support issue/pull comments now or later?

**considerations**:
- both have `comment` collections
- valuable for context (PR review discussions)
- adds complexity (list, create, update, delete comments)

**recommendation**:
- v1: skip comments, focus on core pull CRUD
- v2: add comments once pull basics work
- keeps initial scope manageable

## tool signatures (gh-style)

### create_repo_pull
```python
def create_repo_pull(
    repo: str,                    # gh: -R, --repo
    title: str,                   # gh: -t, --title
    body: str | None = None,      # gh: -b, --body
    base: str = "main",           # gh: -B, --base (target branch)
    head: str,                    # gh: -H, --head (source branch)
    source_sha: str,              # commit hash (required, no gh equiv - we need it for atproto)
    patch: str,                   # git diff (required, no gh equiv - atproto schema)
    labels: list[str] | None = None,  # gh: -l, --label
    draft: bool = False,          # gh: -d, --draft
) -> CreatePullResult:
    """
    create a pull request

    similar to: gh pr create --title "..." --body "..." --base main --head feature --label bug --draft
    """
```

### update_repo_pull
```python
def update_repo_pull(
    repo: str,                    # gh: -R, --repo
    pull_id: int,                 # gh: <number>
    title: str | None = None,     # gh: -t, --title
    body: str | None = None,      # gh: -b, --body
    base: str | None = None,      # gh: -B, --base (change target branch)
    add_labels: list[str] | None = None,     # gh: --add-label
    remove_labels: list[str] | None = None,  # gh: --remove-label
) -> UpdatePullResult:
    """
    edit a pull request

    similar to: gh pr edit 42 --title "..." --add-label bug --remove-label wontfix
    """
```

### list_repo_pulls
```python
def list_repo_pulls(
    repo: str,                    # gh: -R, --repo
    state: str = "open",          # gh: -s, --state {open|closed|merged|all}
    labels: list[str] | None = None,  # gh: -l, --label
    base: str | None = None,      # gh: -B, --base (filter by target branch)
    head: str | None = None,      # gh: -H, --head (filter by source branch)
    draft: bool | None = None,    # gh: -d, --draft (filter by draft state)
    limit: int = 30,              # gh: -L, --limit (default 30)
    cursor: str | None = None,    # pagination
) -> ListPullsResult:
    """
    list pull requests

    similar to: gh pr list --state open --label bug --limit 50
    """
```

### get_repo_pull
```python
def get_repo_pull(
    repo: str,                    # gh: -R, --repo
    pull_id: int,                 # gh: <number>
) -> PullInfo:
    """
    view a pull request

    similar to: gh pr view 42
    """
```

### close_repo_pull
```python
def close_repo_pull(
    repo: str,                    # gh: -R, --repo
    pull_id: int,                 # gh: <number>
) -> UpdatePullResult:
    """
    close a pull request (sets status to closed)

    similar to: gh pr close 42
    """
```

### reopen_repo_pull
```python
def reopen_repo_pull(
    repo: str,                    # gh: -R, --repo
    pull_id: int,                 # gh: <number>
) -> UpdatePullResult:
    """
    reopen a closed pull request (sets status back to open)

    similar to: gh pr reopen 42
    """
```

### merge_repo_pull
```python
def merge_repo_pull(
    repo: str,                    # gh: -R, --repo
    pull_id: int,                 # gh: <number>
) -> UpdatePullResult:
    """
    mark a pull request as merged (sets status to merged)

    note: this is a logical merge (status change), not an actual git merge
    similar to: gh pr merge 42 (but without the git operation)
    """
```

## proposed roadmap

### phase 1: core pr operations (gh parity)

**7 tools matching gh pr commands**:

1. **create_repo_pull** (matches `gh pr create`)
   - parameters: repo, title, body, base, head, source_sha, patch, labels, draft
   - generates pullId (like issueId)
   - creates `sh.tangled.repo.pull` record
   - creates initial `sh.tangled.repo.pull.status` record (open or draft)
   - applies labels if provided
   - returns CreatePullResult with pullId and URL

2. **update_repo_pull** (matches `gh pr edit`)
   - parameters: repo, pull_id, title, body, base, add_labels, remove_labels
   - updates pull record via putRecord + swap
   - handles incremental label changes (add/remove pattern)
   - returns UpdatePullResult with pullId and URL

3. **list_repo_pulls** (matches `gh pr list`)
   - parameters: repo, state, labels, base, head, draft, limit, cursor
   - queries `sh.tangled.repo.pull` + correlates with status
   - filters by state (open/closed/merged/all), labels, branches, draft
   - default limit 30 (matching gh)
   - includes labels for each pull
   - returns ListPullsResult with pulls and cursor

4. **get_repo_pull** (matches `gh pr view`)
   - parameters: repo, pull_id
   - fetches single pull with full details (target, source, patch, status, labels)
   - returns PullInfo model

5. **close_repo_pull** (matches `gh pr close`)
   - parameters: repo, pull_id
   - creates new status record with "closed"
   - returns UpdatePullResult

6. **reopen_repo_pull** (matches `gh pr reopen`)
   - parameters: repo, pull_id
   - creates new status record with "open"
   - only works if current status is "closed"
   - returns UpdatePullResult

7. **merge_repo_pull** (matches `gh pr merge` logically)
   - parameters: repo, pull_id
   - creates new status record with "merged"
   - note: logical merge only (no git operation)
   - returns UpdatePullResult

**types** (following issue pattern):
- `PullInfo` model (uri, cid, pullId, title, body, target, source, createdAt, labels, status)
- `CreatePullResult` (repo, pull_id, url)
- `UpdatePullResult` (repo, pull_id, url)
- `ListPullsResult` (pulls, cursor)

**new module**:
- `src/tangled_mcp/_tangled/_pulls.py` (parallel to _issues.py)
- `src/tangled_mcp/types/_pulls.py` (parallel to _issues.py)

### phase 2: labels + better state
**enhancements**:
- pulls support labels (reuse `_validate_labels`, `_apply_labels`)
- `list_pull_status_history(repo, pull_id)` → all status changes
- pull status in URL: `tangled.org/@owner/repo/pulls/42` shows status

### phase 3: resources
**add resources**:
- `tangled://repo/{owner}/{repo}/pulls/open` → current open PRs
- `tangled://repo/{owner}/{repo}/pulls/{pull_id}` → specific pull context
- helps LLM understand "what PRs exist for this repo?"

### phase 4: cross-repo + comments
**ambitious**:
- cross-repo pull support (forks)
- comment creation/listing
- patch generation via knot XRPC

## open questions

### 1. draft state implementation
**question**: should we use `sh.tangled.repo.pull.status.draft` as a custom state?
- **option a**: separate draft field on pull record (not in lexicon)
- **option b**: draft as custom status value `sh.tangled.repo.pull.status.draft`
- **recommended**: option b - fits lexicon pattern, `draft` → `open` transition

### 2. patch format (v1 scope)
**question**: how do users provide the patch field?
- **v1**: user provides git diff string (simple, no server dependency)
- **v2**: could add knot XRPC to generate from branch refs
- **gh equivalent**: `gh pr create` auto-generates from local branch

### 3. ready-for-review transition
**question**: `gh pr ready` marks draft PR as ready - how to support?
- **option a**: separate `ready_repo_pull(repo, pull_id)` tool
- **option b**: use `update_repo_pull` with status change
- **recommended**: option a - matches gh command structure

### 4. URL format confirmation
**assumption**: `https://tangled.org/@owner/repo/pulls/42`
- matches issue pattern
- need to confirm with tangled.org routing

### 5. merge semantics
**clarification**: `merge_repo_pull` is logical only (status change)
- does NOT perform git merge operation
- tangled may handle actual merge separately
- gh does both (status + git operation)

## implementation notes

### pattern consistency with issues
```python
# issues pattern (working)
def create_issue(repo_id, title, body, labels):
    # 1. resolve repo to AT-URI
    # 2. find next issueId
    # 3. create record with tid rkey
    # 4. apply labels if provided
    # 5. return {uri, cid, issueId}

# pulls pattern (proposed)
def create_pull(repo_id, target_branch, source_branch, source_sha, title, body, patch, labels):
    # 1. resolve repo to AT-URI
    # 2. find next pullId
    # 3. create pull record with {target, source, patch, ...}
    # 4. create status record (open)
    # 5. apply labels if provided
    # 6. return {uri, cid, pullId}
```

### state tracking pattern
```python
def _get_current_pull_status(client, pull_uri):
    """get latest status for a pull by querying status records"""
    status_records = client.com.atproto.repo.list_records(
        collection="sh.tangled.repo.pull.status",
        repo=client.me.did,
    )

    # find all status records for this pull
    pull_statuses = [
        r for r in status_records.records
        if getattr(r.value, "pull", None) == pull_uri
    ]

    # return most recent (last created)
    if pull_statuses:
        latest = max(pull_statuses, key=lambda r: getattr(r.value, "createdAt", ""))
        return getattr(latest.value, "status", "open")

    return "open"  # default
```

### label reuse
```python
# labels work the same for issues and pulls
# _apply_labels takes a subject_uri (issue or pull)
_apply_labels(client, pull_uri, labels, repo_labels, current_labels)

# so label ops are generic:
{
  "$type": "sh.tangled.label.op",
  "subject": "at://did/sh.tangled.repo.pull/abc123",  # or issue URI
  "add": [...],
  "delete": [...]
}
```

## summary: gh pr → tangled MCP mapping

### v1 feature matrix (phase 1)

| feature | gh command | tangled tool | parameters | notes |
|---------|-----------|--------------|------------|-------|
| create PR | `gh pr create` | `create_repo_pull` | title, body, base, head, source_sha, patch, labels, draft | ✅ full parity except auto-patch |
| edit PR | `gh pr edit` | `update_repo_pull` | title, body, base, add_labels, remove_labels | ✅ full parity |
| list PRs | `gh pr list` | `list_repo_pulls` | state, labels, base, head, draft, limit | ✅ full parity (default limit 30) |
| view PR | `gh pr view` | `get_repo_pull` | pull_id | ✅ full parity |
| close PR | `gh pr close` | `close_repo_pull` | pull_id | ✅ status change only |
| reopen PR | `gh pr reopen` | `reopen_repo_pull` | pull_id | ✅ status change only |
| merge PR | `gh pr merge` | `merge_repo_pull` | pull_id | ⚠️ logical only (no git merge) |
| mark ready | `gh pr ready` | `ready_repo_pull` | pull_id | ✅ draft → open transition |

### not in v1 (future)
- `gh pr comment` → need `sh.tangled.repo.pull.comment` support
- `gh pr diff` → could show `patch` field
- `gh pr review` → need review records
- `gh pr checks` → no CI concept in tangled

### key differences from gh
1. **patch field**: users provide git diff string (gh auto-generates)
2. **merge**: logical status change only (gh performs git merge)
3. **source_sha**: required parameter (gh infers from branch)
4. **pullId**: explicit numeric ID (gh uses number or branch name)

### preserved gh patterns
- parameter names match gh flags where possible
- state values: `open`, `closed`, `merged`, `draft`
- filtering: state, labels, base, head, draft
- default limit: 30 (matching gh pr list)
- incremental label updates: add/remove pattern

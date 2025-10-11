# pull requests: design exploration

**note**: this is exploratory work. only well-established designs belong in docs/.

## how we create issues (current pattern)

**from `src/tangled_mcp/_tangled/_issues.py`**:

1. **client-side sequential ID** (lines 61-80):
   - query all existing issues for the repo from user's PDS
   - find max issueId and increment: `next_issue_id = max_issue_id + 1`
   - MCP client generates the issueId (not appview)

2. **create atproto record**:
   - generate TID for rkey: `int(datetime.now(timezone.utc).timestamp() * 1000000)`
   - create record with `$type: "sh.tangled.repo.issue"`
   - fields: repo (AT-URI), issueId, owner, title, body, createdAt
   - use `putRecord` to create on user's PDS

3. **labels**:
   - applied via separate `sh.tangled.label.op` records
   - each op: `{subject: issue_uri, add: [...], delete: [...]}`
   - current state = accumulated result of all ops

4. **no appview XRPC calls**:
   - everything is atproto records on user's PDS
   - appview ingests from firehose and builds its database
   - appview assigns/validates IDs when ingesting

## how pulls should work (following issue pattern)

### create_repo_pull implementation

```python
def create_repo_pull(
    repo_id: str,
    title: str,
    base: str,  # target branch
    head: str,  # source branch (if branch-based)
    patch: str,  # git diff
    body: str | None = None,
    source_sha: str | None = None,  # commit hash (if branch-based)
    labels: list[str] | None = None,
) -> dict:
    """create pull request (similar to: gh pr create)"""

    client = _get_authenticated_client()

    # 1. parse repo_id -> owner_did, repo_name
    owner_did, repo_name = repo_id.split("/", 1)

    # 2. find repo AT-URI
    repo_at_uri = _find_repo_at_uri(owner_did, repo_name)

    # 3. query existing pulls to find next pullId
    existing_pulls = client.com.atproto.repo.list_records(
        repo=client.me.did,
        collection="sh.tangled.repo.pull",
        limit=100,
    )

    max_pull_id = 0
    for pull_record in existing_pulls.records:
        if pull_record.value.target.repo == repo_at_uri:
            pull_id = getattr(pull_record.value, "pullId", None)
            if pull_id:
                max_pull_id = max(max_pull_id, pull_id)

    next_pull_id = max_pull_id + 1

    # 4. generate TID for rkey
    tid = int(datetime.now(timezone.utc).timestamp() * 1000000)
    rkey = str(tid)

    # 5. create pull record
    record = {
        "$type": "sh.tangled.repo.pull",
        "target": {
            "repo": repo_at_uri,
            "branch": base,
        },
        "source": {
            "branch": head,
            "sha": source_sha,  # 40-char commit hash
            # "repo": source_repo_at_uri,  # optional for forks
        },
        "pullId": next_pull_id,  # client generates (like issueId)
        "title": title,
        "body": body,
        "patch": patch,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # 6. putRecord to user's PDS
    response = client.com.atproto.repo.put_record(
        repo=client.me.did,
        collection="sh.tangled.repo.pull",
        rkey=rkey,
        record=record,
    )

    pull_uri = response.uri
    result = {"uri": pull_uri, "cid": response.cid, "pullId": next_pull_id}

    # 7. apply labels if specified
    if labels:
        _apply_labels(client, pull_uri, labels, repo_labels, set())

    return result
```

### update vs state changes

**from tangled-core appview/db/pulls.go**:
- pulls have `State` field in record itself
- state helpers: `ClosePull`, `ReopenPull`, `MergePull` update pull record
- NOT separate `sh.tangled.repo.pull.status` records

**but**: lexicon defines `sh.tangled.repo.pull.status` collection

**question**: do we:
- (a) update pull record's state field via putRecord? (but pull record doesn't have state field in lexicon)
- (b) create `sh.tangled.repo.pull.status` records? (like lexicon suggests)

**need to check**: does pull record schema have a state field or not?

## immediate investigation needed

### 1. check pull record schema
look at `sandbox/tangled-core/lexicons/pulls/pull.json`:
- does it have a `state` or `pullId` field?
- or are those appview-only fields?

### 2. check if pull.status is used
search tangled-core for `sh.tangled.repo.pull.status` usage:
- is it actually created anywhere?
- or is it defined but unused?

### 3. understand submissions
- how are submissions created?
- is there a `sh.tangled.repo.pull.submission` collection?
- or are they appview-only (stored in `pull_submissions` table)?

## proposed tools (gh-style)

1. **create_repo_pull** - create with title, body, base, head, patch, labels
2. **update_repo_pull** - edit title, body, base, labels (NOT state - see below)
3. **list_repo_pulls** - list with filters (state, labels, base, head, limit)
4. **get_repo_pull** - view single pull

**state transitions** (if using status records):
5. **close_repo_pull** - create status record with "closed"
6. **reopen_repo_pull** - create status record with "open"
7. **merge_repo_pull** - create status record with "merged"

OR (if updating pull record):
- `update_repo_pull` includes optional `state` parameter

## key differences from gh

1. **pullId is client-calculated**: query existing + increment (like issueId)
2. **patch required**: users provide git diff (gh auto-generates)
3. **source.sha required**: 40-character commit hash
4. **no draft state**: tangled only has open/closed/merged
5. **merge is logical**: status change, not git operation
6. **labels via ops**: separate `sh.tangled.label.op` records

## next steps

1. **read pull lexicon schema** - see what fields exist in the record
2. **check status record usage** - understand state management pattern
3. **implement create_repo_pull** - following issue pattern exactly

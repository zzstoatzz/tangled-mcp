# tangled-mcp notes

## dependencies
- `uv add` only (NEVER `uv pip`)
- httpx for XRPC — no atproto SDK; dulwich for building and pushing commits

## deployment
- pushes to `main` on `origin` (tangled) deploy: `.tangled/workflows/deploy.yml`
  tests, then uploads the checkout to Prefect Horizon (`scripts/horizon_deploy.py`)
- the GitHub mirror only publishes releases on `v*` tags

## architecture (org.tangled era)
- tangled moved to `org.tangled.*` lexicons on 2026-10-30; every `sh.tangled.*`
  query 404s. lexicons: `~/tangled.org/tangled.org/core/lexicons/org/tangled`,
  record placement: `docs/src/content/docs/reference/records.md` in that repo.
  endpoint map: `docs/bobbin-api.md`
- **index reads** (repos, tickets, comments, search) go to bobbin (`api.tangled.org`)
- **git reads** (`org.tangled.git.*`) go to the repo's knot, keyed by repo DID;
  bobbin does not serve them
- repositories are their own DIDs whose PDS is the knot. tickets (issues and
  pulls), patches, comments, and labels live in that account
- **writes** are the knot's `com.atproto.repo.*` methods with a service token
  from the caller's PDS (`aud` = repo DID, `lxm` = the method), then an
  `org.tangled.graph.attestation` on the caller's PDS
- a pull is a ticket with `targetBranch` plus immutable `org.tangled.review.patch`
  rounds (base/head commit ids), created by `org.tangled.review.submitPatch`
  from a pushed branch. `create_pull`/`update_pull` build one commit from
  whole-file edits (dulwich, depth-1 fetch of the branch tip), push it to
  `https://<knot>/<repo did>` with a receivePack token (`aud` = the knot's
  did:web) as the basic-auth password, then submit the round. the caller
  needs push access to the repo
- migrated pulls have no patch records; their rounds come from the author's
  legacy `sh.tangled.repo.pull` record (matched by author + target + title)

## dev
- justfile: `setup`, `test`, `check`, `push`
- versioning: uv-dynamic-versioning (git tags)
- type checking: ty + ruff (I, UP)
- remember that `tree` is your friend, better than `ls` and a dream
- **use `jq` for JSON parsing** (not python pipes)
  - example: `curl -s https://pypi.org/pypi/tangled-mcp/json | jq -r '.info.version'`
- **never use `sleep`** - poll/check with actual tools instead

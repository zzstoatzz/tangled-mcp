# bobbin — tangled's public XRPC API

explored 2026-07-06. base URL: `https://api.tangled.org` (service self-describes at `/`).
source: `tangled.org/core` → `bobbin/` (rust). lexicons in `bobbin/crates/types/lexicons/`,
routes in `bobbin/crates/xrpc/src/lib.rs`.

## what it is

- read-only, **no auth**, stateless "edge index" appview over `sh.tangled.*` records
- writes stay direct-to-PDS (records) and knot (git ops) — unchanged from before
- fed by hydrant (event stream) + slingshot (record fetch); returns 502 if slingshot down
- health/backfill: `sh.tangled.bobbin.getCoverage` → `{ready, eventsProcessed, lastCursor}`

## key data-model changes since v1

- **repos have their own DIDs**: repo record carries `repoDid` (e.g. `did:plc:...` with PDS = the knot)
- **new-style repo records use the repo name as rkey** and have `name: null`;
  legacy records keep a TID rkey and a `name` field. handle both.
- issue/PR lists are keyed by **repo DID** (`subject=<repoDid>`), not owner DID
- lists return rkeys, not sequential issue/PR numbers
- issue state is derived from `sh.tangled.repo.issue.state` records (open/closed filterable)

## endpoint families (all GET /xrpc/<nsid>)

### single lookups (AT-URI params)
- `sh.tangled.repo.getRepo?repo=<at-uri>` (+ `getRepos` bulk, `getRepoByRepoDid?repoDid=`)
- `sh.tangled.repo.getIssue?issue=<at-uri>` (+ `getIssues`)
- `sh.tangled.repo.getPull?pull=<at-uri>` (+ `getPulls`)
- `sh.tangled.actor.getProfile?actor=<at-uri of profile record>` (+ `getProfiles`)

### aggregations — list/count pairs, `subject=` keyed, plus `...By` variants keyed by author
common params: `subject` (did), `cursor`, `limit` (≤1000), `order` (asc|desc); response `{items, cursor}` or `{count, distinctAuthors}`

| family | methods |
|---|---|
| repo | listRepos, listIssues, listPulls, listArtifacts, listCollaborators (+counts, +By) |
| repo.issue | listStates (+By, counts) |
| repo.pull | listStatuses (+By, counts) |
| feed | listStars, listComments, listReactions (+By, counts) |
| graph | listFollows, listVouches (+By, counts) |
| git | listRefUpdates (+By, counts) |
| label | listDefinitions, listOps (+By, counts) |
| pipeline | listPipelines, listStatuses (+By, counts) — CI! |
| knot | listKnots, listMembers (+By, counts) |
| spindle | listSpindles, listMembers (+By, counts) |
| publicKey | listKeys (+count) |
| string | listStrings (+count) — pastes/gists |

### search
- `sh.tangled.search.query?q=...&limit=...` — full-text over repos/issues/strings, returns scored hits with hydrated records

### git operations (proxied to knots; pass `repo=<repo record at-uri>`, bobbin resolves the knot)
`archive, blob, branch, branches, compare, describeRepo, diff, getDefaultBranch, languages, log, tag, tags, tree`
- e.g. `sh.tangled.repo.blob?repo=<at-uri>&path=README.md` → `{content}`
- `log` returns full commit objects (hash currently a byte array)

### knot passthrough (pass `knot=<host>`)
`sh.tangled.owner`, `sh.tangled.knot.version`, `sh.tangled.knot.listKeys`

## gotchas observed live

- `listIssues?subject=` rejects at-uris — must be the bare **repoDid**
- legacy repos (TID rkey): resolve name via record `value.name`; new repos: name = rkey
- proxied git endpoints error `UpstreamFailed`/`RepoNotFound` for empty or misconfigured repos
- `getProfile` wants the full profile record at-uri (`.../sh.tangled.actor.profile/self`), not a handle/DID
- identity resolution (handle→DID) still needs to happen client-side (e.g. via PDS/bsky resolveHandle)

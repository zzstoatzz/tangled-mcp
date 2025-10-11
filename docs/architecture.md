# architecture

## tangled platform overview

tangled is a git collaboration platform built on the AT Protocol. it consists of:

### components

- **appview** (tangled.org): web interface using traditional HTTP routes
  - handles OAuth authentication for browser users
  - serves HTML/CSS/JS for the UI
  - proxies git operations to knots
  - does NOT expose XRPC endpoints

- **knots** (e.g., knot1.tangled.sh): git hosting servers
  - expose XRPC endpoints for git operations
  - host actual git repositories
  - handle git-upload-pack, git-receive-pack, etc.

- **PDS** (Personal Data Server): AT Protocol user data storage
  - stores user's atproto records
  - repos stored in `sh.tangled.repo` collection
  - each repo record contains: name, knot, description, etc.

### data flow

1. user creates repo on tangled.org
2. appview writes repo record to user's PDS (`sh.tangled.repo` collection)
3. repo record includes `knot` field indicating which knot hosts it
4. git operations routed through appview to the appropriate knot

## MCP server implementation

### resolution flow

when a client calls `list_repo_branches("@owner/repo")`:

1. **normalize input**: strip @ if present (`@owner` → `owner`)

2. **resolve handle to DID**:
   - if already DID format: use as-is
   - otherwise: call `com.atproto.identity.resolveHandle`
   - result: `did:plc:...`

3. **query repo collection**:
   - call `com.atproto.repo.listRecords` on owner's PDS
   - collection: `sh.tangled.repo` (NOT `sh.tangled.repo.repo`)
   - find record where `name` matches repo name

4. **extract knot**:
   - get `knot` field from repo record
   - example: `knot1.tangled.sh`

5. **call knot XRPC**:
   - construct URL: `https://{knot}/xrpc/sh.tangled.repo.branches`
   - params: `{"repo": "{did}/{repo_name}", "limit": N}`
   - auth: service token from `com.atproto.server.getServiceAuth`

### authentication

uses AT Protocol service auth:

1. authenticate to user's PDS with handle/password
2. call `com.atproto.server.getServiceAuth` with `aud: did:web:tangled.org`
3. receive service token (60 second expiration)
4. use token in `Authorization: Bearer {token}` header for XRPC calls

### key implementation details

- **collection name**: `sh.tangled.repo`
- **knot resolution**: dynamic based on repo record, not hardcoded
- **handle formats**: both `owner/repo` and `@owner/repo` accepted
- **private implementation**: resolution logic in `_tangled/` package
- **public API**: clean tool interface in `server.py`

### error handling

- invalid format: `ValueError` with clear message
- handle not found: `ValueError` from identity resolution
- repo not found: `ValueError` after querying collection
- XRPC errors: raised from httpx with status code

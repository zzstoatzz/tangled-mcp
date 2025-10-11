# publishing to mcp registry

this document explains how we set up automated publishing to the [MCP registry](https://github.com/modelcontextprotocol/registry) and the lessons learned along the way.

## overview

the MCP registry is Anthropic's official directory of Model Context Protocol servers. publishing makes your server discoverable and installable through Claude Desktop and other MCP clients.

## setup

### required files

1. **`server.json`** - registry metadata
   - must match PyPI package version exactly
   - uses namespace format: `io.github.username/server-name`
   - validated against https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json

2. **`README.md`** - must contain `mcp-name:` line
   - format: `mcp-name: io.github.username/server-name`
   - can appear anywhere in the file (we put it at the bottom)
   - validation uses simple `strings.Contains()` check

3. **`.github/workflows/publish-mcp.yml`** - automation workflow
   - triggers on version tags (e.g., `v0.0.6`)
   - publishes to PyPI first, then MCP registry
   - uses GitHub OIDC for authentication (no secrets needed)

### github secrets

only one secret required:
- `PYPI_API_TOKEN` - from https://pypi.org/manage/account/token/

## workflow

when you push a version tag:

```bash
git tag v0.0.6
git push origin v0.0.6
```

the workflow automatically:
1. runs tests
2. builds the package with `uv build`
3. publishes to PyPI with `uv publish`
4. installs `mcp-publisher` binary (v1.2.3)
5. authenticates using GitHub OIDC
6. publishes to MCP registry

## cutting a release

to cut a new release:

1. **update server.json version** (both fields must match the version you're releasing)
   ```json
   {
     "version": "0.0.9",
     "packages": [{
       "version": "0.0.9"
     }]
   }
   ```

2. **run pre-commit checks**
   ```bash
   just check
   ```

3. **commit and push your changes**
   ```bash
   git add .
   git commit -m "your commit message"
   git push origin main
   ```

4. **create and push the version tag**
   ```bash
   git tag v0.0.9
   git push origin v0.0.9
   ```

5. **verify the release**
   - workflow: https://github.com/zzstoatzz/tangled-mcp/actions/workflows/publish-mcp.yml
   - pypi: https://pypi.org/project/tangled-mcp/
   - mcp registry: `https://registry.modelcontextprotocol.io/v0/servers/io.github.zzstoatzz%2Ftangled-mcp/versions/X.Y.Z`

## key learnings

### mcp-publisher installation

the official docs suggest using a "latest" URL that doesn't actually work:

```bash
# ❌ doesn't work - 404s
curl -L "https://github.com/modelcontextprotocol/registry/releases/download/latest/..."

# ✅ use specific version
curl -L "https://github.com/modelcontextprotocol/registry/releases/download/v1.2.3/mcp-publisher_1.2.3_linux_amd64.tar.gz"
```

the publisher is a Go binary, not an npm package. don't try `npm install`.

### version synchronization

`server.json` version must match the PyPI package version:

```json
{
  "version": "0.0.6",
  "packages": [{
    "version": "0.0.6"
  }]
}
```

if they don't match, registry validation fails with:
```
PyPI package 'tangled-mcp' not found (status: 404)
```

### readme validation

the `mcp-name:` line just needs to exist somewhere in the README content. the validator uses:

```go
strings.Contains(description, "mcp-name: io.github.username/server-name")
```

so you can place it wherever looks best aesthetically. we put it at the bottom after a horizontal rule.

### authentication

GitHub OIDC is the recommended method for CI/CD:

```yaml
permissions:
  id-token: write
  contents: read

steps:
  - name: login to mcp registry (github oidc)
    run: mcp-publisher login github-oidc
```

no need for additional tokens or secrets - GitHub handles it automatically.

## common errors

### "PyPI package not found (status: 404)"

**cause**: version mismatch between `server.json` and actual PyPI package

**fix**: ensure `server.json` versions match the git tag and PyPI will build that version

### "ownership validation failed"

**cause**: missing or incorrect `mcp-name:` in README

**fix**: add `mcp-name: io.github.username/server-name` anywhere in README.md

### "failed to install mcp-publisher"

**cause**: wrong download URL or npm package attempt

**fix**: use specific version binary download from GitHub releases

## resources

- [MCP registry docs](https://github.com/modelcontextprotocol/registry/tree/main/docs)
- [MCP publisher source](https://github.com/modelcontextprotocol/registry)
- [our workflow](.github/workflows/publish-mcp.yml)
- [our server.json](server.json)

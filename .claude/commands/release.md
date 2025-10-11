check git state and commit and push if appropriate, we are doing to release.

read @docs/publishing.md and use it to help me cut a new release of tangled-mcp.

use gh to view the website for the current repo, it should point to the latest published version of the MCP in the official registry, verify after release this points to the new version you just released.

also curl pypi to verify that the new version is available.

run a smoke test of the MCP as a top level executable of the library, then follow by a test of the individual tools with the FastMCP client.
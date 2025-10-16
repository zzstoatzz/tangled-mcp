"""unit tests for tangled MCP server"""

from fastmcp.client import Client

from tangled_mcp.server import tangled_mcp


class TestServerStructure:
    """test that server exposes correct resources and tools"""

    async def test_server_has_resources(self):
        """test that server exposes the tangled_status resource"""
        async with Client(tangled_mcp) as client:
            resources = await client.list_resources()

            assert len(resources) == 1
            assert resources[0].name == "tangled_status"
            assert str(resources[0].uri) == "tangled://status"

    async def test_server_has_tools(self):
        """test that server exposes expected tools"""
        async with Client(tangled_mcp) as client:
            tools = await client.list_tools()

            assert len(tools) == 6

            tool_names = {tool.name for tool in tools}
            assert "list_repo_branches" in tool_names
            assert "create_repo_issue" in tool_names
            assert "update_repo_issue" in tool_names
            assert "delete_repo_issue" in tool_names
            assert "list_repo_issues" in tool_names
            assert "list_repo_labels" in tool_names

    async def test_list_repo_branches_tool_schema(self):
        """test list_repo_branches tool has correct schema"""
        async with Client(tangled_mcp) as client:
            tools = await client.list_tools()

            tool = next(t for t in tools if t.name == "list_repo_branches")

            # check input schema
            assert tool.inputSchema is not None
            assert tool.inputSchema["type"] == "object"

            properties = tool.inputSchema["properties"]

            # required fields
            assert "repo" in properties
            assert properties["repo"]["type"] == "string"

            # optional fields with defaults
            assert "limit" in properties
            assert properties["limit"]["type"] == "integer"
            assert properties["limit"]["minimum"] == 1
            assert properties["limit"]["maximum"] == 100
            assert properties["limit"]["default"] == 50

            # required parameters
            assert tool.inputSchema["required"] == ["repo"]

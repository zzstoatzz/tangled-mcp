"""tangled MCP server"""

try:
    from importlib.metadata import version

    __version__ = version("tangled-mcp")
except Exception:
    __version__ = "0.0.0"

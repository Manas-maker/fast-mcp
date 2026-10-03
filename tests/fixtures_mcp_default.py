"""Fixture module exporting only 'mcp'."""

from fast_mcp import FastMCP

mcp = FastMCP(name="only-mcp-server")


@mcp.tool()
def ping() -> str:
    return "pong"

from __future__ import annotations

import json
import pytest
from fastapi import FastAPI

from fast_mcp import FastMCP
from tests.conftest import connect_mcp_test_client


@pytest.mark.asyncio
async def test_sync_endpoint_and_no_params_route():
    app = FastAPI()

    # Sync endpoint with no parameters
    @app.get("/ping", tags=["mcp"])
    def sync_ping() -> dict:
        """Health check endpoint."""
        return {"status": "pong"}

    # Mount passing app to mount() directly
    mcp = FastMCP(name="sync-test", version="1.0.0")
    mcp.mount(app=app)

    async with connect_mcp_test_client(app) as client:
        # Check tools/list
        res = await client.send_request("tools/list")
        assert "result" in res
        tools = res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "sync_ping" in tool_names
        sync_tool = next(t for t in tools if t["name"] == "sync_ping")
        assert "Health check endpoint." in sync_tool["description"]
        assert sync_tool["inputSchema"]["type"] == "object"

        # Call the sync tool
        call_res = await client.send_request("tools/call", {"name": "sync_ping", "arguments": {}})
        assert "result" in call_res
        data = json.loads(call_res["result"]["content"][0]["text"])
        assert data == {"status": "pong"}


@pytest.mark.asyncio
async def test_unknown_tool_call_returns_error():
    app = FastAPI()
    mcp = FastMCP(app=app)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        call_res = await client.send_request("tools/call", {"name": "non_existent_tool", "arguments": {}})
        assert "result" in call_res
        result = call_res["result"]
        assert result.get("isError") is True
        assert "Unknown tool" in result["content"][0]["text"]

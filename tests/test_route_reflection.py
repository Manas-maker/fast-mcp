from __future__ import annotations

import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field

from fast_mcp import FastMCP
from tests.conftest import connect_mcp_test_client


class UserCreate(BaseModel):
    username: str = Field(description="The user's unique username")
    email: str = Field(description="The user's email address")


@pytest.mark.asyncio
async def test_route_reflection_tools_list():
    app = FastAPI()

    @app.get("/items/{item_id}", tags=["mcp"])
    async def get_item(item_id: int, query: str = "default") -> dict:
        """Fetch item by its unique integer ID."""
        return {"item_id": item_id, "query": query}

    @app.post("/users", tags=["mcp"])
    async def create_user(user: UserCreate) -> dict:
        """Create a new user record in the system."""
        return {"username": user.username, "email": user.email}

    @app.get("/admin/metrics", tags=["internal"])
    async def get_metrics() -> dict:
        """Internal admin metrics route that should not be exposed."""
        return {"uptime": 100}

    mcp = FastMCP(app=app, name="reflection-test", version="1.0.0")
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/list")
        assert "result" in res, f"Expected result in response: {res}"
        tools = res["result"]["tools"]

        tool_names = [t["name"] for t in tools]

        # Tagged routes must be present
        assert "get_item" in tool_names
        assert "create_user" in tool_names

        # Untagged route must NOT be present
        assert "get_metrics" not in tool_names

        # Check get_item tool details
        get_item_tool = next(t for t in tools if t["name"] == "get_item")
        assert "Fetch item by its unique integer ID." in get_item_tool["description"]
        assert get_item_tool["inputSchema"]["type"] == "object"
        assert "item_id" in get_item_tool["inputSchema"]["properties"]
        assert get_item_tool["inputSchema"]["properties"]["item_id"]["type"] == "integer"
        assert "query" in get_item_tool["inputSchema"]["properties"]
        assert "item_id" in get_item_tool["inputSchema"]["required"]
        assert "query" not in get_item_tool["inputSchema"].get("required", [])

        # Check create_user tool details
        create_user_tool = next(t for t in tools if t["name"] == "create_user")
        assert "Create a new user record in the system." in create_user_tool["description"]
        assert create_user_tool["inputSchema"]["type"] == "object"
        # Should have username and email in schema
        props = create_user_tool["inputSchema"]["properties"]
        assert "username" in props or "user" in props

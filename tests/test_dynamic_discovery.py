from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field
import pytest

from fast_mcp import FastMCP
from fast_mcp.router import BaseToolRouter
from tests.conftest import connect_mcp_test_client


class UserQuery(BaseModel):
    user_id: int = Field(description="Unique identifier for user")


@pytest.mark.asyncio
async def test_dynamic_discovery_disabled_by_default():
    app = FastAPI()

    @app.get("/items", tags=["mcp"])
    def list_items() -> list[str]:
        """List all items in the inventory."""
        return ["item1", "item2"]

    @app.get("/users", tags=["mcp"])
    def list_users() -> list[str]:
        """List all registered users."""
        return ["user1"]

    mcp = FastMCP(app=app)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/list")
        tool_names = [t["name"] for t in res["result"]["tools"]]

        assert "list_items" in tool_names
        assert "list_users" in tool_names
        assert "search_tools" not in tool_names

        # Attempting to call search_tools when disabled returns unknown tool error
        call_res = await client.send_request("tools/call", {"name": "search_tools", "arguments": {"query": "items"}})
        assert call_res["result"].get("isError") is True
        assert "Unknown tool: search_tools" in call_res["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_dynamic_discovery_enabled_exposes_baseline_and_search_tools():
    app = FastAPI()

    @app.get("/health", tags=["mcp", "baseline"])
    def health_check() -> dict[str, str]:
        """Service health check."""
        return {"status": "ok"}

    @app.get("/users/{user_id}", tags=["mcp"])
    def get_user(user_id: int) -> dict[str, Any]:
        """Retrieve user details by user ID."""
        return {"user_id": user_id, "name": "Alice"}

    @app.post("/items", tags=["mcp"])
    def create_item(name: str) -> dict[str, Any]:
        """Create a new item in the warehouse."""
        return {"name": name, "created": True}

    @app.get("/reports", tags=["mcp"])
    def generate_report() -> dict[str, Any]:
        """Generate financial audit reports."""
        return {"report": "data"}

    # Dynamic discovery enabled
    mcp = FastMCP(app=app, dynamic_discovery=True)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/list")
        tools = res["result"]["tools"]
        tool_names = [t["name"] for t in tools]

        # Only baseline tool ("health_check") and "search_tools" meta-tool should be listed
        assert "health_check" in tool_names
        assert "search_tools" in tool_names

        # Non-baseline tools must NOT be present in initial tools/list
        assert "get_user" not in tool_names
        assert "create_item" not in tool_names
        assert "generate_report" not in tool_names

        # Verify search_tools meta-tool schema
        search_tool = next(t for t in tools if t["name"] == "search_tools")
        assert "Search available tools" in search_tool["description"]
        schema = search_tool["inputSchema"]
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["properties"]["query"]["type"] == "string"
        assert "query" in schema.get("required", [])


@pytest.mark.asyncio
async def test_dynamic_discovery_search_tools_returns_matching_schemas():
    app = FastAPI()

    @app.get("/users/{user_id}", tags=["mcp"])
    def get_user(user_id: int) -> dict[str, Any]:
        """Retrieve user profile by unique ID."""
        return {"user_id": user_id, "role": "admin"}

    @app.post("/items", tags=["mcp"])
    def create_item(name: str, quantity: int = 1) -> dict[str, Any]:
        """Add an inventory item with quantity."""
        return {"name": name, "quantity": quantity}

    mcp = FastMCP(app=app, dynamic_discovery=True)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # Search for "user"
        call_res = await client.send_request(
            "tools/call",
            {"name": "search_tools", "arguments": {"query": "user"}},
        )
        assert "result" in call_res
        result = call_res["result"]
        assert not result.get("isError", False)

        content = result["content"][0]["text"]
        found_tools = json.loads(content)
        assert isinstance(found_tools, list)

        found_names = [t["name"] for t in found_tools]
        assert "get_user" in found_names
        assert "create_item" not in found_names

        # Check full schema of found tool
        user_tool = next(t for t in found_tools if t["name"] == "get_user")
        assert user_tool["name"] == "get_user"
        assert "Retrieve user profile" in user_tool["description"]
        assert "inputSchema" in user_tool
        input_schema = user_tool["inputSchema"]
        assert input_schema["type"] == "object"
        assert "user_id" in input_schema["properties"]


@pytest.mark.asyncio
async def test_discovered_tool_can_be_executed_via_tools_call():
    app = FastAPI()

    @app.get("/catalog/{item_id}", tags=["mcp"])
    def get_catalog_item(item_id: int) -> dict[str, Any]:
        """Fetch item from the catalog."""
        return {"item_id": item_id, "in_stock": True}

    mcp = FastMCP(app=app, dynamic_discovery=True)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # Step 1: Discover via search_tools
        search_res = await client.send_request(
            "tools/call",
            {"name": "search_tools", "arguments": {"query": "catalog"}},
        )
        found = json.loads(search_res["result"]["content"][0]["text"])
        assert len(found) == 1
        assert found[0]["name"] == "get_catalog_item"

        # Step 2: Call the discovered tool directly
        call_res = await client.send_request(
            "tools/call",
            {"name": "get_catalog_item", "arguments": {"item_id": 42}},
        )
        assert not call_res["result"].get("isError", False)
        output = json.loads(call_res["result"]["content"][0]["text"])
        assert output == {"item_id": 42, "in_stock": True}


@pytest.mark.asyncio
async def test_dynamic_discovery_explicit_baseline_tools():
    app = FastAPI()

    @app.get("/ping", tags=["mcp"])
    def ping() -> dict[str, str]:
        """Ping endpoint."""
        return {"ping": "pong"}

    @app.get("/orders", tags=["mcp"])
    def get_orders() -> list[str]:
        """Customer orders."""
        return ["order1"]

    # Provide explicit baseline_tools list by name
    mcp = FastMCP(app=app, dynamic_discovery=True, baseline_tools=["ping"])
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/list")
        tool_names = [t["name"] for t in res["result"]["tools"]]

        assert "ping" in tool_names
        assert "search_tools" in tool_names
        assert "get_orders" not in tool_names


@pytest.mark.asyncio
async def test_dynamic_discovery_with_custom_router():
    app = FastAPI()

    @app.get("/foo", tags=["mcp"])
    def foo() -> str:
        """Foo endpoint."""
        return "foo"

    @app.get("/bar", tags=["mcp"])
    def bar() -> str:
        """Bar endpoint."""
        return "bar"

    class CustomFixedRouter(BaseToolRouter):
        async def select_tools(
            self,
            query: str,
            candidate_tools: list[Any],
            top_k: int | None = None,
        ) -> list[Any]:
            # Always return only 'bar' regardless of query
            return [t for t in candidate_tools if getattr(t, "name", "") == "bar"]

    mcp = FastMCP(app=app, dynamic_discovery=True, router=CustomFixedRouter())
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        call_res = await client.send_request(
            "tools/call",
            {"name": "search_tools", "arguments": {"query": "anything"}},
        )
        found = json.loads(call_res["result"]["content"][0]["text"])
        assert len(found) == 1
        assert found[0]["name"] == "bar"


@pytest.mark.asyncio
async def test_dynamic_discovery_search_empty_when_no_match():
    app = FastAPI()

    @app.get("/users", tags=["mcp"])
    def get_users() -> list[str]:
        """User management."""
        return []

    mcp = FastMCP(app=app, dynamic_discovery=True)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        call_res = await client.send_request(
            "tools/call",
            {"name": "search_tools", "arguments": {"query": "nonexistent_term"}},
        )
        found = json.loads(call_res["result"]["content"][0]["text"])
        assert found == []


@pytest.mark.asyncio
async def test_dynamic_discovery_threshold_trigger():
    app = FastAPI()

    @app.get("/tool1", tags=["mcp"])
    def tool1() -> str:
        """Tool 1."""
        return "1"

    @app.get("/tool2", tags=["mcp"])
    def tool2() -> str:
        """Tool 2."""
        return "2"

    @app.get("/tool3", tags=["mcp"])
    def tool3() -> str:
        """Tool 3."""
        return "3"

    # dynamic_discovery is False, but threshold is 2 (3 > 2 tools mounted)
    mcp = FastMCP(app=app, dynamic_discovery_threshold=2)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/list")
        tool_names = [t["name"] for t in res["result"]["tools"]]

        assert "search_tools" in tool_names
        # Since none are marked baseline, only search_tools is returned
        assert len(tool_names) == 1


@pytest.mark.asyncio
async def test_dynamic_discovery_search_tools_edge_cases():
    app = FastAPI()

    @app.get("/status", tags=["mcp"])
    def status() -> str:
        """System status."""
        return "ok"

    mcp = FastMCP(app=app, dynamic_discovery=True)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # Calling search_tools with None / empty arguments
        call_res = await client.send_request("tools/call", {"name": "search_tools", "arguments": None})
        assert not call_res["result"].get("isError", False)
        found = json.loads(call_res["result"]["content"][0]["text"])
        assert found == []

        # Calling search_tools with query as integer
        call_int = await client.send_request("tools/call", {"name": "search_tools", "arguments": {"query": 123}})
        assert not call_int["result"].get("isError", False)

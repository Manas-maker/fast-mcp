from __future__ import annotations

import json
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field

from fast_mcp import FastMCP
from tests.conftest import connect_mcp_test_client


class ItemPayload(BaseModel):
    title: str = Field(description="The title of the item")
    priority: int = Field(default=1, description="The priority level (1-5)")


def test_custom_tool_decorator_variations():
    app = FastAPI()
    mcp = FastMCP(app=app)

    # 1. Bare decorator without parentheses
    @mcp.tool
    def bare_tool(x: int) -> int:
        """A bare tool."""
        return x * 2

    # 2. Decorator with empty parentheses
    @mcp.tool()
    def empty_parens_tool(y: str) -> str:
        """Tool with empty parentheses."""
        return f"hello {y}"

    # 3. Decorator with explicit arguments
    @mcp.tool(name="custom_multiply", description="Explicit multiply tool", tags=["math", "ai"])
    def multiply(a: int, b: int = 2) -> int:
        return a * b

    assert "bare_tool" in mcp._custom_tools
    assert mcp._custom_tools["bare_tool"].name == "bare_tool"
    assert mcp._custom_tools["bare_tool"].description == "A bare tool."

    assert "empty_parens_tool" in mcp._custom_tools
    assert mcp._custom_tools["empty_parens_tool"].name == "empty_parens_tool"
    assert mcp._custom_tools["empty_parens_tool"].description == "Tool with empty parentheses."

    assert "custom_multiply" in mcp._custom_tools
    assert mcp._custom_tools["custom_multiply"].name == "custom_multiply"
    assert mcp._custom_tools["custom_multiply"].description == "Explicit multiply tool"
    assert mcp._custom_tools["custom_multiply"].tags == ["math", "ai"]


def test_custom_tool_schema_inference_primitives_and_docstrings():
    app = FastAPI()
    mcp = FastMCP(app=app)

    # Google-style docstrings
    @mcp.tool
    def search_items(query: str, limit: int = 10, offset: int = 0) -> list:
        """Search items in the database.

        Args:
            query: The search keywords to match against item titles.
            limit: Maximum items to return.
            offset: The pagination offset.
        """
        return []

    # Sphinx-style docstrings
    @mcp.tool
    def calculate_tax(amount: float, rate: float = 0.2) -> float:
        """Calculate sales tax.

        :param amount: Total transaction amount in dollars.
        :param rate: Tax percentage rate as a decimal.
        """
        return amount * rate

    search_tool = mcp._custom_tools["search_items"]
    schema = search_tool.input_schema
    assert schema["type"] == "object"
    props = schema["properties"]

    assert "query" in props
    assert props["query"]["type"] == "string"
    assert props["query"]["description"] == "The search keywords to match against item titles."

    assert "limit" in props
    assert props["limit"]["type"] == "integer"
    assert props["limit"]["default"] == 10
    assert props["limit"]["description"] == "Maximum items to return."

    assert "offset" in props
    assert props["offset"]["type"] == "integer"
    assert props["offset"]["default"] == 0
    assert props["offset"]["description"] == "The pagination offset."

    assert schema.get("required") == ["query"]

    tax_tool = mcp._custom_tools["calculate_tax"]
    tax_props = tax_tool.input_schema["properties"]
    assert tax_props["amount"]["description"] == "Total transaction amount in dollars."
    assert tax_props["rate"]["description"] == "Tax percentage rate as a decimal."
    assert tax_props["rate"]["default"] == 0.2


def test_custom_tool_schema_inference_pydantic():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def create_todo(item: ItemPayload, notify: bool = False) -> dict:
        """Create a todo item."""
        return {"title": item.title, "priority": item.priority, "notify": notify}

    tool = mcp._custom_tools["create_todo"]
    schema = tool.input_schema
    props = schema["properties"]

    assert "title" in props
    assert props["title"]["type"] == "string"
    assert props["title"]["description"] == "The title of the item"

    assert "priority" in props
    assert props["priority"]["type"] == "integer"
    assert props["priority"]["default"] == 1
    assert props["priority"]["description"] == "The priority level (1-5)"

    assert "notify" in props
    assert props["notify"]["type"] == "boolean"
    assert props["notify"]["default"] is False


@pytest.mark.asyncio
async def test_custom_tool_execution_async_and_sync():
    app = FastAPI()
    mcp = FastMCP(app=app, name="custom-tools-test")

    # Async tool
    @mcp.tool
    async def async_concat(a: str, b: str = "!") -> str:
        """Asynchronously concatenate strings."""
        return f"{a}{b}"

    # Sync tool (run in threadpool)
    @mcp.tool
    def sync_compute(x: int, y: int = 5) -> int:
        """Synchronously compute product."""
        return x * y

    # Tool taking Pydantic model
    @mcp.tool
    def add_item(item: ItemPayload) -> dict:
        """Add item via Pydantic model."""
        return {"title": item.title, "priority": item.priority, "created": True}

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # Check tools/list
        list_res = await client.send_request("tools/list")
        assert "result" in list_res
        tools = list_res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "async_concat" in tool_names
        assert "sync_compute" in tool_names
        assert "add_item" in tool_names

        # Execute async tool
        call_async = await client.send_request(
            "tools/call",
            {"name": "async_concat", "arguments": {"a": "hello world"}},
        )
        assert "result" in call_async
        assert not call_async["result"].get("isError")
        assert call_async["result"]["content"][0]["text"] == "hello world!"

        # Execute sync tool
        call_sync = await client.send_request(
            "tools/call",
            {"name": "sync_compute", "arguments": {"x": 7, "y": 6}},
        )
        assert "result" in call_sync
        assert not call_sync["result"].get("isError")
        assert call_sync["result"]["content"][0]["text"] == "42"

        # Execute Pydantic model tool with flat arguments
        call_item = await client.send_request(
            "tools/call",
            {"name": "add_item", "arguments": {"title": "Buy groceries", "priority": 3}},
        )
        assert "result" in call_item
        assert not call_item["result"].get("isError")
        item_data = json.loads(call_item["result"]["content"][0]["text"])
        assert item_data == {"title": "Buy groceries", "priority": 3, "created": True}


@pytest.mark.asyncio
async def test_custom_tool_with_reflected_routes_coexistence():
    app = FastAPI()

    @app.get("/reflected-info", tags=["mcp"])
    def get_info() -> dict:
        """Reflected route info."""
        return {"source": "fastapi-route"}

    mcp = FastMCP(app=app)

    @mcp.tool
    def ai_tool(prompt: str) -> dict:
        """Custom AI tool."""
        return {"response": f"AI processed: {prompt}"}

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        list_res = await client.send_request("tools/list")
        tool_names = [t["name"] for t in list_res["result"]["tools"]]
        assert "get_info" in tool_names
        assert "ai_tool" in tool_names

        call_route = await client.send_request("tools/call", {"name": "get_info", "arguments": {}})
        assert json.loads(call_route["result"]["content"][0]["text"]) == {"source": "fastapi-route"}

        call_custom = await client.send_request("tools/call", {"name": "ai_tool", "arguments": {"prompt": "test"}})
        assert json.loads(call_custom["result"]["content"][0]["text"]) == {"response": "AI processed: test"}


@pytest.mark.asyncio
async def test_custom_tool_registered_after_mount():
    app = FastAPI()
    mcp = FastMCP(app=app)
    mcp.mount()

    # Register after mount
    @mcp.tool
    def late_tool(num: int) -> int:
        """Tool registered post-mount."""
        return num + 100

    async with connect_mcp_test_client(app) as client:
        list_res = await client.send_request("tools/list")
        tool_names = [t["name"] for t in list_res["result"]["tools"]]
        assert "late_tool" in tool_names

        call_res = await client.send_request("tools/call", {"name": "late_tool", "arguments": {"num": 5}})
        assert call_res["result"]["content"][0]["text"] == "105"


@pytest.mark.asyncio
async def test_custom_tool_no_args_and_defaults():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def ping() -> str:
        """Simple ping tool with no args."""
        return "pong"

    @mcp.tool
    def greet(name: str = "World", enthusiasm: int = 1) -> str:
        """Tool with defaults."""
        return f"Hello, {name}!" * enthusiasm

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # Call tool with no args
        ping_res = await client.send_request("tools/call", {"name": "ping", "arguments": {}})
        assert not ping_res["result"].get("isError")
        assert ping_res["result"]["content"][0]["text"] == "pong"

        # Call greet tool with defaults (empty args)
        greet_def_res = await client.send_request("tools/call", {"name": "greet", "arguments": {}})
        assert not greet_def_res["result"].get("isError")
        assert greet_def_res["result"]["content"][0]["text"] == "Hello, World!"

        # Call greet tool with custom args
        greet_custom_res = await client.send_request("tools/call", {"name": "greet", "arguments": {"name": "Alice", "enthusiasm": 2}})
        assert not greet_custom_res["result"].get("isError")
        assert greet_custom_res["result"]["content"][0]["text"] == "Hello, Alice!Hello, Alice!"

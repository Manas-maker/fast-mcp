from __future__ import annotations

import json
import pytest
from fastapi import Depends, FastAPI, Header
from starlette.requests import Request

from fast_mcp import FastMCP
from tests.conftest import connect_mcp_test_client


@pytest.mark.asyncio
async def test_builtin_inspect_tool_in_tools_list_and_execution():
    app = FastAPI()
    mcp = FastMCP(app=app, name="test-inspector", version="1.0.0", enable_ui=True)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # 1. tools/list must include 'inspect' with _meta.ui.resourceUri
        list_res = await client.send_request("tools/list")
        assert "result" in list_res
        tools = list_res["result"]["tools"]
        inspect_tool = next((t for t in tools if t["name"] == "inspect"), None)
        assert inspect_tool is not None
        assert "Inspect" in inspect_tool["description"]
        assert "_meta" in inspect_tool
        assert "ui" in inspect_tool["_meta"]
        assert inspect_tool["_meta"]["ui"]["resourceUri"] == "ui://fast-mcp/inspector"

        # 2. tools/call on inspect tool returns MCP App iframe
        call_res = await client.send_request("tools/call", {"name": "inspect", "arguments": {}})
        assert "result" in call_res
        result = call_res["result"]
        assert not result.get("isError")
        content = result["content"][0]["text"]
        assert '<iframe src="ui://fast-mcp/inspector"' in content


@pytest.mark.asyncio
async def test_resources_list_and_read():
    app = FastAPI()
    mcp = FastMCP(app=app, name="test-resources", version="0.1.0", enable_ui=True)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # 1. resources/list must return ui://fast-mcp/inspector
        list_res = await client.send_request("resources/list")
        assert "result" in list_res
        resources = list_res["result"]["resources"]
        uris = [r["uri"] for r in resources]
        assert "ui://fast-mcp/inspector" in uris

        inspector_res = next(r for r in resources if r["uri"] == "ui://fast-mcp/inspector")
        assert inspector_res["mimeType"] == "text/html"

        # 2. resources/read returns the HTML bundle with mimeType="text/html"
        read_res = await client.send_request(
            "resources/read",
            {"uri": "ui://fast-mcp/inspector"},
        )
        assert "result" in read_res
        contents = read_res["result"]["contents"]
        assert len(contents) > 0
        assert contents[0]["uri"] == "ui://fast-mcp/inspector"
        assert contents[0]["mimeType"] == "text/html"
        assert "<!DOCTYPE html>" in contents[0]["text"] or "<html" in contents[0]["text"]
        assert "test-resources" in contents[0]["text"]


@pytest.mark.asyncio
async def test_read_unknown_resource_fails():
    app = FastAPI()
    mcp = FastMCP(app=app, enable_ui=True)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        read_res = await client.send_request(
            "resources/read",
            {"uri": "ui://nonexistent/resource"},
        )
        # Should return error for unknown resource
        assert "error" in read_res


@pytest.mark.asyncio
async def test_custom_mcp_app_decorator():
    app = FastAPI()
    mcp = FastMCP(app=app, name="app-server")

    # Author an interactive widget using @mcp.app(...)
    @mcp.app(
        name="sales_dashboard",
        description="Interactive sales dashboard widget",
        resource_uri="ui://analytics/sales",
        html="<div id='sales-app'><h1>Sales Dashboard</h1></div>",
        tags=["analytics"],
    )
    def sales_dashboard(region: str = "US") -> dict[str, Any]:
        """Fetch sales summary."""
        return {"region": region, "total_revenue": 50000}

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # 1. tools/list contains sales_dashboard with SEP-1865 metadata
        tools_res = await client.send_request("tools/list")
        tools = tools_res["result"]["tools"]
        dashboard_tool = next((t for t in tools if t["name"] == "sales_dashboard"), None)
        assert dashboard_tool is not None
        assert dashboard_tool["description"] == "Interactive sales dashboard widget"
        assert dashboard_tool["_meta"]["ui"]["resourceUri"] == "ui://analytics/sales"

        # 2. tools/call invokes the underlying tool
        call_res = await client.send_request(
            "tools/call",
            {"name": "sales_dashboard", "arguments": {"region": "APAC"}},
        )
        assert "result" in call_res
        call_data = json.loads(call_res["result"]["content"][0]["text"])
        assert call_data == {"region": "APAC", "total_revenue": 50000}

        # 3. resources/list contains the declared resourceUri
        res_list = await client.send_request("resources/list")
        resources = res_list["result"]["resources"]
        uris = [r["uri"] for r in resources]
        assert "ui://analytics/sales" in uris

        # 4. resources/read returns the configured HTML bundle
        read_res = await client.send_request(
            "resources/read",
            {"uri": "ui://analytics/sales"},
        )
        assert "result" in read_res
        contents = read_res["result"]["contents"]
        assert contents[0]["uri"] == "ui://analytics/sales"
        assert contents[0]["mimeType"] == "text/html"
        assert contents[0]["text"] == "<div id='sales-app'><h1>Sales Dashboard</h1></div>"


@pytest.mark.asyncio
async def test_custom_mcp_app_bare_decorator():
    app = FastAPI()
    mcp = FastMCP(app=app, name="bare-server")

    # Bare decorator with function returning HTML widget
    @mcp.app
    def simple_card() -> str:
        """A simple card widget."""
        return "<div class='card'>Card Content</div>"

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        tools_res = await client.send_request("tools/list")
        tools = tools_res["result"]["tools"]
        card_tool = next((t for t in tools if t["name"] == "simple_card"), None)
        assert card_tool is not None
        assert card_tool["_meta"]["ui"]["resourceUri"] == f"ui://{mcp.name}/simple_card"

        # Invocation
        call_res = await client.send_request("tools/call", {"name": "simple_card", "arguments": {}})
        assert not call_res["result"].get("isError")
        assert "Card Content" in call_res["result"]["content"][0]["text"]

        # Read resource
        read_res = await client.send_request(
            "resources/read",
            {"uri": f"ui://{mcp.name}/simple_card"},
        )
        assert "result" in read_res
        assert "Card Content" in read_res["result"]["contents"][0]["text"]


@pytest.mark.asyncio
async def test_custom_tool_ui_parameter():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool(name="custom_ui_tool", ui="ui://custom/interface")
    def custom_ui_tool() -> str:
        return "data"

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        tools_res = await client.send_request("tools/list")
        tools = tools_res["result"]["tools"]
        target = next((t for t in tools if t["name"] == "custom_ui_tool"), None)
        assert target is not None
        assert target["_meta"]["ui"]["resourceUri"] == "ui://custom/interface"


@pytest.mark.asyncio
async def test_reflected_route_ui_meta():
    app = FastAPI()

    @app.get(
        "/reflected-widget",
        tags=["mcp"],
        openapi_extra={"_meta": {"ui": {"resourceUri": "ui://reflected/widget"}}},
    )
    def reflected_widget() -> dict[str, str]:
        """Reflected widget endpoint."""
        return {"status": "ok"}

    mcp = FastMCP(app=app)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        tools_res = await client.send_request("tools/list")
        tools = tools_res["result"]["tools"]
        target = next((t for t in tools if t["name"] == "reflected_widget"), None)
        assert target is not None
        assert target["_meta"]["ui"]["resourceUri"] == "ui://reflected/widget"


@pytest.mark.asyncio
async def test_mcp_app_with_dependencies():
    app = FastAPI()
    mcp = FastMCP(app=app)

    def verify_auth(x_token: str = Header(...)) -> str:
        return x_token

    @mcp.app(
        name="secure_widget",
        resource_uri="ui://secure/widget",
        html="<div>Secure</div>",
    )
    def secure_widget(token: str = Depends(verify_auth)) -> dict[str, str]:
        return {"authenticated_with": token}

    mcp.mount()

    async with connect_mcp_test_client(app, headers={"x-token": "secret-123"}) as client:
        call_res = await client.send_request("tools/call", {"name": "secure_widget", "arguments": {}})
        assert "result" in call_res
        assert not call_res["result"].get("isError")
        data = json.loads(call_res["result"]["content"][0]["text"])
        assert data == {"authenticated_with": "secret-123"}


@pytest.mark.asyncio
async def test_mcp_app_async_handler():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.app(name="async_dashboard", resource_uri="ui://dashboard/async", html="<div>Async Dashboard</div>")
    async def async_dashboard(val: int) -> dict[str, int]:
        return {"val": val * 2}

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        call_res = await client.send_request("tools/call", {"name": "async_dashboard", "arguments": {"val": 21}})
        assert "result" in call_res
        assert not call_res["result"].get("isError")
        data = json.loads(call_res["result"]["content"][0]["text"])
        assert data == {"val": 42}


@pytest.mark.asyncio
async def test_multiple_mcp_apps_resources_list():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.app(name="widget_a", resource_uri="ui://widgets/a", html="<div>Widget A</div>")
    def widget_a():
        return "a"

    @mcp.app(name="widget_b", resource_uri="ui://widgets/b", html="<div>Widget B</div>")
    def widget_b():
        return "b"

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("resources/list")
        resources = res["result"]["resources"]
        uris = [r["uri"] for r in resources]
        assert "ui://fast-mcp/inspector" in uris
        assert "ui://widgets/a" in uris
        assert "ui://widgets/b" in uris


@pytest.mark.asyncio
async def test_inspect_tool_discoverable_via_search_tools():
    app = FastAPI()
    mcp = FastMCP(app=app, dynamic_discovery=True)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        call_res = await client.send_request(
            "tools/call",
            {"name": "search_tools", "arguments": {"query": "inspect"}},
        )
        assert "result" in call_res
        tools = json.loads(call_res["result"]["content"][0]["text"])
        tool_names = [t["name"] for t in tools]
        assert "inspect" in tool_names


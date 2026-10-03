from __future__ import annotations

import json
import pytest
from fastapi import FastAPI, HTTPException
import httpx

from fast_mcp import FastMCP


@pytest.mark.asyncio
async def test_docs_ui_enabled_by_default():
    app = FastAPI()
    mcp = FastMCP(app=app, name="docs-test", version="1.2.3")
    mcp.mount()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/mcp/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        body = response.text
        assert "<!DOCTYPE html>" in body or "<html" in body
        assert "docs-test" in body
        assert "1.2.3" in body
        assert "FastMCP Inspector" in body or "fast-mcp" in body


@pytest.mark.asyncio
async def test_docs_ui_disabled_returns_404():
    app = FastAPI()
    mcp = FastMCP(app=app, enable_ui=False)
    mcp.mount()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/mcp/docs")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_docs_ui_custom_mount_path():
    app = FastAPI()
    mcp = FastMCP(app=app, mount_path="/api/v1/mcp", enable_ui=True)
    mcp.mount()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Default mount path /mcp/docs should 404
        res_default = await client.get("/mcp/docs")
        assert res_default.status_code == 404

        # Custom mount path should 200
        response = await client.get("/api/v1/mcp/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_docs_ui_execution_endpoint():
    app = FastAPI()

    @app.get("/calculate", tags=["mcp"])
    def calculate(x: int, y: int) -> dict[str, int]:
        """Multiply two numbers."""
        return {"result": x * y}

    mcp = FastMCP(app=app, enable_ui=True)

    @mcp.tool(name="greet")
    def greet(name: str) -> str:
        """Greeting tool."""
        return f"Hello, {name}!"

    mcp.mount()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Execute reflected tool
        calc_res = await client.post(
            "/mcp/docs/call",
            json={"name": "calculate", "arguments": {"x": 6, "y": 7}},
        )
        assert calc_res.status_code == 200
        calc_data = calc_res.json()
        assert calc_data.get("is_error") is False
        assert calc_data.get("result") == {"result": 42}

        # 2. Execute custom tool
        greet_res = await client.post(
            "/mcp/docs/call",
            json={"name": "greet", "arguments": {"name": "Alice"}},
        )
        assert greet_res.status_code == 200
        greet_data = greet_res.json()
        assert greet_data.get("is_error") is False
        assert greet_data.get("result") == "Hello, Alice!"


@pytest.mark.asyncio
async def test_docs_ui_execution_handles_errors():
    app = FastAPI()

    @app.get("/error_endpoint", tags=["mcp"])
    def error_endpoint():
        raise HTTPException(status_code=400, detail="Invalid request parameters")

    mcp = FastMCP(app=app, enable_ui=True)
    mcp.mount()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/mcp/docs/call",
            json={"name": "error_endpoint", "arguments": {}},
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("is_error") is True
        assert "Invalid request parameters" in data.get("error", "")

        # Unknown tool
        unknown_res = await client.post(
            "/mcp/docs/call",
            json={"name": "nonexistent", "arguments": {}},
        )
        assert unknown_res.status_code == 200
        unknown_data = unknown_res.json()
        assert unknown_data.get("is_error") is True
        assert "Unknown tool" in unknown_data.get("error", "")


@pytest.mark.asyncio
async def test_docs_ui_tools_endpoint():
    app = FastAPI()

    @app.get("/items", tags=["mcp"])
    def list_items() -> list[str]:
        """List items."""
        return ["item1", "item2"]

    mcp = FastMCP(app=app, enable_ui=True)
    mcp.mount()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/mcp/docs/tools")
        assert res.status_code == 200
        data = res.json()
        assert "tools" in data
        assert "resources" in data
        tool_names = [t["name"] for t in data["tools"]]
        assert "list_items" in tool_names


@pytest.mark.asyncio
async def test_docs_ui_disabled_no_subroutes():
    app = FastAPI()
    mcp = FastMCP(app=app, enable_ui=False)
    mcp.mount()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res_call = await client.post("/mcp/docs/call", json={"name": "foo", "arguments": {}})
        assert res_call.status_code == 404

        res_tools = await client.get("/mcp/docs/tools")
        assert res_tools.status_code == 404


@pytest.mark.asyncio
async def test_docs_ui_trailing_slash():
    app = FastAPI()
    mcp = FastMCP(app=app, enable_ui=True)
    mcp.mount()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/mcp/docs/")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_docs_ui_call_invalid_json():
    app = FastAPI()
    mcp = FastMCP(app=app, enable_ui=True)
    mcp.mount()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Invalid body without name
        res = await client.post("/mcp/docs/call", content=b"not-json", headers={"content-type": "application/json"})
        assert res.status_code == 200
        data = res.json()
        assert data.get("is_error") is True


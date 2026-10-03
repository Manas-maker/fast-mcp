from __future__ import annotations

import json
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field

from fast_mcp import FastMCP
from tests.conftest import connect_mcp_test_client


class UserCreate(BaseModel):
    username: str = Field(description="The user's unique username")
    email: str = Field(description="The user's email address")


@pytest.mark.asyncio
async def test_tool_call_execution_get_and_post():
    app = FastAPI()

    @app.get("/items/{item_id}", tags=["mcp"])
    async def get_item(item_id: int, query: str = "default") -> dict:
        """Fetch item by its unique integer ID."""
        return {"item_id": item_id, "query": query, "found": True}

    @app.post("/users", tags=["mcp"])
    async def create_user(user: UserCreate) -> dict:
        """Create a new user record in the system."""
        return {"id": 42, "username": user.username, "email": user.email}

    mcp = FastMCP(app=app, name="execution-test", version="1.0.0")
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # Call get_item tool
        call_res = await client.send_request(
            "tools/call",
            {"name": "get_item", "arguments": {"item_id": 10, "query": "custom"}},
        )
        assert "result" in call_res, f"Unexpected error: {call_res}"
        result = call_res["result"]
        assert not result.get("isError", False)
        assert len(result["content"]) > 0
        text_content = result["content"][0]["text"]
        data = json.loads(text_content)
        assert data == {"item_id": 10, "query": "custom", "found": True}

        # Call create_user tool with top-level fields
        user_call_res = await client.send_request(
            "tools/call",
            {
                "name": "create_user",
                "arguments": {"username": "bob", "email": "bob@example.com"},
            },
        )
        assert "result" in user_call_res, f"Unexpected error: {user_call_res}"
        user_result = user_call_res["result"]
        assert not user_result.get("isError", False)
        assert len(user_result["content"]) > 0
        user_data = json.loads(user_result["content"][0]["text"])
        assert user_data == {"id": 42, "username": "bob", "email": "bob@example.com"}

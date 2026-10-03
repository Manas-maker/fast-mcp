from __future__ import annotations

import json
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from fast_mcp import FastMCP
from tests.conftest import connect_mcp_test_client


class ItemCreate(BaseModel):
    name: str = Field(description="Name of item")
    price: float = Field(description="Price of item")
    category: str = Field(default="general", description="Category")

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Price cannot be negative")
        return v


@pytest.mark.asyncio
async def test_http_exception_404_in_endpoint():
    """Verify that HTTPException(404) in a reflected route returns is_error=True with status code and detail."""
    app = FastAPI()

    @app.get("/items/{item_id}", tags=["mcp"])
    def get_item(item_id: int) -> dict:
        """Fetch an item or raise 404."""
        if item_id == 404:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"item_id": item_id, "found": True}

    mcp = FastMCP(app=app)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "get_item", "arguments": {"item_id": 404}})
        assert "result" in res, f"Expected JSON-RPC result instead of error: {res}"
        assert "error" not in res, "Protocol-level error should not be returned for HTTPException"
        result = res["result"]
        assert result.get("isError") is True
        content_text = result["content"][0]["text"]
        assert "Error 404: Item not found" == content_text


@pytest.mark.asyncio
async def test_http_exception_in_custom_tool():
    """Verify that HTTPException(400) in a custom tool returns is_error=True."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def validate_code(code: str) -> str:
        """Validate coupon code."""
        if code != "DISCOUNT":
            raise HTTPException(status_code=400, detail="Invalid coupon code")
        return "Applied"

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "validate_code", "arguments": {"code": "WRONG"}})
        assert "result" in res
        assert "error" not in res
        result = res["result"]
        assert result.get("isError") is True
        assert result["content"][0]["text"] == "Error 400: Invalid coupon code"


@pytest.mark.asyncio
async def test_http_exception_dict_detail():
    """Verify that HTTPException with dictionary detail serializes cleanly."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def complex_failure() -> None:
        """Fails with structured detail."""
        raise HTTPException(
            status_code=422,
            detail={"error_code": "RESOURCE_LOCKED", "retry_after": 30},
        )

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "complex_failure", "arguments": {}})
        assert "result" in res
        result = res["result"]
        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "Error 422:" in text
        assert "RESOURCE_LOCKED" in text
        assert "30" in text


@pytest.mark.asyncio
async def test_invalid_tool_argument_type():
    """Verify that passing an invalid argument type returns is_error=True with clear validation message."""
    app = FastAPI()

    @app.get("/calc/{number}", tags=["mcp"])
    def square(number: int) -> dict:
        """Square a number."""
        return {"result": number * number}

    mcp = FastMCP(app=app)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "square", "arguments": {"number": "not_an_int"}})
        assert "result" in res
        assert "error" not in res
        result = res["result"]
        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "Validation error" in text
        assert "number" in text
        assert "valid integer" in text or "integer" in text.lower()


@pytest.mark.asyncio
async def test_missing_required_tool_argument():
    """Verify that omitting a required argument returns is_error=True with Field required message."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def send_email(recipient: str, subject: str) -> str:
        """Send email tool."""
        return f"Sent to {recipient}"

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # Miss both recipient and subject
        res = await client.send_request("tools/call", {"name": "send_email", "arguments": {}})
        assert "result" in res
        assert "error" not in res
        result = res["result"]
        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "Validation error" in text
        assert "recipient" in text
        assert "subject" in text
        assert "Field required" in text


@pytest.mark.asyncio
async def test_pydantic_custom_field_validator_error():
    """Verify that Pydantic field validator failures produce clean tool error messages."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def add_product(item: ItemCreate) -> dict:
        """Add a product with validated price."""
        return {"name": item.name, "price": item.price}

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request(
            "tools/call",
            {"name": "add_product", "arguments": {"name": "Gadget", "price": -10.0}},
        )
        assert "result" in res
        result = res["result"]
        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "Validation error" in text
        assert "price" in text
        assert "Price cannot be negative" in text


@pytest.mark.asyncio
async def test_unhandled_exception_sanitized_no_protocol_crash():
    """Verify that unhandled exceptions do not trigger JSON-RPC errors and return sanitized error descriptions."""
    app = FastAPI()
    mcp = FastMCP(app=app, debug=False)

    @mcp.tool
    def buggy_tool() -> None:
        """A tool that raises an unexpected runtime exception."""
        raise RuntimeError("Database connection timed out during query")

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "buggy_tool", "arguments": {}})
        assert "result" in res
        assert "error" not in res
        result = res["result"]
        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "Database connection timed out during query" in text
        # Stack trace should NOT be leaked when debug=False
        assert "Traceback" not in text


@pytest.mark.asyncio
async def test_debug_mode_true_includes_traceback():
    """Verify that when debug=True, traceback is included for unhandled exceptions."""
    app = FastAPI()
    mcp = FastMCP(app=app, debug=True)

    @mcp.tool
    def failing_tool() -> None:
        raise ValueError("Something unexpected broke")

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "failing_tool", "arguments": {}})
        assert "result" in res
        result = res["result"]
        assert result.get("isError") is True
        text = result["content"][0]["text"]
        assert "ValueError: Something unexpected broke" in text
        assert "Traceback" in text


def test_format_validation_error_unit():
    """Unit tests for format_validation_error utility."""
    from fast_mcp import format_validation_error
    from pydantic import ValidationError

    class Dummy(BaseModel):
        num: int
        name: str

    # Single error
    try:
        Dummy.model_validate({"name": "foo"})
    except ValidationError as e:
        msg = format_validation_error(e)
        assert msg.startswith("Validation error: num: Field required")

    # Multiple errors
    try:
        Dummy.model_validate({})
    except ValidationError as e:
        msg = format_validation_error(e)
        assert "Validation error:" in msg
        assert "- num: Field required" in msg
        assert "- name: Field required" in msg

    # Fallback for non-validation object
    assert format_validation_error(RuntimeError("foo")) == "Validation error: foo"


@pytest.mark.asyncio
async def test_protocol_never_throws_jsonrpc_error_for_anticipated_errors():
    """Verify that protocol-level JSON-RPC errors are never thrown for anticipated business logic or validation errors."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def business_error(action: str) -> str:
        if action == "not_found":
            raise HTTPException(status_code=404, detail="Resource not found")
        elif action == "bad_request":
            raise HTTPException(status_code=400, detail="Invalid business rule")
        elif action == "unprocessable":
            raise HTTPException(status_code=422, detail="Cannot process entity")
        return "success"

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        for action in ["not_found", "bad_request", "unprocessable"]:
            res = await client.send_request("tools/call", {"name": "business_error", "arguments": {"action": action}})
            # Must have JSON-RPC 'result' and NO 'error' key
            assert "result" in res, f"Action {action} returned JSON-RPC error payload: {res}"
            assert "error" not in res
            assert res["result"].get("isError") is True

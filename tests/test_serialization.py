from __future__ import annotations

import json
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field

from fast_mcp import FastMCP
from tests.conftest import connect_mcp_test_client


class UserSummary(BaseModel):
    user_id: int
    name: str
    roles: list[str] = Field(default_factory=list)


class Report(BaseModel):
    title: str
    score: float


class SpecialReport(Report):
    special_notes: str


@pytest.mark.asyncio
async def test_default_minified_json_serialization():
    """Verify that default serialization produces compact minified JSON without spaces."""
    app = FastAPI()

    @app.get("/data", tags=["mcp"])
    def get_data() -> dict:
        """Returns structured dictionary."""
        return {
            "name": "Widget",
            "count": 42,
            "tags": ["alpha", "beta"],
        }

    @app.get("/items", tags=["mcp"])
    def get_items() -> list[dict]:
        """Returns list of items."""
        return [{"id": 1}, {"id": 2}]

    mcp = FastMCP(app=app)
    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # Check dictionary response
        res1 = await client.send_request("tools/call", {"name": "get_data", "arguments": {}})
        assert not res1["result"].get("isError")
        text1 = res1["result"]["content"][0]["text"]
        # Minified JSON must not have whitespace separators ", " or ": "
        assert ", " not in text1
        assert ": " not in text1
        parsed1 = json.loads(text1)
        assert parsed1 == {"name": "Widget", "count": 42, "tags": ["alpha", "beta"]}

        # Check list response
        res2 = await client.send_request("tools/call", {"name": "get_items", "arguments": {}})
        assert not res2["result"].get("isError")
        text2 = res2["result"]["content"][0]["text"]
        assert ", " not in text2
        parsed2 = json.loads(text2)
        assert parsed2 == [{"id": 1}, {"id": 2}]


@pytest.mark.asyncio
async def test_custom_serializer_with_type_arg_markdown():
    """Verify @mcp.serializer(TargetType) formats output into custom Markdown."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.serializer(UserSummary)
    def serialize_user(summary: UserSummary) -> str:
        roles_str = ", ".join(summary.roles)
        return f"# User: {summary.name} (ID: {summary.user_id})\n**Roles:** {roles_str}"

    @mcp.tool
    def get_user() -> UserSummary:
        """Get user summary."""
        return UserSummary(user_id=101, name="Alice", roles=["admin", "editor"])

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "get_user", "arguments": {}})
        assert not res["result"].get("isError")
        text = res["result"]["content"][0]["text"]
        expected = "# User: Alice (ID: 101)\n**Roles:** admin, editor"
        assert text == expected


@pytest.mark.asyncio
async def test_custom_serializer_bare_decorator_inferred_type():
    """Verify bare @mcp.serializer infers target type from first argument annotation."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.serializer
    def format_report(rep: Report) -> str:
        return f"Report '{rep.title}': {rep.score:.1f}%"

    @mcp.tool
    def generate_report() -> Report:
        """Generate sample report."""
        return Report(title="Q3 Audit", score=98.5)

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "generate_report", "arguments": {}})
        assert not res["result"].get("isError")
        text = res["result"]["content"][0]["text"]
        assert text == "Report 'Q3 Audit': 98.5%"


@pytest.mark.asyncio
async def test_custom_serializer_inheritance():
    """Verify serializer registered for base class applies to subclasses unless overridden."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.serializer(Report)
    def serialize_any_report(rep: Report) -> str:
        return f"[Generic Report] {rep.title}"

    @mcp.tool
    def get_special_report() -> SpecialReport:
        """Get special report."""
        return SpecialReport(title="Annual", score=100.0, special_notes="Top tier")

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "get_special_report", "arguments": {}})
        assert not res["result"].get("isError")
        assert res["result"]["content"][0]["text"] == "[Generic Report] Annual"


@pytest.mark.asyncio
async def test_custom_serializer_subclass_override():
    """Verify subclass-specific serializer takes precedence over base class serializer."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.serializer(Report)
    def serialize_base(rep: Report) -> str:
        return f"[Base] {rep.title}"

    @mcp.serializer(SpecialReport)
    def serialize_special(rep: SpecialReport) -> str:
        return f"[Special] {rep.title}: {rep.special_notes}"

    @mcp.tool
    def get_standard() -> Report:
        return Report(title="Standard", score=50.0)

    @mcp.tool
    def get_special() -> SpecialReport:
        return SpecialReport(title="Executive", score=90.0, special_notes="Confidential")

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res1 = await client.send_request("tools/call", {"name": "get_standard", "arguments": {}})
        assert res1["result"]["content"][0]["text"] == "[Base] Standard"

        res2 = await client.send_request("tools/call", {"name": "get_special", "arguments": {}})
        assert res2["result"]["content"][0]["text"] == "[Special] Executive: Confidential"


@pytest.mark.asyncio
async def test_custom_serializer_async_and_manual_registration():
    """Verify async serializers and manual registration via register_serializer."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    class CustomData:
        def __init__(self, val: str) -> None:
            self.val = val

    async def async_serializer(data: CustomData) -> str:
        return f"Async: {data.val.upper()}"

    mcp.register_serializer(CustomData, async_serializer)

    @mcp.tool
    def get_custom() -> CustomData:
        return CustomData("hello world")

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "get_custom", "arguments": {}})
        assert not res["result"].get("isError")
        assert res["result"]["content"][0]["text"] == "Async: HELLO WORLD"


def test_serializer_decorator_variations_and_validation():
    """Verify various syntax variations and validation errors on @mcp.serializer."""
    mcp = FastMCP()

    class Alpha:
        pass

    # 1. target_type keyword
    @mcp.serializer(target_type=Alpha)
    def s_target(a: Alpha) -> str:
        return "alpha_target"

    assert Alpha in mcp._serializers

    # 2. type keyword
    class Beta:
        pass

    @mcp.serializer(type=Beta)
    def s_type(b: Beta) -> str:
        return "beta"

    assert Beta in mcp._serializers

    # 3. Empty parentheses
    class Gamma:
        pass

    @mcp.serializer()
    def s_gamma(g: Gamma) -> str:
        return "gamma"

    assert Gamma in mcp._serializers

    # 4. TypeError for non-type
    with pytest.raises(TypeError, match="target_type must be a type/class"):
        mcp.register_serializer("not_a_type", lambda x: "bad")

    # 5. ValueError for function without parameters
    with pytest.raises(ValueError, match="at least one argument"):
        @mcp.serializer
        def no_params() -> str:
            return ""

    # 6. ValueError for unannotated parameter
    with pytest.raises(ValueError, match="must have a type annotation"):
        @mcp.serializer
        def unannotated(val) -> str:
            return ""


@pytest.mark.asyncio
async def test_serializer_returning_call_tool_result_and_dict():
    """Verify serializers returning CallToolResult, TextContent, or dict."""
    from mcp import types

    app = FastAPI()
    mcp = FastMCP(app=app)

    class CustomWidget:
        def __init__(self, code: str) -> None:
            self.code = code

    class CustomDict:
        def __init__(self, key: str, val: int) -> None:
            self.key = key
            self.val = val

    @mcp.serializer(CustomWidget)
    def serialize_widget(w: CustomWidget) -> types.CallToolResult:
        return types.CallToolResult(
            is_error=False,
            content=[types.TextContent(type="text", text=f"CUSTOM-WIDGET:{w.code}")],
        )

    @mcp.serializer(CustomDict)
    def serialize_dict(d: CustomDict) -> dict:
        return {d.key: d.val}

    @mcp.tool
    def get_widget() -> CustomWidget:
        return CustomWidget("ABC")

    @mcp.tool
    def get_dict_obj() -> CustomDict:
        return CustomDict("count", 99)

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res1 = await client.send_request("tools/call", {"name": "get_widget", "arguments": {}})
        assert res1["result"]["content"][0]["text"] == "CUSTOM-WIDGET:ABC"

        res2 = await client.send_request("tools/call", {"name": "get_dict_obj", "arguments": {}})
        assert res2["result"]["content"][0]["text"] == '{"count":99}'


@pytest.mark.asyncio
async def test_serializer_exception_caught_as_tool_error():
    """Verify that exceptions raised inside a serializer hook are trapped and returned as tool errors."""
    app = FastAPI()
    mcp = FastMCP(app=app)

    class Fragile:
        pass

    @mcp.serializer(Fragile)
    def bad_serializer(f: Fragile) -> str:
        raise RuntimeError("Serializer crash during formatting")

    @mcp.tool
    def get_fragile() -> Fragile:
        return Fragile()

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "get_fragile", "arguments": {}})
        assert "result" in res
        assert "error" not in res
        assert res["result"].get("isError") is True
        assert "Serializer crash during formatting" in res["result"]["content"][0]["text"]


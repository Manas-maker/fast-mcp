from __future__ import annotations

from contextlib import AsyncExitStack
import inspect
import json
from typing import Any, Callable
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.routing import Route

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import ServerRequestContext
from mcp.server.sse import SseServerTransport
from pydantic import BaseModel, Field

from fast_mcp.bridge import (
    ASGIScopeBridge,
    current_request_var,
    current_scope_var,
    get_current_request,
    get_current_scope,
)
from fast_mcp.reflector import ReflectedTool, RouteReflector
from fast_mcp.router import BaseToolRouter, KeywordTagRouter
from fast_mcp.tools import CustomTool, MCPTool


class SearchToolsInput(BaseModel):
    query: str = Field(
        description="Search query to discover relevant tools by name, description, or tags"
    )


class _SSEEndpoint:
    def __init__(self, transport: SseServerTransport, server: Server, bridge: ASGIScopeBridge) -> None:
        self.transport = transport
        self.server = server
        self.bridge = bridge

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        before_sessions = set(self.transport._read_stream_writers.keys())
        async with self.transport.connect_sse(scope, receive, send) as (read_stream, write_stream):
            after_sessions = set(self.transport._read_stream_writers.keys())
            diff = after_sessions - before_sessions
            session_id = diff.pop().hex if diff else None
            if session_id:
                self.bridge.record_sse_scope(session_id, scope)
            try:
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options(),
                )
            finally:
                if session_id:
                    self.bridge.remove_session(session_id)


class _MessagesEndpoint:
    def __init__(self, transport: SseServerTransport, bridge: ASGIScopeBridge) -> None:
        self.transport = transport
        self.bridge = bridge

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        query_string = scope.get("query_string", b"").decode("latin-1")
        params = parse_qs(query_string)
        session_ids = params.get("session_id", [])
        if session_ids:
            self.bridge.record_message_scope(session_ids[0], scope)
        await self.transport.handle_post_message(scope, receive, send)


class FastMCP:
    """Hybrid server instance bound directly to a FastAPI application."""

    def __init__(
        self,
        app: FastAPI | None = None,
        name: str = "fast-mcp",
        version: str = "0.1.0",
        mount_path: str = "/mcp",
        route_tag: str = "mcp",
        dynamic_discovery: bool = False,
        router: BaseToolRouter | None = None,
        baseline_tools: list[str] | set[str] | None = None,
        baseline_tag: str = "baseline",
        dynamic_discovery_threshold: int | None = None,
    ) -> None:
        self.app = app
        self.name = name
        self.version = version
        self.mount_path = mount_path.rstrip("/")
        self.route_tag = route_tag
        self.dynamic_discovery = dynamic_discovery
        self.dynamic_discovery_threshold = dynamic_discovery_threshold
        self.router = router if router is not None else (KeywordTagRouter() if dynamic_discovery else None)
        self.baseline_tools = set(baseline_tools or [])
        self.baseline_tag = baseline_tag

        self.reflector = RouteReflector(tag=self.route_tag)
        self.scope_bridge = ASGIScopeBridge()
        self._reflected_tools: dict[str, ReflectedTool] = {}
        self._custom_tools: dict[str, CustomTool] = {}

        self.server = Server(
            name=self.name,
            version=self.version,
            on_list_tools=self._handle_list_tools,
            on_call_tool=self._handle_call_tool,
        )
        self.sse_transport = SseServerTransport(f"{self.mount_path}/messages")
        self._mounted = False

    def tool(
        self,
        name_or_func: str | Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> Any:
        """Register a custom AI tool on the FastMCP instance.

        Can be used as a decorator with or without arguments:
            @mcp.tool
            def my_tool(...): ...

            @mcp.tool()
            def my_tool(...): ...

            @mcp.tool(name="custom", description="...", tags=["ai"])
            def my_tool(...): ...
        """
        # Bare decorator without parentheses: @mcp.tool
        if callable(name_or_func):
            fn = name_or_func
            custom_tool = CustomTool.from_func(fn, name=name, description=description, tags=tags)
            self._custom_tools[custom_tool.name] = custom_tool
            return fn

        # Decorator with parentheses or arguments: @mcp.tool(...)
        resolved_name = name or (name_or_func if isinstance(name_or_func, str) else None)

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            custom_tool = CustomTool.from_func(fn, name=resolved_name, description=description, tags=tags)
            self._custom_tools[custom_tool.name] = custom_tool
            return fn

        return decorator

    @staticmethod
    def get_current_request() -> Request | None:
        """Access the active synthetic ASGI Request inside a tool execution."""
        return get_current_request()

    @staticmethod
    def get_current_scope() -> dict[str, Any] | None:
        """Access the active ASGI scope inside a tool execution."""
        return get_current_scope()

    @property
    def _all_tools(self) -> dict[str, MCPTool]:
        return {**self._reflected_tools, **self._custom_tools}

    @property
    def is_dynamic_discovery_active(self) -> bool:
        return bool(
            self.dynamic_discovery
            or (
                self.dynamic_discovery_threshold is not None
                and len(self._all_tools) > self.dynamic_discovery_threshold
            )
        )

    def _get_active_router(self) -> BaseToolRouter:
        if self.router is None:
            self.router = KeywordTagRouter()
        return self.router

    def _is_baseline_tool(self, tool: MCPTool) -> bool:
        return bool(
            (self.baseline_tools and tool.name in self.baseline_tools)
            or (self.baseline_tag and self.baseline_tag in (tool.tags or []))
        )

    def _get_search_tools_meta_tool(self) -> types.Tool:
        schema = SearchToolsInput.model_json_schema()
        return types.Tool(
            name="search_tools",
            description="Search available tools by keyword or description query to progressively discover tools relevant to your task.",
            inputSchema=schema,
        )

    def _tool_to_schema_dict(self, tool: Any) -> dict[str, Any]:
        if hasattr(tool, "to_mcp_tool"):
            mcp_tool = tool.to_mcp_tool()
            d = mcp_tool.model_dump(by_alias=True, exclude_none=True)
        elif isinstance(tool, types.Tool):
            d = tool.model_dump(by_alias=True, exclude_none=True)
        elif isinstance(tool, dict):
            d = dict(tool)
        else:
            name = getattr(tool, "name", "")
            description = getattr(tool, "description", "")
            input_schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {}) or {}
            d = {"name": name, "description": description, "inputSchema": input_schema}

        # Normalize both inputSchema and input_schema for client convenience
        if "inputSchema" in d and "input_schema" not in d:
            d["input_schema"] = d["inputSchema"]
        elif "input_schema" in d and "inputSchema" not in d:
            d["inputSchema"] = d["input_schema"]

        return d

    async def _handle_list_tools(
        self,
        ctx: ServerRequestContext[Any],
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        if self.is_dynamic_discovery_active:
            tools = [
                tool.to_mcp_tool()
                for tool in self._all_tools.values()
                if self._is_baseline_tool(tool)
            ]
            tools.append(self._get_search_tools_meta_tool())
            return types.ListToolsResult(tools=tools)

        tools = [tool.to_mcp_tool() for tool in self._all_tools.values()]
        return types.ListToolsResult(tools=tools)

    async def _handle_search_tools(
        self, arguments: dict[str, Any] | None = None
    ) -> types.CallToolResult:
        args = arguments or {}
        query = args.get("query", args.get("q", ""))
        if not isinstance(query, str):
            query = str(query)

        candidate_tools = [
            tool for name, tool in self._all_tools.items()
            if name != "search_tools"
        ]

        active_router = self._get_active_router()
        res = active_router.select_tools(query, candidate_tools)
        if inspect.isawaitable(res):
            matching = await res
        else:
            matching = res

        serialized_tools = [self._tool_to_schema_dict(t) for t in matching]
        text = json.dumps(serialized_tools, separators=(",", ":"))
        return types.CallToolResult(
            is_error=False,
            content=[types.TextContent(type="text", text=text)],
        )

    async def _handle_call_tool(
        self,
        ctx: ServerRequestContext[Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult | types.InputRequiredResult:
        tool_name = params.name

        if tool_name == "search_tools" and self.is_dynamic_discovery_active:
            return await self._handle_search_tools(params.arguments)

        all_tools = self._all_tools
        if tool_name not in all_tools:
            return types.CallToolResult(
                is_error=True,
                content=[types.TextContent(type="text", text=f"Unknown tool: {tool_name}")],
            )

        tool = all_tools[tool_name]

        session_id: str | None = None
        msg_scope: dict[str, Any] | None = None
        if hasattr(ctx, "request") and ctx.request is not None:
            session_id = ctx.request.query_params.get("session_id")
            msg_scope = ctx.request.scope

        scoped_context = self.scope_bridge.get_scoped_context(session_id, msg_scope)

        async with AsyncExitStack() as astack:
            request = self.scope_bridge.synthesize_request(
                scope=scoped_context,
                args=params.arguments,
                app=self.app,
                astack=astack,
            )

            # Set ContextVars for client scope/request
            token_scope = current_scope_var.set(request.scope)
            token_req = current_request_var.set(request)
            try:
                raw_result = await tool.invoke(
                    arguments=params.arguments,
                    request=request,
                    app=self.app,
                )
                encoded = jsonable_encoder(raw_result)
                if isinstance(encoded, (dict, list)):
                    text = json.dumps(encoded, separators=(",", ":"))
                else:
                    text = str(encoded)

                return types.CallToolResult(
                    is_error=False,
                    content=[types.TextContent(type="text", text=text)],
                )
            except HTTPException as exc:
                return types.CallToolResult(
                    is_error=True,
                    content=[types.TextContent(type="text", text=f"Error {exc.status_code}: {exc.detail}")],
                )
            except RequestValidationError as exc:
                return types.CallToolResult(
                    is_error=True,
                    content=[types.TextContent(type="text", text=f"Validation error: {exc}")],
                )
            except Exception as exc:
                return types.CallToolResult(
                    is_error=True,
                    content=[types.TextContent(type="text", text=str(exc))],
                )
            finally:
                current_scope_var.reset(token_scope)
                current_request_var.reset(token_req)

    def mount(self, app: FastAPI | None = None) -> None:
        target_app = app or self.app
        if target_app is None:
            raise ValueError("No FastAPI application provided to mount.")
        self.app = target_app

        if self._mounted:
            return

        # Perform route reflection
        self._reflected_tools = self.reflector.reflect_routes(target_app.routes)

        if self.is_dynamic_discovery_active and self.router is None:
            self.router = KeywordTagRouter()

        # Mount ASGI endpoints
        target_app.routes.append(
            Route(
                f"{self.mount_path}/sse",
                endpoint=_SSEEndpoint(self.sse_transport, self.server, self.scope_bridge),
                methods=["GET"],
            )
        )
        target_app.routes.append(
            Route(
                f"{self.mount_path}/messages",
                endpoint=_MessagesEndpoint(self.sse_transport, self.scope_bridge),
                methods=["POST"],
            )
        )
        self._mounted = True

from __future__ import annotations

from contextlib import AsyncExitStack
import inspect
import json
import typing
from typing import Any, Callable
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.routing import Route

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import ServerRequestContext
from mcp.server.sse import SseServerTransport
from pydantic import BaseModel, Field, ValidationError


def format_validation_error(exc: Any) -> str:
    """Format Pydantic or FastAPI validation errors into clean, human-readable strings."""
    try:
        errors = exc.errors() if hasattr(exc, "errors") else []
        if not errors:
            return f"Validation error: {exc}"

        formatted_lines: list[str] = []
        for err in errors:
            loc = err.get("loc", ())
            field_parts = [str(p) for p in loc if p != "body"]
            field_str = ".".join(field_parts) if field_parts else "input"
            msg = err.get("msg", "Invalid value")
            formatted_lines.append(f"{field_str}: {msg}")

        if len(formatted_lines) == 1:
            return f"Validation error: {formatted_lines[0]}"
        return "Validation error:\n" + "\n".join(f"- {line}" for line in formatted_lines)
    except Exception:
        return f"Validation error: {exc}"

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
        debug: bool = False,
    ) -> None:
        self.app = app
        self.name = name
        self.version = version
        self.mount_path = mount_path.rstrip("/")
        self.route_tag = route_tag
        self.dynamic_discovery = dynamic_discovery
        self.dynamic_discovery_threshold = dynamic_discovery_threshold
        self.debug = debug
        self.router = router if router is not None else (KeywordTagRouter() if dynamic_discovery else None)
        self.baseline_tools = set(baseline_tools or [])
        self.baseline_tag = baseline_tag

        self.reflector = RouteReflector(tag=self.route_tag)
        self.scope_bridge = ASGIScopeBridge()
        self._reflected_tools: dict[str, ReflectedTool] = {}
        self._custom_tools: dict[str, CustomTool] = {}
        self._serializers: dict[type, Callable[[Any], Any]] = {}

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

    def register_serializer(
        self, target_type: type, serializer_fn: Callable[[Any], Any]
    ) -> None:
        """Register a custom response serializer callable for a specific return type or model."""
        if not isinstance(target_type, type):
            raise TypeError(f"target_type must be a type/class, got {type(target_type).__name__}")
        self._serializers[target_type] = serializer_fn

    def add_serializer(
        self, target_type: type, serializer_fn: Callable[[Any], Any]
    ) -> None:
        """Alias for register_serializer."""
        self.register_serializer(target_type, serializer_fn)

    def serializer(
        self,
        type_or_func: type | Callable[..., Any] | None = None,
        *,
        target_type: type | None = None,
        **kwargs: Any,
    ) -> Any:
        """Register a custom response serializer for specific return types/classes.

        Can be used as:
            @mcp.serializer(User)
            def format_user(user: User) -> str: ...

            @mcp.serializer
            def format_user(user: User) -> str: ...

            @mcp.serializer()
            def format_user(user: User) -> str: ...

            @mcp.serializer(target_type=User)
            def format_user(user: User) -> str: ...
        """
        kw_type = target_type or kwargs.get("type")
        is_type = isinstance(type_or_func, type)
        explicit_type = type_or_func if (type_or_func is not None and is_type) else kw_type

        def _infer_type(fn: Callable[..., Any]) -> type:
            try:
                hints = typing.get_type_hints(fn)
            except Exception:
                hints = {}

            sig = inspect.signature(fn)
            params = list(sig.parameters.values())
            if not params:
                raise ValueError("Serializer function must accept at least one argument.")
            first_param = params[0]
            param_name = first_param.name

            resolved_ann = hints.get(param_name)
            if resolved_ann is None:
                raw_ann = first_param.annotation
                if raw_ann is not inspect.Parameter.empty and isinstance(raw_ann, type):
                    resolved_ann = raw_ann
                elif isinstance(raw_ann, str):
                    if hasattr(fn, "__globals__") and raw_ann in fn.__globals__:
                        val = fn.__globals__[raw_ann]
                        if isinstance(val, type):
                            resolved_ann = val
                    if resolved_ann is None:
                        frame = inspect.currentframe()
                        while frame:
                            if raw_ann in frame.f_locals:
                                val = frame.f_locals[raw_ann]
                                if isinstance(val, type):
                                    resolved_ann = val
                                    break
                            if raw_ann in frame.f_globals:
                                val = frame.f_globals[raw_ann]
                                if isinstance(val, type):
                                    resolved_ann = val
                                    break
                            frame = frame.f_back

            if (
                resolved_ann is None
                or resolved_ann is inspect.Parameter.empty
                or not isinstance(resolved_ann, type)
            ):
                raise ValueError(
                    f"Serializer function '{fn.__name__}' must have a type annotation on its first argument or specify target type explicitly: @mcp.serializer(TargetType)"
                )
            return resolved_ann

        # Bare decorator: @mcp.serializer
        if type_or_func is not None and callable(type_or_func) and not is_type:
            fn = type_or_func
            resolved = explicit_type or _infer_type(fn)
            self.register_serializer(resolved, fn)
            return fn

        # Decorator with arguments: @mcp.serializer(TargetType) or @mcp.serializer()
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            resolved = explicit_type or _infer_type(fn)
            self.register_serializer(resolved, fn)
            return fn

        return decorator

    def _find_serializer(self, result_type: type) -> Callable[[Any], Any] | None:
        """Lookup serializer for result_type, honoring class inheritance via MRO."""
        if result_type in self._serializers:
            return self._serializers[result_type]
        for base in inspect.getmro(result_type):
            if base is object:
                continue
            if base in self._serializers:
                return self._serializers[base]
        if object in self._serializers:
            return self._serializers[object]
        return None

    async def _serialize_result(self, raw_result: Any) -> types.CallToolResult:
        """Serialize a raw tool return value into an MCP CallToolResult."""
        if isinstance(raw_result, types.CallToolResult):
            return raw_result

        if isinstance(raw_result, types.TextContent):
            return types.CallToolResult(is_error=False, content=[raw_result])

        serializer = self._find_serializer(type(raw_result))
        if serializer is not None:
            formatted = serializer(raw_result)
            if inspect.isawaitable(formatted):
                formatted = await formatted

            if isinstance(formatted, types.CallToolResult):
                return formatted
            if isinstance(formatted, types.TextContent):
                return types.CallToolResult(is_error=False, content=[formatted])
            if isinstance(formatted, str):
                text = formatted
            elif isinstance(formatted, (dict, list)):
                encoded = jsonable_encoder(formatted)
                text = json.dumps(encoded, separators=(",", ":"))
            else:
                text = str(formatted)
            return types.CallToolResult(
                is_error=False,
                content=[types.TextContent(type="text", text=text)],
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
                return await self._serialize_result(raw_result)
            except (HTTPException, StarletteHTTPException) as exc:
                detail = exc.detail
                if isinstance(detail, (dict, list)):
                    detail_str = json.dumps(detail)
                else:
                    detail_str = str(detail)
                return types.CallToolResult(
                    is_error=True,
                    content=[types.TextContent(type="text", text=f"Error {exc.status_code}: {detail_str}")],
                )
            except (RequestValidationError, ValidationError) as exc:
                return types.CallToolResult(
                    is_error=True,
                    content=[types.TextContent(type="text", text=format_validation_error(exc))],
                )
            except Exception as exc:
                if self.debug:
                    import traceback
                    tb = traceback.format_exc()
                    err_msg = f"Internal error: {type(exc).__name__}: {exc}\n{tb}"
                else:
                    err_msg = f"Error: {exc}" if str(exc) else f"Internal error: {type(exc).__name__}"
                return types.CallToolResult(
                    is_error=True,
                    content=[types.TextContent(type="text", text=err_msg)],
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

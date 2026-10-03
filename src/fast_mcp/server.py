from __future__ import annotations

import json
from typing import Any
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from starlette.routing import Route
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import ServerRequestContext
from mcp.server.sse import SseServerTransport
import mcp.types as types

from fast_mcp.reflector import ReflectedTool, RouteReflector


class _SSEEndpoint:
    def __init__(self, transport: SseServerTransport, server: Server) -> None:
        self.transport = transport
        self.server = server

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        async with self.transport.connect_sse(scope, receive, send) as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


class _MessagesEndpoint:
    def __init__(self, transport: SseServerTransport) -> None:
        self.transport = transport

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
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
    ) -> None:
        self.app = app
        self.name = name
        self.version = version
        self.mount_path = mount_path.rstrip("/")
        self.route_tag = route_tag

        self.reflector = RouteReflector(tag=self.route_tag)
        self._reflected_tools: dict[str, ReflectedTool] = {}

        self.server = Server(
            name=self.name,
            version=self.version,
            on_list_tools=self._handle_list_tools,
            on_call_tool=self._handle_call_tool,
        )
        self.sse_transport = SseServerTransport(f"{self.mount_path}/messages")
        self._mounted = False

    async def _handle_list_tools(
        self,
        ctx: ServerRequestContext[Any],
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        tools = [tool.to_mcp_tool() for tool in self._reflected_tools.values()]
        return types.ListToolsResult(tools=tools)

    async def _handle_call_tool(
        self,
        ctx: ServerRequestContext[Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult | types.InputRequiredResult:
        tool_name = params.name
        if tool_name not in self._reflected_tools:
            return types.CallToolResult(
                is_error=True,
                content=[types.TextContent(type="text", text=f"Unknown tool: {tool_name}")],
            )

        reflected = self._reflected_tools[tool_name]
        try:
            raw_result = await reflected.invoke(params.arguments)
            encoded = jsonable_encoder(raw_result)
            if isinstance(encoded, (dict, list)):
                text = json.dumps(encoded, separators=(",", ":"))
            else:
                text = str(encoded)

            return types.CallToolResult(
                is_error=False,
                content=[types.TextContent(type="text", text=text)],
            )
        except Exception as e:
            return types.CallToolResult(
                is_error=True,
                content=[types.TextContent(type="text", text=str(e))],
            )

    def mount(self, app: FastAPI | None = None) -> None:
        target_app = app or self.app
        if target_app is None:
            raise ValueError("No FastAPI application provided to mount.")
        self.app = target_app

        if self._mounted:
            return

        # Perform route reflection
        self._reflected_tools = self.reflector.reflect_routes(target_app.routes)

        # Mount ASGI endpoints
        target_app.routes.append(
            Route(
                f"{self.mount_path}/sse",
                endpoint=_SSEEndpoint(self.sse_transport, self.server),
                methods=["GET"],
            )
        )
        target_app.routes.append(
            Route(
                f"{self.mount_path}/messages",
                endpoint=_MessagesEndpoint(self.sse_transport),
                methods=["POST"],
            )
        )
        self._mounted = True

from __future__ import annotations

import inspect
from typing import Any, Callable
from fastapi.routing import APIRoute
from pydantic import BaseModel
from fast_mcp.tools import MCPTool, build_tool_schema_and_models, parse_docstring_params


class ReflectedTool(MCPTool):
    """Represents a reflected FastAPI route exposed as an MCP tool."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        endpoint: Callable[..., Any],
        route: APIRoute,
        body_param_names: list[str],
        body_models: dict[str, type[BaseModel]],
        tags: list[str] | None = None,
        input_model: type[BaseModel] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            input_schema=input_schema,
            fn=endpoint,
            dependant=route.dependant,
            body_param_names=body_param_names,
            body_models=body_models,
            tags=tags if tags is not None else list(route.tags or []),
            input_model=input_model,
        )
        self.endpoint = endpoint
        self.route = route


class RouteReflector:
    """Reflects FastAPI routes into MCP tool definitions."""

    def __init__(self, tag: str = "mcp") -> None:
        self.tag = tag

    def reflect_route(self, route: APIRoute) -> ReflectedTool | None:
        if self.tag not in (route.tags or []):
            return None

        tool_name = route.name or getattr(route.endpoint, "__name__", "unknown_tool")

        # Extract docstring or summary
        raw_doc = (
            route.description
            or (inspect.getdoc(route.endpoint) if route.endpoint else "")
            or route.summary
            or ""
        )
        description = inspect.cleandoc(raw_doc) if raw_doc else ""
        doc_params = parse_docstring_params(raw_doc)

        input_schema, body_param_names, body_models, input_model = build_tool_schema_and_models(
            tool_name=tool_name,
            dependant=route.dependant,
            docstring_params=doc_params,
        )

        return ReflectedTool(
            name=tool_name,
            description=description,
            input_schema=input_schema,
            endpoint=route.endpoint,
            route=route,
            body_param_names=body_param_names,
            body_models=body_models,
            tags=list(route.tags or []),
            input_model=input_model,
        )

    def reflect_routes(self, routes: list[Any]) -> dict[str, ReflectedTool]:
        tools: dict[str, ReflectedTool] = {}
        for route in routes:
            if isinstance(route, APIRoute):
                reflected = self.reflect_route(route)
                if reflected:
                    tools[reflected.name] = reflected
            elif hasattr(route, "routes"):
                # Nested router or mount
                tools.update(self.reflect_routes(route.routes))
        return tools

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable
from fastapi.routing import APIRoute
from pydantic import BaseModel, create_model, Field
import mcp.types as types


class ReflectedTool:
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
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.endpoint = endpoint
        self.route = route
        self.body_param_names = body_param_names
        self.body_models = body_models

    def to_mcp_tool(self) -> types.Tool:
        return types.Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
        )

    async def invoke(self, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        call_kwargs: dict[str, Any] = {}

        # 1. Match path & query parameters
        for param in self.route.dependant.path_params + self.route.dependant.query_params:
            if param.name in args:
                call_kwargs[param.name] = args[param.name]
            elif param.alias in args:
                call_kwargs[param.name] = args[param.alias]
            elif not param.field_info.is_required() and param.field_info.default is not ...:
                call_kwargs[param.name] = param.field_info.default

        # 2. Match body parameters
        for body_param in self.route.dependant.body_params:
            param_name = body_param.name
            if param_name in self.body_models:
                model_cls = self.body_models[param_name]
                if param_name in args and isinstance(args[param_name], dict):
                    call_kwargs[param_name] = model_cls.model_validate(args[param_name])
                else:
                    # Filter keys matching model fields
                    model_data = {k: v for k, v in args.items() if k in model_cls.model_fields}
                    call_kwargs[param_name] = model_cls.model_validate(model_data)
            else:
                if param_name in args:
                    call_kwargs[param_name] = args[param_name]
                elif not body_param.field_info.is_required() and body_param.field_info.default is not ...:
                    call_kwargs[param_name] = body_param.field_info.default

        # 3. Call endpoint handler
        if inspect.iscoroutinefunction(self.endpoint):
            return await self.endpoint(**call_kwargs)
        else:
            return await asyncio.to_thread(self.endpoint, **call_kwargs)


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

        dependant = route.dependant
        fields: dict[str, Any] = {}
        body_param_names: list[str] = []
        body_models: dict[str, type[BaseModel]] = {}

        # 1. Path & query parameters
        for param in dependant.path_params + dependant.query_params:
            param_name = param.name
            annotation = param.field_info.annotation or Any
            if param.field_info.is_required():
                default = ...
            else:
                default = param.field_info.default

            field_kw: dict[str, Any] = {"default": default}
            if param.field_info.description:
                field_kw["description"] = param.field_info.description
            if param.field_info.title:
                field_kw["title"] = param.field_info.title

            fields[param_name] = (annotation, Field(**field_kw))

        # 2. Body parameters
        for body_param in dependant.body_params:
            param_name = body_param.name
            body_param_names.append(param_name)
            annotation = body_param.field_info.annotation

            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                body_models[param_name] = annotation
                # Unpack BaseModel fields into top-level tool parameters
                for fname, finfo in annotation.model_fields.items():
                    fields[fname] = (finfo.annotation, finfo)
            else:
                default = ... if body_param.field_info.is_required() else body_param.field_info.default
                fields[param_name] = (annotation or Any, Field(default=default))

        # Build JSON Schema
        if fields:
            model = create_model(f"{tool_name}_Input", **fields)
            input_schema = model.model_json_schema()
            input_schema["type"] = "object"
        else:
            input_schema = {"type": "object", "properties": {}}

        return ReflectedTool(
            name=tool_name,
            description=description,
            input_schema=input_schema,
            endpoint=route.endpoint,
            route=route,
            body_param_names=body_param_names,
            body_models=body_models,
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

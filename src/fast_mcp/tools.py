from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import inspect
import re
from typing import Any, Callable
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant, solve_dependencies
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, create_model
from starlette.requests import Request
import mcp.types as types


def parse_docstring_params(doc: str | None) -> dict[str, str]:
    """Parse parameter descriptions from Google-style or Sphinx-style docstrings."""
    if not doc:
        return {}

    params: dict[str, str] = {}
    lines = doc.splitlines()

    # 1. Sphinx style: :param <name>: <desc> or :param <type> <name>: <desc>
    sphinx_re = re.compile(r"^\s*:param\s+(?:(?:\w+)\s+)?(\w+)\s*:\s*(.*)$")
    for line in lines:
        m = sphinx_re.match(line)
        if m:
            params[m.group(1)] = m.group(2).strip()

    # 2. Google / NumPy style
    in_args = False
    cur_arg: str | None = None
    cur_desc: list[str] = []
    google_arg_re = re.compile(r"^\s{4,}(\w+)(?:\s*\([^)]*\))?\s*:\s*(.*)$")

    for line in lines:
        stripped = line.strip()
        if stripped in ("Args:", "Arguments:", "Parameters:", "Parameters\n----------"):
            in_args = True
            continue
        elif in_args and stripped and not line.startswith(" ") and not line.startswith("\t"):
            in_args = False

        if in_args:
            m = google_arg_re.match(line)
            if m:
                if cur_arg and cur_arg not in params:
                    params[cur_arg] = " ".join(cur_desc).strip()
                cur_arg = m.group(1)
                cur_desc = [m.group(2).strip()] if m.group(2).strip() else []
            elif cur_arg and (line.startswith("        ") or line.startswith("\t\t")):
                cur_desc.append(line.strip())

    if cur_arg and cur_arg not in params:
        params[cur_arg] = " ".join(cur_desc).strip()

    return params


def build_tool_schema_and_models(
    tool_name: str,
    dependant: Dependant,
    docstring_params: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[str], dict[str, type[BaseModel]], type[BaseModel] | None]:
    """Inspect a function's Dependant and generate an MCP JSON schema and parameter mappings."""
    doc_params = docstring_params or {}
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

        desc = param.field_info.description or doc_params.get(param_name)
        field_kw: dict[str, Any] = {"default": default}
        if desc:
            field_kw["description"] = desc
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
                desc = finfo.description or doc_params.get(fname)
                fkw: dict[str, Any] = {
                    "default": ... if finfo.is_required() else finfo.default,
                }
                if desc:
                    fkw["description"] = desc
                if finfo.title:
                    fkw["title"] = finfo.title
                fields[fname] = (finfo.annotation, Field(**fkw))
        else:
            default = ... if body_param.field_info.is_required() else body_param.field_info.default
            desc = body_param.field_info.description or doc_params.get(param_name)
            fkw = {"default": default}
            if desc:
                fkw["description"] = desc
            fields[param_name] = (annotation or Any, Field(**fkw))

    # Build JSON Schema and input model
    if fields:
        model = create_model(f"{tool_name}_Input", **fields)
        input_schema = model.model_json_schema()
        input_schema["type"] = "object"
    else:
        model = None
        input_schema = {"type": "object", "properties": {}}

    return input_schema, body_param_names, body_models, model


class MCPTool:
    """Base class for MCP tools with ASGI-bridged dependency resolution."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        fn: Callable[..., Any],
        dependant: Dependant,
        body_param_names: list[str],
        body_models: dict[str, type[BaseModel]],
        tags: list[str] | None = None,
        input_model: type[BaseModel] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.fn = fn
        self.dependant = dependant
        self.body_param_names = body_param_names
        self.body_models = body_models
        self.tags = tags or []
        self.input_model = input_model

        # Create a dependency-only Dependant for solving FastAPI Depends() and Security()
        self.dependency_dependant = Dependant(
            dependencies=dependant.dependencies,
            header_params=dependant.header_params,
            cookie_params=dependant.cookie_params,
            request_param_name=dependant.request_param_name,
            websocket_param_name=dependant.websocket_param_name,
            http_connection_param_name=dependant.http_connection_param_name,
            response_param_name=dependant.response_param_name,
            background_tasks_param_name=dependant.background_tasks_param_name,
            security_scopes_param_name=dependant.security_scopes_param_name,
            own_oauth_scopes=dependant.own_oauth_scopes,
            parent_oauth_scopes=dependant.parent_oauth_scopes,
            use_cache=dependant.use_cache,
            path=dependant.path,
            scope=dependant.scope,
        )

    def to_mcp_tool(self) -> types.Tool:
        return types.Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
        )

    async def invoke(
        self,
        arguments: dict[str, Any] | None = None,
        request: Request | None = None,
        app: Any = None,
    ) -> Any:
        args = arguments or {}
        call_kwargs: dict[str, Any] = {}

        if self.input_model is not None:
            args_to_validate = dict(args)
            for body_param_name in self.body_models:
                if body_param_name in args_to_validate and isinstance(args_to_validate[body_param_name], dict):
                    for k, v in args_to_validate[body_param_name].items():
                        if k not in args_to_validate:
                            args_to_validate[k] = v

            for param in self.dependant.path_params + self.dependant.query_params:
                if param.alias and param.alias in args_to_validate and param.name not in args_to_validate:
                    args_to_validate[param.name] = args_to_validate[param.alias]

            validated = self.input_model.model_validate(args_to_validate)

            # 1. Match path & query parameters
            for param in self.dependant.path_params + self.dependant.query_params:
                if hasattr(validated, param.name):
                    call_kwargs[param.name] = getattr(validated, param.name)
                elif param.alias and hasattr(validated, param.alias):
                    call_kwargs[param.name] = getattr(validated, param.alias)
                elif not param.field_info.is_required() and param.field_info.default is not ...:
                    call_kwargs[param.name] = param.field_info.default

            # 2. Match body parameters
            for body_param in self.dependant.body_params:
                param_name = body_param.name
                if param_name in self.body_models:
                    model_cls = self.body_models[param_name]
                    if param_name in args and isinstance(args[param_name], dict):
                        call_kwargs[param_name] = model_cls.model_validate(args[param_name])
                    else:
                        model_data = {
                            k: getattr(validated, k)
                            for k in model_cls.model_fields
                            if hasattr(validated, k)
                        }
                        call_kwargs[param_name] = model_cls.model_validate(model_data)
                else:
                    if hasattr(validated, param_name):
                        call_kwargs[param_name] = getattr(validated, param_name)
                    elif not body_param.field_info.is_required() and body_param.field_info.default is not ...:
                        call_kwargs[param_name] = body_param.field_info.default
        else:
            # Fallback when no input_model exists
            for param in self.dependant.path_params + self.dependant.query_params:
                if param.name in args:
                    call_kwargs[param.name] = args[param.name]
                elif param.alias in args:
                    call_kwargs[param.name] = args[param.alias]
                elif not param.field_info.is_required() and param.field_info.default is not ...:
                    call_kwargs[param.name] = param.field_info.default

            for body_param in self.dependant.body_params:
                param_name = body_param.name
                if param_name in self.body_models:
                    model_cls = self.body_models[param_name]
                    if param_name in args and isinstance(args[param_name], dict):
                        call_kwargs[param_name] = model_cls.model_validate(args[param_name])
                    else:
                        model_data = {k: v for k, v in args.items() if k in model_cls.model_fields}
                        call_kwargs[param_name] = model_cls.model_validate(model_data)
                else:
                    if param_name in args:
                        call_kwargs[param_name] = args[param_name]
                    elif not body_param.field_info.is_required() and body_param.field_info.default is not ...:
                        call_kwargs[param_name] = body_param.field_info.default

        # 3. Resolve FastAPI dependencies (Depends, Security, Header, Cookie)
        if request is not None and (
            self.dependency_dependant.dependencies
            or self.dependency_dependant.header_params
            or self.dependency_dependant.cookie_params
            or self.dependency_dependant.request_param_name
        ):
            astack = request.scope.get("fastapi_inner_astack")
            assert isinstance(astack, AsyncExitStack), (
                "fastapi_inner_astack not found in request scope"
            )
            solved_result = await solve_dependencies(
                request=request,
                dependant=self.dependency_dependant,
                dependency_overrides_provider=app,
                async_exit_stack=astack,
                embed_body_fields=False,
            )
            if solved_result.errors:
                raise RequestValidationError(solved_result.errors)
            call_kwargs.update(solved_result.values)

        if request is not None and self.dependant.request_param_name:
            call_kwargs[self.dependant.request_param_name] = request

        # 4. Invoke endpoint / handler (coroutine or sync threadpool)
        if inspect.iscoroutinefunction(self.fn):
            return await self.fn(**call_kwargs)
        else:
            return await asyncio.to_thread(self.fn, **call_kwargs)


class CustomTool(MCPTool):
    """Represents a custom AI tool registered via @mcp.tool()."""

    @classmethod
    def from_func(
        cls,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> CustomTool:
        tool_name = name or fn.__name__
        raw_doc = inspect.getdoc(fn) or ""
        tool_desc = description or inspect.cleandoc(raw_doc) if (description or raw_doc) else ""

        doc_params = parse_docstring_params(raw_doc)
        dependant = get_dependant(path="", call=fn)
        input_schema, body_param_names, body_models, input_model = build_tool_schema_and_models(
            tool_name=tool_name,
            dependant=dependant,
            docstring_params=doc_params,
        )

        return cls(
            name=tool_name,
            description=tool_desc,
            input_schema=input_schema,
            fn=fn,
            dependant=dependant,
            body_param_names=body_param_names,
            body_models=body_models,
            tags=tags or [],
            input_model=input_model,
        )

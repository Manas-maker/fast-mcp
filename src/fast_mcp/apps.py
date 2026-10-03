from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable
from fastapi.dependencies.utils import get_dependant
from pydantic import BaseModel
from mcp import types
from mcp.shared.exceptions import MCPError

from fast_mcp.tools import CustomTool, build_tool_schema_and_models, parse_docstring_params


class UIResource:
    """Represents an interactive MCP UI resource (SEP-1865)."""

    def __init__(
        self,
        uri: str,
        name: str = "",
        description: str = "",
        mime_type: str = "text/html",
        content: str | Callable[[], str | Awaitable[str]] = "",
    ) -> None:
        self.uri = uri
        self.name = name or uri.split("/")[-1]
        self.description = description
        self.mime_type = mime_type
        self.content = content

    async def get_content(self) -> str:
        """Resolve and return the HTML content string."""
        if callable(self.content):
            res = self.content()
            if inspect.isawaitable(res):
                return str(await res)
            return str(res)
        return str(self.content)

    def to_mcp_resource(self) -> types.Resource:
        return types.Resource(
            uri=self.uri,
            name=self.name,
            description=self.description,
            mimeType=self.mime_type,
        )


class MCPApp(CustomTool):
    """Represents an interactive in-chat MCP App widget (SEP-1865)."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        fn: Callable[..., Any],
        dependant: Any,
        body_param_names: list[str],
        body_models: dict[str, type[BaseModel]],
        resource_uri: str,
        html: str | Callable[..., Any] | None = None,
        tags: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        merged_meta = dict(meta or {})
        merged_meta["ui"] = {"resourceUri": resource_uri}
        super().__init__(
            name=name,
            description=description,
            input_schema=input_schema,
            fn=fn,
            dependant=dependant,
            body_param_names=body_param_names,
            body_models=body_models,
            tags=tags,
            meta=merged_meta,
        )
        self.resource_uri = resource_uri
        self.html = html

    @classmethod
    def from_func(
        cls,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        resource_uri: str | None = None,
        html: str | Callable[..., Any] | None = None,
        tags: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> MCPApp:
        tool_name = name or fn.__name__
        raw_doc = inspect.getdoc(fn) or ""
        tool_desc = description or inspect.cleandoc(raw_doc) if (description or raw_doc) else ""

        doc_params = parse_docstring_params(raw_doc)
        dependant = get_dependant(path="", call=fn)
        input_schema, body_param_names, body_models = build_tool_schema_and_models(
            tool_name=tool_name,
            dependant=dependant,
            docstring_params=doc_params,
        )

        resolved_uri = resource_uri or f"ui://fast-mcp/{tool_name}"

        return cls(
            name=tool_name,
            description=tool_desc,
            input_schema=input_schema,
            fn=fn,
            dependant=dependant,
            body_param_names=body_param_names,
            body_models=body_models,
            resource_uri=resolved_uri,
            html=html,
            tags=tags or [],
            meta=meta,
        )


class MCPAppRegistry:
    """Registry managing interactive MCP Apps and UI resources."""

    def __init__(self) -> None:
        self._apps: dict[str, MCPApp] = {}
        self._resources: dict[str, UIResource] = {}

    def register_resource(
        self,
        uri: str,
        content: str | Callable[..., Any],
        name: str = "",
        description: str = "",
        mime_type: str = "text/html",
    ) -> UIResource:
        res = UIResource(
            uri=uri,
            name=name,
            description=description,
            mime_type=mime_type,
            content=content,
        )
        self._resources[uri] = res
        return res

    def register_app(self, app: MCPApp) -> None:
        self._apps[app.name] = app
        if app.resource_uri not in self._resources:
            # If explicit html provided, use that.
            # Otherwise, use a content generator that tries invoking fn or returns fallback HTML.
            if app.html is not None:
                content = app.html
            else:
                def default_content_generator() -> str:
                    try:
                        # Try calling if parameterless
                        sig = inspect.signature(app.fn)
                        required_params = [
                            p for p in sig.parameters.values()
                            if p.default is inspect.Parameter.empty
                            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                        ]
                        if not required_params:
                            val = app.fn()
                            if isinstance(val, str):
                                return val
                    except Exception:
                        pass
                    return (
                        f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                        f"<title>{app.name}</title></head>"
                        f"<body><div id='app'><h1>{app.name}</h1>"
                        f"<p>{app.description}</p></div></body></html>"
                    )
                content = default_content_generator

            self.register_resource(
                uri=app.resource_uri,
                content=content,
                name=app.name,
                description=app.description,
                mime_type="text/html",
            )

    def get_resource(self, uri: str) -> UIResource | None:
        return self._resources.get(uri)

    def get_app(self, name: str) -> MCPApp | None:
        return self._apps.get(name)

    def list_resources(self) -> list[types.Resource]:
        return [r.to_mcp_resource() for r in self._resources.values()]

    async def read_resource(self, uri: str) -> types.ReadResourceResult:
        res = self._resources.get(uri)
        if res is None:
            raise MCPError(types.INVALID_PARAMS, f"Resource not found: {uri}")
        content_text = await res.get_content()
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=res.uri,
                    mimeType=res.mime_type,
                    text=content_text,
                )
            ]
        )

from __future__ import annotations

from contextvars import ContextVar
from typing import Any
from urllib.parse import urlencode
from starlette.requests import Request
from starlette.types import Scope

current_scope_var: ContextVar[dict[str, Any] | None] = ContextVar("fast_mcp_current_scope", default=None)
current_request_var: ContextVar[Request | None] = ContextVar("fast_mcp_current_request", default=None)


def get_current_request() -> Request | None:
    """Return the active synthesized ASGI Request for the current tool execution, if any."""
    return current_request_var.get()


def get_current_scope() -> dict[str, Any] | None:
    """Return the active ASGI scope for the current tool execution, if any."""
    return current_scope_var.get()


class ASGIScopeBridge:
    """Bridges incoming SSE and HTTP transport scopes into in-memory ASGI request contexts."""

    def __init__(self) -> None:
        self._session_sse_scopes: dict[str, dict[str, Any]] = {}
        self._session_post_scopes: dict[str, dict[str, Any]] = {}

    def record_sse_scope(self, session_id: str, scope: Scope) -> None:
        """Capture the ASGI scope from an SSE handshake connection."""
        self._session_sse_scopes[session_id] = dict(scope)

    def remove_session(self, session_id: str) -> None:
        """Clean up stored session scopes when a client disconnects."""
        self._session_sse_scopes.pop(session_id, None)
        self._session_post_scopes.pop(session_id, None)

    def record_message_scope(self, session_id: str, scope: Scope) -> None:
        """Capture the ASGI scope from an HTTP POST message request."""
        self._session_post_scopes[session_id] = dict(scope)

    def get_scoped_context(
        self,
        session_id: str | None = None,
        current_msg_scope: Scope | None = None,
    ) -> dict[str, Any]:
        """Consolidate SSE handshake headers and POST message headers into a unified scope."""
        base_scope: dict[str, Any] = {}
        if session_id and session_id in self._session_sse_scopes:
            base_scope = dict(self._session_sse_scopes[session_id])

        msg_scope: dict[str, Any] = dict(current_msg_scope) if current_msg_scope else {}
        if not msg_scope and session_id and session_id in self._session_post_scopes:
            msg_scope = dict(self._session_post_scopes[session_id])

        # If neither scope is stored, return empty or fallback context
        if not base_scope and not msg_scope:
            return {}

        merged: dict[str, Any] = dict(base_scope) if base_scope else dict(msg_scope)

        # Merge headers: start with SSE headers, overlay POST headers
        base_headers = base_scope.get("headers", [])
        msg_headers = msg_scope.get("headers", [])

        header_dict: dict[bytes, bytes] = {}
        for k, v in base_headers:
            header_dict[k.lower()] = v
        for k, v in msg_headers:
            header_dict[k.lower()] = v

        merged["headers"] = [(k, v) for k, v in header_dict.items()]

        # Transfer connection attributes from msg_scope if available
        for key in ("client", "server", "scheme", "http_version", "root_path", "app"):
            if key in msg_scope and msg_scope[key]:
                merged[key] = msg_scope[key]

        return merged

    def synthesize_request(
        self,
        scope: dict[str, Any] | None,
        args: dict[str, Any] | None = None,
        app: Any = None,
        astack: Any = None,
    ) -> Request:
        """Construct an in-memory Starlette/FastAPI Request object populated with bridged headers."""
        resolved_scope = dict(scope) if scope else {}
        args = args or {}

        # Extract path parameters from args
        path_params = {k: v for k, v in args.items() if not isinstance(v, (dict, list))}

        # Construct query string from scalar args
        query_data = {
            k: v for k, v in args.items() if isinstance(v, (str, int, float, bool))
        }
        synthetic_query_bytes = urlencode(query_data).encode("latin-1") if query_data else b""

        synthetic_scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": resolved_scope.get("http_version", "1.1"),
            "method": "POST",
            "scheme": resolved_scope.get("scheme", "http"),
            "path": resolved_scope.get("path", "/"),
            "raw_path": resolved_scope.get("raw_path", b"/"),
            "query_string": synthetic_query_bytes or resolved_scope.get("query_string", b""),
            "headers": list(resolved_scope.get("headers", [])),
            "client": resolved_scope.get("client", ("127.0.0.1", 12345)),
            "server": resolved_scope.get("server", ("testserver", 80)),
            "root_path": resolved_scope.get("root_path", ""),
            "app": app or resolved_scope.get("app"),
            "path_params": path_params,
            "fastapi_inner_astack": astack,
            "fastapi_function_astack": astack,
            "fastapi_middleware_astack": astack,
        }

        return Request(synthetic_scope)

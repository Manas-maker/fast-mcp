# 0002. Dual-UI, ASGI Scope Bridging, and Resilient Error Handling

## Context

Desktop AI clients (Claude Desktop, Cursor, VS Code) now support the SEP-1865 (MCP Apps) protocol to render in-chat iframes directly within conversations. Concurrently, real-world FastAPI applications rely heavily on HTTP headers/Bearer tokens via `Depends()` and throw `HTTPException` when domain validation fails. If an MCP server drops headers or translates HTTP errors to JSON-RPC protocol faults, client connections break and LLM self-correction is disabled.

## Decision

1. **Dual UI Strategy & MCP Apps (SEP-1865):**
   - The built-in inspector is dual-served: in-browser at `/mcp/docs` and in-chat via a built-in `inspect()` tool returning an MCP App (`ui://fast-mcp/inspector`).
   - A `@mcp.app()` decorator and `ui` parameter on `@mcp.tool()` are provided so developers can easily return custom interactive HTML/JS widgets in AI client chats.
2. **ASGI Scope Bridging:**
   - Transport-level credentials (Bearer tokens, API keys, cookies) captured during SSE/HTTP connection handshakes are synthesized into an in-memory ASGI `Request` scope during tool execution, allowing native `Depends()` and `Security()` to resolve without requiring explicit token parameters.
3. **Resilient Error Handling:**
   - Route exceptions (`HTTPException`, `RequestValidationError`) are caught and transformed into `CallToolResult(isError=True, content=[TextContent(text=...)])`.
   - Protocol-level JSON-RPC errors are reserved exclusively for transport and wire-level protocol failures.
4. **Response Serialization:**
   - Tool outputs default to compact minified JSON, with an optional `@mcp.serializer` hook for custom summaries or formatting.

## Consequences

- Desktop AI users can inspect servers and interact with rich widgets without window switching.
- Zero-modification security: existing FastAPI authentication handlers run unmodified.
- LLMs can self-correct when an API returns 400/404 errors instead of crashing the conversation session.

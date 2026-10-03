# 01: Core ASGI Mount & Route Reflection

**What to build:**
A minimal `FastMCP` class that mounts directly onto an existing FastAPI application over ASGI. The server exposes standard MCP endpoints (`/mcp/sse`, `/mcp/messages`) and automatically inspects FastAPI route handlers tagged with `tags=["mcp"]`, extracting Pydantic models, docstrings, path parameters, and query parameters into valid MCP Tool definitions. Incoming `tools/call` requests dispatch to the corresponding FastAPI endpoint functions and return successful text responses over the SSE transport.

**Blocked by:** None (can start immediately)

**Status:** completed

- [x] `FastMCP(app)` can be initialized and mounted to a FastAPI application using `mcp.mount()`.
- [x] Endpoints tagged with `tags=["mcp"]` appear in the `tools/list` response with correct names, descriptions, and JSON Schemas derived from their Pydantic and primitive parameters.
- [x] Routes without the opt-in tag are NOT exposed in `tools/list`.
- [x] Calling an exposed tool via `tools/call` over the ASGI SSE transport successfully invokes the underlying FastAPI route handler and returns the serialized result.
- [x] All tests run through the ASGI Protocol Seam using `httpx.AsyncClient` with `ASGITransport(app=app)`.

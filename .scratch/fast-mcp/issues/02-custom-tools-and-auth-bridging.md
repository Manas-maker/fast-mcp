# 02: Custom AI Tools & ASGI Scope-Bridged Depends() Auth

**What to build:**
Enable developers to define custom AI-only tools on the `FastMCP` instance using an `@mcp.tool()` decorator, and implement ASGI Scope Bridging so that both reflected routes and `@mcp.tool()` handlers natively resolve FastAPI's `Depends()` and `Security()` dependencies (e.g. database sessions, current user authentication). Incoming authorization headers (Bearer tokens, API keys) and cookies from the MCP connection handshake are transparently passed into the endpoint execution scope.

**Blocked by:** 01-core-asgi-mount-route-reflection

**Status:** ready-for-agent

- [ ] Custom tools registered via `@mcp.tool()` appear in `tools/list` and can be invoked alongside reflected routes.
- [ ] Incoming HTTP/SSE headers (e.g. `Authorization: Bearer <token>`) are captured from the MCP client request and synthesized into an in-memory ASGI `Request`.
- [ ] Reflected routes and `@mcp.tool()` handlers with `Depends(get_current_user)` or `Security()` execute and authenticate properly using the bridged credentials.
- [ ] Calling a protected tool without valid credentials triggers FastAPI dependency authentication failure rather than leaking unauthorized data.
- [ ] End-to-end tests verify authenticated tool calls over the ASGI Protocol Seam.

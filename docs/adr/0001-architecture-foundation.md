# 0001. Architecture Foundation and Hybrid Scope

## Context

Existing Python MCP solutions either require building standalone servers isolated from existing web infrastructure (official SDK, Prefect FastMCP) or use fragile external HTTP calls with hanging connections and lack of custom tool support (`fastapi_mcp`). FastAPI developers need a way to expose existing endpoints while authoring custom AI tools that share existing database connections, authentication dependencies, and middleware.

## Decision

We will build `fast-mcp` as a **Hybrid Dual-Citizen ASGI mount**:
1. **Binding:** `mcp = FastMCP(app)` directly mounts onto FastAPI's ASGI lifecycle and routing table, avoiding subprocesses or external HTTP loops.
2. **Reflection Policy:** Routes are reflected using configurable filters, defaulting to explicit opt-in (`tags=["mcp"]`) to prevent accidental internal endpoint leakage and context window bloat.
3. **Dependency Injection:** Custom `@mcp.tool()` and reflected routes execute through FastAPI's native dependency injection engine (`Depends()`, `Security()`), automatically propagating headers and tokens from SSE/HTTP requests.
4. **Dynamic Discovery:** Include a progressive discovery engine (`search_tools` meta-tool) backed by a pluggable `ToolRouter` interface to prevent context exhaustion on large APIs.
5. **Dual UI Strategy:** Provide an embedded web inspector at `/mcp/docs` and native support for the MCP Apps protocol (SEP-1865, `_meta.ui.resourceUri`) so interactive dashboards and tool UIs render directly inside desktop AI clients (Claude, Cursor, VS Code).

## Consequences

- Direct ASGI integration means zero extra network hops and seamless `Depends()` auth, but requires careful handling of Starlette lifespan and SSE streams.
- Defaulting to opt-in route reflection protects LLMs from context exhaustion, requiring developers to tag routes they want exposed.
- Supporting SEP-1865 MCP Apps makes `fast-mcp` the first FastAPI framework capable of serving in-chat UI components without window switching.

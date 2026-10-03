# Specification: fast-mcp Core Framework (V1)

**Status:** `ready-for-agent`  
**Governing Documents:** [GLOSSARY.md](file:///c:/Users/Manas/Downloads/Repos/fast-mcp/GLOSSARY.md), [ADR 0001](file:///c:/Users/Manas/Downloads/Repos/fast-mcp/docs/adr/0001-architecture-foundation.md), [ADR 0002](file:///c:/Users/Manas/Downloads/Repos/fast-mcp/docs/adr/0002-dual-ui-auth-bridging-and-error-handling.md)  

---

## Problem Statement

FastAPI developers want to empower AI agents (such as Claude, Cursor, and custom autonomous agents) with their application's tools, data, and business logic using the standardized Model Context Protocol (MCP). However, existing solutions present severe blockers:

1. **Isolation & Code Duplication:** Existing tools force developers to rewrite their business logic from scratch in a standalone server framework, abandoning their existing FastAPI routing, middleware, and dependency injection.
2. **Context Window Exhaustion:** Mounting an existing FastAPI app blindly dumps 50+ endpoints into the LLM context, which degrades model reasoning accuracy, skyrockets token costs, and leads to tool hallucination.
3. **Broken Authentication & Unstable Transports:** The primary open-source attempts to bridge FastAPI and MCP suffer from hanging HTTP connections, protocol serialization errors, and an inability to propagate Bearer tokens and cookies into FastAPI's native `Depends()` and `Security()` handlers.
4. **Poor Developer & User Experience:** Testing MCP servers requires switching away to external command-line Node.js tools, and agents cannot render interactive visual interfaces in modern desktop AI chat apps.

---

## Solution

`fast-mcp` is a production-grade, FastAPI-native MCP framework built as a **Hybrid Dual-Citizen ASGI mount**:
- Binds directly onto an existing FastAPI app in-process with zero network hops or hanging subprocesses.
- Reflects existing FastAPI routes into MCP tools using safe, configurable opt-in filters (`tags=["mcp"]`).
- Allows authoring custom, AI-only tools (`@mcp.tool()`), resources, and prompts that share the exact same database pools and `Depends()` dependency injection.
- Automatically bridges incoming HTTP headers and Bearer tokens into an in-memory ASGI `Request` scope so security dependencies resolve with zero code changes.
- Defends the agent's context window through progressive dynamic discovery via an automatic `search_tools` meta-tool and pluggable `ToolRouter`.
- Delivers a dual UI experience: an embedded browser inspector at `/mcp/docs` plus native support for the in-chat SEP-1865 **MCP Apps** protocol (`_meta.ui.resourceUri`) for rich interactive widgets in desktop AI clients.
- Traps route-level exceptions (`HTTPException`, validation errors) and returns friendly tool-level errors (`isError=True`) so AI agents can inspect the failure and self-correct.

---

## User Stories

1. As a FastAPI developer, I want to mount an MCP server onto my existing `FastAPI` instance using a single call, so that my web app and MCP endpoints run in a single process without extra infrastructure.
2. As a FastAPI developer, I want routes marked with `tags=["mcp"]` to automatically convert into MCP tools, so that I don't have to duplicate endpoints or maintain parallel tool definitions.
3. As a FastAPI developer, I want route docstrings, parameter types, and Pydantic models automatically translated into high-quality MCP tool descriptions and JSON schemas, so that AI models know exactly how and when to call each tool.
4. As a FastAPI developer, I want to define AI-specialized tools using `@mcp.tool()`, so that I can provide multi-step composite logic specifically tailored for LLMs.
5. As a FastAPI developer, I want both reflected routes and `@mcp.tool()` handlers to resolve FastAPI dependencies like `Depends(get_db)` and `Depends(get_current_user)`, so that all data access and authorization rules are strictly reused.
6. As a security engineer, I want incoming client authorization headers (Bearer tokens, API keys) from the MCP connection to pass transparently into FastAPI's `Security()` dependencies, so that unauthenticated or unauthorized agents cannot access protected tools.
7. As an AI agent user, I want an API with 80 endpoints to present only relevant tools or a `search_tools` meta-tool, so that my prompt context window is not clogged with irrelevant schemas.
8. As an AI agent, I want to call `search_tools(query=...)` to discover specialized tools dynamically during a multi-step workflow, so that I can discover and execute the exact tool needed.
9. As a library maintainer, I want the `ToolRouter` to have an abstract interface defaulting to fast local keyword matching, so that advanced semantic or System 1 decision models can be added later without core churn.
10. As a developer, I want to open `/mcp/docs` in my browser, so that I can visually inspect available MCP tools and test tool executions without installing Node.js or external CLIs.
11. As a desktop AI user (Claude Desktop, Cursor), I want an `inspect()` tool that returns an interactive MCP App iframe, so that I can monitor server state directly inside my chat window without switching windows.
12. As a FastAPI developer, I want to author interactive in-chat widgets using `@mcp.app()`, so that my endpoints can render charts, cards, and interactive forms directly in the user's AI client.
13. As an AI agent calling a tool, I want 404 or 422 `HTTPException` responses returned as `CallToolResult(isError=True)` with clear error descriptions, so that I can adjust my parameters and self-correct instead of having the connection crash.
14. As a developer, I want tool responses automatically minified to compact JSON by default, so that large response payloads do not waste tokens.
15. As a developer, I want to register custom response serializers via `@mcp.serializer`, so that I can format complex responses into tailored markdown or summaries for LLMs.
16. As an operations engineer, I want `fast-mcp` to use native Starlette SSE and ASGI streaming, so that requests never hang indefinitely and resource cleanup occurs on disconnection.

---

## Implementation Decisions

### Module 1: `FastMCP` Core & ASGI Mount
- Serves as the primary public entry point initialized with `mcp = FastMCP(app, ...)`.
- Implements the ASGI interface to handle both standard Starlette routing and SSE/Streamable HTTP protocol endpoints (`/mcp/sse`, `/mcp/messages`).
- Manages the lifecycle of the underlying official MCP protocol server (`mcp.server.lowlevel.Server`).
- Coordinates route reflection, custom tool registration, and UI mounts.

### Module 2: Route Reflection (`RouteReflector`)
- Inspects the parent FastAPI router table upon mount.
- Evaluates routes against inclusion criteria (defaulting to checking for `tags=["mcp"]` or presence of explicit `@mcp.include` decorators).
- Extracts path parameters, query parameters, header parameters, and Pydantic request bodies from the route's endpoint signature.
- Compiles the schema into an MCP `Tool` definition matching JSON Schema standards.
- Employs a dispatcher that routes incoming `tools/call` invocations directly into the FastAPI endpoint function.

### Module 3: ASGI Scope Bridging (`ASGIScopeBridge`)
- When an MCP client connects over SSE or sends an HTTP message, the incoming connection headers, cookies, client IP, and query parameters are captured into a request context.
- During tool execution, the bridge constructs a synthetic ASGI `Request` containing these headers and attaches it to the FastAPI dependency context.
- Resolves all `Depends()` and `Security()` providers through FastAPI's `solve_dependencies` engine before executing the tool handler.

### Module 4: Dynamic Discovery & `ToolRouter`
- Implements an abstract `BaseToolRouter` interface defining `select_tools(query: str, candidate_tools: list[Tool]) -> list[Tool]`.
- Implements `KeywordTagRouter` as the default zero-dependency implementation, using tokenized keyword and tag matching.
- When dynamic discovery is enabled (`dynamic_discovery=True` or tool count > threshold), `tools/list` returns a baseline set plus the `search_tools` meta-tool. Calling `search_tools` executes the router and returns the matching tool schemas.

### Module 5: MCP Apps & Dual UI (`MCPAppRegistry` & Inspector)
- Exposes a static asset mount serving an interactive in-browser single-page inspector at `/mcp/docs`.
- Implements the SEP-1865 (MCP Apps) specification:
  - Supports declaring `_meta.ui.resourceUri` on tool definitions.
  - Serves UI HTML bundles via MCP resources (`ui://...`).
  - Bridges JSON-RPC `postMessage` protocol between host iframes and server endpoints.
- Provides `@mcp.app(name="...")` and a built-in `inspect()` tool returning the inspector MCP App.

### Module 6: Error & Response Serialization
- Intercepts exceptions raised during endpoint execution:
  - `HTTPException` is unwrapped and formatted into `CallToolResult(isError=True, content=[TextContent(text=f"Error {status_code}: {detail}")])`.
  - Pydantic `RequestValidationError` is formatted into concise field-level error messages.
  - Unexpected internal errors return sanitized failure messages without leaking raw stack traces unless in debug mode.
- Output serialization defaults to compact minified JSON, with support for `@mcp.serializer` decorators for custom formatting.

---

## Testing Decisions

### Good Test Philosophy
- Tests MUST exercise **external behavior across public interfaces**, never mocking internal helper functions or inspecting private attributes.
- Tests will follow Test-Driven Development (TDD) red-green-refactor cycles.

### Seams Under Test
1. **The Primary ASGI Protocol Seam:**
   - Exercised via `httpx.AsyncClient` with `ASGITransport(app=app)`.
   - Sends real MCP JSON-RPC payloads over the mounted `/mcp/` routes.
   - Tests end-to-end SSE connection initialization, `tools/list`, `tools/call`, authorization header forwarding, `search_tools` dynamic discovery, and error reporting.
2. **The Secondary ToolRouter Seam:**
   - Isolated unit tests validating `KeywordTagRouter` matching accuracy on sample queries and candidate tool definitions.

---

## Out of Scope

- Client-side desktop application code (e.g. modifying Claude Desktop or Cursor).
- Direct dependencies on unreleased, closed-preview APIs (e.g. OpenAI Decisions API).
- Distributed multi-server state synchronization (V1 runs strictly in-process with the FastAPI ASGI application).
- Automatic database migrations or ORM scaffolding.

---

## Further Notes

- **Dependencies:** `fastapi`, `starlette`, `pydantic>=2.0`, `mcp>=1.0.0`.
- **Development Tooling:** `pytest`, `pytest-asyncio`, `httpx`, `uv`.
- **Packaging:** Standard `pyproject.toml` with zero heavy CLI bloat.

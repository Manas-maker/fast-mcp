# fast-mcp Glossary

A production-grade, FastAPI-native framework bridging FastAPI applications and the Model Context Protocol (MCP).

## Language

**FastMCP**:
The hybrid server instance bound directly to a FastAPI application, combining automatic route reflection with custom AI tool, resource, and prompt authoring.
_Avoid_: MCP adapter, FastAPI wrapper

**Route Reflection**:
The process of inspecting FastAPI route handlers, Pydantic models, and docstrings to automatically register them as MCP tools or resources without modifying underlying endpoints.
_Avoid_: Endpoint scraping, route translation

**Dynamic Discovery**:
The mechanism that exposes a curated subset of tools and a `search_tools` meta-tool to the LLM on demand, preventing prompt context bloat on large API surfaces.
_Avoid_: Tool flooding, static tool listing

**ToolRouter**:
The internal pluggable interface responsible for evaluating user queries against candidate tools to select the most relevant tools for dynamic discovery.
_Avoid_: Decision engine, model middleware

**MCP App**:
An interactive user interface declared via `_meta.ui.resourceUri` (SEP-1865) that renders inside a sandboxed iframe directly within desktop AI clients (e.g. Claude Desktop, VS Code).
_Avoid_: Webview tool, iframe plugin

**ASGI Scope Bridging**:
The synthesis of an in-memory ASGI HTTP `Request` scope populated with client transport credentials (headers, cookies) so FastAPI's native `Depends()` and `Security()` resolve without modifying endpoint handlers.
_Avoid_: Auth proxying, credential spoofing

**Tool Error Handling**:
The mapping of internal server exceptions and `HTTPException` to `CallToolResult(isError=True)` instead of JSON-RPC protocol faults, enabling LLM self-correction.
_Avoid_: Protocol error throwing, exception bubbling


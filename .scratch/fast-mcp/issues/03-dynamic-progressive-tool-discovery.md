# 03: Dynamic Progressive Tool Discovery & ToolRouter

**What to build:**
A progressive tool discovery engine that prevents LLM prompt context exhaustion when mounting large FastAPI applications. When dynamic discovery is enabled, `tools/list` returns a compact baseline set plus a `search_tools` meta-tool. An abstract `BaseToolRouter` interface is provided, with a zero-dependency `KeywordTagRouter` default implementation that searches tool descriptions and tags to retrieve candidate tool schemas on demand.

**Blocked by:** 01-core-asgi-mount-route-reflection

**Status:** ready-for-agent

- [x] `FastMCP(app, dynamic_discovery=True)` activates progressive tool discovery.
- [x] When dynamic discovery is enabled, `tools/list` exposes the `search_tools(query: str)` meta-tool.
- [x] Calling `search_tools` invokes the `ToolRouter` and returns matching tool definitions with their full JSON schemas.
- [x] `BaseToolRouter` provides an abstract class with `select_tools(query, candidate_tools)`, cleanly isolating routing logic.
- [x] `KeywordTagRouter` correctly ranks and filters candidate tools based on keyword overlap across names, descriptions, and tags.

# 04: Resilient Tool Error Handling & Response Serialization

**What to build:**
Resilient error interception and token-conscious response serialization for tool calls. When an endpoint or tool handler raises `HTTPException` (e.g. 404 Not Found, 400 Bad Request) or Pydantic `RequestValidationError`, `fast-mcp` traps the exception and converts it into a `CallToolResult(isError=True)` with clear recovery descriptions so AI models can self-correct instead of terminating the conversation. Responses default to minified JSON, and developers can register custom formatting hooks using `@mcp.serializer`.

**Blocked by:** 02-custom-tools-and-auth-bridging

**Status:** ready-for-agent

- [ ] Raising `HTTPException(status_code=404, detail="Item not found")` in an endpoint results in `isError=True` in the MCP tool response containing the status code and detail.
- [ ] Pydantic validation errors on tool arguments are caught and returned as clean, readable error messages with `isError=True`.
- [ ] Successful tool returns default to compact, minified JSON serialization.
- [ ] Developers can register custom serializers with `@mcp.serializer` to format specific return types into tailored markdown or summaries.
- [ ] Protocol-level JSON-RPC errors are never thrown for anticipated business logic errors.

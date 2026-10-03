# 05: Dual UI: Embedded /mcp/docs & In-Chat MCP Apps (SEP-1865)

**What to build:**
A complete visual testing and interactive UI system. Mounts an embedded in-browser inspector UI at `/mcp/docs` (interactive single-page app to view tools and test invocations), and implements the SEP-1865 (MCP Apps) specification so that tools can declare `_meta.ui.resourceUri` (`ui://` scheme) to render sandboxed, interactive iframes directly inside desktop AI clients (Claude Desktop, Cursor, VS Code). Includes a built-in `inspect()` MCP App tool and an `@mcp.app()` decorator for authoring custom interactive in-chat widgets.

**Blocked by:** 02-custom-tools-and-auth-bridging

**Status:** ready-for-agent

- [ ] Navigating to `/mcp/docs` in a browser renders an interactive web UI listing all available tools and allowing manual test calls.
- [ ] Setting `enable_ui=False` in `FastMCP` disables the `/mcp/docs` route for headless production environments.
- [ ] MCP tools can declare `_meta.ui.resourceUri` pointing to HTML resources via the `ui://` scheme conforming to SEP-1865.
- [ ] A built-in `inspect()` tool is registered that returns an MCP App iframe for viewing server status directly inside desktop AI clients.
- [ ] Developers can use `@mcp.app(name="...")` to return interactive HTML widgets for their own endpoints.
- [ ] Static UI assets are bundled cleanly without requiring Node.js at runtime.

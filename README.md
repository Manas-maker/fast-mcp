# fast-mcp

> **FastAPI-native Model Context Protocol (MCP) framework** with automatic route reflection, ASGI scope bridging, dynamic progressive tool discovery, resilient error recovery, and interactive in-chat MCP Apps (SEP-1865).

[![Tests](https://img.shields.io/badge/tests-108%20passed-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)]()
[![MCP](https://img.shields.io/badge/MCP-1.0%2B-purple.svg)]()

---

## Highlights

- ⚡ **Hybrid Dual-Citizen ASGI Mount:** Mounts directly onto any existing `FastAPI` instance in-process over standard ASGI—zero external proxying, zero hanging subprocesses.
- 🔌 **Local stdio CLI Runner & Desktop AI Bridge:** Run `fast-mcp stdio main:app` or `python -m fast_mcp stdio main:app` to connect desktop AI clients (Claude Desktop, Cursor) over standard I/O pipes with zero network setup.
- 🔍 **Route Reflection:** Opt-in tags (`tags=["mcp"]`) automatically convert FastAPI endpoints, Pydantic models, docstrings, path/query/body parameters into MCP tools.
- 🛠️ **Custom AI Tools (`@mcp.tool`):** Define AI-tailored composite tools alongside reflected routes with automatic schema and docstring extraction.
- 🔐 **ASGI Scope Bridging:** Client authorization headers (`Authorization: Bearer <token>`, cookies, API keys) captured during the MCP handshake are bridged into an in-memory ASGI `Request`, natively resolving FastAPI's `Depends()` and `Security()` providers without code changes.
- 🧠 **Dynamic Progressive Tool Discovery:** Protect agent context windows via progressive discovery (`dynamic_discovery=True`), the `search_tools(query: str)` meta-tool, and zero-dependency `KeywordTagRouter`.
- 🛡️ **Resilient Error Recovery & Minified JSON:** Traps route `HTTPException` and Pydantic validation errors into informative `CallToolResult(isError=True)` responses so LLMs can self-correct without protocol failures. Output defaults to compact, token-conscious minified JSON with custom `@mcp.serializer` formatting hooks.
- 🖥️ **Dual UI & In-Chat MCP Apps (SEP-1865):** Embedded browser inspector at `/mcp/docs` plus native support for in-chat interactive iframes in desktop AI clients (Claude Desktop, Cursor, VS Code) via `_meta.ui.resourceUri`, the built-in `inspect()` tool, and the `@mcp.app()` decorator.

---

## Installation

```bash
pip install fast-mcp
```

Or using `uv`:

```bash
uv add fast-mcp
```

---

## Quickstart

```python
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from fast_mcp import FastMCP

app = FastAPI(title="Store API")
mcp = FastMCP(app=app, name="store-mcp")

# 1. Existing FastAPI route reflected automatically via tags=["mcp"]
class Product(BaseModel):
    id: int
    name: str
    price: float

@app.get("/products/{product_id}", tags=["mcp"])
async def get_product(product_id: int) -> Product:
    """Fetch product details by ID."""
    if product_id == 404:
        raise HTTPException(status_code=404, detail="Product not found")
    return Product(id=product_id, name="Smart Widget", price=29.99)

# 2. Custom AI tool with native dependency injection
def verify_token(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token")
    return authorization.split(" ")[1]

@mcp.tool(name="order_status", description="Check customer order status")
def check_order(order_id: str, user: str = Depends(verify_token)) -> dict:
    return {"order_id": order_id, "customer": user, "status": "Shipped"}

# 3. Mount MCP endpoints (/mcp/sse, /mcp/messages, /mcp/docs)
mcp.mount()
```

Run with standard ASGI servers:
```bash
uvicorn main:app --reload
```

---

## Core Capabilities

### 1. Route Reflection

Routes tagged with `tags=["mcp"]` (configurable via `route_tag`) are automatically inspected upon `mcp.mount()`:
- Endpoint docstrings (Google, Sphinx, NumPy format) become tool descriptions and parameter docs.
- Pydantic request models, query parameters, and path variables become MCP input schemas.
- Untagged endpoints remain standard HTTP routes and are never leaked to LLMs.

```python
@app.post("/items/create", tags=["mcp"])
async def create_item(item: ItemModel) -> ItemModel:
    """Create a new catalog item.

    Args:
        item: The catalog item specification.
    """
    return item
```

### 2. Custom AI Tools (`@mcp.tool`)

Register AI-specialized tools that don't need dedicated REST endpoints:

```python
# Bare decorator
@mcp.tool
def calculate_quote(quantity: int, discount: float = 0.0) -> float:
    return quantity * 100.0 * (1.0 - discount)

# Parameterized decorator
@mcp.tool(name="inventory_lookup", description="Lookup stock levels", tags=["inventory"])
async def check_inventory(sku: str) -> dict:
    return {"sku": sku, "in_stock": True, "count": 42}
```

### 3. ASGI Scope Bridging & Native Auth

Incoming headers (`Authorization: Bearer ...`, cookies, API keys) from the MCP client's SSE handshake or message posts are captured into an active request context:

```python
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

@mcp.tool
async def user_profile(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = creds.credentials
    return {"user": "alice", "token_verified": True}
```

If authorization fails or headers are omitted, `fast-mcp` unwraps the resulting `HTTPException(401)` into `CallToolResult(is_error=True)` so the agent receives an actionable authentication error rather than crashing the transport.

### 4. Dynamic Progressive Tool Discovery

Prevent LLM context window bloat on large FastAPI applications with hundreds of endpoints:

```python
mcp = FastMCP(
    app=app,
    dynamic_discovery=True,  # Or set dynamic_discovery_threshold=20
    baseline_tools=["search_tools", "get_system_status"],
    baseline_tag="baseline",
)
```

- When active, `tools/list` exposes only baseline tools plus the `search_tools(query: str)` meta-tool.
- Calling `search_tools(query="invoice")` executes the pluggable `ToolRouter` (defaults to zero-dependency `KeywordTagRouter` with tokenized name/tag/description ranking) and returns matching tool definitions with full JSON schemas.

### 5. Resilient Error Interception & Custom Serializers

- **Exception Traps:** `HTTPException` (400, 404, 422) and Pydantic validation errors return clean, concise messages with `isError=True`.
- **Minified Output:** Responses serialize to compact minified JSON (`{"id":1,"name":"widget"}`) saving prompt tokens.
- **Custom Serializers:** Format return types into tailored markdown or summaries:

```python
class Report(BaseModel):
    title: str
    metrics: dict[str, int]

@mcp.serializer(Report)
def format_report(report: Report) -> str:
    md = f"### {report.title}\n"
    for k, v in report.metrics.items():
        md += f"- **{k}**: {v}\n"
    return md
```

### 6. Dual UI: Browser Inspector & In-Chat MCP Apps (SEP-1865)

#### Embedded Browser Inspector
Open `http://localhost:8000/mcp/docs` in any browser to inspect registered tools, view schemas, and execute test invocations interactively without external Node.js CLIs. (Disable with `FastMCP(app, enable_ui=False)`).

#### In-Chat MCP Apps (SEP-1865)
Render rich interactive HTML/JS widgets directly in modern desktop AI clients (Claude Desktop, Cursor, VS Code):

```python
# Built-in server inspector tool
# Agent calling `inspect()` receives an interactive iframe pointed to ui://fast-mcp/inspector

# Authoring custom in-chat widgets:
@mcp.app(
    name="dashboard",
    resource_uri="ui://store/dashboard",
    html="""
    <div style="font-family: sans-serif; padding: 1rem; border-radius: 8px; background: #f0f4f8;">
        <h2>Store Live Metrics</h2>
        <p>Active Users: <strong>1,420</strong></p>
    </div>
    """
)
def live_dashboard() -> str:
    return '<iframe src="ui://store/dashboard" width="100%" height="400"></iframe>'
```

### 7. Local stdio CLI Runner & Desktop AI Bridge

Connect desktop AI clients (Claude Desktop, Cursor) directly to your FastAPI backend or FastMCP instance over standard input/output (`stdio`) pipes with zero network setup, port conflicts, or external proxying.

#### Command-Line Usage

```bash
# Run stdio runner pointing to FastAPI app or FastMCP instance
fast-mcp stdio main:app

# Or via Python module invocation
python -m fast_mcp stdio main:app

# Target attribute defaults to 'app' or 'mcp' if omitted:
fast-mcp stdio main

# The 'stdio' subcommand can also be omitted as default:
fast-mcp main:app
```

#### Claude Desktop Configuration (`claude_desktop_config.json`)

Configure Claude Desktop to launch your FastMCP server directly:

```json
{
  "mcpServers": {
    "my-fast-mcp-app": {
      "command": "fast-mcp",
      "args": ["stdio", "main:app"]
    }
  }
}
```

Or using `uv` to manage the virtual environment automatically:

```json
{
  "mcpServers": {
    "my-fast-mcp-app": {
      "command": "uv",
      "args": ["run", "fast-mcp", "stdio", "main:app"]
    }
  }
}
```

#### Programmatic Stdio Runner

You can also run stdio mode programmatically from Python:

```python
import asyncio
from fast_mcp import FastMCP, run_stdio

mcp = FastMCP(name="my-stdio-server")

@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b

if __name__ == "__main__":
    asyncio.run(run_stdio(mcp))
```

---

## Testing & Verification

`fast-mcp` exercises external behavior across the **ASGI Protocol Seam** using `httpx.AsyncClient` with `ASGITransport`:

```bash
# Run full test suite
pytest

# Run tests with coverage
pytest --cov=fast_mcp --cov-report=term-missing
```

---

## Specification & Architectural Documents

- [Specification: fast-mcp Core Framework (V1)](file:///docs/specs/0001-fast-mcp-core.md)
- [GLOSSARY.md](file:///GLOSSARY.md)
- [ADR 0001: Architecture Foundation and Hybrid Scope](file:///docs/adr/0001-architecture-foundation.md)
- [ADR 0002: Dual-UI, ASGI Scope Bridging, and Resilient Error Handling](file:///docs/adr/0002-dual-ui-auth-bridging-and-error-handling.md)

---

## License

MIT

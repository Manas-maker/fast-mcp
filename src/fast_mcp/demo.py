"""Demo FastAPI application showcasing FastMCP capabilities.

This module acts as an immediately executable MCP server target for
local stdio clients (Claude Desktop, Cursor), Smithery, Glama microVMs,
and the official Model Context Protocol registry.
"""

from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from fast_mcp import FastMCP

app = FastAPI(
    title="FastMCP Demo Server",
    description="Showcase server illustrating FastAPI-native Model Context Protocol integration.",
    version="0.1.0",
)

mcp = FastMCP(
    app=app,
    name="fast-mcp-demo",
    route_tag="mcp",
    dynamic_discovery=True,
    enable_ui=True,
)


class SystemMetric(BaseModel):
    name: str = Field(..., description="Unique metric identifier, e.g. 'cpu_usage' or 'memory_allocated'")
    value: float = Field(..., description="Numerical reading of the measured system parameter")
    unit: str = Field(..., description="Standard engineering unit of the measurement (e.g. 'percent', 'MB')")


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """Check application health status."""
    return {"status": "healthy", "service": "fast-mcp-demo"}


# 1. Route Reflection Tool (Auto-exposed to MCP via tags=["mcp"])
@app.get("/metrics/summary", response_model=List[SystemMetric], tags=["mcp"])
async def get_system_metrics(
    filter_unit: Optional[str] = Query(None, description="Optional unit filter, e.g. 'percent' or 'MB'")
) -> List[SystemMetric]:
    """Retrieve operational telemetry metrics for application performance monitoring.

    Returns an array of current hardware and runtime statistics including memory consumption,
    request latencies, and thread pool availability. Use this tool when diagnosing throughput
    bottlenecks or verifying server health.
    """
    metrics = [
        SystemMetric(name="cpu_utilization", value=14.2, unit="percent"),
        SystemMetric(name="memory_resident_set", value=128.5, unit="MB"),
        SystemMetric(name="active_connections", value=42.0, unit="count"),
        SystemMetric(name="avg_response_latency_ms", value=4.8, unit="ms"),
    ]
    if filter_unit:
        return [m for m in metrics if m.unit.lower() == filter_unit.lower()]
    return metrics


# 2. Custom AI Tool with native FastMCP decorator
@mcp.tool(
    name="echo_transform",
    description=(
        "Transform an input text string into uppercase, lowercase, or title-cased format. "
        "Use this tool when normalizing user queries or formatting names for consistent presentation."
    ),
)
def echo_transform(
    text: str,
    mode: str = "upper",
) -> dict:
    """Transform text string into uppercase, lowercase, or title case.

    Args:
        text: Raw text string to format.
        mode: Target transformation format ('upper', 'lower', or 'title').
    """
    normalized_mode = mode.lower().strip()
    if normalized_mode == "upper":
        transformed = text.upper()
    elif normalized_mode == "lower":
        transformed = text.lower()
    elif normalized_mode == "title":
        transformed = text.title()
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format mode '{mode}'. Supported modes are 'upper', 'lower', or 'title'."
        )
    return {"original": text, "transformed": transformed, "mode": normalized_mode}


# Mount MCP ASGI endpoints (/mcp/sse, /mcp/messages, /mcp/docs)
mcp.mount()

import json
import pytest
from fastapi import FastAPI
import httpx

from fast_mcp import FastMCP
from tests.conftest import StreamingASGITransport


@pytest.mark.asyncio
async def test_fast_mcp_mount_and_initialize():
    app = FastAPI()
    mcp = FastMCP(app=app, name="test-mcp", version="0.1.0")
    mcp.mount()

    transport = StreamingASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Start SSE stream
        async with client.stream("GET", "/mcp/sse") as sse_response:
            assert sse_response.status_code == 200
            assert "text/event-stream" in sse_response.headers.get("content-type", "")

            lines_iter = sse_response.aiter_lines()

            # First event should be endpoint
            endpoint_url = None
            async for line in lines_iter:
                if line.startswith("data: "):
                    endpoint_url = line[len("data: "):].strip()
                    break

            assert endpoint_url is not None
            assert "/mcp/messages" in endpoint_url

            # Send initialize JSON-RPC request to the endpoint
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            }

            post_response = await client.post(endpoint_url, json=init_payload)
            assert post_response.status_code in (200, 202)

            # Receive initialize result via SSE
            init_result = None
            async for line in lines_iter:
                if line.startswith("data: "):
                    msg = json.loads(line[len("data: "):].strip())
                    if msg.get("id") == 1:
                        init_result = msg.get("result")
                        break

            assert init_result is not None
            assert init_result["serverInfo"]["name"] == "test-mcp"
            assert init_result["serverInfo"]["version"] == "0.1.0"

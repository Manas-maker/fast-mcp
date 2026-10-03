from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from typing import Any, AsyncIterator
import httpx
import pytest


class StreamingASGIResponse(httpx.AsyncByteStream):
    def __init__(self, queue: asyncio.Queue[bytes | None], on_close: Any = None) -> None:
        self.queue = queue
        self.on_close = on_close

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self.queue.get()
            if chunk is None:
                break
            yield chunk

    async def aclose(self) -> None:
        if self.on_close:
            await self.on_close()


class StreamingASGITransport(httpx.AsyncBaseTransport):
    """An ASGI transport for httpx that supports streaming responses (SSE)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        content = await request.aread()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(k.lower(), v) for (k, v) in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port or 80),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
        }
        started_event = asyncio.Event()
        status_code = 200
        response_headers: list[tuple[bytes, bytes]] = []
        body_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        disconnect_event = asyncio.Event()
        body_sent = False

        async def receive() -> dict[str, Any]:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": content, "more_body": False}
            if disconnect_event.is_set():
                return {"type": "http.disconnect"}
            await disconnect_event.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = message.get("headers", [])
                started_event.set()
            elif message["type"] == "http.response.body":
                body = message.get("body", b'')
                if body:
                    await body_queue.put(body)
                if not message.get("more_body", False):
                    await body_queue.put(None)

        async def run_app() -> None:
            try:
                await self.app(scope, receive, send)
            finally:
                await body_queue.put(None)

        task = asyncio.create_task(run_app())
        await started_event.wait()

        async def on_close() -> None:
            disconnect_event.set()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except Exception:
                pass

        stream = StreamingASGIResponse(body_queue, on_close=on_close)
        return httpx.Response(status_code, headers=response_headers, stream=stream)


class MCPTestClient:
    def __init__(self, client: httpx.AsyncClient, lines_iter: AsyncIterator[str], endpoint_url: str) -> None:
        self.client = client
        self.lines_iter = lines_iter
        self.endpoint_url = endpoint_url
        self._msg_id = 0

    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self._msg_id += 1
        req_id = self._msg_id
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        res = await self.client.post(self.endpoint_url, json=payload, headers=headers)
        assert res.status_code in (200, 202)
        async for line in self.lines_iter:
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):].strip())
                if data.get("id") == req_id:
                    return data
        raise RuntimeError(f"No response received for request id {req_id}")

    async def initialize(self) -> dict[str, Any]:
        return await self.send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        )


@asynccontextmanager
async def connect_mcp_test_client(
    app: Any,
    mount_path: str = "/mcp",
    headers: dict[str, str] | None = None,
    sse_headers: dict[str, str] | None = None,
) -> AsyncIterator[MCPTestClient]:
    transport = StreamingASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as client:
        async with client.stream("GET", f"{mount_path}/sse", headers=sse_headers) as sse_response:
            assert sse_response.status_code == 200
            lines_iter = sse_response.aiter_lines()
            endpoint_url = None
            async for line in lines_iter:
                if line.startswith("data: "):
                    endpoint_url = line[len("data: "):].strip()
                    break
            assert endpoint_url is not None
            test_client = MCPTestClient(client, lines_iter, endpoint_url)
            await test_client.initialize()
            yield test_client

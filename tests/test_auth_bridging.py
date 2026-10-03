from __future__ import annotations

import json
import pytest
from fastapi import FastAPI, Depends, Security, Header, Cookie, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, SecurityScopes
from starlette.requests import Request

from fast_mcp import FastMCP, get_current_request
from tests.conftest import connect_mcp_test_client


bearer_scheme = HTTPBearer()


def get_current_user_header(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header format")
    token = authorization.split(" ", 1)[1]
    if token != "valid-secret-token":
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"username": "alice", "token": token}


def get_current_user_security(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)) -> dict:
    if credentials.credentials != "valid-secret-token":
        raise HTTPException(status_code=403, detail="Forbidden: token rejected")
    return {"username": "security-alice", "token": credentials.credentials}


@pytest.mark.asyncio
async def test_sse_header_authorization_bridged_to_reflected_route():
    app = FastAPI()

    executed = False

    @app.get("/protected/data", tags=["mcp"])
    def get_data(user: dict = Depends(get_current_user_header)) -> dict:
        """Fetch protected user data."""
        nonlocal executed
        executed = True
        return {"data": "confidential", "user": user["username"]}

    mcp = FastMCP(app=app)
    mcp.mount()

    # Pass Authorization in the SSE handshake headers
    sse_headers = {"authorization": "Bearer valid-secret-token"}
    async with connect_mcp_test_client(app, sse_headers=sse_headers) as client:
        res = await client.send_request("tools/call", {"name": "get_data", "arguments": {}})
        assert "result" in res
        result = res["result"]
        assert not result.get("isError")
        data = json.loads(result["content"][0]["text"])
        assert data == {"data": "confidential", "user": "alice"}
        assert executed is True


@pytest.mark.asyncio
async def test_sse_header_authorization_bridged_to_custom_tool():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    async def protected_custom_tool(item_id: int, user: dict = Depends(get_current_user_header)) -> dict:
        """A protected custom AI tool."""
        return {"item_id": item_id, "user": user["username"]}

    mcp.mount()

    # In tools/list, 'user' must NOT be in inputSchema!
    sse_headers = {"authorization": "Bearer valid-secret-token"}
    async with connect_mcp_test_client(app, sse_headers=sse_headers) as client:
        list_res = await client.send_request("tools/list")
        tool = next(t for t in list_res["result"]["tools"] if t["name"] == "protected_custom_tool")
        props = tool["inputSchema"]["properties"]
        assert "item_id" in props
        assert "user" not in props

        # Call tool
        call_res = await client.send_request(
            "tools/call",
            {"name": "protected_custom_tool", "arguments": {"item_id": 99}},
        )
        assert not call_res["result"].get("isError")
        data = json.loads(call_res["result"]["content"][0]["text"])
        assert data == {"item_id": 99, "user": "alice"}


@pytest.mark.asyncio
async def test_security_http_bearer_with_bridged_credentials():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def secure_action(user: dict = Security(get_current_user_security)) -> dict:
        """Action requiring HTTPBearer."""
        return {"authorized_as": user["username"]}

    mcp.mount()

    sse_headers = {"authorization": "Bearer valid-secret-token"}
    async with connect_mcp_test_client(app, sse_headers=sse_headers) as client:
        call_res = await client.send_request("tools/call", {"name": "secure_action", "arguments": {}})
        assert not call_res["result"].get("isError")
        data = json.loads(call_res["result"]["content"][0]["text"])
        assert data == {"authorized_as": "security-alice"}


@pytest.mark.asyncio
async def test_unauthenticated_call_fails_with_is_error():
    app = FastAPI()

    route_executed = False

    @app.get("/secret-route", tags=["mcp"])
    def secret_route(user: dict = Depends(get_current_user_header)) -> dict:
        nonlocal route_executed
        route_executed = True
        return {"secret": 123}

    mcp = FastMCP(app=app)

    custom_executed = False

    @mcp.tool
    def secret_custom(user: dict = Depends(get_current_user_header)) -> dict:
        nonlocal custom_executed
        custom_executed = True
        return {"secret": 456}

    mcp.mount()

    # Connect with NO credentials
    async with connect_mcp_test_client(app) as client:
        # Call reflected route
        res1 = await client.send_request("tools/call", {"name": "secret_route", "arguments": {}})
        assert "result" in res1
        assert res1["result"].get("isError") is True
        error_text1 = res1["result"]["content"][0]["text"]
        assert "401" in error_text1 or "Field required" in error_text1 or "Unauthorized" in error_text1
        assert route_executed is False

        # Call custom tool
        res2 = await client.send_request("tools/call", {"name": "secret_custom", "arguments": {}})
        assert "result" in res2
        assert res2["result"].get("isError") is True
        error_text2 = res2["result"]["content"][0]["text"]
        assert "401" in error_text2 or "Field required" in error_text2 or "Unauthorized" in error_text2
        assert custom_executed is False


@pytest.mark.asyncio
async def test_invalid_credentials_fails_with_is_error():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def secured_tool(user: dict = Security(get_current_user_security)) -> dict:
        return {"ok": True}

    mcp.mount()

    sse_headers = {"authorization": "Bearer bad-token"}
    async with connect_mcp_test_client(app, sse_headers=sse_headers) as client:
        res = await client.send_request("tools/call", {"name": "secured_tool", "arguments": {}})
        assert res["result"].get("isError") is True
        error_text = res["result"]["content"][0]["text"]
        assert "403" in error_text or "token rejected" in error_text


@pytest.mark.asyncio
async def test_post_message_header_authorization():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def check_auth(user: dict = Depends(get_current_user_header)) -> dict:
        return {"user": user["username"]}

    mcp.mount()

    # SSE connects WITHOUT authorization, but send_request sends Authorization on POST
    async with connect_mcp_test_client(app) as client:
        res = await client.send_request(
            "tools/call",
            {"name": "check_auth", "arguments": {}},
            headers={"authorization": "Bearer valid-secret-token"},
        )
        assert not res["result"].get("isError")
        data = json.loads(res["result"]["content"][0]["text"])
        assert data == {"user": "alice"}


@pytest.mark.asyncio
async def test_cookie_and_api_key_bridging():
    app = FastAPI()

    def get_cookie_auth(session_id: str = Cookie(default="")) -> str:
        if not session_id:
            raise HTTPException(status_code=401, detail="Session cookie missing")
        return session_id

    def get_api_key(x_api_key: str = Header(default="")) -> str:
        if x_api_key != "super-api-key":
            raise HTTPException(status_code=403, detail="Invalid API key")
        return x_api_key

    mcp = FastMCP(app=app)

    @mcp.tool
    def multi_auth_tool(
        session: str = Depends(get_cookie_auth),
        key: str = Depends(get_api_key),
    ) -> dict:
        return {"session": session, "key": key}

    mcp.mount()

    headers = {
        "cookie": "session_id=sess_abc123",
        "x-api-key": "super-api-key",
    }
    async with connect_mcp_test_client(app, headers=headers) as client:
        res = await client.send_request("tools/call", {"name": "multi_auth_tool", "arguments": {}})
        assert not res["result"].get("isError")
        data = json.loads(res["result"]["content"][0]["text"])
        assert data == {"session": "sess_abc123", "key": "super-api-key"}


@pytest.mark.asyncio
async def test_fastapi_dependency_overrides():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def whoami(user: dict = Depends(get_current_user_header)) -> dict:
        return {"user": user["username"]}

    mcp.mount()

    # Override dependency on app
    app.dependency_overrides[get_current_user_header] = lambda: {"username": "mocked-user"}

    try:
        async with connect_mcp_test_client(app) as client:
            res = await client.send_request("tools/call", {"name": "whoami", "arguments": {}})
            assert not res["result"].get("isError")
            data = json.loads(res["result"]["content"][0]["text"])
            assert data == {"user": "mocked-user"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sub_dependencies_and_generator_cleanup():
    app = FastAPI()
    cleanup_done = False

    def get_db():
        nonlocal cleanup_done
        db = {"status": "connected"}
        try:
            yield db
        finally:
            cleanup_done = True

    def get_repo(db: dict = Depends(get_db)):
        return {"db_status": db["status"]}

    mcp = FastMCP(app=app)

    @mcp.tool
    def db_tool(repo: dict = Depends(get_repo)) -> dict:
        return repo

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        res = await client.send_request("tools/call", {"name": "db_tool", "arguments": {}})
        assert not res["result"].get("isError")
        data = json.loads(res["result"]["content"][0]["text"])
        assert data == {"db_status": "connected"}
        # Generator dependency cleanup must have executed
        assert cleanup_done is True


@pytest.mark.asyncio
async def test_get_current_request_context_var():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def inspect_request() -> dict:
        req = get_current_request()
        assert req is not None
        assert isinstance(req, Request)
        auth = req.headers.get("authorization")
        client_host = req.client.host if req.client else None
        return {"has_request": True, "auth": auth, "client_host": client_host}

    mcp.mount()

    headers = {"authorization": "Bearer inspect-token"}
    async with connect_mcp_test_client(app, headers=headers) as client:
        res = await client.send_request("tools/call", {"name": "inspect_request", "arguments": {}})
        assert not res["result"].get("isError")
        data = json.loads(res["result"]["content"][0]["text"])
        assert data["has_request"] is True
        assert data["auth"] == "Bearer inspect-token"
        assert data["client_host"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_concurrent_sessions_isolated_auth():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def get_session_user(user: dict = Depends(get_current_user_header)) -> dict:
        return {"user": user["username"], "token": user["token"]}

    mcp.mount()

    # Two clients connecting concurrently: client1 with valid token, client2 with invalid token

    async with connect_mcp_test_client(app, sse_headers={"authorization": "Bearer valid-secret-token"}) as client1:
        res1 = await client1.send_request("tools/call", {"name": "get_session_user", "arguments": {}})
        assert not res1["result"].get("isError")
        data1 = json.loads(res1["result"]["content"][0]["text"])
        assert data1["token"] == "valid-secret-token"

        # Client 2 connects with bad token and fails
        async with connect_mcp_test_client(app, sse_headers={"authorization": "Bearer bad-token"}) as client2:
            res2 = await client2.send_request("tools/call", {"name": "get_session_user", "arguments": {}})
            assert res2["result"].get("isError") is True

        # Client 1 can still make requests with its valid session!
        res1_again = await client1.send_request("tools/call", {"name": "get_session_user", "arguments": {}})
        assert not res1_again["result"].get("isError")
        data1_again = json.loads(res1_again["result"]["content"][0]["text"])
        assert data1_again["token"] == "valid-secret-token"


@pytest.mark.asyncio
async def test_domain_http_exception_handling():
    app = FastAPI()
    mcp = FastMCP(app=app)

    @mcp.tool
    def find_item(item_id: int) -> dict:
        """Find an item or raise 404."""
        if item_id == 404:
            raise HTTPException(status_code=404, detail="Item not found in catalog")
        return {"item_id": item_id, "found": True}

    mcp.mount()

    async with connect_mcp_test_client(app) as client:
        # Success case
        res = await client.send_request("tools/call", {"name": "find_item", "arguments": {"item_id": 1}})
        assert not res["result"].get("isError")
        assert json.loads(res["result"]["content"][0]["text"]) == {"item_id": 1, "found": True}

        # 404 error case
        res_404 = await client.send_request("tools/call", {"name": "find_item", "arguments": {"item_id": 404}})
        assert res_404["result"].get("isError") is True
        error_msg = res_404["result"]["content"][0]["text"]
        assert "404" in error_msg
        assert "Item not found in catalog" in error_msg


@pytest.mark.asyncio
async def test_security_with_scopes():
    app = FastAPI()
    mcp = FastMCP(app=app)

    def verify_scopes(
        security_scopes: SecurityScopes,
        authorization: str = Header(...),
    ) -> list[str]:
        if authorization != "Bearer admin-token":
            raise HTTPException(status_code=403, detail="Invalid token for scopes")
        # Check required scopes
        return security_scopes.scopes

    @mcp.tool
    def admin_action(scopes: list[str] = Security(verify_scopes, scopes=["admin:read", "admin:write"])) -> dict:
        return {"scopes": scopes}

    mcp.mount()

    async with connect_mcp_test_client(app, sse_headers={"authorization": "Bearer admin-token"}) as client:
        res = await client.send_request("tools/call", {"name": "admin_action", "arguments": {}})
        assert not res["result"].get("isError")
        data = json.loads(res["result"]["content"][0]["text"])
        assert data["scopes"] == ["admin:read", "admin:write"]

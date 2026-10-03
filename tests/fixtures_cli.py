"""Fixtures for CLI target resolution and stdio testing."""

from fastapi import FastAPI
from fast_mcp import FastMCP

# 1. Bare FastAPI app with routes tagged 'mcp'
bare_app = FastAPI()


@bare_app.get("/items/{item_id}", tags=["mcp"])
def get_item(item_id: int) -> dict[str, int]:
    return {"item_id": item_id}


# 1b. Fresh app for custom mount path test
custom_mount_app = FastAPI()


@custom_mount_app.get("/custom", tags=["mcp"])
def get_custom() -> dict[str, str]:
    return {"status": "custom"}


# 2. FastAPI app with FastMCP pre-mounted
mounted_app = FastAPI()
_mounted_mcp = FastMCP(app=mounted_app, name="pre-mounted-server")


@mounted_app.get("/status", tags=["mcp"])
def get_status() -> dict[str, str]:
    return {"status": "ok"}


_mounted_mcp.mount()

# 3. Standalone FastMCP instance
standalone_mcp = FastMCP(name="standalone-mcp")


@standalone_mcp.tool()
def multiply(a: int, b: int) -> int:
    return a * b


# 4. Proxy app (mcp.app)
_proxy_mcp = FastMCP(name="proxy-server")


@_proxy_mcp.tool()
def echo(message: str) -> str:
    return message


proxy_app = _proxy_mcp.app

# 5. Invalid object
not_a_server = "just a string"

# 6. Default export for testing module without attribute colon
app = bare_app

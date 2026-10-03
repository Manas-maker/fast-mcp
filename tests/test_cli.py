import json
import os
import subprocess
import sys
import pytest
from fast_mcp import FastMCP
from fast_mcp.cli import parse_args, resolve_target


def test_parse_args_explicit_stdio_subcommand():
    args = parse_args(["stdio", "main:app"])
    assert args.command == "stdio"
    assert args.target == "main:app"
    assert args.mount_path is None


def test_parse_args_default_subcommand():
    # Calling without "stdio" explicitly should default to stdio
    args = parse_args(["main:app"])
    assert args.command == "stdio"
    assert args.target == "main:app"
    assert args.mount_path is None


def test_parse_args_with_mount_path():
    args = parse_args(["stdio", "my_pkg.srv:mcp", "--mount-path", "/custom/mcp"])
    assert args.command == "stdio"
    assert args.target == "my_pkg.srv:mcp"
    assert args.mount_path == "/custom/mcp"


def test_parse_args_no_args_exits():
    with pytest.raises(SystemExit):
        parse_args([])


def test_resolve_target_standalone_fastmcp():
    mcp = resolve_target("tests.fixtures_cli:standalone_mcp")
    assert isinstance(mcp, FastMCP)
    assert mcp._mounted is True
    assert "multiply" in mcp._all_tools


def test_resolve_target_proxy_app():
    mcp = resolve_target("tests.fixtures_cli:proxy_app")
    assert isinstance(mcp, FastMCP)
    assert mcp._mounted is True
    assert "echo" in mcp._all_tools


def test_resolve_target_pre_mounted_app():
    mcp = resolve_target("tests.fixtures_cli:mounted_app")
    assert isinstance(mcp, FastMCP)
    assert mcp.name == "pre-mounted-server"
    assert mcp._mounted is True
    assert "get_status" in mcp._all_tools


def test_resolve_target_bare_fastapi_app():
    mcp = resolve_target("tests.fixtures_cli:bare_app")
    assert isinstance(mcp, FastMCP)
    assert mcp._mounted is True
    assert "get_item" in mcp._all_tools


def test_resolve_target_bare_fastapi_app_custom_mount_path():
    mcp = resolve_target("tests.fixtures_cli:custom_mount_app", mount_path="/api/custom")
    assert isinstance(mcp, FastMCP)
    assert mcp.mount_path == "/api/custom"


def test_resolve_target_default_app_attr():
    mcp = resolve_target("tests.fixtures_cli")
    assert isinstance(mcp, FastMCP)
    assert mcp._mounted is True


def test_resolve_target_default_mcp_attr():
    mcp = resolve_target("tests.fixtures_mcp_default")
    assert isinstance(mcp, FastMCP)
    assert mcp._mounted is True
    assert "ping" in mcp._all_tools


def test_resolve_target_invalid_type():
    with pytest.raises(TypeError, match="expected FastMCP or FastAPI"):
        resolve_target("tests.fixtures_cli:not_a_server")


def test_resolve_target_missing_attribute():
    with pytest.raises(AttributeError, match="has no attribute"):
        resolve_target("tests.fixtures_cli:nonexistent_attr")


def test_resolve_target_missing_module():
    with pytest.raises(ModuleNotFoundError):
        resolve_target("nonexistent_module_12345:app")


def test_resolve_target_invalid_format():
    with pytest.raises(ValueError, match="Invalid target"):
        resolve_target("")


class InMemoryAsyncStdin:
    def __init__(self, messages: list[str]):
        self.messages = list(messages)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        import anyio

        if self._index < len(self.messages):
            msg = self.messages[self._index]
            self._index += 1
            await anyio.sleep(0.01)
            return msg
        await anyio.sleep(0.05)
        raise StopAsyncIteration


class InMemoryAsyncStdout:
    def __init__(self):
        self.lines: list[str] = []

    async def write(self, s: str):
        self.lines.append(s)

    async def flush(self):
        pass


@pytest.mark.asyncio
async def test_programmatic_run_stdio_with_fastmcp():
    from fast_mcp import run_stdio

    mcp = FastMCP(name="prog-mcp")

    @mcp.tool()
    def add(x: int, y: int) -> int:
        return x + y

    init_msg = (
        json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        })
        + "\n"
    )

    init_notif = (
        json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        + "\n"
    )

    call_msg = (
        json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "add", "arguments": {"x": 10, "y": 32}},
        })
        + "\n"
    )

    stdin = InMemoryAsyncStdin([init_msg, init_notif, call_msg])
    stdout = InMemoryAsyncStdout()

    await run_stdio(mcp, stdin=stdin, stdout=stdout)

    assert len(stdout.lines) == 2
    res1 = json.loads(stdout.lines[0])
    assert res1["id"] == 1
    assert res1["result"]["serverInfo"]["name"] == "prog-mcp"

    res2 = json.loads(stdout.lines[1])
    assert res2["id"] == 2
    assert res2["result"]["content"][0]["text"] == "42"


@pytest.mark.asyncio
async def test_programmatic_run_stdio_with_string_target():
    from fast_mcp import run_stdio

    init_msg = (
        json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        })
        + "\n"
    )

    stdin = InMemoryAsyncStdin([init_msg])
    stdout = InMemoryAsyncStdout()

    await run_stdio("tests.fixtures_cli:standalone_mcp", stdin=stdin, stdout=stdout)

    assert len(stdout.lines) == 1
    res = json.loads(stdout.lines[0])
    assert res["id"] == 1
    assert res["result"]["serverInfo"]["name"] == "standalone-mcp"


@pytest.mark.asyncio
async def test_programmatic_run_stdio_with_bare_fastapi():
    from fastapi import FastAPI
    from fast_mcp import run_stdio

    app = FastAPI()

    @app.get("/hello", tags=["mcp"])
    def hello() -> str:
        return "world"

    init_msg = (
        json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        })
        + "\n"
    )

    list_msg = (
        json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        + "\n"
    )

    stdin = InMemoryAsyncStdin([init_msg, list_msg])
    stdout = InMemoryAsyncStdout()

    await run_stdio(app, stdin=stdin, stdout=stdout)

    assert len(stdout.lines) == 2
    res2 = json.loads(stdout.lines[1])
    tool_names = [t["name"] for t in res2["result"]["tools"]]
    assert "hello" in tool_names


def _run_subprocess_session(
    target: str, requests: list[dict], extra_args: list[str] | None = None
) -> tuple[list[dict], int]:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env = dict(os.environ)
    src_dir = os.path.join(repo_root, "src")
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [sys.executable, "-m", "fast_mcp"]
    if extra_args:
        cmd.extend(extra_args)
    else:
        cmd.extend(["stdio", target])

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=repo_root,
        env=env,
    )

    responses: list[dict] = []
    for req in requests:
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        if "id" in req:
            line = proc.stdout.readline()
            if line:
                responses.append(json.loads(line.strip()))

    proc.stdin.close()
    proc.wait(timeout=5)
    return responses, proc.returncode


def test_subprocess_standalone_fastmcp():
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "multiply", "arguments": {"a": 6, "b": 7}},
        },
    ]

    responses, code = _run_subprocess_session("tests.fixtures_cli:standalone_mcp", requests)
    assert code == 0
    assert len(responses) == 3

    assert responses[0]["id"] == 1
    assert responses[0]["result"]["serverInfo"]["name"] == "standalone-mcp"

    assert responses[1]["id"] == 2
    tool_names = [t["name"] for t in responses[1]["result"]["tools"]]
    assert "multiply" in tool_names

    assert responses[2]["id"] == 3
    assert responses[2]["result"]["content"][0]["text"] == "42"


def test_subprocess_bare_fastapi_app():
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_item", "arguments": {"item_id": 99}},
        },
    ]

    responses, code = _run_subprocess_session("tests.fixtures_cli:bare_app", requests)
    assert code == 0
    assert len(responses) == 3

    assert responses[0]["id"] == 1
    assert responses[1]["id"] == 2
    tool_names = [t["name"] for t in responses[1]["result"]["tools"]]
    assert "get_item" in tool_names

    assert responses[2]["id"] == 3
    assert json.loads(responses[2]["result"]["content"][0]["text"]) == {"item_id": 99}


def test_subprocess_default_subcommand_without_stdio():
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
    ]

    responses, code = _run_subprocess_session(
        "tests.fixtures_cli:standalone_mcp",
        requests,
        extra_args=["tests.fixtures_cli:standalone_mcp"],
    )
    assert code == 0
    assert len(responses) == 1
    assert responses[0]["result"]["serverInfo"]["name"] == "standalone-mcp"


def test_cli_main_error_handling():
    from fast_mcp.cli import main

    assert main(["stdio", "nonexistent_target_123:app"]) == 1

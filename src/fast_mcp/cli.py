"""Command-line interface for FastMCP."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
from typing import Any, Sequence

from fastapi import FastAPI
from mcp.server.stdio import stdio_server

from fast_mcp.server import FastMCP


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for fast-mcp CLI."""
    parser = argparse.ArgumentParser(
        prog="fast-mcp",
        description="FastMCP - FastAPI-native Model Context Protocol framework CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    stdio_parser = subparsers.add_parser(
        "stdio",
        help="Run MCP server over standard I/O (stdio) for local AI desktop clients",
    )
    stdio_parser.add_argument(
        "target",
        help="Target application or MCP server in 'module:attribute' format (e.g., 'main:app' or 'main:mcp')",
    )
    stdio_parser.add_argument(
        "--mount-path",
        default=None,
        help="Custom mount path when auto-mounting FastMCP onto a FastAPI instance (default: '/mcp')",
    )

    return parser


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments, defaulting to stdio subcommand if omitted."""
    if args is None:
        raw_args = list(sys.argv[1:])
    else:
        raw_args = list(args)

    parser = create_parser()

    # If first argument is not a known subcommand and not a help/version flag, default to 'stdio'
    known_commands = {"stdio"}
    if raw_args and not raw_args[0].startswith("-") and raw_args[0] not in known_commands:
        raw_args.insert(0, "stdio")

    parsed = parser.parse_args(raw_args)
    if not parsed.command:
        parser.error("A subcommand must be specified (e.g. 'fast-mcp stdio <target>')")

    return parsed


def _find_mcp_on_fastapi(app: FastAPI) -> FastMCP | None:
    """Find an existing FastMCP instance mounted or attached to a FastAPI app."""
    # 1. Check app.state.mcp
    if hasattr(app, "state"):
        mcp_state = getattr(app.state, "mcp", None)
        if isinstance(mcp_state, FastMCP):
            return mcp_state

    # 2. Check app._mcp
    mcp_attr = getattr(app, "_mcp", None)
    if isinstance(mcp_attr, FastMCP):
        return mcp_attr

    # 3. Check routes
    for route in getattr(app, "routes", []):
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None:
            if hasattr(endpoint, "_mcp") and isinstance(endpoint._mcp, FastMCP):
                return endpoint._mcp
            if hasattr(endpoint, "mcp") and isinstance(endpoint.mcp, FastMCP):
                return endpoint.mcp

    return None


def _ensure_mcp_instance(obj: Any, mount_path: str | None = None) -> FastMCP:
    """Ensure an object (FastMCP, _AppProxy, or FastAPI) is wrapped/mounted as a FastMCP instance."""
    # Handle _AppProxy or objects with _mcp attribute
    if hasattr(obj, "_mcp") and isinstance(obj._mcp, FastMCP):
        obj = obj._mcp

    if isinstance(obj, FastMCP):
        if obj._app is None:
            obj.mount(FastAPI())
        elif not obj._mounted:
            obj.mount()
        return obj

    if isinstance(obj, FastAPI):
        existing = _find_mcp_on_fastapi(obj)
        if existing is not None:
            if not existing._mounted:
                existing.mount(obj)
            return existing

        kwargs: dict[str, Any] = {}
        if mount_path is not None:
            kwargs["mount_path"] = mount_path
        new_mcp = FastMCP(app=obj, **kwargs)
        new_mcp.mount()
        return new_mcp

    raise TypeError(
        f"Target resolved to '{type(obj).__name__}', expected FastMCP or FastAPI instance"
    )


def resolve_target(target: str, mount_path: str | None = None) -> FastMCP:
    """Resolve an import target string like 'module:attribute' or 'module' into a FastMCP instance."""
    if not target or not isinstance(target, str):
        raise ValueError(f"Invalid target: '{target}'. Expected 'module:attribute' or 'module'.")

    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    if ":" in target:
        module_path, attr_name = target.split(":", 1)
        module_path = module_path.strip()
        attr_name = attr_name.strip()
        if not module_path or not attr_name:
            raise ValueError(f"Invalid target format: '{target}'. Expected 'module:attribute' or 'module'.")
    else:
        module_path = target.strip()
        attr_name = None
        if not module_path:
            raise ValueError(f"Invalid target format: '{target}'.")

    try:
        mod = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        if exc.name == module_path or exc.name == module_path.split(".")[0]:
            raise ModuleNotFoundError(f"Could not import module '{module_path}': {exc}") from exc
        raise

    if attr_name is not None:
        if not hasattr(mod, attr_name):
            raise AttributeError(f"Module '{module_path}' has no attribute '{attr_name}'")
        obj = getattr(mod, attr_name)
    else:
        if hasattr(mod, "app"):
            obj = getattr(mod, "app")
        elif hasattr(mod, "mcp"):
            obj = getattr(mod, "mcp")
        else:
            raise AttributeError(f"Module '{module_path}' has neither 'app' nor 'mcp' attribute")

    return _ensure_mcp_instance(obj, mount_path=mount_path)


async def run_stdio(
    target: FastMCP | FastAPI | str,
    stdin: Any | None = None,
    stdout: Any | None = None,
    mount_path: str | None = None,
) -> None:
    """Run an MCP server over standard input/output pipes."""
    if isinstance(target, str):
        mcp = resolve_target(target, mount_path=mount_path)
    else:
        mcp = _ensure_mcp_instance(target, mount_path=mount_path)

    async with stdio_server(stdin=stdin, stdout=stdout) as (read_stream, write_stream):
        await mcp.server.run(
            read_stream,
            write_stream,
            mcp.server.create_initialization_options(),
        )


def main(args: Sequence[str] | None = None) -> int:
    """CLI entrypoint for fast-mcp."""
    try:
        parsed_args = parse_args(args)
        if parsed_args.command == "stdio":
            asyncio.run(
                run_stdio(
                    parsed_args.target,
                    mount_path=parsed_args.mount_path,
                )
            )
            return 0
        else:
            sys.stderr.write(f"Unknown command: {parsed_args.command}\n")
            return 1
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1

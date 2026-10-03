"""Executable module entrypoint for fast-mcp (`python -m fast_mcp`)."""

import sys
from fast_mcp.cli import main

if __name__ == "__main__":
    sys.exit(main())

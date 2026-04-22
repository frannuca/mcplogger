#!/usr/bin/env python3
"""
MCP Log Analyzer – HTTP Service Entry Point.

Runs the FastMCP server with ``streamable-http`` transport so that multiple
clients (threads, processes, or remote machines) can call MCP tools
simultaneously without competing over a single stdin/stdout pipe.

Usage
-----
    python server/service.py                        # 127.0.0.1:8000
    python server/service.py --host 0.0.0.0 --port 9000
    python -m server.service --port 9000

MCP endpoint
------------
    http://<host>:<port>/mcp

All tools defined in ``server/tools.py`` are automatically exposed.
"""

import argparse
import sys
from pathlib import Path

# Allow running as a standalone script from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.tools import mcp  # noqa: E402  (import after sys.path fix)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCP Log Analyzer – HTTP service (streamable-http transport)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind to ('0.0.0.0' to listen on all interfaces)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="TCP port to listen on",
    )
    args = parser.parse_args()

    # FastMCP reads host/port from its settings object.
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    print(f"🚀  MCP Log Analyzer HTTP service starting …")
    print(f"   Endpoint : http://{args.host}:{args.port}/mcp")
    print(f"   Transport: streamable-http")
    print(f"   Press Ctrl-C to stop.\n", flush=True)

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

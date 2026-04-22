#!/usr/bin/env python3
"""
MCP Log Analyzer Server

Supports two transports:

* **stdio** (default) – classic stdin/stdout pipe, compatible with MCP
  clients that spawn the server as a subprocess (e.g. Claude Desktop).

* **streamable-http** – HTTP-based service that accepts concurrent
  connections from multiple threads or processes.  Use this mode when
  you need thread-safe, multi-client access.

Usage
-----
    python main.py                                  # stdio (default)
    python main.py --transport streamable-http      # HTTP on 127.0.0.1:8000
    python main.py --transport streamable-http --host 0.0.0.0 --port 9000
"""

import argparse
import sys
from pathlib import Path

# Allow running as a standalone script from any working directory.
sys.path.insert(0, str(Path(__file__).parent))

from server.tools import mcp  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCP Log Analyzer Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport protocol to use",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (streamable-http only)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (streamable-http only)",
    )
    args = parser.parse_args()

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(
            f"🚀  MCP Log Analyzer HTTP service → http://{args.host}:{args.port}/mcp",
            file=sys.stderr,
            flush=True,
        )

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()

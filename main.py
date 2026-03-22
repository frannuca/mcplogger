#!/usr/bin/env python3
"""
MCP Log Analyzer Server
Stdio-based MCP server for analyzing log files and searching for specific problems.
"""

import sys
from pathlib import Path

# Add parent directory to path so relative imports work when run directly
sys.path.insert(0, str(Path(__file__).parent))

from tools import mcp

if __name__ == "__main__":
    mcp.run()

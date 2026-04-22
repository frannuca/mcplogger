"""
conftest.py – pytest configuration.

Adds the project root to sys.path so that tests can import project
modules directly (e.g. ``from server.http_client import MCPHttpClient``).
"""

import sys
from pathlib import Path

# Ensure the project root is on the Python path regardless of how pytest
# is invoked.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

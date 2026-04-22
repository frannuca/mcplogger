"""
tests/test_http_service.py – Tests for the FastMCP HTTP service.

These tests:

1. Start the FastMCP server with ``streamable-http`` transport as a
   background subprocess.
2. Exercise the :class:`~server.http_client.MCPHttpClient` from a pool
   of threads to verify thread-safe concurrent access.
3. Verify basic functional correctness of the tool responses.

The tests use a real subprocess + real HTTP connections so that the
entire integration (FastMCP ↔ HTTP ↔ client) is exercised.
"""

import concurrent.futures
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_service(
    base_url: str,
    timeout: float = 15.0,
    interval: float = 0.3,
) -> bool:
    """Poll the MCP endpoint until it accepts connections or *timeout* elapses."""
    from server.http_client import MCPHttpClient

    deadline = time.monotonic() + timeout
    client = MCPHttpClient(base_url)
    while time.monotonic() < deadline:
        try:
            client.list_tools()
            return True
        except Exception:
            time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mcp_service():
    """Start the FastMCP HTTP service on a fixed port and tear it down after tests."""
    port = 18765
    proc = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "main.py"),
            "--transport", "streamable-http",
            "--host", "127.0.0.1",
            "--port", str(port),
        ],
        stderr=subprocess.PIPE,
        cwd=str(ROOT),
    )

    base_url = f"http://127.0.0.1:{port}"
    ready = _wait_for_service(base_url)
    if not ready:
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(f"MCP HTTP service did not start on port {port} within timeout")

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMCPHttpClientBasic:
    """Basic functional tests for MCPHttpClient."""

    def test_list_tools_returns_known_tools(self, mcp_service: str) -> None:
        from server.http_client import MCPHttpClient

        client = MCPHttpClient(mcp_service)
        tools = client.list_tools()

        tool_names = {t["name"] for t in tools}
        expected = {
            "analyze_logs",
            "search_logs_tool",
            "explain_error",
            "reset_file_cache",
            "semantic_analysis",
        }
        assert expected.issubset(tool_names), (
            f"Missing tools: {expected - tool_names}"
        )

    def test_reset_file_cache_no_args(self, mcp_service: str) -> None:
        from server.http_client import MCPHttpClient

        client = MCPHttpClient(mcp_service)
        result = client.call_tool("reset_file_cache", {})

        assert isinstance(result, dict)
        assert result.get("status") == "ok"
        assert result.get("reset") == "all"

    def test_reset_file_cache_with_files(
        self, tmp_path: Path, mcp_service: str
    ) -> None:
        from server.http_client import MCPHttpClient

        log_file = tmp_path / "test.log"
        log_file.write_text("2024-01-01 ERROR something went wrong\n")

        client = MCPHttpClient(mcp_service)
        result = client.call_tool(
            "reset_file_cache", {"log_files": [str(log_file)]}
        )
        assert isinstance(result, dict)
        assert result.get("status") == "ok"

    def test_analyze_logs_returns_expected_fields(
        self, tmp_path: Path, mcp_service: str
    ) -> None:
        from server.http_client import MCPHttpClient

        log_file = tmp_path / "app.log"
        log_file.write_text(
            "2024-01-01T10:00:00 INFO  service started\n"
            "2024-01-01T10:01:00 ERROR database connection failed\n"
            "2024-01-01T10:02:00 ERROR request timeout\n"
            "2024-01-01T10:03:00 INFO  retrying connection\n"
        )

        client = MCPHttpClient(mcp_service)
        result = client.call_tool(
            "analyze_logs",
            {
                "log_files": [str(log_file)],
                "bucket_minutes": 5,
                "high_error_threshold": 0.20,
                "max_samples": 10,
            },
        )

        assert isinstance(result, dict)
        for field in ("total_lines", "error_lines", "error_rate", "pattern_counts"):
            assert field in result, f"Field '{field}' missing from analyze_logs result"

        assert result["total_lines"] == 4
        assert result["error_lines"] == 2

    def test_search_logs_tool_returns_matches(
        self, tmp_path: Path, mcp_service: str
    ) -> None:
        from server.http_client import MCPHttpClient

        log_file = tmp_path / "search.log"
        log_file.write_text(
            "2024-01-01T10:00:00 INFO  starting\n"
            "2024-01-01T10:01:00 ERROR database timeout exceeded\n"
            "2024-01-01T10:02:00 ERROR database timeout exceeded\n"
            "2024-01-01T10:03:00 INFO  recovered\n"
        )

        client = MCPHttpClient(mcp_service)
        result = client.call_tool(
            "search_logs_tool",
            {
                "prompt": "database timeout",
                "log_files": [str(log_file)],
                "max_matches": 50,
                "context_lines": 0,
            },
        )

        assert isinstance(result, dict)
        assert "matches" in result
        assert result.get("total_matches", 0) >= 2


class TestMCPHttpClientConcurrency:
    """Thread-safety tests: many threads calling tools simultaneously."""

    _NUM_THREADS = 10
    _CALLS_PER_THREAD = 3

    def _make_log_file(self, tmp_path: Path, index: int) -> Path:
        f = tmp_path / f"concurrent_{index}.log"
        f.write_text(
            f"2024-01-01T10:00:0{index % 10} INFO  thread {index} started\n"
            f"2024-01-01T10:00:0{index % 10} ERROR thread {index} failed\n"
        )
        return f

    def test_concurrent_reset_cache(
        self, tmp_path: Path, mcp_service: str
    ) -> None:
        """Multiple threads calling reset_file_cache simultaneously must not crash."""
        from server.http_client import MCPHttpClient

        client = MCPHttpClient(mcp_service)

        def task(i: int) -> Dict[str, Any]:
            return client.call_tool("reset_file_cache", {})

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._NUM_THREADS
        ) as executor:
            futures = [executor.submit(task, i) for i in range(self._NUM_THREADS)]
            results = [f.result(timeout=30) for f in futures]

        assert all(r.get("status") == "ok" for r in results), (
            f"Some concurrent reset_file_cache calls failed: {results}"
        )

    def test_concurrent_analyze_logs(
        self, tmp_path: Path, mcp_service: str
    ) -> None:
        """Multiple threads calling analyze_logs on different files simultaneously."""
        from server.http_client import MCPHttpClient

        client = MCPHttpClient(mcp_service)
        log_files = [
            self._make_log_file(tmp_path, i) for i in range(self._NUM_THREADS)
        ]

        def task(log_file: Path) -> Dict[str, Any]:
            return client.call_tool(
                "analyze_logs",
                {
                    "log_files": [str(log_file)],
                    "bucket_minutes": 5,
                    "high_error_threshold": 0.20,
                    "max_samples": 5,
                },
            )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._NUM_THREADS
        ) as executor:
            futures = [executor.submit(task, lf) for lf in log_files]
            results = [f.result(timeout=60) for f in futures]

        for i, result in enumerate(results):
            assert isinstance(result, dict), f"Thread {i} got non-dict result"
            assert "total_lines" in result, (
                f"Thread {i} result missing 'total_lines': {result}"
            )
            assert result["total_lines"] == 2, (
                f"Thread {i} expected 2 lines, got {result['total_lines']}"
            )
            assert result["error_lines"] == 1, (
                f"Thread {i} expected 1 error line, got {result['error_lines']}"
            )

    def test_concurrent_search_logs(
        self, tmp_path: Path, mcp_service: str
    ) -> None:
        """Multiple threads calling search_logs_tool simultaneously."""
        from server.http_client import MCPHttpClient

        client = MCPHttpClient(mcp_service)
        log_file = tmp_path / "shared_search.log"
        log_file.write_text(
            "2024-01-01T10:00:00 ERROR authentication failed\n"
            "2024-01-01T10:01:00 ERROR authentication failed\n"
            "2024-01-01T10:02:00 INFO  user logged in\n"
        )

        def task(_: int) -> Dict[str, Any]:
            return client.call_tool(
                "search_logs_tool",
                {
                    "prompt": "authentication failed",
                    "log_files": [str(log_file)],
                    "max_matches": 10,
                    "context_lines": 0,
                },
            )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._NUM_THREADS
        ) as executor:
            futures = [executor.submit(task, i) for i in range(self._NUM_THREADS)]
            results = [f.result(timeout=60) for f in futures]

        for i, result in enumerate(results):
            assert isinstance(result, dict), f"Thread {i}: expected dict, got {type(result)}"
            assert "matches" in result, (
                f"Thread {i}: 'matches' key missing from result: {result}"
            )
            assert result.get("total_matches", 0) >= 2, (
                f"Thread {i}: expected ≥2 matches, got {result.get('total_matches')}"
            )

    def test_mixed_concurrent_tool_calls(
        self, tmp_path: Path, mcp_service: str
    ) -> None:
        """Mix of different tool calls issued concurrently from multiple threads."""
        from server.http_client import MCPHttpClient

        client = MCPHttpClient(mcp_service)
        log_file = tmp_path / "mixed.log"
        log_file.write_text(
            "2024-01-01T10:00:00 ERROR disk full\n"
            "2024-01-01T10:01:00 INFO  cleanup started\n"
            "2024-01-01T10:02:00 ERROR disk full\n"
        )

        tasks: List = [
            ("reset_file_cache", {}),
            ("analyze_logs", {"log_files": [str(log_file)], "max_samples": 5}),
            ("search_logs_tool", {"prompt": "disk full", "log_files": [str(log_file)]}),
            ("reset_file_cache", {}),
            ("analyze_logs", {"log_files": [str(log_file)], "max_samples": 5}),
        ]

        def run_task(tool_name: str, tool_args: Dict[str, Any]) -> Dict:
            return client.call_tool(tool_name, tool_args)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = [executor.submit(run_task, name, args) for name, args in tasks]
            results = [f.result(timeout=60) for f in futures]

        # All calls must return dicts without raising
        assert all(isinstance(r, dict) for r in results), (
            f"Some mixed concurrent calls returned non-dict: {results}"
        )
        # No result should be an error
        for i, result in enumerate(results):
            assert "error" not in result, (
                f"Task {i} ({tasks[i][0]}) returned error: {result.get('error')}"
            )

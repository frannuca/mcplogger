"""
Thread-safe HTTP client for the FastMCP Log Analyzer service.

Each :py:meth:`MCPHttpClient.call_tool` invocation opens its own async
MCP session over HTTP (streamable-http transport) and closes it when the
call returns.  Because no shared state is held between calls the class is
safe to use concurrently from many threads.

Typical usage
-------------
Start the service first::

    python server/service.py --port 8000

Then in your code::

    from server.http_client import MCPHttpClient

    client = MCPHttpClient("http://127.0.0.1:8000")

    # Thread-safe – can be called from multiple threads simultaneously.
    result = client.call_tool("analyze_logs", {"log_files": ["/var/log/app.log"]})
    result = client.call_tool("search_logs_tool", {"prompt": "database timeout"})
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _result_to_dict(result: CallToolResult) -> Dict[str, Any]:
    """Convert a :class:`~mcp.types.CallToolResult` to a plain ``dict``.

    FastMCP returns ``structuredContent`` for tools that return a ``dict``.
    The wrapper is ``{"result": {…}}``; we unwrap it here so callers always
    get the tool's own return value.
    """
    sc = result.structuredContent
    if sc is not None:
        if isinstance(sc, dict):
            inner = sc.get("result")
            if isinstance(inner, dict):
                return inner
            return sc
        return {}  # unexpected type – return empty rather than crash

    # Fallback: unstructured tools place JSON in content[0].text
    if result.content:
        first = result.content[0]
        text = getattr(first, "text", None)
        if text:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"text": text}

    return {}


# ---------------------------------------------------------------------------
# Public client
# ---------------------------------------------------------------------------

class MCPHttpClient:
    """Thread-safe MCP client for the FastMCP HTTP service.

    Parameters
    ----------
    base_url:
        Base URL of the running FastMCP service, e.g.
        ``"http://127.0.0.1:8000"``.  The ``/mcp`` path is appended
        automatically.
    timeout:
        Seconds to wait for a response from the service (per call).

    Notes
    -----
    Thread-safety is achieved by creating a *fresh* ``ClientSession`` for
    every :py:meth:`call_tool` / :py:meth:`list_tools` invocation via
    ``asyncio.run()`` (which spins up a dedicated event loop on the calling
    thread).  There is therefore no shared mutable state between concurrent
    calls.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._mcp_url = f"{self.base_url}/mcp"
        self._timeout = timeout

    # ── public API ──────────────────────────────────────────────────────────

    def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call an MCP tool and return its result as a plain ``dict``.

        Thread-safe: each invocation runs inside its own isolated event loop.

        Parameters
        ----------
        name:
            Tool name, e.g. ``"analyze_logs"``.
        arguments:
            Keyword arguments for the tool.  Pass ``None`` or ``{}`` for
            tools that accept no required parameters.

        Returns
        -------
        dict
            The tool's return value, unwrapped from FastMCP's response
            envelope.

        Raises
        ------
        RuntimeError
            If the MCP service signals a tool-level error.
        ConnectionError
            If the service cannot be reached.
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self._async_call_tool(name, arguments or {})
            )
        finally:
            loop.close()

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return metadata for all tools registered with the service.

        Thread-safe: uses the same isolated-event-loop pattern as
        :py:meth:`call_tool`.
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._async_list_tools())
        finally:
            loop.close()

    # ── async internals ─────────────────────────────────────────────────────

    async def _async_call_tool(
        self, name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http_client:
                async with streamable_http_client(
                    self._mcp_url, http_client=http_client
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result: CallToolResult = await session.call_tool(
                            name, arguments
                        )
                        if result.isError:
                            # Collect any error text from content
                            msgs = [
                                getattr(c, "text", str(c))
                                for c in (result.content or [])
                            ]
                            raise RuntimeError(
                                f"Tool '{name}' returned an error: "
                                + "; ".join(msgs)
                            )
                        return _result_to_dict(result)
        except RuntimeError:
            raise
        except Exception as exc:
            raise ConnectionError(
                f"Failed to call tool '{name}' at {self._mcp_url}: {exc}"
            ) from exc

    async def _async_list_tools(self) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http_client:
                async with streamable_http_client(
                    self._mcp_url, http_client=http_client
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        return [t.model_dump() for t in result.tools]
        except Exception as exc:
            raise ConnectionError(
                f"Failed to list tools at {self._mcp_url}: {exc}"
            ) from exc

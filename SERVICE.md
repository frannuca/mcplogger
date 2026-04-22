# MCP Log Analyzer – HTTP Service Mode

The MCP Log Analyzer can run as a **long-lived HTTP service** instead of
the classic stdio subprocess.  The HTTP mode uses FastMCP's
`streamable-http` transport, which means:

- **Multiple clients** can connect simultaneously.
- **Multiple threads** in the same process can call tools concurrently
  without competing over a single stdin/stdout pipe.
- The service is accessible over a network (configure `--host 0.0.0.0`
  for non-local access).

---

## Quick Start

### 1 – Start the HTTP service

```bash
# Default: listen on http://127.0.0.1:8000/mcp
python server/service.py

# Custom host/port
python server/service.py --host 0.0.0.0 --port 9000

# Alternatively, use main.py with --transport
python main.py --transport streamable-http --port 8000
```

The console will print the MCP endpoint URL when the server is ready:

```
🚀  MCP Log Analyzer HTTP service starting …
   Endpoint : http://127.0.0.1:8000/mcp
   Transport: streamable-http
   Press Ctrl-C to stop.
```

### 2 – Use the HTTP client in your code

```python
from server.http_client import MCPHttpClient

client = MCPHttpClient("http://127.0.0.1:8000")

# Analyze log files
result = client.call_tool("analyze_logs", {
    "log_files": ["/var/log/app.log"],
    "bucket_minutes": 5,
    "high_error_threshold": 0.20,
    "max_samples": 30,
})
print(result["error_rate"])

# Search for a specific problem
matches = client.call_tool("search_logs_tool", {
    "prompt": "database connection timeout",
    "log_files": ["/var/log/app.log"],
    "max_matches": 50,
})
print(matches["total_matches"])
```

### 3 – Use `ask.py` / `smart_ask.py` with the HTTP service

```bash
# Connect to a running service instead of spawning a subprocess
python ask.py --service-url http://127.0.0.1:8000 app.log

python smart_ask.py --service-url http://127.0.0.1:8000 app.log
```

### 4 – Web UI

The Flask web UI (`web/app.py`) automatically starts an embedded MCP HTTP
service when the user clicks **Start** in the browser.  No manual steps are
needed.

```bash
python web/app.py        # opens http://localhost:5000
```

The embedded service uses port **8787** by default.  Pass
`"service_port": <port>` in the start API payload to use a different port.

---

## Thread Safety

`MCPHttpClient.call_tool()` is **fully thread-safe**.

Each call opens a fresh HTTP session, runs it to completion in an
isolated event loop (`asyncio.new_event_loop()`), and then closes
the loop.  There is no shared mutable state between concurrent calls.

```python
import threading
from server.http_client import MCPHttpClient

client = MCPHttpClient("http://127.0.0.1:8000")

def worker(log_file: str) -> dict:
    return client.call_tool("analyze_logs", {"log_files": [log_file]})

threads = [
    threading.Thread(target=worker, args=(f"/var/log/app{i}.log",))
    for i in range(10)
]
for t in threads:
    t.start()
for t in threads:
    t.join()
```

---

## Environment Variables

The HTTP service reads the same environment variables as the stdio server:

| Variable | Description |
|---|---|
| `LOG_FILES` | Default log files (comma-separated paths) |
| `LLM_API_KEY` / `OPENAI_API_KEY` | LLM API key for AI summaries |
| `LLM_BASE_URL` | LLM base URL (default: OpenAI cloud) |
| `OPENAI_MODEL` | LLM model name |
| `LLM_EMBEDDING_URL` | Embedding server URL for semantic search |

Set them in `.env` or export before starting the service.

---

## Choosing a Transport

| Scenario | Recommended transport |
|---|---|
| Claude Desktop / single-user CLI | `stdio` (default) |
| Web UI with multiple browser tabs | `streamable-http` |
| Multithreaded application | `streamable-http` |
| Microservice / remote access | `streamable-http` with `--host 0.0.0.0` |

---

## Running Tests

```bash
python -m pytest tests/test_http_service.py -v
```

The test suite starts a real HTTP service on port **18765**, exercises all
tools with concurrent threads, and verifies functional correctness.

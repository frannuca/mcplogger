#!/usr/bin/env python3
"""
Flask web frontend for the MCP Log Analyzer.

Spawns the MCP Log Analyzer as an **HTTP service** (FastMCP
``streamable-http`` transport) and forwards REST API calls to it via
:class:`~server.http_client.MCPHttpClient`.

Compared with the previous stdio-pipe approach, the HTTP service
handles concurrent requests natively, so multiple browser tabs or API
clients can query the analyzer at the same time without contention.

Usage
-----
    python web/app.py                 # starts on http://localhost:5000
    python web/app.py --port 8888     # custom port
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent          # mcplogger/
MAIN_PY = ROOT / "main.py"

# Port used by the embedded MCP HTTP service.
_DEFAULT_MCP_SERVICE_PORT = 8787

sys.path.insert(0, str(ROOT))
from server.http_client import MCPHttpClient  # noqa: E402

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)

# ── MCP session state ─────────────────────────────────────────────────────────


class MCPSession:
    """Manages the lifecycle of the MCP HTTP service subprocess.

    The web app spawns ``main.py --transport streamable-http`` as a child
    process on *start* and connects to it with :class:`MCPHttpClient`.
    Because the HTTP client creates an independent connection per call, all
    Flask request-handler threads can issue tool calls concurrently without
    any additional locking.
    """

    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.config: Dict = {}
        self.tools: List[Dict] = []
        self._client: Optional[MCPHttpClient] = None
        self._service_port: int = _DEFAULT_MCP_SERVICE_PORT

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self, config: Dict) -> Dict:
        if self.running:
            return {"ok": False, "error": "Server already running"}

        self.config = config

        # Build env vars from the UI config
        env = {**os.environ}
        mode = config.get("mode", "local")
        if mode == "remote":
            env["OPENAI_API_KEY"] = config.get("api_key", "")
            env["OPENAI_MODEL"] = config.get("model", "gpt-4o-mini")
            env.pop("LLM_BASE_URL", None)
            env.pop("LLM_API_KEY", None)
            env.pop("LLM_EMBEDDING_URL", None)
        else:
            llm_url = config.get("llm_url", "http://localhost:8080/v1")
            env["LLM_BASE_URL"] = llm_url
            env["LLM_API_KEY"] = "local"
            env["OPENAI_MODEL"] = config.get("model", "local")
            embed_url = config.get("embedding_url", "")
            if embed_url:
                env["LLM_EMBEDDING_URL"] = embed_url
            else:
                env.pop("LLM_EMBEDDING_URL", None)

        log_files = config.get("log_files", [])
        env["LOG_FILES"] = ",".join(log_files)

        port = config.get("service_port", _DEFAULT_MCP_SERVICE_PORT)
        self._service_port = int(port)

        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    str(MAIN_PY),
                    "--transport", "streamable-http",
                    "--host", "127.0.0.1",
                    "--port", str(self._service_port),
                ],
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=str(ROOT),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        # Wait for the HTTP service to become ready (up to 10 s).
        base_url = f"http://127.0.0.1:{self._service_port}"
        self._client = MCPHttpClient(base_url)
        deadline = time.monotonic() + 10.0
        last_exc: Exception = RuntimeError("timeout waiting for service")
        while time.monotonic() < deadline:
            if not self.running:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                return {"ok": False, "error": f"Service exited early. stderr: {stderr}"}
            try:
                self.tools = self._client.list_tools()
                break
            except ConnectionError as exc:
                last_exc = exc
                time.sleep(0.3)
        else:
            self.stop()
            return {"ok": False, "error": f"Service did not become ready: {last_exc}"}

        return {
            "ok": True,
            "pid": self.process.pid,
            "tools": len(self.tools),
            "service_url": f"{base_url}/mcp",
        }

    def stop(self) -> Dict:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
        self._client = None
        self.tools = []
        return {"ok": True}

    # ── tool calls ─────────────────────────────────────────────────────────

    def call_tool(self, name: str, arguments: Dict) -> Optional[Dict]:
        """Call an MCP tool via the HTTP service.

        Thread-safe: :class:`MCPHttpClient` creates a fresh connection per
        call, so concurrent Flask threads do not block each other.
        """
        if not self.running or self._client is None:
            return {"error": "Server not running"}
        try:
            return self._client.call_tool(name, arguments)
        except (RuntimeError, ConnectionError) as exc:
            return {"error": str(exc)}


session = MCPSession()

# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify({"running": session.running, "config": session.config})


@app.route("/api/start", methods=["POST"])
def api_start():
    config = request.json or {}
    return jsonify(session.start(config))


@app.route("/api/stop", methods=["POST"])
def api_stop():
    return jsonify(session.stop())


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    body = request.json or {}
    log_files = session.config.get("log_files", [])
    result = session.call_tool("analyze_logs", {
        "log_files": log_files,
        "bucket_minutes": body.get("bucket_minutes", 5),
        "high_error_threshold": body.get("high_error_threshold", 0.20),
        "max_samples": body.get("max_samples", 50),
        "hour_min": body.get("hour_min"),
        "hour_max": body.get("hour_max"),
        "time_start": body.get("time_start"),
        "time_end": body.get("time_end"),
        "prompt": body.get("prompt"),
        "prompt_threshold": body.get("prompt_threshold"),
    })
    if result is None:
        return jsonify({"error": "No response"}), 500
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/api/search", methods=["POST"])
def api_search():
    body = request.json or {}
    prompt = body.get("prompt", "")
    if not prompt.strip():
        return jsonify({"error": "prompt is required"}), 400
    log_files = session.config.get("log_files", [])
    result = session.call_tool("search_logs_tool", {
        "prompt": prompt,
        "log_files": log_files,
        "max_matches": body.get("max_matches", 50),
        "context_lines": body.get("context_lines", 2),
        "hour_min": body.get("hour_min"),
        "hour_max": body.get("hour_max"),
        "time_start": body.get("time_start"),
        "time_end": body.get("time_end"),
        "prompt_threshold": body.get("prompt_threshold"),
    })
    if result is None:
        return jsonify({"error": "No response"}), 500
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/api/semantic_analyze", methods=["POST"])
def api_semantic_analyze():
    body = request.json or {}
    prompt = body.get("prompt", "")
    if not prompt.strip():
        return jsonify({"error": "prompt is required"}), 400
    log_files = session.config.get("log_files", [])
    result = session.call_tool("semantic_analysis", {
        "prompt": prompt,
        "log_files": log_files,
        "max_clusters": body.get("max_clusters", 20),
        "prompt_threshold": body.get("prompt_threshold"),
        "hour_min": body.get("hour_min"),
        "hour_max": body.get("hour_max"),
        "time_start": body.get("time_start"),
        "time_end": body.get("time_end"),
    })
    if result is None:
        return jsonify({"error": "No response"}), 500
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/api/reset_cache", methods=["POST"])
def api_reset_cache():
    result = session.call_tool("reset_file_cache", {})
    if result is None:
        return jsonify({"error": "No response"}), 500
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/api/explain", methods=["POST"])
def api_explain():
    body = request.json or {}
    error_line = body.get("error_line", "")
    if not error_line.strip():
        return jsonify({"error": "error_line is required"}), 400
    result = session.call_tool("explain_error", {
        "error_line": error_line,
    })
    if result is None:
        return jsonify({"error": "No response"}), 500
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    print(f"🌐  MCP Log Analyzer Web UI → http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=True)


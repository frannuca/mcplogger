#!/usr/bin/env python3
"""
Flask web frontend for the MCP Log Analyzer.

Manages an MCP server subprocess and exposes REST endpoints that the
browser-side JS calls. The browser never touches the MCP server directly.

Usage:
    uv run web/app.py                 # starts on http://localhost:5000
    uv run web/app.py --port 8888     # custom port
"""

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent          # mcplogger/
MAIN_PY = ROOT / "main.py"

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)

# ── MCP session state ─────────────────────────────────────────────────────────

class MCPSession:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._lock = threading.Lock()
        self.config: Dict = {}       # last applied config from the UI
        self.tools: List[Dict] = []  # from tools/list

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self, config: Dict) -> Dict:
        if self.running:
            return {"ok": False, "error": "Server already running"}

        self.config = config

        # Build env vars from the UI config
        env = {**__import__("os").environ}
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

        try:
            self.process = subprocess.Popen(
                [sys.executable, str(MAIN_PY)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
                cwd=str(ROOT),
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        # handshake
        resp = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "web-ui", "version": "1.0.0"},
        })
        if resp is None or "error" in resp:
            self.stop()
            return {"ok": False, "error": f"Handshake failed: {resp}"}

        self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # fetch tools
        tl = self._send("tools/list", {})
        if tl and "result" in tl:
            self.tools = tl["result"].get("tools", [])

        return {"ok": True, "pid": self.process.pid, "tools": len(self.tools)}

    def stop(self) -> Dict:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
        self.tools = []
        return {"ok": True}

    # ── tool calls ─────────────────────────────────────────────────────────

    def call_tool(self, name: str, arguments: Dict) -> Optional[Dict]:
        if not self.running:
            return {"error": "Server not running"}
        with self._lock:
            resp = self._send("tools/call", {"name": name, "arguments": arguments})
        if resp is None:
            return {"error": "No response from server"}
        if "error" in resp:
            return {"error": resp["error"]}

        result = resp.get("result", {})
        return self._extract_data(result)

    @staticmethod
    def _extract_data(result: Dict) -> Dict:
        """Unpack FastMCP's response wrapper to get the actual tool return value."""
        # FastMCP wraps structured tools as: { structuredContent: { result: {…} } }
        sc = result.get("structuredContent")
        if isinstance(sc, dict):
            inner = sc.get("result")
            if isinstance(inner, dict):
                return inner
            return sc

        # Fallback: unstructured tools put JSON in content[0].text
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":
                try:
                    return json.loads(first["text"])
                except (json.JSONDecodeError, KeyError):
                    pass

        return result

    # ── transport ──────────────────────────────────────────────────────────

    def _write(self, obj: Dict):
        self.process.stdin.write(json.dumps(obj) + "\n")
        self.process.stdin.flush()

    def _read(self) -> Optional[Dict]:
        line = self.process.stdout.readline()
        return json.loads(line) if line else None

    def _send(self, method: str, params: Dict) -> Optional[Dict]:
        self._req_id += 1
        self._write({"jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params})
        return self._read()


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


#!/usr/bin/env python3
"""
smart_ask.py — Natural-language MCP client.

The user types a plain English question.  An LLM reads the MCP tool
descriptions (from tools/list) and decides WHICH tool to call and with
WHAT arguments.  The result is printed to the terminal.

Usage:
    uv run smart_ask.py                       # uses LOG_FILES from .env
    uv run smart_ask.py test_app.log          # explicit log files

Flow:
    ┌────────────────────────┐
    │  user types question   │
    └───────────┬────────────┘
                │
                ▼
    ┌────────────────────────┐
    │  LLM receives:         │
    │   - the question        │
    │   - tool descriptions   │    ← from tools/list
    │   - parameter schemas   │
    │                        │
    │  LLM responds with a   │
    │  tool_call JSON:       │
    │   { name, arguments }  │
    └───────────┬────────────┘
                │
                ▼
    ┌────────────────────────┐
    │  smart_ask sends       │
    │  tools/call to the     │    ← MCP JSON-RPC over stdio
    │  MCP server            │
    └───────────┬────────────┘
                │
                ▼
    ┌────────────────────────┐
    │  print result          │
    └────────────────────────┘
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ── configuration ─────────────────────────────────────────────────────────────

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY  = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "local"
LLM_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# ── MCP session (start server, handshake, call tools) ─────────────────────────

class MCPSession:
    """Manages the MCP server subprocess and JSON-RPC communication (stdio)."""

    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self._req_id = 0
        self.tools: List[Dict] = []            # raw tool defs from tools/list
        self.tools_for_llm: List[Dict] = []    # OpenAI function-calling format

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> bool:
        script = Path(__file__).parent / "main.py"
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            print(f"✗ Could not start server: {exc}")
            return False

        if not self._handshake():
            return False
        return self._fetch_tools()

    def stop(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    # ── MCP protocol ──────────────────────────────────────────────────────

    def _handshake(self) -> bool:
        resp = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smart-ask", "version": "1.0.0"},
        })
        if resp is None or "error" in resp:
            print(f"✗ Handshake failed: {resp}")
            return False
        self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return True

    def _fetch_tools(self) -> bool:
        """Call tools/list and convert to OpenAI function-calling format."""
        resp = self._send("tools/list", {})
        if resp is None or "error" in resp:
            print(f"✗ Could not fetch tools: {resp}")
            return False

        self.tools = resp["result"]["tools"]
        self.tools_for_llm = []
        for t in self.tools:
            self.tools_for_llm.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {}),
                },
            })
        return True

    def call_tool(self, name: str, arguments: Dict) -> Optional[Dict]:
        resp = self._send("tools/call", {"name": name, "arguments": arguments})
        if resp is None:
            return None
        if "error" in resp:
            return {"error": resp["error"]}
        return resp.get("result")

    # ── transport ──────────────────────────────────────────────────────────

    def _write(self, obj: Dict) -> None:
        self.process.stdin.write(json.dumps(obj) + "\n")
        self.process.stdin.flush()

    def _read(self) -> Optional[Dict]:
        line = self.process.stdout.readline()
        return json.loads(line) if line else None

    def _send(self, method: str, params: Dict) -> Optional[Dict]:
        self._req_id += 1
        self._write({
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params,
        })
        return self._read()


# ── HTTP service session ──────────────────────────────────────────────────────

class MCPHttpSession:
    """MCP session backed by the FastMCP HTTP service.

    Thread-safe: each call_tool() invocation creates an independent
    HTTP connection, so multiple threads can call tools concurrently.
    """

    def __init__(self, service_url: str) -> None:
        from server.http_client import MCPHttpClient
        self._client = MCPHttpClient(service_url)
        self.tools: List[Dict] = []
        self.tools_for_llm: List[Dict] = []

    def start(self) -> bool:
        try:
            raw_tools = self._client.list_tools()
        except ConnectionError as exc:
            print(f"✗ Could not connect to HTTP service: {exc}")
            return False
        self.tools = raw_tools
        self.tools_for_llm = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {}),
                },
            }
            for t in raw_tools
        ]
        return True

    def stop(self) -> None:
        pass  # HTTP service manages its own lifecycle

    def call_tool(self, name: str, arguments: Dict) -> Optional[Dict]:
        try:
            result = self._client.call_tool(name, arguments)
            # Wrap in structuredContent so print_result() works identically
            return {"structuredContent": {"result": result}}
        except (RuntimeError, ConnectionError) as exc:
            return {"error": str(exc)}


# ── LLM tool selection ────────────────────────────────────────────────────────

def ask_llm_to_pick_tool(
    question: str,
    tools_for_llm: List[Dict],
    log_files: List[str],
) -> Optional[Dict]:
    """
    Send the user's question + tool descriptions to the LLM.
    The LLM responds with a tool_call: { name, arguments }.
    """
    system_prompt = (
        "You are a log analysis assistant.  The user will ask a question about "
        "their log files.  You have access to MCP tools described below.\n\n"
        "RULES:\n"
        "1. ALWAYS respond with exactly one tool_call — never answer directly.\n"
        "2. Choose the tool whose description best matches the question.\n"
        "3. For search_logs_tool, pass the user's question as the 'prompt' argument.\n"
        f"4. Unless the user specifies files, use: {json.dumps(log_files)}\n"
    )

    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": question},
        ],
        "tools": tools_for_llm,
        "tool_choice": "required",     # force a tool call, never plain text
        "temperature": 0.0,
        "max_tokens": 512,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"✗ LLM request failed: {exc}")
        return None

    data = resp.json()
    choice = data["choices"][0]
    message = choice.get("message", {})

    # ── extract tool_call ──
    tool_calls = message.get("tool_calls")
    if not tool_calls:
        # some models return a plain text response even with tool_choice=required
        print(f"⚠  LLM did not return a tool call.  Response:\n{message.get('content','')}")
        return None

    tc = tool_calls[0]["function"]
    name = tc["name"]
    try:
        arguments = json.loads(tc["arguments"]) if isinstance(tc["arguments"], str) else tc["arguments"]
    except json.JSONDecodeError:
        print(f"✗ Could not parse tool arguments: {tc['arguments']}")
        return None

    return {"name": name, "arguments": arguments}


# ── pretty printing ──────────────────────────────────────────────────────────

def _wrap(text: str, width: int = 100) -> str:
    return "\n".join(
        textwrap.fill(line, width=width) if line.strip() else line
        for line in text.splitlines()
    )


def print_result(tool_name: str, result: Dict) -> None:
    if result is None:
        print("  ✗ No response from server.")
        return
    if "error" in result:
        print(f"  ❌ Error: {result['error']}")
        return

    # structuredContent is the tool return value wrapped by FastMCP
    data0 = result.get("structuredContent", result)
    data = data0.get("result", data0)
    print(f"\n{'─'*70}")

    if tool_name == "analyze_logs":
        total  = data.get("total_matches", 0)
        errors = data.get("error_lines", 0)
        rate   = data.get("error_rate", 0) * 100
        print(f"📊  ANALYSIS — {total:,} lines, {errors:,} errors ({rate:.1f}%)")
        patterns = data.get("pattern_counts", {})
        if patterns:
            for name, count in sorted(patterns.items(), key=lambda x: -x[1])[:8]:
                print(f"    [{count:>4}x]  {name}")

    elif tool_name == "search_logs_tool":
        mode  = data.get("search_mode", "regex")
        total = data.get("total_matches", 0)
        print(f"🔍  SEARCH ({mode}) — {total} match(es)")
        for i, m in enumerate(data.get("matches", [])[:10], 1):
            score = m.get("similarity")
            score_s = f"  sim={score:.3f}" if score is not None else ""
            print(f"    [{i:>3}] {m['file']}:{m['line_number']}{score_s}")
            print(f"          {m['line'][:90]}")

    elif tool_name == "reset_file_cache":
        print(f"🔄  Cache reset: {data.get('reset')}")

    summary = data.get("human_summary", "")
    if summary:
        print(f"\n🤖  AI Summary:\n")
        print(_wrap(summary))

    print(f"{'─'*70}")


# ── REPL ──────────────────────────────────────────────────────────────────────

HELP = """
Commands
────────
  <any question>    LLM picks the right tool and calls it
  tools             show available MCP tools
  help              show this help
  quit / exit       quit

Examples
────────
  "give me a health check of the logs"        → analyze_logs
  "what percentage of lines are errors?"       → analyze_logs
  "show me database timeout errors"            → search_logs_tool
  "why is the payment service returning 500?"  → search_logs_tool
  "re-read the log files from scratch"         → reset_file_cache
"""


def repl(session: MCPSession, log_files: List[str]) -> None:
    print(f"\n✅  Server ready — {len(session.tools)} tool(s) loaded.")
    print(f"    Log files: {', '.join(log_files)}")
    print("    Type any question in plain English, or 'help'.\n")

    while True:
        try:
            raw = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not raw:
            continue
        cmd = raw.lower()
        if cmd in ("quit", "exit", "q"):
            print("Bye!")
            break
        if cmd == "help":
            print(HELP)
            continue
        if cmd == "tools":
            for t in session.tools:
                desc_first_line = (t.get("description") or "").strip().split("\n")[0]
                print(f"  • {t['name']:25s}  {desc_first_line}")
            continue

        # ── ask LLM to pick a tool ──
        print(f"  🧠 Asking LLM which tool to use …")
        decision = ask_llm_to_pick_tool(raw, session.tools_for_llm, log_files)
        if decision is None:
            continue

        tool_name = decision["name"]
        tool_args = decision["arguments"]
        print(f"  🔧 LLM chose: {tool_name}({json.dumps(tool_args, indent=2)})")

        # ── call the MCP tool ──
        print(f"  ⏳ Calling MCP tool …")
        result = session.call_tool(tool_name, tool_args)
        print_result(tool_name, result)


# ── entry point ──────────────────────────────────────────────────────────────

def resolve_log_files(argv_files: List[str]) -> List[str]:
    if argv_files:
        return argv_files
    raw = os.getenv("LOG_FILES", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Natural-language MCP log analyzer (LLM-powered tool selection)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "log_files",
        nargs="*",
        metavar="LOG_FILE",
        help="Log files to watch (falls back to LOG_FILES env var if omitted)",
    )
    parser.add_argument(
        "--service-url",
        metavar="URL",
        default=None,
        help=(
            "Connect to a running FastMCP HTTP service instead of spawning a "
            "stdio subprocess.  Example: http://127.0.0.1:8000  "
            "Start the service with: python server/service.py"
        ),
    )
    args = parser.parse_args()

    log_files = resolve_log_files(args.log_files)
    if not log_files:
        print("⚠️  No log files.  Pass as args or set LOG_FILES in .env")
        sys.exit(1)
    missing = [f for f in log_files if not Path(f).exists()]
    if missing:
        print(f"⚠️  Not found: {', '.join(missing)}")
        sys.exit(1)

    if args.service_url:
        session = MCPHttpSession(args.service_url)
        print(f"🌐  Connecting to HTTP service: {args.service_url} …")
    else:
        session = MCPSession()
        print("🚀  Starting MCP server …")

    if not session.start():
        sys.exit(1)
    try:
        repl(session, log_files)
    finally:
        session.stop()
        if not args.service_url:
            print("🛑  Server stopped.")


if __name__ == "__main__":
    main()


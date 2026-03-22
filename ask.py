#!/usr/bin/env python3
"""
Interactive log query REPL.

Usage:
    python ask.py                          # uses LOG_FILES from .env
    python ask.py app.log worker.log       # explicit log files

Commands at the prompt:
    <any question>   → search logs for that problem
    analyze          → full error/timeout/exception analysis + AI summary
    files            → show which log files are loaded
    help             → print this help
    quit / exit      → stop
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from constants import DEFAULT_CONTEXT_LINES, DEFAULT_MAX_MATCHES

# ── resolve log files ────────────────────────────────────────────────────────

def resolve_log_files(argv_files: List[str]) -> List[str]:
    if argv_files:
        return argv_files
    # fall back to LOG_FILES env var (same logic as config.py)
    from dotenv import load_dotenv
    load_dotenv()
    raw = os.getenv("LOG_FILES", "")
    files = [p.strip() for p in raw.split(",") if p.strip()]
    return files


# ── low-level MCP client ─────────────────────────────────────────────────────

class MCPSession:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self._req_id = 0

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
        except Exception as e:
            print(f"✗ Could not start server: {e}")
            return False

        return self._handshake()

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    # ── MCP handshake ──────────────────────────────────────────────────────

    def _handshake(self) -> bool:
        resp = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ask-repl", "version": "1.0.0"},
        })
        if resp is None or "error" in resp:
            print(f"✗ Handshake failed: {resp}")
            return False
        # send notifications/initialized — no id (fire-and-forget notification)
        self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return True

    # ── transport ──────────────────────────────────────────────────────────

    def _write(self, obj: Dict):
        self.process.stdin.write(json.dumps(obj) + "\n")
        self.process.stdin.flush()

    def _read(self) -> Optional[Dict]:
        line = self.process.stdout.readline()
        if not line:
            return None
        return json.loads(line)

    def _send(self, method: str, params: Dict) -> Optional[Dict]:
        self._req_id += 1
        self._write({"jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params})
        return self._read()

    # ── tool calls ─────────────────────────────────────────────────────────

    def call_tool(self, name: str, arguments: Dict) -> Optional[Dict]:
        resp = self._send("tools/call", {"name": name, "arguments": arguments})
        if resp is None:
            return None
        if "error" in resp:
            return {"error": resp["error"]}
        return resp.get("result")

    def analyze(self, log_files: List[str]) -> Optional[Dict]:
        return self.call_tool("analyze_logs", {
            "log_files": log_files,
            "bucket_minutes": 5,
            "high_error_threshold": 0.20,
            "max_samples": 30,
        })

    def search(self, prompt: str, log_files: List[str], max_matches: int = DEFAULT_MAX_MATCHES) -> Optional[Dict]:
        return self.call_tool("search_logs_tool", {
            "prompt": prompt,
            "log_files": log_files,
            "max_matches": max_matches,
            "context_lines": DEFAULT_CONTEXT_LINES,
        })


# ── pretty printing ──────────────────────────────────────────────────────────

def _wrap(text: str, width: int = 100) -> str:
    return "\n".join(
        textwrap.fill(line, width=width) if line.strip() else line
        for line in text.splitlines()
    )


def print_analysis(result: Dict):
    if "error" in result:
        print(f"\n❌  {result['error']}")
        return
    if "structuredContent" not in result:
        print(f"\n❌  Unexpected response: {result}")
        return

    data = result["structuredContent"]   # tool returns dict directly

    print(f"\n{'─'*70}")
    print(f"📊  ANALYSIS SUMMARY")
    print(f"{'─'*70}")

    total    = data.get("total_lines", 0)
    errors   = data.get("error_lines", 0)
    rate     = data.get("error_rate", 0) * 100   # stored as 0-1 fraction
    files    = data.get("log_files", [])
    buffered = data.get("lines_buffered", {})
    mode     = data.get("search_mode", "")

    print(f"  Files     : {', '.join(files) or '(none)'}")
    if buffered:
        for f, n in buffered.items():
            print(f"  Buffered  : {f}  →  {n:,} lines")
    print(f"  Lines     : {total:,}  |  Error lines: {errors:,}  ({rate:.1f}%)")
    if mode:
        print(f"  Mode      : {mode}")

    patterns = data.get("pattern_counts", {})
    if patterns:
        print(f"\n  Top error patterns:")
        for name, count in sorted(patterns.items(), key=lambda x: -x[1])[:8]:
            print(f"    [{count:>4}x]  {name}")

    windows = data.get("high_error_windows", [])
    if windows:
        print(f"\n  High-error windows:")
        for w in windows[:5]:
            print(f"    {w['window_start']}  {w['errors']}/{w['total']}  ({w['error_rate']*100:.1f}%)")

    summary = data.get("human_summary", "")
    if summary:
        print(f"\n🤖  AI Summary:\n")
        print(_wrap(summary))

    print(f"{'─'*70}")


def print_search(result: Dict, prompt: str):
    if "error" in result or "structuredContent" not in result:
        print(f"\n❌  {result}")
        return

    data    = result['structuredContent']['result']  # tool returns dict directly
    matches = data.get("matches", [])
    total   = data.get("total_matches", len(matches))
    mode    = data.get("search_mode", "regex")
    explanation = data.get("human_summary", "")

    print(f"\n{'─'*70}")
    print(f"🔍  SEARCH ({mode}): \"{prompt}\"  —  {total} match(es) found")
    print(f"{'─'*70}")

    for i, m in enumerate(matches, 1):
        file_  = m.get("file", "")
        lineno = m.get("line_number", "?")
        text   = m.get("line", "").rstrip()
        ctx    = m.get("context", "")
        score  = m.get("similarity")

        score_str = f"  sim={score:.3f}" if score is not None else ""
        print(f"  [{i:>3}] {file_}:{lineno}{score_str}")
        if ctx:
            for ctx_line in ctx.splitlines():
                print(f"         {ctx_line}")
        else:
            print(f"       ▶ {text}")

    if explanation:
        print(f"\n🤖  AI Explanation:\n")
        print(_wrap(explanation))
        print()

    if not matches:
        print("  (no matching lines found)")

    print(f"{'─'*70}")


# ── REPL ─────────────────────────────────────────────────────────────────────

HELP = """
Commands
────────
  <question>    search logs  e.g. "database timeout"  "NullPointerException"
  analyze       full error / timeout / exception analysis + AI summary
  files         show which log files are loaded
  help          show this help
  quit / exit   quit
"""


def repl(session: MCPSession, log_files: List[str]):
    print(f"\n✅  Server ready. Watching: {', '.join(log_files) or '(none)'}")
    print("    Type a question, 'analyze', or 'help'.\n")

    while True:
        try:
            raw = input("ask> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not raw:
            continue

        cmd = raw.lower()

        if cmd in ("quit", "exit", "q"):
            print("Bye!")
            break

        elif cmd == "help":
            print(HELP)

        elif cmd == "files":
            print(f"  Log files: {', '.join(log_files) or '(none set)'}")

        elif cmd == "analyze":
            print("  ⏳ Analyzing logs …")
            result = session.analyze(log_files)
            if result is None:
                print("  ✗ No response from server.")
            else:
                print_analysis(result)

        else:
            # treat anything else as a search prompt
            print(f"  ⏳ Searching for \"{raw}\" …")
            result = session.search(raw, log_files)
            if result is None:
                print("  ✗ No response from server.")
            else:
                print_search(result, raw)


# ── entry point ──────────────────────────────────────────────────────────────

def main():
    log_files = resolve_log_files(sys.argv[1:])

    if not log_files:
        print("⚠️  No log files specified.")
        print("   Pass them as arguments:  python ask.py app.log worker.log")
        print("   Or set LOG_FILES=app.log,worker.log in your .env file")
        sys.exit(1)

    # verify files exist
    missing = [f for f in log_files if not Path(f).exists()]
    if missing:
        print(f"⚠️  File(s) not found: {', '.join(missing)}")
        sys.exit(1)

    session = MCPSession()
    print("🚀  Starting MCP log-analyzer server …")
    if not session.start():
        print("✗  Could not start server.")
        sys.exit(1)

    try:
        repl(session, log_files)
    finally:
        session.stop()
        print("🛑  Server stopped.")


if __name__ == "__main__":
    main()


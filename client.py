#!/usr/bin/env python3
"""
MCP Log Analyzer Client
Connects to the MCP server and sends tool calls.
"""

import json
import subprocess
import sys
from typing import Any, Dict

from constants import DEFAULT_MAX_MATCHES, DEFAULT_CONTEXT_LINES


class MCPClient:
    def __init__(self):
        self.process = None
        self.request_id = 0

    def start_server(self):
        """Start the MCP server process and perform the MCP initialization handshake."""
        print("🚀 Starting MCP server...")
        try:
            self.process = subprocess.Popen(
                [sys.executable, "main.py"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            print("✓ Server started (PID: {})".format(self.process.pid))
        except Exception as e:
            print(f"✗ Failed to start server: {e}")
            return False

        # --- MCP handshake (required before any tool call) ---
        # Step 1: send initialize request
        self.request_id += 1
        init_request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp-log-client", "version": "1.0.0"},
            },
        }
        try:
            self.process.stdin.write(json.dumps(init_request) + "\n")
            self.process.stdin.flush()
            response_line = self.process.stdout.readline()
            if not response_line:
                print("✗ No response to initialize from server")
                return False
            init_response = json.loads(response_line)
            if "error" in init_response:
                print(f"✗ Initialize failed: {init_response['error']}")
                return False
            proto = init_response.get("result", {}).get("protocolVersion", "?")
            print(f"✓ MCP handshake complete (protocol {proto})")
        except Exception as e:
            print(f"✗ Handshake error: {e}")
            return False

        # Step 2: send notifications/initialized (notification = no id field)
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        try:
            self.process.stdin.write(json.dumps(notif) + "\n")
            self.process.stdin.flush()
        except Exception as e:
            print(f"✗ Could not send initialized notification: {e}")
            return False

        return True

    def send_request(self, method: str, params: Dict[str, Any]) -> Dict:
        """Send a JSON-RPC request to the server and get response."""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params,
        }

        request_json = json.dumps(request)
        print(f"\n📤 Sending request (ID: {self.request_id}):")
        print(f"   Method: {method}")
        print(f"   Params: {json.dumps(params, indent=2)}")

        try:
            self.process.stdin.write(request_json + "\n")
            self.process.stdin.flush()

            # Read response
            response_line = self.process.stdout.readline()
            if not response_line:
                print("✗ No response from server")
                return {}

            response = json.loads(response_line)
            return response
        except Exception as e:
            print(f"✗ Communication error: {e}")
            return {}

    def analyze_logs(self, log_files=None, bucket_minutes=5, high_error_threshold=0.20):
        """Call the analyze_logs tool."""
        response = self.send_request(
            "tools/call",
            {
                "name": "analyze_logs",
                "arguments": {
                    "log_files": log_files,
                    "bucket_minutes": bucket_minutes,
                    "high_error_threshold": high_error_threshold,
                    "max_samples": 10,
                },
            },
        )
        return response

    def search_logs(self, prompt: str, log_files=None, max_matches=DEFAULT_MAX_MATCHES):
        """Call the search_logs_tool with a question/prompt."""
        response = self.send_request(
            "tools/call",
            {
                "name": "search_logs_tool",
                "arguments": {
                    "prompt": prompt,
                    "log_files": log_files,
                    "max_matches": max_matches,
                    "context_lines": DEFAULT_CONTEXT_LINES,
                },
            },
        )
        return response

    def stop_server(self):
        """Terminate the server process."""
        if self.process:
            print("\n🛑 Stopping server...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            print("✓ Server stopped")


def print_response(response: Dict):
    """Pretty-print a response."""
    if "error" in response:
        print(f"\n❌ Error: {response['error']}")
        return

    if "result" in response:
        result = response["result"]
        print(f"\n✅ Response received:")
        print(json.dumps(result, indent=2))
    else:
        print(f"\n📋 Full response:")
        print(json.dumps(response, indent=2))


def main():
    client = MCPClient()

    if not client.start_server():
        return

    try:
        # Example 1: Analyze logs for general patterns
        print("\n" + "="*70)
        print("EXAMPLE 1: Analyze logs for errors, timeouts, exceptions")
        print("="*70)
        response = client.analyze_logs(
            log_files=["test_app.log"],
            bucket_minutes=5,
            high_error_threshold=0.20,
        )
        print_response(response)

        # Example 2: Search for specific problem - database issues
        print("\n" + "="*70)
        print("EXAMPLE 2: Search for database connection issues")
        print("="*70)
        response = client.search_logs(
            prompt="database connection timeout",
            log_files=["test_app.log"],
            max_matches=10,
        )
        print_response(response)

        # Example 3: Search for authentication problems
        print("\n" + "="*70)
        print("EXAMPLE 3: Search for authentication failures")
        print("="*70)
        response = client.search_logs(
            prompt="authentication jwt token invalid",
            log_files=["test_app.log"],
            max_matches=10,
        )
        print_response(response)

        # Example 4: Search for service availability issues
        print("\n" + "="*70)
        print("EXAMPLE 4: Search for service unavailability (5xx errors)")
        print("="*70)
        response = client.search_logs(
            prompt="service unavailable 503 504 gateway timeout",
            log_files=["test_app.log"],
            max_matches=10,
        )
        print_response(response)

    finally:
        client.stop_server()


if __name__ == "__main__":
    main()


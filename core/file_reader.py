"""
file_reader.py – live tail reader that tracks byte offsets per file.

Each call to read_lines() returns ALL lines seen so far (buffered) plus
any lines appended to the file since the previous call.  This lets the
MCP tools stay up-to-date without re-scanning the whole file every time.

All diagnostic output goes to stderr so it never pollutes the JSON-RPC
stdout channel used by the MCP server.
"""

import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional


class LiveFileReader:
    """
    Tracks the read position (byte offset) for each log file.

    Thread-safe: a single shared instance is used by all tool calls.
    """

    def __init__(self):
        self._offsets: Dict[str, int] = {}       # path -> last byte offset
        self._buffers: Dict[str, List[str]] = {}  # path -> accumulated lines (no newlines)
        self._lock = threading.Lock()

    # ── public API ──────────────────────────────────────────────────────────

    def read_lines(self, path: Path) -> List[str]:
        """
        Return every line seen so far for *path*, including any new lines
        appended since the last call.  Lines are returned without trailing
        newlines or carriage returns.
        """
        key = str(path.resolve())

        with self._lock:
            if key not in self._buffers:
                self._buffers[key] = []
                self._offsets[key] = 0

            if not path.exists() or not path.is_file():
                _warn(f"File not found: {path}")
                return list(self._buffers[key])

            # Detect truncation / log-rotation (file shrank)
            file_size = path.stat().st_size
            if file_size < self._offsets[key]:
                _warn(f"{path.name}: file shrank (rotated?) – re-reading from start")
                self._buffers[key] = []
                self._offsets[key] = 0

            new_lines: List[str] = []
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as fh:
                    fh.seek(self._offsets[key])
                    chunk = fh.readlines()
                    self._offsets[key] = fh.tell()
                new_lines = [ln.rstrip("\r\n") for ln in chunk]
            except OSError as exc:
                _warn(f"Could not read {path}: {exc}")
                return list(self._buffers[key])

            if new_lines:
                self._buffers[key].extend(new_lines)
                _info(
                    f"{path.name}: +{len(new_lines)} new line(s) "
                    f"(total buffered: {len(self._buffers[key])})"
                )

            return list(self._buffers[key])

    def buffered_count(self, path: Path) -> int:
        """Return how many lines are currently buffered for *path*."""
        key = str(path.resolve())
        with self._lock:
            return len(self._buffers.get(key, []))

    def reset(self, path: Optional[Path] = None):
        """
        Drop buffered lines and reset the offset.

        Pass a specific *path* to reset only that file, or call with no
        argument to reset all files (e.g. after log rotation).
        """
        with self._lock:
            if path is not None:
                key = str(path.resolve())
                self._offsets.pop(key, None)
                self._buffers.pop(key, None)
            else:
                self._offsets.clear()
                self._buffers.clear()


# ── singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[LiveFileReader] = None
_instance_lock = threading.Lock()


def get_reader() -> LiveFileReader:
    """
    Return the process-wide singleton LiveFileReader.

    Use this anywhere you need the reader:
        from file_reader import get_reader
        reader = get_reader()
        lines = reader.read_lines(path)
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:           # double-checked locking
                _instance = LiveFileReader()
    return _instance


# Convenience alias — ``from file_reader import reader`` still works
reader: LiveFileReader = None  # type: ignore[assignment]


def __getattr__(name: str):
    """Module-level __getattr__ so `from file_reader import reader` is lazy."""
    if name == "reader":
        return get_reader()
    raise AttributeError(f"module 'file_reader' has no attribute {name!r}")



# ── helpers ───────────────────────────────────────────────────────────────────

def _info(msg: str):
    print(f"[file_reader] {msg}", file=sys.stderr, flush=True)


def _warn(msg: str):
    print(f"[file_reader] WARNING {msg}", file=sys.stderr, flush=True)


"""
time_filter.py — Extract time windows from natural-language prompts and
filter log lines by timestamp.

Supported phrases (case-insensitive):
    "last 10 minutes"   "past 2 hours"   "last 30 seconds"
    "last 1 day"        "last 3h"        "last 45m"
    "past 30s"          "last 1d"        "since 10 minutes ago"

If no time reference is found the full line set is returned unchanged.
"""

import re
import sys
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from core.patterns import TS_FORMATS, TS_PATTERNS

# ── prompt parsing ────────────────────────────────────────────────────────────

# Matches:  "last 10 minutes", "past 2 hours", "last 30s", "since 5m ago"
_TIME_RE = re.compile(
    r"(?:last|past|since|within|recent)\s+"
    r"(\d+)\s*"
    r"(s|sec|secs|seconds?|m|min|mins|minutes?|h|hrs?|hours?|d|days?)\b",
    re.IGNORECASE,
)

_UNIT_MAP = {
    "s": "seconds", "sec": "seconds", "secs": "seconds", "second": "seconds", "seconds": "seconds",
    "m": "minutes", "min": "minutes", "mins": "minutes", "minute": "minutes", "minutes": "minutes",
    "h": "hours",   "hr": "hours",    "hrs": "hours",    "hour": "hours",     "hours": "hours",
    "d": "days",    "day": "days",    "days": "days",
}


def parse_time_window(prompt: str) -> Optional[timedelta]:
    """
    Extract a time window from a natural-language prompt.

    Returns a timedelta if found, or None if there's no time reference.

    >>> parse_time_window("show me database errors from the last 10 minutes")
    datetime.timedelta(seconds=600)
    >>> parse_time_window("what are the timeout issues") is None
    True
    """
    match = _TIME_RE.search(prompt)
    if not match:
        return None

    amount = int(match.group(1))
    unit_raw = match.group(2).lower()
    unit = _UNIT_MAP.get(unit_raw)
    if not unit or amount <= 0:
        return None

    delta = timedelta(**{unit: amount})
    _log(f"Parsed time window from prompt: last {amount} {unit} → {delta}")
    return delta


def strip_time_phrase(prompt: str) -> str:
    """
    Remove the time-window phrase from the prompt so it doesn't pollute
    keyword extraction.

    >>> strip_time_phrase("database errors for the last 10 minutes")
    'database errors for the'
    """
    # also strip trailing "ago" and leading "for the" / "from the" / "in the"
    cleaned = _TIME_RE.sub("", prompt)
    cleaned = re.sub(r"\b(for|from|in|within|of)\s+the\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bago\b", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


# ── line filtering ────────────────────────────────────────────────────────────

def _parse_line_ts(line: str) -> Optional[datetime]:
    """Try to extract a datetime from the beginning of a log line."""
    for pat in TS_PATTERNS:
        m = pat.search(line)
        if m:
            ts_str = m.group("ts")
            for fmt in TS_FORMATS:
                try:
                    return datetime.strptime(ts_str, fmt)
                except ValueError:
                    continue
    return None


def filter_lines_by_time(
    lines: List[str],
    window: timedelta,
    now: Optional[datetime] = None,
) -> Tuple[List[Tuple[int, str]], datetime]:
    """
    Return only lines whose timestamp falls within ``[now - window, now]``.

    Returns a list of ``(original_index, line_text)`` tuples so callers
    can still reference the correct line numbers.

    If *now* is None, the timestamp of the **last parseable line** in the
    file is used as "now" — this handles log files whose timestamps are in
    the past or future relative to wall-clock time.
    """
    if now is None:
        # scan backwards for the latest timestamp
        for line in reversed(lines):
            ts = _parse_line_ts(line)
            if ts:
                now = ts
                break
        if now is None:
            # no timestamps found at all — return everything
            _log("No timestamps found in log lines; returning all lines")
            return [(i, l) for i, l in enumerate(lines)], datetime.now()

    cutoff = now - window
    _log(f"Time window: {cutoff} → {now}  (last {window})")

    result: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines):
        ts = _parse_line_ts(line)
        if ts is not None:
            if cutoff <= ts <= now:
                result.append((idx, line))
        # Lines with no parseable timestamp that sit between timestamped lines
        # within the window are included (e.g. stack trace continuation lines)
        elif result and (idx - result[-1][0]) <= 5:
            result.append((idx, line))

    _log(f"Time filter: {len(result)} / {len(lines)} lines in window")
    return result, now


def _log(msg: str) -> None:
    print(f"[time_filter] {msg}", file=sys.stderr, flush=True)


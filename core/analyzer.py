from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config import Config
from core.file_reader import get_reader
from core.patterns import ERROR_PATTERNS, TS_FORMATS, TS_PATTERNS


class LogAnalyzer:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def _parse_timestamp(self, line: str) -> Optional[datetime]:
        for pattern in TS_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            raw_ts = match.group("ts")
            for fmt in TS_FORMATS:
                try:
                    return datetime.strptime(raw_ts, fmt)
                except ValueError:
                    continue
        return None

    def _tag_line(self, line: str) -> List[str]:
        return [name for name, pattern in ERROR_PATTERNS.items() if pattern.search(line)]

    def analyze(self) -> Dict:
        totals = {"lines": 0, "error_lines": 0}
        pattern_counts: Counter = Counter()
        sample_lines: List[str] = []
        bucket_stats = defaultdict(lambda: {"total": 0, "errors": 0})
        missing_files: List[str] = []

        _reader = get_reader()
        for path in self.cfg.log_files:
            if not path.exists() or not path.is_file():
                missing_files.append(str(path))
                continue

            for clean in _reader.read_lines(path):
                totals["lines"] += 1

                ts = self._parse_timestamp(clean)
                if ts:
                    bucket = ts.replace(second=0, microsecond=0)
                    bucket = bucket - timedelta(minutes=bucket.minute % self.cfg.bucket_minutes)
                    bucket_stats[bucket]["total"] += 1

                tags = self._tag_line(clean)
                if tags:
                    totals["error_lines"] += 1
                    pattern_counts.update(tags)
                    if len(sample_lines) < self.cfg.max_samples:
                        sample_lines.append(clean[:500])
                    if ts:
                        bucket_stats[bucket]["errors"] += 1

        error_rate = (totals["error_lines"] / totals["lines"]) if totals["lines"] else 0.0

        high_error_windows = []
        for bucket, stats in sorted(bucket_stats.items(), key=lambda item: item[0]):
            if stats["total"] == 0:
                continue
            rate = stats["errors"] / stats["total"]
            if rate >= self.cfg.high_error_threshold:
                high_error_windows.append(
                    {
                        "window_start": bucket.isoformat(sep=" "),
                        "window_minutes": self.cfg.bucket_minutes,
                        "total": stats["total"],
                        "errors": stats["errors"],
                        "error_rate": round(rate, 4),
                    }
                )

        return {
            "log_files": [str(p) for p in self.cfg.log_files],
            "lines_buffered": {str(p): get_reader().buffered_count(p) for p in self.cfg.log_files},
            "missing_files": missing_files,
            "total_lines": totals["lines"],
            "error_lines": totals["error_lines"],
            "error_rate": round(error_rate, 4),
            "pattern_counts": dict(pattern_counts.most_common()),
            "high_error_windows": high_error_windows,
            "sample_error_lines": sample_lines,
        }


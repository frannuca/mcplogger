import re

ERROR_PATTERNS = {
    "error": re.compile(r"\berror\b", re.IGNORECASE),
    "timeout": re.compile(r"\btime\s*out\b|\btimeout\b|\btimed\s*out\b", re.IGNORECASE),
    "exception": re.compile(r"\bexception\b|\btraceback\b", re.IGNORECASE),
    "critical": re.compile(r"\bcritical\b|\bfatal\b", re.IGNORECASE),
    "http_5xx": re.compile(r"\b5\d\d\b"),
}

TS_PATTERNS = [
    re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"),
    re.compile(r"(?P<ts>\d{4}/\d{2}/\d{2}[ T]\d{2}:\d{2}:\d{2})"),
]

TS_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%dT%H:%M:%S",
]


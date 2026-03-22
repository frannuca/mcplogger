# mcplogger package
# Import the mcp instance and tools to register them when the package is imported.
from .config import Config, build_config, parse_paths_from_env
from .analyzer import LogAnalyzer
from .summarizer import ChatGPTSummarizer
from .searcher import search_logs, keyword_regex_from_prompt
from .tools import mcp, analyze_logs, search_logs_tool

__all__ = [
    "Config",
    "build_config",
    "parse_paths_from_env",
    "LogAnalyzer",
    "ChatGPTSummarizer",
    "search_logs",
    "keyword_regex_from_prompt",
    "mcp",
    "analyze_logs",
    "search_logs_tool",
]

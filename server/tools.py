from typing import Dict, List, Optional

import requests
from mcp.server.fastmcp import FastMCP

from config import build_config
from config.constants import (
    DEFAULT_BUCKET_MINUTES,
    DEFAULT_CONTEXT_LINES,
    DEFAULT_HIGH_ERROR_THRESHOLD,
    DEFAULT_MAX_MATCHES,
    DEFAULT_MAX_SAMPLES,
)
from core.analyzer import LogAnalyzer
from core.file_reader import get_reader
from llm.summarizer import LLMSummarizer
from search.searcher import search_logs

mcp = FastMCP("log-analyzer")


@mcp.tool()
def analyze_logs(
    log_files: Optional[List[str]] = None,
    bucket_minutes: int = DEFAULT_BUCKET_MINUTES,
    high_error_threshold: float = DEFAULT_HIGH_ERROR_THRESHOLD,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    openai_model: Optional[str] = None,
) -> Dict:
    """Analyze log files for errors/timeouts/exceptions and produce stats + AI summary."""
    cfg = build_config(log_files, bucket_minutes, high_error_threshold, max_samples, openai_model)
    findings = LogAnalyzer(cfg).analyze()

    if cfg.llm_api_key:
        try:
            findings["human_summary"] = LLMSummarizer(
                api_key=cfg.llm_api_key,
                model=cfg.openai_model,
                base_url=cfg.llm_base_url,
            ).summarize_findings(findings)
        except requests.RequestException as exc:
            findings["human_summary"] = f"Summary API call failed: {exc}"
    else:
        findings["human_summary"] = "LLM_API_KEY / OPENAI_API_KEY not set; summary skipped."

    return findings


@mcp.tool()
def search_logs_tool(
    prompt: str,
    log_files: Optional[List[str]] = None,
    max_matches: int = DEFAULT_MAX_MATCHES,
    context_lines: int = DEFAULT_CONTEXT_LINES,
    openai_model: Optional[str] = None,
) -> Dict:
    """Search logs for prompt-specific problems and return contextual matches + AI explanation."""
    if not prompt.strip():
        raise ValueError("prompt is required")
    cfg = build_config(
        log_files,
        bucket_minutes=DEFAULT_BUCKET_MINUTES,
        high_error_threshold=DEFAULT_HIGH_ERROR_THRESHOLD,
        max_samples=10000,
        openai_model=openai_model,
    )
    return search_logs(
        cfg,
        prompt=prompt,
        max_matches=max(max_matches, 1),
        context_lines=max(context_lines, 0),
    )


@mcp.tool()
def reset_file_cache(log_files: Optional[List[str]] = None) -> Dict:
    """
    Drop the in-memory line buffer and reset byte offsets for the given log
    files (or all files if none specified).  Use this after a log rotation or
    when you want the next tool call to re-read from the beginning of the file.
    """
    if log_files:
        from pathlib import Path
        for f in log_files:
            get_reader().reset(Path(f))
        return {"reset": log_files, "status": "ok"}
    get_reader().reset()
    return {"reset": "all", "status": "ok"}


from typing import Annotated, Dict, List, Optional

import requests
from mcp.server.fastmcp import FastMCP
from pydantic import Field

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
    log_files: Annotated[
        Optional[List[str]],
        Field(description="List of log file paths to analyze. If omitted, uses LOG_FILES from .env."),
    ] = None,
    bucket_minutes: Annotated[
        int,
        Field(description="Time-window width in minutes for grouping error rates (default 5)."),
    ] = DEFAULT_BUCKET_MINUTES,
    high_error_threshold: Annotated[
        float,
        Field(description="Error rate (0.0–1.0) above which a time window is flagged as high-error. Default 0.20 = 20%."),
    ] = DEFAULT_HIGH_ERROR_THRESHOLD,
    max_samples: Annotated[
        int,
        Field(description="Maximum number of sample error lines to include in the output."),
    ] = DEFAULT_MAX_SAMPLES,
    openai_model: Annotated[
        Optional[str],
        Field(description="Override the LLM model name for the AI summary."),
    ] = None,
) -> Dict:
    """
    Scan log files and produce a full statistical report of all errors, timeouts, exceptions, and critical events.

    USE THIS TOOL WHEN the user asks for:
    - A general overview or health check of the logs
    - Error counts, error rates, or error percentages
    - Time-window analysis ("when did errors spike?")
    - Pattern breakdown ("what types of errors are there?")
    - Any broad quantitative question about the logs ("how many errors", "what percentage")

    DO NOT use this tool when the user asks about a specific problem — use search_logs_tool instead.

    Returns: total_lines, error_lines, error_rate, pattern_counts, high_error_windows, sample_error_lines, and an AI-generated human_summary.
    """
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
    prompt: Annotated[
        str,
        Field(description="Natural-language description of the problem to search for. "
        "Examples: 'database connection timeout', 'disk full', 'authentication failure JWT expired'."),
    ],
    log_files: Annotated[
        Optional[List[str]],
        Field(description="List of log file paths to search. If omitted, uses LOG_FILES from .env."),
    ] = None,
    max_matches: Annotated[
        int,
        Field(description="Maximum number of matching lines to return."),
    ] = DEFAULT_MAX_MATCHES,
    context_lines: Annotated[
        int,
        Field(description="Number of surrounding lines to include above and below each match for context."),
    ] = DEFAULT_CONTEXT_LINES,
    openai_model: Annotated[
        Optional[str],
        Field(description="Override the LLM model name for the AI explanation."),
    ] = None,
) -> Dict:
    """
    Search log files for lines related to a specific problem and return matching lines with context and an AI explanation.

    USE THIS TOOL WHEN the user asks about:
    - A specific error or symptom ("database timeout", "out of memory", "503 errors")
    - A particular service or component ("what happened with the payment service?")
    - Root-cause investigation ("why did the API return 500?")
    - Any targeted question about a concrete problem in the logs

    DO NOT use this tool for general stats — use analyze_logs instead.

    The prompt is matched against log lines using keyword regex (or semantic vector search if embeddings are configured).
    Returns: matched lines with file/line_number/context, total_matches, and an AI-generated human_summary explaining the likely issue.
    """
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
def reset_file_cache(
    log_files: Annotated[
        Optional[List[str]],
        Field(description="List of log file paths to reset. If omitted, resets all cached files."),
    ] = None,
) -> Dict:
    """
    Drop the in-memory line buffer and reset byte offsets so the next call re-reads from the beginning of the file.

    USE THIS TOOL WHEN:
    - The user says logs have been rotated or truncated
    - The user wants a fresh re-read of the entire file
    - Results seem stale or inconsistent

    This does NOT delete any files — it only clears the server's internal read cache.
    """
    if log_files:
        from pathlib import Path
        for f in log_files:
            get_reader().reset(Path(f))
        return {"reset": log_files, "status": "ok"}
    get_reader().reset()
    return {"reset": "all", "status": "ok"}

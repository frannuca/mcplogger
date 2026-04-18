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
from search.clusterer import semantic_analyze

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
    time_start: Annotated[
        Optional[str],
        Field(description="ISO-8601 start of time range filter, e.g. '2025-01-15T08:00:00'. Only lines at or after this timestamp are included."),
    ] = None,
    time_end: Annotated[
        Optional[str],
        Field(description="ISO-8601 end of time range filter, e.g. '2025-01-15T12:00:00'. Only lines at or before this timestamp are included."),
    ] = None,
    hour_min: Annotated[
        Optional[int],
        Field(description="Minimum hour of day (0–23) for time-of-day filtering. Lines with timestamp hour < hour_min are excluded."),
    ] = None,
    hour_max: Annotated[
        Optional[int],
        Field(description="Maximum hour of day (0–23) for time-of-day filtering. Lines with timestamp hour > hour_max are excluded."),
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
    cfg = build_config(log_files, bucket_minutes, high_error_threshold, max_samples, openai_model,
                       time_start=time_start, time_end=time_end, hour_min=hour_min, hour_max=hour_max)
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
    hour_min: Annotated[
        Optional[int],
        Field(description="Minimum hour of day (0–23) for time-of-day filtering."),
    ] = None,
    hour_max: Annotated[
        Optional[int],
        Field(description="Maximum hour of day (0–23) for time-of-day filtering."),
    ] = None,
    time_start: Annotated[
        Optional[str],
        Field(description="ISO-8601 start of date range filter, e.g. '2025-01-15T00:00:00'."),
    ] = None,
    time_end: Annotated[
        Optional[str],
        Field(description="ISO-8601 end of date range filter, e.g. '2025-01-15T23:59:59'."),
    ] = None,
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
        hour_min=hour_min,
        hour_max=hour_max,
        time_start=time_start,
        time_end=time_end,
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


@mcp.tool()
def semantic_analysis(
    prompt: Annotated[
        str,
        Field(description="Natural-language question about error patterns. "
        "Examples: 'what is the most common cause of error in the last 12 hours', "
        "'what types of failures are happening', 'cluster errors by root cause'."),
    ],
    log_files: Annotated[
        Optional[List[str]],
        Field(description="List of log file paths. If omitted, uses LOG_FILES from .env."),
    ] = None,
    max_clusters: Annotated[
        int,
        Field(description="Maximum number of error clusters to return."),
    ] = 20,
    hour_min: Annotated[
        Optional[int],
        Field(description="Minimum hour of day (0–23) for time-of-day filtering."),
    ] = None,
    hour_max: Annotated[
        Optional[int],
        Field(description="Maximum hour of day (0–23) for time-of-day filtering."),
    ] = None,
    time_start: Annotated[
        Optional[str],
        Field(description="ISO-8601 start of date range filter, e.g. '2025-01-15T00:00:00'."),
    ] = None,
    time_end: Annotated[
        Optional[str],
        Field(description="ISO-8601 end of date range filter, e.g. '2025-01-15T23:59:59'."),
    ] = None,
    openai_model: Annotated[
        Optional[str],
        Field(description="Override the LLM model name for cluster summaries."),
    ] = None,
) -> Dict:
    """
    Group error lines by semantic similarity into clusters, label each cluster with a representative keyword, and return cluster sizes and sample lines.

    USE THIS TOOL WHEN the user asks:
    - "What is the most common cause of error?"
    - "What types of failures are happening?"
    - "Cluster the errors by root cause"
    - "What are the main error categories in the last N hours?"
    - Any question about grouping, categorizing, or summarizing error patterns by meaning

    DO NOT use this for specific error searches — use search_logs_tool instead.
    DO NOT use this for raw statistics — use analyze_logs instead.

    Requires embedding server (LLM_EMBEDDING_URL). Returns labeled clusters with sizes, percentages, keywords, and sample lines.
    """
    cfg = build_config(
        log_files,
        bucket_minutes=DEFAULT_BUCKET_MINUTES,
        high_error_threshold=DEFAULT_HIGH_ERROR_THRESHOLD,
        max_samples=DEFAULT_MAX_SAMPLES,
        openai_model=openai_model,
        hour_min=hour_min,
        hour_max=hour_max,
        time_start=time_start,
        time_end=time_end,
    )

    result = semantic_analyze(cfg, prompt=prompt, max_clusters=max_clusters)

    # add LLM summary if available and clusters exist
    if cfg.llm_api_key and result.get("clusters") and "error" not in result:
        try:
            summary_input = [
                f"{c['label']} ({c['size']} lines, {c['percentage']}%): {', '.join(c['keywords'])}"
                for c in result["clusters"][:10]
            ]
            llm = LLMSummarizer(
                api_key=cfg.llm_api_key,
                model=cfg.openai_model,
                base_url=cfg.llm_base_url,
            )
            result["human_summary"] = llm.summarize_search(
                prompt,
                summary_input,
                total_matches=result.get("total_error_lines", 0),
                total_lines=result.get("total_lines", 0),
            )
        except requests.RequestException as exc:
            result["human_summary"] = f"Summary API call failed: {exc}"

    return result


import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from .constants import (
    DEFAULT_BUCKET_MINUTES,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_HIGH_ERROR_THRESHOLD,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_MAX_SAMPLES,
    DEFAULT_OPENAI_MODEL,
)

# Load environment variables from .env file
load_dotenv()


@dataclass
class Config:
    log_files: List[Path]
    bucket_minutes: int = DEFAULT_BUCKET_MINUTES
    high_error_threshold: float = DEFAULT_HIGH_ERROR_THRESHOLD
    max_samples: int = DEFAULT_MAX_SAMPLES
    openai_api_key: Optional[str] = None        # kept for backward compat
    openai_model: str = DEFAULT_OPENAI_MODEL
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_api_key: Optional[str] = None           # LLM_API_KEY or fallback to OPENAI_API_KEY
    # Embedding — set LLM_EMBEDDING_URL to enable semantic search
    llm_embedding_url: Optional[str] = None     # e.g. http://localhost:8080/v1
    llm_embedding_model: str = DEFAULT_EMBEDDING_MODEL


def parse_paths_from_env() -> List[Path]:
    raw = os.getenv("LOG_FILES", "")
    return [Path(p.strip()) for p in raw.split(",") if p.strip()]


def build_config(
    log_files: Optional[List[str]],
    bucket_minutes: int,
    high_error_threshold: float,
    max_samples: int,
    openai_model: Optional[str],
) -> Config:
    paths = [Path(p) for p in log_files] if log_files else parse_paths_from_env()
    if not paths:
        raise ValueError("No log files provided. Pass log_files or set LOG_FILES env var.")
    if bucket_minutes <= 0:
        raise ValueError("bucket_minutes must be > 0")
    if not 0 <= high_error_threshold <= 1:
        raise ValueError("high_error_threshold must be between 0 and 1")

    return Config(
        log_files=paths,
        bucket_minutes=bucket_minutes,
        high_error_threshold=high_error_threshold,
        max_samples=max(max_samples, 1),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=openai_model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        llm_base_url=os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        # If LLM_EMBEDDING_URL is set, semantic (vector) search is used instead of regex
        llm_embedding_url=os.getenv("LLM_EMBEDDING_URL") or None,
        llm_embedding_model=os.getenv("LLM_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
    )

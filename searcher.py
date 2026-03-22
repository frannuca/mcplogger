import re
import sys
from typing import Dict, List, Tuple

import requests

from config import Config
from constants import (
    DEFAULT_CONTEXT_LINES,
    DEFAULT_MAX_MATCHES,
    EMBEDDING_PREFILTER_SIZE,
    FALLBACK_SEARCH_PATTERN,
    MAX_PROMPT_TERMS,
    MIN_TERM_LENGTH,
    STOPWORDS,
)
from embedder import LogEmbedder
from file_reader import get_reader
from patterns import ERROR_PATTERNS
from summarizer import LLMSummarizer


# ── prompt → regex ────────────────────────────────────────────────────────────

def keyword_regex_from_prompt(prompt: str) -> re.Pattern:
    words = [
        w for w in re.findall(rf"[A-Za-z0-9_\-.]{{{MIN_TERM_LENGTH},}}", prompt.lower())
        if w not in STOPWORDS
    ]
    if not words:
        return re.compile(FALLBACK_SEARCH_PATTERN, re.IGNORECASE)
    terms = [re.escape(w) for w in words[:MAX_PROMPT_TERMS]]
    return re.compile("|".join(terms), re.IGNORECASE)


# ── public entry point ────────────────────────────────────────────────────────

def search_logs(
    cfg: Config,
    prompt: str,
    max_matches: int = DEFAULT_MAX_MATCHES,
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> Dict:
    """Dispatch to semantic or regex search depending on config."""
    if cfg.llm_embedding_url:
        _log(f"Using semantic (embedding) search → {cfg.llm_embedding_url}")
        return _semantic_search(cfg, prompt, max_matches, context_lines)
    return _regex_search(cfg, prompt, max_matches, context_lines)


# ── regex search (default) ────────────────────────────────────────────────────

def _regex_search(
    cfg: Config,
    prompt: str,
    max_matches: int,
    context_lines: int,
) -> Dict:
    matcher = keyword_regex_from_prompt(prompt)
    matches: List[Dict] = []
    missing_files: List[str] = []

    for path in cfg.log_files:
        if not path.exists() or not path.is_file():
            missing_files.append(str(path))
            continue

        lines = get_reader().read_lines(path)

        for idx, clean in enumerate(lines):
            if matcher.search(clean) or any(p.search(clean) for p in ERROR_PATTERNS.values()):
                matches.append(_make_match(str(path), idx, clean, lines, context_lines))
                if len(matches) >= max_matches:
                    break
        if len(matches) >= max_matches:
            break

    return _build_response(cfg, prompt, matches, missing_files, search_mode="regex")


# ── semantic search (embedding-based) ────────────────────────────────────────

def _semantic_search(
    cfg: Config,
    prompt: str,
    max_matches: int,
    context_lines: int,
) -> Dict:
    """
    Two-phase approach:
      1. Regex pre-filter  → keeps up to EMBEDDING_PREFILTER_SIZE candidates
         (prevents sending 50 000 raw lines to the embedding API)
      2. Embed + rank      → cosine similarity against the prompt vector,
         return top-N above the similarity threshold
    """
    embedder = LogEmbedder(
        base_url=cfg.llm_embedding_url,
        model=cfg.llm_embedding_model,
        api_key=cfg.llm_api_key or "local",
    )

    # broad regex pre-filter — any error pattern OR any prompt keyword
    broad_matcher = keyword_regex_from_prompt(prompt)
    missing_files: List[str] = []
    # (path_str, line_index, clean_line, all_lines_for_that_file)
    candidates: List[Tuple[str, int, str, List[str]]] = []

    for path in cfg.log_files:
        if not path.exists() or not path.is_file():
            missing_files.append(str(path))
            continue

        lines = get_reader().read_lines(path)

        for idx, clean in enumerate(lines):
            is_error = any(p.search(clean) for p in ERROR_PATTERNS.values())
            is_keyword = broad_matcher.search(clean)
            if is_error or is_keyword:
                candidates.append((str(path), idx, clean, lines))
            if len(candidates) >= EMBEDDING_PREFILTER_SIZE:
                break
        if len(candidates) >= EMBEDDING_PREFILTER_SIZE:
            break

    _log(f"Pre-filter kept {len(candidates)} / {EMBEDDING_PREFILTER_SIZE} candidates")

    if not candidates:
        return _build_response(cfg, prompt, [], missing_files, search_mode="semantic")

    # embed candidates + rank by cosine similarity
    candidate_texts = [c[2] for c in candidates]
    try:
        ranked = embedder.rank_lines(prompt, candidate_texts, top_n=max_matches)
    except requests.RequestException as exc:
        _log(f"Embedding failed, falling back to regex: {exc}")
        return _regex_search(cfg, prompt, max_matches, context_lines)

    matches: List[Dict] = []
    for cand_idx, score in ranked:
        path_str, line_idx, clean, all_lines = candidates[cand_idx]
        m = _make_match(path_str, line_idx, clean, all_lines, context_lines)
        m["similarity"] = score
        matches.append(m)

    return _build_response(cfg, prompt, matches, missing_files, search_mode="semantic")


# ── shared helpers ─────────────────────────────────────────────────────────────

def _make_match(
    path_str: str,
    idx: int,
    clean: str,
    lines: List[str],
    context_lines: int,
) -> Dict:
    start = max(0, idx - context_lines)
    end = min(len(lines), idx + context_lines + 1)
    snippet = "\n".join(lines[start:end])
    return {
        "file": path_str,
        "line_number": idx + 1,
        "line": clean[:500],
        "context": snippet[:1200],
    }


def _build_response(
    cfg: Config,
    prompt: str,
    matches: List[Dict],
    missing_files: List[str],
    search_mode: str,
) -> Dict:
    response = {
        "query": prompt,
        "search_mode": search_mode,
        "log_files": [str(p) for p in cfg.log_files],
        "lines_buffered": {str(p): get_reader().buffered_count(p) for p in cfg.log_files},
        "missing_files": missing_files,
        "total_matches": len(matches),
        "matches": matches,
    }

    if cfg.llm_api_key:
        try:
            llm = LLMSummarizer(
                api_key=cfg.llm_api_key,
                model=cfg.openai_model,
                base_url=cfg.llm_base_url,
            )
            response["human_summary"] = llm.summarize_search(
                prompt, [m["context"] for m in matches[:20]]
            )
        except requests.RequestException as exc:
            response["human_summary"] = f"Search summary API call failed: {exc}"
    else:
        response["human_summary"] = "LLM_API_KEY / OPENAI_API_KEY not set; AI summary skipped."

    return response


def _log(msg: str) -> None:
    print(f"[searcher] {msg}", file=sys.stderr, flush=True)

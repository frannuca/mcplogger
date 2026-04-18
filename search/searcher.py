import re
import sys
from typing import Dict, List, Tuple

import requests

from config import Config
from config.constants import (
    DEFAULT_CONTEXT_LINES,
    DEFAULT_MAX_MATCHES,
    EMBEDDING_PREFILTER_SIZE,
    FALLBACK_SEARCH_PATTERN,
    MAX_PROMPT_TERMS,
    MIN_TERM_LENGTH,
    STOPWORDS,
)
from core.file_reader import get_reader
from core.patterns import ERROR_PATTERNS
from llm.summarizer import LLMSummarizer
from search.embedder import LogEmbedder
from search.time_filter import filter_lines_by_time, parse_time_window, strip_time_phrase


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
    time_window = parse_time_window(prompt)
    search_prompt = strip_time_phrase(prompt) if time_window else prompt
    matcher = keyword_regex_from_prompt(search_prompt)
    matches: List[Dict] = []
    missing_files: List[str] = []

    for path in cfg.log_files:
        if not path.exists() or not path.is_file():
            missing_files.append(str(path))
            continue

        all_lines = get_reader().read_lines(path)

        # apply time window if present
        if time_window:
            indexed_lines, _ = filter_lines_by_time(all_lines, time_window)
        else:
            indexed_lines = [(i, l) for i, l in enumerate(all_lines)]

        for idx, clean in indexed_lines:
            if matcher.search(clean) or any(p.search(clean) for p in ERROR_PATTERNS.values()):
                matches.append(_make_match(str(path), idx, clean, all_lines, context_lines))
                if len(matches) >= max_matches:
                    break
        if len(matches) >= max_matches:
            break

    # rank matches by relevance instead of file order
    matches = _rank_matches(cfg, search_prompt, matches)

    return _build_response(cfg, prompt, matches, missing_files, search_mode="regex",
                           time_window=str(time_window) if time_window else None)


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
    time_window = parse_time_window(prompt)
    search_prompt = strip_time_phrase(prompt) if time_window else prompt

    embedder = LogEmbedder(
        base_url=cfg.llm_embedding_url,
        model=cfg.llm_embedding_model,
        api_key=cfg.llm_api_key or "local",
    )

    # broad regex pre-filter — any error pattern OR any prompt keyword
    broad_matcher = keyword_regex_from_prompt(search_prompt)
    missing_files: List[str] = []
    # (path_str, line_index, clean_line, all_lines_for_that_file)
    candidates: List[Tuple[str, int, str, List[str]]] = []

    for path in cfg.log_files:
        if not path.exists() or not path.is_file():
            missing_files.append(str(path))
            continue

        all_lines = get_reader().read_lines(path)

        # apply time window if present
        if time_window:
            indexed_lines, _ = filter_lines_by_time(all_lines, time_window)
        else:
            indexed_lines = [(i, l) for i, l in enumerate(all_lines)]

        for idx, clean in indexed_lines:
            is_error = any(p.search(clean) for p in ERROR_PATTERNS.values())
            is_keyword = broad_matcher.search(clean)
            if is_error or is_keyword:
                candidates.append((str(path), idx, clean, all_lines))
            if len(candidates) >= EMBEDDING_PREFILTER_SIZE:
                break
        if len(candidates) >= EMBEDDING_PREFILTER_SIZE:
            break

    _log(f"Pre-filter kept {len(candidates)} / {EMBEDDING_PREFILTER_SIZE} candidates")

    if not candidates:
        return _build_response(cfg, prompt, [], missing_files, search_mode="semantic",
                               time_window=str(time_window) if time_window else None)

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

    return _build_response(cfg, prompt, matches, missing_files, search_mode="semantic",
                           time_window=str(time_window) if time_window else None)


# ── shared helpers ─────────────────────────────────────────────────────────────

def _rank_matches(cfg: Config, prompt: str, matches: List[Dict]) -> List[Dict]:
    """
    Re-rank matches by semantic proximity to the prompt.

    - If an embedding server is configured, use cosine similarity.
    - Otherwise, fall back to keyword hit-count scoring.

    Either way the result list is sorted descending by relevance.
    """
    if not matches:
        return matches

    # ── try embedding-based ranking ───────────────────────────────────────
    if cfg.llm_embedding_url:
        try:
            embedder = LogEmbedder(
                base_url=cfg.llm_embedding_url,
                model=cfg.llm_embedding_model,
                api_key=cfg.llm_api_key or "local",
            )
            texts = [m["line"] for m in matches]
            ranked = embedder.rank_lines(prompt, texts, top_n=len(texts), threshold=0.0)
            # ranked is [(idx, score), ...] sorted descending
            reordered = []
            for idx, score in ranked:
                m = matches[idx].copy()
                m["similarity"] = score
                reordered.append(m)
            _log(f"Re-ranked {len(reordered)} matches by embedding similarity")
            return reordered
        except Exception as exc:
            _log(f"Embedding re-rank failed, falling back to keyword scoring: {exc}")

    # ── fallback: keyword frequency scoring ───────────────────────────────
    matcher = keyword_regex_from_prompt(prompt)
    for m in matches:
        hits = len(matcher.findall(m["line"]))
        m["similarity"] = round(hits / max(len(m["line"].split()), 1), 4)

    matches.sort(key=lambda m: m.get("similarity", 0), reverse=True)
    _log(f"Re-ranked {len(matches)} matches by keyword frequency")
    return matches


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
    time_window: str = None,
) -> Dict:
    response = {
        "query": prompt,
        "search_mode": search_mode,
        "time_window": time_window,
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
            total_lines = sum(response["lines_buffered"].values())
            response["human_summary"] = llm.summarize_search(
                prompt,
                [m["context"] for m in matches[:20]],
                total_matches=len(matches),
                total_lines=total_lines,
            )
        except requests.RequestException as exc:
            response["human_summary"] = f"Search summary API call failed: {exc}"
    else:
        response["human_summary"] = "LLM_API_KEY / OPENAI_API_KEY not set; AI summary skipped."

    return response


def _log(msg: str) -> None:
    print(f"[searcher] {msg}", file=sys.stderr, flush=True)

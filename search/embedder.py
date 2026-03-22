"""
embedder.py – vector embeddings via any OpenAI-compatible /v1/embeddings endpoint.

Works with llama.cpp embedding models:
    llama-server -m nomic-embed-text-v1.5.Q4_K_M.gguf --port 8081 --embeddings

Strategy
────────
1. Regex pre-filter  →  keeps up to EMBEDDING_PREFILTER_SIZE candidate lines
   (fast; avoids sending 50,000 lines to the embedding API)
2. Batch embed       →  prompt + candidates in groups of EMBEDDING_BATCH_SIZE
3. Cosine ranking    →  sort by similarity, keep lines above threshold
4. Return top-N      →  with original line indices so callers can add context

All I/O goes to stderr so it never touches the JSON-RPC stdout channel.
"""

import sys
from typing import Dict, List, Optional, Tuple

import requests

from config.constants import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_PREFILTER_SIZE,
    EMBEDDING_SIMILARITY_THRESHOLD,
)


class LogEmbedder:
    """Wraps a /v1/embeddings endpoint for semantic log search."""

    def __init__(
        self,
        base_url: str,
        model: str = "text-embedding",
        api_key: str = "local",
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/embeddings"
        self.model = model
        self.api_key = api_key
        self.batch_size = batch_size
        _log(f"Embedder ready → {self.url}  model={self.model}  batch={self.batch_size}")

    # ── public API ────────────────────────────────────────────────────────────

    def rank_lines(
        self,
        query: str,
        lines: List[str],
        top_n: int,
        threshold: float = EMBEDDING_SIMILARITY_THRESHOLD,
    ) -> List[Tuple[int, float]]:
        """
        Return up to *top_n* ``(line_index, cosine_score)`` tuples sorted by
        descending similarity to *query*.  Only lines with score >= *threshold*
        are included.

        *lines* are expected to be already pre-filtered to at most
        EMBEDDING_PREFILTER_SIZE entries.
        """
        if not lines:
            return []

        all_texts = [query] + lines
        _log(f"Embedding {len(all_texts)} texts ({len(lines)} candidates + 1 query)…")

        try:
            vectors = self._embed_batch(all_texts)
        except requests.RequestException as exc:
            _log(f"Embedding API error: {exc}")
            raise

        query_vec = vectors[0]
        scored: List[Tuple[int, float]] = []
        for i, vec in enumerate(vectors[1:]):
            score = _cosine(query_vec, vec)
            if score >= threshold:
                scored.append((i, round(score, 4)))

        scored.sort(key=lambda t: t[1], reverse=True)
        _log(f"Ranked {len(scored)} lines above threshold {threshold}")
        return scored[:top_n]

    # ── internals ─────────────────────────────────────────────────────────────

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Send texts in batches and return all embedding vectors in order."""
        results: Dict[int, List[float]] = {}

        for start in range(0, len(texts), self.batch_size):
            chunk = texts[start : start + self.batch_size]
            resp = requests.post(
                self.url,
                json={"model": self.model, "input": chunk},
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            for item in resp.json()["data"]:
                results[start + item["index"]] = item["embedding"]

        return [results[i] for i in range(len(texts))]


# ── math helpers ──────────────────────────────────────────────────────────────

def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _log(msg: str) -> None:
    print(f"[embedder] {msg}", file=sys.stderr, flush=True)


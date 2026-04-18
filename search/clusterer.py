"""
clusterer.py — Semantic clustering of log error lines.

Groups error lines by embedding similarity into clusters, then labels
each cluster with a representative keyword extracted from its lines.

Strategy
────────
1. Collect all error lines (optionally time-filtered)
2. Embed them in batches via /v1/embeddings
3. Greedy agglomerative clustering: assign each line to the nearest
   existing centroid, or start a new cluster if similarity < threshold
4. Label each cluster by extracting the most frequent meaningful tokens
5. Return clusters sorted by size (largest first)
"""

import re
import sys
from collections import Counter
from typing import Dict, List, Optional, Tuple

from config import Config
from config.constants import EMBEDDING_PREFILTER_SIZE
from core.file_reader import get_reader
from core.patterns import ERROR_PATTERNS
from search.embedder import LogEmbedder
from search.time_filter import filter_lines_by_date_range, filter_lines_by_hour_range, filter_lines_by_time, parse_time_window, strip_time_phrase

# ── cluster config ────────────────────────────────────────────────────────────

# Minimum cosine similarity for a line to join an existing cluster
CLUSTER_THRESHOLD = 0.82

# Max error lines to embed (keeps latency manageable)
MAX_LINES_TO_EMBED = 2000

# Words to skip when labeling clusters
_LABEL_STOPWORDS = frozenset({
    "error", "warning", "info", "debug", "critical", "fatal",
    "the", "for", "and", "from", "with", "that", "this", "not",
    "was", "are", "were", "has", "had", "but", "its", "all",
    "can", "will", "been", "have", "does", "did", "got", "get",
    "log", "logs", "http", "https", "after", "before", "into",
    "none", "null", "true", "false", "com", "org", "net",
    "api", "v1", "v2", "usr", "var", "etc", "bin", "tmp",
    "localhost", "internal", "example", "service",
    # year prefixes picked up from timestamps
    "2024", "2025", "2026", "2027",
})

# Regex to extract tokens from a log line
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-.]{2,}")


# ── public API ────────────────────────────────────────────────────────────────

def semantic_analyze(
    cfg: Config,
    prompt: str,
    max_clusters: int = 20,
) -> Dict:
    """
    Cluster error lines semantically and return labeled groups.

    Returns:
        {
            "query": str,
            "time_window": str | None,
            "total_error_lines": int,
            "total_lines": int,
            "clusters": [
                {
                    "label": "DATABASE TIMEOUT",
                    "keywords": ["database", "timeout", "connection"],
                    "size": 142,
                    "percentage": 23.5,
                    "sample_lines": ["2026-04-18 ... timeout after 30s", ...],
                    "centroid_similarity": 0.82,
                },
                ...
            ],
        }
    """
    if not cfg.llm_embedding_url:
        return {"error": "Semantic analysis requires LLM_EMBEDDING_URL to be configured."}

    time_window = parse_time_window(prompt)

    # ── collect error lines ───────────────────────────────────────────────
    error_lines: List[Tuple[str, int, str]] = []  # (file, line_idx, text)
    total_lines = 0

    for path in cfg.log_files:
        if not path.exists() or not path.is_file():
            continue

        all_lines = get_reader().read_lines(path)
        total_lines += len(all_lines)

        if cfg.hour_min is not None and cfg.hour_max is not None:
            indexed = filter_lines_by_hour_range(
                all_lines, cfg.hour_min, cfg.hour_max,
                date_start=cfg.time_start, date_end=cfg.time_end,
            )
        elif cfg.time_start or cfg.time_end:
            indexed = filter_lines_by_date_range(all_lines, cfg.time_start, cfg.time_end)
        elif time_window:
            indexed, _ = filter_lines_by_time(all_lines, time_window)
        else:
            indexed = [(i, l) for i, l in enumerate(all_lines)]

        for idx, line in indexed:
            if any(p.search(line) for p in ERROR_PATTERNS.values()):
                error_lines.append((str(path), idx, line))

    # evenly sample if we collected more than the embedding limit
    if len(error_lines) > MAX_LINES_TO_EMBED:
        total_collected = len(error_lines)
        step = total_collected / MAX_LINES_TO_EMBED
        error_lines = [error_lines[int(i * step)] for i in range(MAX_LINES_TO_EMBED)]
        _log(f"Evenly sampled {MAX_LINES_TO_EMBED} from {total_collected} error lines")

    if not error_lines:
        return {
            "query": prompt,
            "time_window": str(time_window) if time_window else None,
            "total_error_lines": 0,
            "total_lines": total_lines,
            "clusters": [],
        }

    _log(f"Collected {len(error_lines)} error lines for clustering")

    # ── embed ─────────────────────────────────────────────────────────────
    embedder = LogEmbedder(
        base_url=cfg.llm_embedding_url,
        model=cfg.llm_embedding_model,
        api_key=cfg.llm_api_key or "local",
    )

    texts = [e[2] for e in error_lines]
    try:
        vectors = embedder._embed_batch(texts)
    except Exception as exc:
        _log(f"Embedding failed: {exc}")
        return {"error": f"Embedding API call failed: {exc}"}

    # ── cluster ───────────────────────────────────────────────────────────
    clusters = _greedy_cluster(vectors, CLUSTER_THRESHOLD)
    _log(f"Formed {len(clusters)} clusters from {len(error_lines)} lines")

    # ── build response ────────────────────────────────────────────────────
    result_clusters = []
    for cluster_indices in clusters:
        cluster_lines = [error_lines[i] for i in cluster_indices]
        cluster_texts = [e[2] for e in cluster_lines]

        # label from most frequent meaningful tokens
        keywords = _extract_keywords(cluster_texts, top_n=5)
        label = " ".join(k.upper() for k in keywords[:3]) if keywords else "UNKNOWN"

        # average intra-cluster similarity to centroid
        centroid = _mean_vector([vectors[i] for i in cluster_indices])
        avg_sim = sum(_cosine(vectors[i], centroid) for i in cluster_indices) / len(cluster_indices)

        # sample lines — all lines in the cluster, untruncated
        samples = cluster_texts

        result_clusters.append({
            "label": label,
            "keywords": keywords,
            "size": len(cluster_indices),
            "percentage": round(len(cluster_indices) / len(error_lines) * 100, 1),
            "sample_lines": samples,
            "centroid_similarity": round(avg_sim, 4),
        })

    # sort by size descending
    result_clusters.sort(key=lambda c: c["size"], reverse=True)

    # limit to max_clusters
    result_clusters = result_clusters[:max_clusters]

    return {
        "query": prompt,
        "time_window": str(time_window) if time_window else None,
        "total_error_lines": len(error_lines),
        "total_lines": total_lines,
        "clusters": result_clusters,
    }


# ── clustering ────────────────────────────────────────────────────────────────

def _greedy_cluster(
    vectors: List[List[float]],
    threshold: float,
) -> List[List[int]]:
    """
    Simple greedy agglomerative clustering.
    For each vector, find the most similar existing centroid.
    If similarity >= threshold, add to that cluster and update centroid.
    Otherwise, start a new cluster.
    """
    clusters: List[List[int]] = []
    centroids: List[List[float]] = []

    for i, vec in enumerate(vectors):
        best_cluster = -1
        best_sim = -1.0

        for ci, centroid in enumerate(centroids):
            sim = _cosine(vec, centroid)
            if sim > best_sim:
                best_sim = sim
                best_cluster = ci

        if best_sim >= threshold and best_cluster >= 0:
            clusters[best_cluster].append(i)
            # update centroid as running mean
            centroids[best_cluster] = _mean_vector(
                [vectors[j] for j in clusters[best_cluster]]
            )
        else:
            clusters.append([i])
            centroids.append(vec)

    return clusters


# ── labeling ──────────────────────────────────────────────────────────────────

def _extract_keywords(lines: List[str], top_n: int = 5) -> List[str]:
    """Extract the most frequent meaningful tokens from a set of lines."""
    counter: Counter = Counter()
    for line in lines:
        tokens = _TOKEN_RE.findall(line.lower())
        seen = set()
        for t in tokens:
            if t not in _LABEL_STOPWORDS and t not in seen and not t.isdigit():
                counter[t] += 1
                seen.add(t)
    return [word for word, _ in counter.most_common(top_n)]


# ── math helpers ──────────────────────────────────────────────────────────────

def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _mean_vector(vecs: List[List[float]]) -> List[float]:
    n = len(vecs)
    if n == 0:
        return []
    dim = len(vecs[0])
    return [sum(v[d] for v in vecs) / n for d in range(dim)]


def _log(msg: str) -> None:
    print(f"[clusterer] {msg}", file=sys.stderr, flush=True)


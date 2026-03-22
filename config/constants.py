"""
constants.py – single source of truth for every magic value in the project.

Import from here instead of scattering literals across modules:
    from constants import STOPWORDS, FALLBACK_SEARCH_PATTERN
    from constants import DEFAULT_BUCKET_MINUTES, DEFAULT_MAX_MATCHES, ...
"""

# ── search / NLP ──────────────────────────────────────────────────────────────

# Words stripped from user prompts before building keyword regex
STOPWORDS: frozenset = frozenset({
    "with", "from", "that", "this", "there", "where", "when",
    "what", "error", "errors", "issue", "issues", "problem", "problems",
    "log", "logs", "find", "show", "any", "all", "the", "for",
})

# Regex used when no meaningful keyword survives STOPWORDS filtering
FALLBACK_SEARCH_PATTERN: str = r"error|timeout|exception|critical|fatal|5\d\d"

# Maximum keyword terms extracted from a single prompt
MAX_PROMPT_TERMS: int = 10

# Minimum character length for a prompt token to be kept
MIN_TERM_LENGTH: int = 3

# ── analysis defaults ─────────────────────────────────────────────────────────

DEFAULT_BUCKET_MINUTES: int = 5
DEFAULT_HIGH_ERROR_THRESHOLD: float = 0.20
DEFAULT_MAX_SAMPLES: int = 30

# ── search defaults ───────────────────────────────────────────────────────────

DEFAULT_MAX_MATCHES: int = 5000
DEFAULT_CONTEXT_LINES: int = 1

# ── OpenAI ────────────────────────────────────────────────────────────────────

DEFAULT_OPENAI_MODEL: str = "gpt-4o-mini"

# ── LLM backend URLs ──────────────────────────────────────────────────────────

# Default: OpenAI cloud API
DEFAULT_LLM_BASE_URL: str = "https://api.openai.com/v1"

# llama.cpp local server  (start with: llama-server -m model.gguf --port 8080)
LLAMACPP_BASE_URL: str = "http://localhost:8080/v1"

# ── embedding (semantic search) ───────────────────────────────────────────────

# Model name sent to the embeddings endpoint (llama.cpp ignores it)
DEFAULT_EMBEDDING_MODEL: str = "text-embedding"

# How many texts to send per /v1/embeddings request
EMBEDDING_BATCH_SIZE: int = 128

# Max candidate lines fed into the embedder (regex pre-filters the rest)
EMBEDDING_PREFILTER_SIZE: int = 500

# Minimum cosine similarity score to include a line in results
EMBEDDING_SIMILARITY_THRESHOLD: float = 0.25


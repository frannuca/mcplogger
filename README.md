# MCP Log Analyzer Server

A Python MCP server (stdio transport) that exposes tools to analyze and search logs.

It can:
- extract errors, timeouts, exceptions, criticals, and 5xx patterns
- compute error stats and high-error windows
- summarize findings with any OpenAI-compatible LLM (cloud or local)
- search logs for prompt-specific issues and return contextual matches
- tail log files live — new lines are picked up on every tool call

## Setup

```bash
# install uv if you don't have it yet
curl -LsSf https://astral.sh/uv/install.sh | sh

# install dependencies and create the virtual environment
uv sync
```

> All dependencies are declared in `pyproject.toml` and pinned in `uv.lock`.  
> Never edit `requirements.txt` directly — use `uv add <package>` to add new dependencies.

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

---

## LLM Backend

The server works with **any OpenAI-compatible endpoint**.  
Switch between backends by changing two lines in `.env` — no code changes required.

---

### Option A — OpenAI (default)

```dotenv
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
# LLM_BASE_URL is not needed — defaults to https://api.openai.com/v1
```

---

### Option B — llama.cpp (local, no API key needed)

**1. Start the llama.cpp server**

```bash
# Basic (CPU only)
llama-server -m /path/to/your-model.gguf --port 8080

# With GPU layers offloaded (faster)
llama-server -m /path/to/your-model.gguf --port 8080 -ngl 35

# With a larger context window
llama-server -m /path/to/your-model.gguf --port 8080 -ngl 35 -c 8192
```

Verify it is running:
```bash
curl http://localhost:8080/health
# {"status":"ok"}
```

**2. Set `.env`**

Comment out (or remove) the OpenAI lines and add:

```dotenv
# OpenAI — disabled
# OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o-mini

# llama.cpp local
LLM_BASE_URL=http://localhost:8080/v1
LLM_API_KEY=local          # any non-empty string — llama.cpp ignores the value
OPENAI_MODEL=local         # ignored by llama.cpp; the loaded .gguf is used
```

**3. Start the MCP server as usual**

```bash
python main.py
# [summarizer] LLM backend: http://localhost:8080/v1/chat/completions  model: local
```

---

### Option B-2 — llama.cpp Semantic Search (vector embeddings)

Instead of regex keyword matching, log lines are converted to embedding vectors
and ranked by **cosine similarity** against the search prompt.

This catches semantically related lines that don't share keywords — e.g. searching
for *"slow query"* will also surface lines about *"high latency"* or *"response time exceeded"*.

**How it works**

```
prompt ──► embed ──► query vector ─┐
                                   ├──► cosine similarity ──► ranked matches
log lines ──► regex pre-filter     │
              (up to 500 lines)    │
              ──► embed in batches ─┘
```

**1. Start a second llama.cpp server with an embedding model**

An embedding model is separate from a chat model.
Recommended: [nomic-embed-text](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF)

```bash
# Download (one time)
huggingface-cli download nomic-ai/nomic-embed-text-v1.5-GGUF \
    nomic-embed-text-v1.5.Q4_K_M.gguf --local-dir ./models

# Start embedding server on a DIFFERENT port from the chat server
llama-server -m ./models/nomic-embed-text-v1.5.Q4_K_M.gguf \
    --port 8081 --embeddings --ctx-size 2048
```

Verify:
```bash
curl -s http://localhost:8081/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"test","input":["hello world"]}' | python -m json.tool
```

**2. Set `.env`**

```dotenv
# chat/summary server (port 8080 as before)
LLM_BASE_URL=http://localhost:8080/v1
LLM_API_KEY=local

# embedding server (port 8081)
LLM_EMBEDDING_URL=http://localhost:8081/v1
LLM_EMBEDDING_MODEL=nomic-embed-text   # informational; llama.cpp ignores it
```

**3. Use `ask.py` as normal** — the server auto-selects semantic mode:

```
ask> database connection refused
  ⏳ Searching for "database connection refused" …
[searcher] Using semantic (embedding) search → http://localhost:8081/v1
[embedder] Pre-filter kept 87 candidates
[embedder] Embedding 88 texts (87 candidates + 1 query)…
[embedder] Ranked 23 lines above threshold 0.25

──────────────────────────────────────────────────────────────────────
🔍  SEARCH (semantic): "database connection refused" — 23 match(es)
──────────────────────────────────────────────────────────────────────
  [  1] app.log:1042  sim=0.891
         2026-03-22 14:03:11 ERROR db.pool - Max retries exceeded
       ▶ 2026-03-22 14:03:11 ERROR db.pool - Connection pool exhausted
  [  2] app.log:987   sim=0.854
       ▶ 2026-03-22 13:58:44 WARN  db - Query timeout after 30s
```

---

### Option C — Ollama (local)

```bash
ollama serve            # starts Ollama if not already running
ollama pull llama3      # download a model
```

```dotenv
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=local
OPENAI_MODEL=llama3     # must match the name used with `ollama pull`
```

---

### Key env variables

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Base URL of any OpenAI-compatible API |
| `LLM_API_KEY` | *(falls back to `OPENAI_API_KEY`)* | API key — set to `local` for llama.cpp / Ollama |
| `OPENAI_API_KEY` | — | Classic OpenAI key (backward compat) |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name sent in the request |
| `LOG_FILES` | — | Comma-separated list of log file paths |
| `BUCKET_MINUTES` | `5` | Time-bucket width for error-rate windows |
| `HIGH_ERROR_THRESHOLD` | `0.20` | Error rate (0–1) to flag a window as high-error |

---

## Run

```bash
# MCP server (used by client / ask.py automatically)
uv run main.py

# Interactive REPL — asks questions about logs
uv run ask.py test_app.log
uv run ask.py app.log worker.log

# Batch demo (runs 4 example tool calls)
uv run client.py
```

## Tools

### `analyze_logs`
Inputs:
- `log_files` (optional `string[]`): overrides `LOG_FILES`
- `bucket_minutes` (default `5`)
- `high_error_threshold` (default `0.20`)
- `max_samples` (default `30`)
- `openai_model` (optional)

Output includes:
- `pattern_counts`, `error_rate`, `high_error_windows`
- `sample_error_lines`, `lines_buffered`
- `human_summary` — generated by the configured LLM

### `search_logs_tool`
Inputs:
- `prompt` (required `string`): natural language problem statement
- `log_files` (optional `string[]`): overrides `LOG_FILES`
- `max_matches` (default `40`)
- `context_lines` (default `1`)
- `openai_model` (optional)

Output includes:
- matched file / line / context snippets
- `total_matches`, `lines_buffered`
- `human_summary` — LLM explanation of the likely issue and next steps

### `reset_file_cache`
Drops the in-memory line buffer and resets byte offsets so the next call
re-reads the file from the beginning. Useful after log rotation.

Inputs:
- `log_files` (optional `string[]`): reset specific files, or all if omitted

## Notes

- **Live tailing** — each tool call reads only the bytes appended since the
  last call; the full buffer is held in memory for the lifetime of the server.
- Timestamp formats supported: `YYYY-MM-DD HH:MM:SS`, `YYYY-MM-DDTHH:MM:SS`,
  `YYYY/MM/DD HH:MM:SS`, `YYYY/MM/DDTHH:MM:SS`
- If no LLM key is configured both tools still run and return a fallback
  summary message instead of calling the LLM.

---

## Architecture — `embedder.py`

`embedder.py` powers the semantic search path. It is used automatically by
`searcher.py` when `LLM_EMBEDDING_URL` is set.

### Two-phase strategy

Embedding every line in a large log file would be slow and wasteful.
Instead the module uses a **regex pre-filter → embed → rank** pipeline:

```
All buffered log lines
        │
        ▼
┌───────────────────────┐
│  Phase 1: pre-filter  │  regex (keyword + error patterns)
│  up to 500 candidates │  fast — no network call
└───────────┬───────────┘
            │ ≤ 500 lines
            ▼
┌───────────────────────┐
│  Phase 2: embed       │  POST /v1/embeddings  (batches of 128)
│  prompt + candidates  │  one network round-trip per batch
└───────────┬───────────┘
            │ vectors
            ▼
┌───────────────────────┐
│  Phase 3: cosine rank │  pure Python dot-product
│  filter by threshold  │  threshold = 0.25 (configurable)
└───────────┬───────────┘
            │ top-N (line_index, score)
            ▼
       matches returned
       (with context lines added by searcher.py)
```

If the embedding API call fails, `searcher.py` **automatically falls back to
regex search** — no errors surface to the client.

### `LogEmbedder` class

```python
from embedder import LogEmbedder

embedder = LogEmbedder(
    base_url="http://localhost:8081/v1",   # LLM_EMBEDDING_URL
    model="nomic-embed-text",              # LLM_EMBEDDING_MODEL (informational)
    api_key="local",                       # any string for llama.cpp
    batch_size=128,                        # texts per /v1/embeddings request
)

# returns [(line_index, cosine_score), ...] sorted descending
ranked = embedder.rank_lines(
    query="database connection timeout",
    lines=candidate_lines,   # pre-filtered list of strings
    top_n=40,
    threshold=0.25,
)
```

### Key constants (`constants.py`)

| Constant | Default | Description |
|---|---|---|
| `EMBEDDING_BATCH_SIZE` | `128` | Max texts per `/v1/embeddings` request |
| `EMBEDDING_PREFILTER_SIZE` | `500` | Max candidate lines sent to the embedder |
| `EMBEDDING_SIMILARITY_THRESHOLD` | `0.25` | Min cosine score to include a line |
| `DEFAULT_EMBEDDING_MODEL` | `"text-embedding"` | Model name (ignored by llama.cpp) |

### Cosine similarity

Computed in pure Python — no numpy dependency:

```python
def _cosine(a, b):
    dot    = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return 0.0 if norm_a == 0 or norm_b == 0 else dot / (norm_a * norm_b)
```

Score range: `0.0` (unrelated) → `1.0` (identical).  
In practice log lines above `0.6` are strongly related; `0.25–0.5` are topically related.

### New field in search results

When semantic mode is active each match includes a `similarity` score:

```json
{
  "file": "app.log",
  "line_number": 1042,
  "line": "ERROR db.pool - Connection pool exhausted",
  "context": "...",
  "similarity": 0.891
}
```

`ask.py` displays it as `sim=0.891` next to the file/line reference.
  summary message instead of calling the LLM.


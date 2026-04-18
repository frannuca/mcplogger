# Installation Guide

Complete guide to setting up MCP Log Analyzer with a local LLM backend (llama.cpp).

---

## 1. Prerequisites

```bash
# Python 3.10+
python3 --version

# uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# cmake (for building llama.cpp)
# macOS
brew install cmake

# Ubuntu / Debian
sudo apt install cmake build-essential

# Fedora / RHEL
sudo dnf install cmake gcc-c++ make

# huggingface-cli (for downloading models)
# If using the project venv (recommended):
uv add huggingface-hub
# Or globally:
pip install huggingface-hub
# Then always run it with: uv run huggingface-cli ...
# Or activate the venv first: source .venv/bin/activate
```

---

## 2. Install MCP Log Analyzer

```bash
git clone <your-repo-url> mcplogger
cd mcplogger
uv sync
```

Copy the environment config:
```bash
cp .env.example .env
```

---

## 3. Build llama.cpp from source

llama.cpp is the inference engine that runs GGUF models locally.
You compile it once — after that you get the `llama-server` binary.

```bash
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp
```

### CPU-only build (works everywhere)

```bash
cmake -B build
cmake --build build --config Release -j $(nproc)
```

### macOS with Metal GPU acceleration (recommended on Apple Silicon)

```bash
cmake -B build -DGGML_METAL=ON
cmake --build build --config Release -j $(sysctl -n hw.ncpu)
```

### Linux / Windows with NVIDIA CUDA

Make sure the [CUDA toolkit](https://developer.nvidia.com/cuda-downloads) is installed first.

```bash
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j $(nproc)
```

### Linux with Vulkan (AMD / Intel / NVIDIA)

Requires the [Vulkan SDK](https://vulkan.lunarg.com/sdk/home).

```bash
cmake -B build -DGGML_VULKAN=ON
cmake --build build --config Release -j $(nproc)
```

### Add to PATH

After building, the binaries are in `build/bin/`:

```bash
# Option A: add to PATH for the current session
export PATH="$PWD/build/bin:$PATH"

# Option B: copy to a system-wide location
sudo cp build/bin/llama-server /usr/local/bin/

# Verify
llama-server --help
```

---

## 4. Download models

All models must be in **GGUF format**. Quantized versions (Q4_K_M, Q5_K_M, Q8_0)
are smaller and faster while keeping good quality.

Create a models directory:
```bash
mkdir -p models
```

### 4a. Chat / summary model

This model powers the AI summaries. Pick **one** based on your available RAM:

| Model | Size | RAM needed | Best for |
|---|---|---|---|
| Qwen2.5-7B-Instruct (Q4_K_M) | ~4.5 GB | 6 GB | Good balance of speed and quality |
| Llama-3-8B-Instruct (Q4_K_M) | ~4.7 GB | 6 GB | Strong general-purpose |
| Mistral-7B-Instruct-v0.2 (Q4_K_M) | ~4.4 GB | 6 GB | Fast, good at structured output |
| Phi-3-mini-4k (Q4_K_M) | ~2.2 GB | 4 GB | Lightweight, smaller context |

**Download commands:**

```bash
# Qwen 2.5 7B — recommended
uv run huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF \
    qwen2.5-7b-instruct-q4_k_m.gguf --local-dir ./models

# OR Llama 3 8B
uv run huggingface-cli download QuantFactory/Meta-Llama-3-8B-Instruct-GGUF \
    Meta-Llama-3-8B-Instruct.Q4_K_M.gguf --local-dir ./models

# OR Mistral 7B
uv run huggingface-cli download TheBloke/Mistral-7B-Instruct-v0.2-GGUF \
    mistral-7b-instruct-v0.2.Q4_K_M.gguf --local-dir ./models
```

### 4b. Embedding model (for semantic search)

This model converts text into vectors for similarity-based search.
It runs on a **separate port** from the chat model.
**Skip this if you only want regex-based search.**

| Model | Size | Description |
|---|---|---|
| nomic-embed-text-v1.5 (Q4_K_M) | ~100 MB | Fast, good quality, 2048 token context |
| all-MiniLM-L6-v2 (Q4_K_M) | ~45 MB | Very small and fast |

```bash
# nomic-embed-text — recommended
uv run huggingface-cli download nomic-ai/nomic-embed-text-v1.5-GGUF \
    nomic-embed-text-v1.5.Q4_K_M.gguf --local-dir ./models

# OR all-MiniLM-L6-v2
uv run huggingface-cli download leliuga/all-MiniLM-L6-v2-GGUF \
    all-MiniLM-L6-v2.Q4_K_M.gguf --local-dir ./models
```

---

## 5. Start the llama.cpp servers

### Chat server (port 8080)

```bash
# CPU only
llama-server -m ./models/qwen2.5-7b-instruct-q4_k_m.gguf --port 8080

# With GPU layers offloaded (much faster)
llama-server -m ./models/qwen2.5-7b-instruct-q4_k_m.gguf --port 8080 -ngl 35

# With a larger context window (if your model supports it)
llama-server -m ./models/qwen2.5-7b-instruct-q4_k_m.gguf --port 8080 -ngl 35 -c 8192
```

Verify:
```bash
curl http://localhost:8080/health
# {"status":"ok"}
```

### Embedding server (port 8081) — optional

Only needed for semantic search. Must run on a **different port** from the chat server.

```bash
llama-server -m ./models/nomic-embed-text-v1.5.Q4_K_M.gguf \
    --port 8081 --embeddings --ctx-size 2048
```

Verify:
```bash
curl -s http://localhost:8081/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"test","input":["hello world"]}' | python3 -m json.tool
```

---

## 6. Configure `.env`

### Local model only (no semantic search)

```dotenv
LOG_FILES=test_app.log

# llama.cpp local
LLM_BASE_URL=http://localhost:8080/v1
LLM_API_KEY=local
OPENAI_MODEL=local
```

### Local model + semantic search

```dotenv
LOG_FILES=test_app.log

# llama.cpp chat server
LLM_BASE_URL=http://localhost:8080/v1
LLM_API_KEY=local
OPENAI_MODEL=local

# llama.cpp embedding server
LLM_EMBEDDING_URL=http://localhost:8081/v1
LLM_EMBEDDING_MODEL=nomic-embed-text
```

### OpenAI (cloud)

```dotenv
LOG_FILES=test_app.log

OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
```

---

## 7. Run MCP Log Analyzer

```bash
# Web UI (recommended)
uv run python web/app.py                    # http://localhost:5000
uv run python web/app.py --port 8888        # custom port

# CLI tools
uv run python main.py                       # MCP server (stdio)
uv run python smart_ask.py test_app.log     # LLM picks the tool automatically
uv run python ask.py test_app.log           # interactive REPL
uv run python cli.py                        # simple CLI
```

---

## Troubleshooting

### "Connection refused" on port 8080 / 8081

The llama.cpp server isn't running. Start it first (step 5).

### Slow responses from local model

- **Offload layers to GPU** with `-ngl 35` (or higher). Use `-ngl 999` to offload everything.
- **Use a smaller model** — Phi-3-mini is ~2 GB and fast on CPU.
- **Use a higher quantization** — Q4_K_M is a good tradeoff. Q8_0 is better quality but slower.
- **Reduce context** — lower `-c` value if you don't need large context windows.

### Truncated AI summaries

The model ran out of generation tokens. In `llm/summarizer.py`, increase `max_tokens` in the API payload.
Also make sure `prompt tokens + max_tokens` fits within the model's context window (`-c` flag).

### "No embedding URL configured"

Semantic search requires `LLM_EMBEDDING_URL` in `.env`. Set it to the embedding server (step 5).
If you don't want semantic search, just use the default regex search — it works without an embedding server.

### cmake errors during build

- **macOS:** make sure Xcode command-line tools are installed: `xcode-select --install`
- **Linux:** install build tools: `sudo apt install cmake build-essential`
- **CUDA build fails:** check `nvcc --version` — the CUDA toolkit must be installed and on PATH.

---

## Quick reference: model files after setup

```
mcplogger/
├── models/
│   ├── qwen2.5-7b-instruct-q4_k_m.gguf    ← chat model (~4.5 GB)
│   └── nomic-embed-text-v1.5.Q4_K_M.gguf  ← embedding model (~100 MB)
├── .env                                     ← your configuration
├── web/app.py                               ← start the web UI
└── ...
```

---

## Running everything (example session)

```bash
# Terminal 1: chat model
llama-server -m ./models/qwen2.5-7b-instruct-q4_k_m.gguf --port 8080 -ngl 35

# Terminal 2: embedding model (optional)
llama-server -m ./models/nomic-embed-text-v1.5.Q4_K_M.gguf --port 8081 --embeddings --ctx-size 2048

# Terminal 3: web UI
cd mcplogger
uv run python web/app.py
# Open http://localhost:5000 in your browser
```


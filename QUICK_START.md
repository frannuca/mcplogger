# MCP Log Analyzer - Quick Reference

## 🚀 Start Interactive CLI (Recommended)

```bash
python3 cli.py
```

## 💬 Ask Questions

```
mcplogger> analyze
mcplogger> search database timeout
mcplogger> search error
mcplogger> search critical
mcplogger> exit
```

## 🔧 Run MCP Server

```bash
python3 main.py              # Server (stdin/stdout)
python3 client.py            # Example client in another terminal
```

## 📊 Test Analyzer

```bash
python3 test_analyzer.py     # Run once and display results
```

## ⚙️ Configuration (`.env`)

```bash
LOG_FILES=test_app.log              # Which logs to analyze
OPENAI_API_KEY=sk-your-key-here     # Optional: AI summaries
BUCKET_MINUTES=5                     # Time bucketing for analysis
HIGH_ERROR_THRESHOLD=0.20            # Error rate threshold (20%)
```

## 📋 Search Examples

```
search database connection issue
search timeout
search authentication failure
search 503 service unavailable
search critical error
search exception
search memory
search fatal
```

## 🏗️ Project Structure

```
cli.py           ← Interactive CLI (START HERE)
main.py          ← MCP Server
client.py        ← MCP Client example
test_analyzer.py ← Quick test

analyzer.py      ← Core analysis
searcher.py      ← Pattern matching & search
summarizer.py    ← OpenAI integration
config.py        ← Config & .env loading
patterns.py      ← Regex patterns
tools.py         ← MCP tool definitions

test_app.log     ← Test data (57 lines)
.env             ← Configuration
```

## 📝 Tool API (for integration)

### `analyze_logs`
- Input: `log_files`, `bucket_minutes`, `high_error_threshold`, `max_samples`
- Output: `total_lines`, `error_lines`, `error_rate`, `pattern_counts`, `high_error_windows`, `sample_error_lines`, `human_summary`

### `search_logs_tool`
- Input: `prompt` (required), `log_files`, `max_matches`, `context_lines`
- Output: `query`, `total_matches`, `matches` (with file/line/context), `human_summary`

## ✅ Test Commands

```bash
# Check compilation
python3 -m py_compile *.py

# Test config loading
python3 -c "from config import build_config; print('✓ OK')"

# Quick analysis
python3 test_analyzer.py

# Interactive
python3 cli.py
```

## 🔍 Log Patterns Detected

- **error** — Any line with "error" (case-insensitive)
- **timeout** — "timeout", "timed out", "time out"
- **exception** — "exception", "traceback"
- **critical** — "critical", "fatal"
- **http_5xx** — 500, 501, 502, 503, 504, etc.

## 🎯 Most Common Use Cases

```
# 1. Quick overview
python3 cli.py
mcplogger> analyze

# 2. Find specific issues
mcplogger> search database timeout
mcplogger> search authentication
mcplogger> search 503

# 3. Export results
# (Copy/paste from CLI or use JSON output from server)

# 4. Add real logs
# Edit .env: LOG_FILES=/var/log/app.log,/var/log/worker.log
```

---

**Ready to start?** → `python3 cli.py`


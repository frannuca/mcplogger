# How to Run MCP Log Analyzer & Ask Questions

## Quick Start

### Option 1: Interactive CLI (Easiest) ⭐

```bash
cd /Users/fran/mcps/mcplogger
python3 cli.py
```

Then type your questions:
```
mcplogger> database connection timeout
mcplogger> search authentication failures
mcplogger> analyze
mcplogger> exit
```

### Option 2: Run MCP Server

Start the MCP server in one terminal:
```bash
python3 main.py
```

Connect with a client in another terminal (requires MCP-compatible client).

### Option 3: Direct Python (Testing)

```bash
python3 test_analyzer.py
```

---

## Option 1: Interactive CLI (Recommended for Testing)

The simplest way to interact with your logs is using `cli.py`:

```bash
python3 cli.py
```

This gives you an interactive prompt where you can:

### Command 1: `analyze`
Analyze all logs for errors, patterns, and statistics.

```
mcplogger> analyze

======================================================================
  ANALYZING LOGS
======================================================================

📄 Log Files: test_app.log
📊 Total Lines: 57
⚠️  Error Lines: 13
📈 Error Rate: 22.81%

🏷️  Error Pattern Counts:
   error         →  7 occurrences
   timeout       →  4 occurrences
   critical      →  2 occurrences
   ...
```

### Command 2: `search <prompt>`
Search logs for specific problems.

```
mcplogger> search database connection issues

======================================================================
  SEARCHING LOGS: database connection issues
======================================================================

🔍 Query: database connection issues
📊 Matches Found: 3

📋 Matching Lines:

   1. test_app.log:7
      ERROR Database query timeout after 30 seconds
      Context: 2024-03-21 08:25:42 ERROR Database query timeout after...

   2. test_app.log:10
      ERROR Failed to fetch user profile: timeout
      Context: 2024-03-21 08:25:43 ERROR Failed to fetch user profile...
```

### More Search Examples

```
# Search for timeout issues
mcplogger> search timeout

# Search for critical errors
mcplogger> search critical system failure

# Search for service availability
mcplogger> search 503 504 service unavailable

# Search for authentication problems
mcplogger> search authentication jwt token invalid

# Search for memory issues
mcplogger> search memory high usage

# Search for recovery attempts
mcplogger> search recovery restart
```

### Command 3: `help`
Show available commands.

```
mcplogger> help
```

### Exit
```
mcplogger> exit
```

---

## Option 2: MCP Server (For Integration)

If you want to run the MCP server for use with other MCP clients:

### Terminal 1: Start Server
```bash
python3 main.py
```

The server listens on stdin/stdout and accepts JSON-RPC requests.

### Terminal 2: Use Client
```bash
python3 client.py
```

This demonstrates:
- Analyzing logs for patterns
- Searching for specific issues
- Calling MCP tools programmatically

### How It Works

The MCP server exposes 2 tools:

#### Tool 1: `analyze_logs`
**Input:**
```json
{
  "log_files": ["test_app.log"],
  "bucket_minutes": 5,
  "high_error_threshold": 0.20,
  "max_samples": 10
}
```

**Output:**
```json
{
  "total_lines": 57,
  "error_lines": 13,
  "error_rate": 0.2281,
  "pattern_counts": {
    "error": 7,
    "timeout": 4,
    "critical": 2
  },
  "high_error_windows": [...],
  "sample_error_lines": [...],
  "human_summary": "..."
}
```

#### Tool 2: `search_logs_tool`
**Input:**
```json
{
  "prompt": "database connection timeout",
  "log_files": ["test_app.log"],
  "max_matches": 20,
  "context_lines": 1
}
```

**Output:**
```json
{
  "query": "database connection timeout",
  "total_matches": 3,
  "matches": [
    {
      "file": "test_app.log",
      "line_number": 7,
      "line": "ERROR Database query timeout after 30 seconds",
      "context": "2024-03-21 08:25:42 ERROR Database query timeout..."
    }
  ],
  "human_summary": "..."
}
```

---

## Option 3: Python Script (Testing)

For quick testing without CLI interaction:

```bash
python3 test_analyzer.py
```

This runs the analyzer once on the test log and displays results.

---

## Configuration

All log paths come from `.env` file:

```bash
cat .env
```

```
LOG_FILES=test_app.log
OPENAI_API_KEY=sk-your-key-here  # Optional for AI summaries
```

### Change Log Files

Edit `.env` and update `LOG_FILES`:
```
LOG_FILES=/var/log/app.log,/var/log/worker.log
```

---

## Examples of Questions You Can Ask

The CLI accepts natural language questions that are matched against logs:

```
mcplogger> search timeout
mcplogger> search error
mcplogger> search exception
mcplogger> search database
mcplogger> search connection refused
mcplogger> search 503
mcplogger> search memory
mcplogger> search critical
mcplogger> search recovery
mcplogger> search authentication
mcplogger> search fatal
```

---

## AI-Powered Analysis (Optional)

If you set `OPENAI_API_KEY` in `.env`, both tools can generate AI summaries:

```bash
# Edit .env
export OPENAI_API_KEY="sk-your-real-api-key-here"

# Run CLI
python3 cli.py

# Now it will show AI-generated insights:
# 🤖 Generating AI summary...
# 📝 Summary: Based on the logs, the system experienced...
```

---

## Architecture

```
main.py          ← MCP Server (JSON-RPC stdin/stdout)
  ↓
tools.py         ← Tool definitions (@mcp.tool())
  ├─ analyze_logs
  └─ search_logs_tool
    ↓
    analyzer.py  ← Core log analysis logic
    searcher.py  ← Log searching & pattern matching
    summarizer.py ← OpenAI integration (optional)
    config.py    ← Configuration & .env loading
    patterns.py  ← Regex patterns for errors

cli.py           ← Interactive CLI (user-friendly)
client.py        ← MCP client example
test_analyzer.py ← Test runner
```

---

## Troubleshooting

### Issue: "No module named 'mcp'"
**Solution:** Install dependencies first
```bash
python3 -m pip install -r requirements.txt
```

### Issue: "LOG_FILES not found"
**Solution:** Make sure `.env` exists and has valid paths
```bash
cat .env
ls test_app.log
```

### Issue: "OPENAI_API_KEY not set"
**This is fine** — the tools still work, just without AI summaries.

---

## Next Steps

1. **Try the CLI** — `python3 cli.py`
2. **Ask questions** — `search database timeout`
3. **Add your logs** — Update `.env` with real log paths
4. **Enable AI** — Add real `OPENAI_API_KEY` to `.env`
5. **Integrate** — Use `main.py` with MCP clients


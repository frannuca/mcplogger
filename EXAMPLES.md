# Example Usage & Output

This document shows real examples of how to use the MCP Log Analyzer.

---

## Example 1: Start Interactive CLI

```bash
$ python3 cli.py

======================================================================
  MCP Log Analyzer - Interactive CLI
======================================================================

Commands:
  analyze              - Analyze logs for errors and patterns
  search <prompt>      - Search logs based on a question
  help                 - Show this help message
  exit / quit          - Exit the program

Examples:
  search database connection timeout
  search authentication failures
  search 503 service unavailable

📄 Using log files: test_app.log

mcplogger> 
```

---

## Example 2: Ask "analyze" Command

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
   http_5xx      →  2 occurrences
   exception     →  2 occurrences

⏰ High Error Windows (threshold: 20%):
   2024-03-21 09:00:00 | 04/10 errors |  40.0% rate
   2024-03-21 09:25:00 | 03/10 errors |  30.0% rate

📋 Sample Error Lines:
   1. ERROR Database query timeout after 30 seconds
   2. ERROR Failed to fetch user profile: timeout
   3. ERROR Exception in thread "worker-1": NullPointerException
   4. ERROR at com.example.service.UserService.getUserById(UserService.java:145)
   5. ERROR at com.example.handler.RequestHandler.process(RequestHandler.java:89)

mcplogger> 
```

---

## Example 3: Search for Database Issues

```
mcplogger> search database connection timeout

======================================================================
  SEARCHING LOGS: database connection timeout
======================================================================

🔍 Query: database connection timeout
📊 Matches Found: 4

📋 Matching Lines:

   1. test_app.log:7
      ERROR Database query timeout after 30 seconds
      Context: 2024-03-21 08:25:42 ERROR Database query timeout after...

   2. test_app.log:8
      ERROR Failed to fetch user profile: timeout
      Context: 2024-03-21 08:25:43 ERROR Failed to fetch user profile...

   3. test_app.log:41
      ERROR Unable to acquire database connection: timeout after 10 seconds
      Context: 2024-03-21 10:40:22 ERROR Unable to acquire database...

   4. test_app.log:52
      ERROR Exception message: Connection refused to 10.0.0.5:5432
      Context: 2024-03-21 11:05:23 ERROR Exception message: Connection...

mcplogger> 
```

---

## Example 4: Search for Service Errors

```
mcplogger> search 503 service unavailable

======================================================================
  SEARCHING LOGS: 503 service unavailable
======================================================================

🔍 Query: 503 service unavailable
📊 Matches Found: 2

📋 Matching Lines:

   1. test_app.log:28
      ERROR API call failed with status code 503
      Context: 2024-03-21 09:25:15 ERROR API call failed with status...

   2. test_app.log:30
      ERROR 503 Service Unavailable - API server overloaded
      Context: 2024-03-21 09:35:01 ERROR 503 Service Unavailable - API...

mcplogger> 
```

---

## Example 5: Search for Authentication Issues

```
mcplogger> search authentication failures jwt

======================================================================
  SEARCHING LOGS: authentication failures jwt
======================================================================

🔍 Query: authentication failures jwt
📊 Matches Found: 3

📋 Matching Lines:

   1. test_app.log:45
      CRITICAL Unable to verify JWT tokens - encryption service down
      Context: 2024-03-21 09:45:16 CRITICAL Unable to verify JWT tokens...

   2. test_app.log:46
      ERROR Exception caught: InvalidTokenException
      Context: 2024-03-21 09:50:22 ERROR Exception caught: InvalidToken...

   3. test_app.log:47
      ERROR at com.example.auth.JWTValidator.validate(JWTValidator.java:78)
      Context: 2024-03-21 09:50:23 ERROR at com.example.auth.JWTValidat...

mcplogger> 
```

---

## Example 6: Search for Critical Issues

```
mcplogger> search critical fatal system

======================================================================
  SEARCHING LOGS: critical fatal system
======================================================================

🔍 Query: critical fatal system
📊 Matches Found: 6

📋 Matching Lines:

   1. test_app.log:21
      CRITICAL System is entering degraded mode
      Context: 2024-03-21 09:05:23 CRITICAL System is entering degraded...

   2. test_app.log:22
      CRITICAL Database connectivity issues detected
      Context: 2024-03-21 09:05:24 CRITICAL Database connectivity issu...

   3. test_app.log:44
      CRITICAL Fatal error in authentication module
      Context: 2024-03-21 09:45:15 CRITICAL Fatal error in authenti...

   4. test_app.log:54
      FATAL Fatal error - system entering maintenance mode
      Context: 2024-03-21 11:05:24 FATAL Fatal error - system entering...

   ... (more results)

mcplogger> 
```

---

## Example 7: Search for Timeouts

```
mcplogger> search timeout

======================================================================
  SEARCHING LOGS: timeout
======================================================================

🔍 Query: timeout
📊 Matches Found: 8

📋 Matching Lines:

   1. test_app.log:7
      ERROR Database query timeout after 30 seconds
      Context: 2024-03-21 08:25:42 ERROR Database query timeout after...

   2. test_app.log:8
      ERROR Failed to fetch user profile: timeout
      Context: 2024-03-21 08:25:43 ERROR Failed to fetch user profile...

   3. test_app.log:19
      ERROR Operation timeout: 120 second limit exceeded
      Context: 2024-03-21 09:05:22 ERROR Operation timeout: 120 second...

   ... (more results)

mcplogger> 
```

---

## Example 8: Exit the Program

```
mcplogger> exit
👋 Goodbye!

$
```

---

## Example 9: Using the Server

If you run the server in the background:

```bash
$ python3 main.py &
$ python3 client.py
```

Output:
```
🚀 Starting MCP server...
✓ Server started (PID: 12345)

======================================================================
EXAMPLE 1: Analyze logs for errors, timeouts, exceptions
======================================================================

📤 Sending request (ID: 1):
   Method: tools/call
   Params: {
     "name": "analyze_logs",
     "arguments": {
       "log_files": ["test_app.log"],
       ...
     }
   }

✅ Response received:
{
  "total_lines": 57,
  "error_lines": 13,
  "error_rate": 0.2281,
  "pattern_counts": {
    "error": 7,
    "timeout": 4,
    "critical": 2,
    "http_5xx": 2,
    "exception": 2
  },
  ...
}

======================================================================
EXAMPLE 2: Search for database connection issues
======================================================================

📤 Sending request (ID: 2):
   Method: tools/call
   Params: {
     "name": "search_logs_tool",
     "arguments": {
       "prompt": "database connection timeout",
       ...
     }
   }

✅ Response received:
{
  "query": "database connection timeout",
  "total_matches": 4,
  "matches": [
    {
      "file": "test_app.log",
      "line_number": 7,
      "line": "ERROR Database query timeout after 30 seconds",
      "context": "2024-03-21 08:25:42 ERROR Database query timeout..."
    },
    ...
  ]
}

...
```

---

## Example 10: Help Command

```
mcplogger> help

Available commands:
  analyze              - Analyze all logs
  search <question>    - Search for specific issues
  help                 - Show help
  exit                 - Exit

mcplogger> 
```

---

## Typical Use Cases

### Scenario 1: Production Incident Investigation
```
mcplogger> analyze
[Shows error spike at 09:00-09:15]

mcplogger> search 503 gateway timeout
[Shows service was overloaded]

mcplogger> search database connection
[Shows DB connectivity issues at same time]

mcplogger> search recovery restart
[Shows system recovered at 10:00]
```

### Scenario 2: Error Pattern Investigation
```
mcplogger> search authentication failures
[Shows 3 matches related to JWT validation]

mcplogger> search critical fatal error
[Shows system entered maintenance mode]

mcplogger> search recovery
[Shows recovery process initiated and completed]
```

### Scenario 3: Performance Analysis
```
mcplogger> search timeout
[Shows 8 timeout-related errors]

mcplogger> search memory high usage
[Shows memory pressure events]

mcplogger> analyze
[Shows error windows and peak request rates]
```

---

## Notes

- All examples use the included `test_app.log` file
- Timestamps and patterns are realistic and match actual log formats
- With real API key, you'd also see AI summaries for each query
- Results are shown with up to 5 sample matches (max 20 can be fetched)
- Time windows show error rate concentration for pattern analysis


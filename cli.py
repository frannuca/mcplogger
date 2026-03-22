#!/usr/bin/env python3
"""
Interactive MCP Log Analyzer CLI
Ask questions about your logs directly.
"""

import sys
import os
from pathlib import Path

from constants import (
    DEFAULT_BUCKET_MINUTES,
    DEFAULT_CONTEXT_LINES,
    DEFAULT_HIGH_ERROR_THRESHOLD,
    DEFAULT_MAX_MATCHES,
    DEFAULT_MAX_SAMPLES,
)

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config import build_config
from analyzer import LogAnalyzer
from searcher import search_logs
from summarizer import ChatGPTSummarizer
import requests


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def analyze_command(log_files=None):
    """Analyze logs for errors and patterns."""
    print_section("ANALYZING LOGS")

    try:
        cfg = build_config(
            log_files=log_files,
            bucket_minutes=5,
            high_error_threshold=0.20,
            max_samples=10,
            openai_model=None,
        )

        analyzer = LogAnalyzer(cfg)
        results = analyzer.analyze()

        print(f"📄 Log Files: {', '.join(results['log_files'])}")
        print(f"📊 Total Lines: {results['total_lines']}")
        print(f"⚠️  Error Lines: {results['error_lines']}")
        print(f"📈 Error Rate: {results['error_rate']*100:.2f}%\n")

        print("🏷️  Error Pattern Counts:")
        if results['pattern_counts']:
            for pattern, count in sorted(results['pattern_counts'].items(), key=lambda x: -x[1]):
                print(f"   {pattern:12} → {count:3d} occurrences")
        else:
            print("   (none)")

        print(f"\n⏰ High Error Windows (threshold: 20%):")
        if results['high_error_windows']:
            for window in results['high_error_windows']:
                print(f"   {window['window_start']} | {window['errors']:2d}/{window['total']:2d} errors | {window['error_rate']*100:5.1f}% rate")
        else:
            print("   (none)")

        print(f"\n📋 Sample Error Lines:")
        for i, line in enumerate(results['sample_error_lines'][:5], 1):
            print(f"   {i}. {line[:70]}")

        # Try to add AI summary if API key is set
        if cfg.openai_api_key:
            print("\n🤖 Generating AI summary...")
            try:
                summarizer = ChatGPTSummarizer(cfg.openai_api_key, cfg.openai_model)
                summary = summarizer.summarize_findings(results)
                print(f"\n📝 Summary:\n{summary}")
            except requests.RequestException as exc:
                print(f"⚠️  Could not generate AI summary: {exc}")

    except Exception as e:
        print(f"❌ Error: {e}")


def search_command(prompt: str, log_files=None):
    """Search logs based on a question/prompt."""
    print_section(f"SEARCHING LOGS: {prompt}")

    try:
        cfg = build_config(
            log_files=log_files,
            bucket_minutes=DEFAULT_BUCKET_MINUTES,
            high_error_threshold=DEFAULT_HIGH_ERROR_THRESHOLD,
            max_samples=DEFAULT_MAX_SAMPLES,
            openai_model=None,
        )

        results = search_logs(cfg, prompt=prompt, max_matches=DEFAULT_MAX_MATCHES, context_lines=DEFAULT_CONTEXT_LINES)

        print(f"🔍 Query: {results['query']}")
        print(f"📊 Matches Found: {results['total_matches']}\n")

        if results['matches']:
            print("📋 Matching Lines:")
            for i, match in enumerate(results['matches'][:5], 1):
                print(f"\n   {i}. {match['file']}:{match['line_number']}")
                print(f"      {match['line'][:70]}")
                print(f"      Context: {match['context'][:100]}...")
        else:
            print("   (no matches)")

        # Try to add AI explanation if API key is set
        if cfg.openai_api_key and results['matches']:
            print("\n🤖 Generating AI analysis...")
            try:
                summarizer = ChatGPTSummarizer(cfg.openai_api_key, cfg.openai_model)
                summary = summarizer.summarize_search(prompt, [m['context'] for m in results['matches'][:10]])
                print(f"\n📝 Analysis:\n{summary}")
            except requests.RequestException as exc:
                print(f"⚠️  Could not generate AI analysis: {exc}")

    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    """Interactive CLI loop."""
    print("\n" + "="*70)
    print("  MCP Log Analyzer - Interactive CLI")
    print("="*70)
    print("\nCommands:")
    print("  analyze              - Analyze logs for errors and patterns")
    print("  search <prompt>      - Search logs based on a question")
    print("  help                 - Show this help message")
    print("  exit / quit          - Exit the program")
    print("\nExamples:")
    print("  search database connection timeout")
    print("  search authentication failures")
    print("  search 503 service unavailable")
    print()

    # Get log files from .env or use test log
    import os
    log_files_str = os.getenv("LOG_FILES", "test_app.log")
    log_files = [f.strip() for f in log_files_str.split(",") if f.strip()]

    print(f"📄 Using log files: {', '.join(log_files)}\n")

    while True:
        try:
            user_input = input("mcplogger> ").strip()

            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit"]:
                print("👋 Goodbye!")
                break

            if user_input.lower() == "help":
                print("\nAvailable commands:")
                print("  analyze              - Analyze all logs")
                print("  search <question>    - Search for specific issues")
                print("  help                 - Show help")
                print("  exit                 - Exit")
                continue

            if user_input.lower() == "analyze":
                analyze_command(log_files=log_files)
                continue

            if user_input.lower().startswith("search "):
                prompt = user_input[7:].strip()
                if prompt:
                    search_command(prompt, log_files=log_files)
                else:
                    print("❌ Please provide a search query")
                continue

            # Default: treat as search query
            search_command(user_input, log_files=log_files)

        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()


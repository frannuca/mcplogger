#!/usr/bin/env python3
"""Test the log analyzer against test_app.log"""

from config import build_config
from analyzer import LogAnalyzer
import json

# Build config from .env (which points to test_app.log)
try:
    cfg = build_config(
        log_files=None,
        bucket_minutes=5,
        high_error_threshold=0.20,
        max_samples=10,
        openai_model=None
    )
    print(f"✓ Config built successfully")
    print(f"  Log files: {cfg.log_files}")
except Exception as e:
    print(f"✗ Config error: {e}")
    exit(1)

# Analyze the test log
try:
    analyzer = LogAnalyzer(cfg)
    results = analyzer.analyze()
    print(f"✓ Analysis completed")
except Exception as e:
    print(f"✗ Analysis error: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Print results
print("\n" + "="*70)
print("TEST LOG ANALYSIS RESULTS")
print("="*70 + "\n")

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

print("\n" + "="*70)


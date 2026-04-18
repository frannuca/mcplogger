#!/usr/bin/env python3
"""
log_generator.py — Continuously generates realistic log lines into test_app.log.

The file is appended to in real-time (a few lines per second) so the MCP
server can tail it live.  When the file exceeds ~50 MB it is deleted and
recreated from scratch.

Usage:
    uv run python log_generator.py                        # default: test_app.log
    uv run python log_generator.py /tmp/myapp.log         # custom path
    uv run python log_generator.py --rate 100              # lines per second

Press Ctrl+C to stop.
"""

import argparse
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── limits ────────────────────────────────────────────────────────────────────
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# ── applications ──────────────────────────────────────────────────────────────
APPS = [
    "payment-service",
    "user-api",
    "order-processor",
    "auth-gateway",
    "inventory-service",
    "notification-worker",
    "search-indexer",
    "billing-engine",
    "analytics-pipeline",
    "cache-manager",
]

THREADS = [
    "main", "worker-1", "worker-2", "worker-3", "http-nio-8080-exec-1",
    "http-nio-8080-exec-2", "scheduler-1", "async-pool-4", "db-pool-7",
    "grpc-handler-3",
]

# ── fake URLs / hosts ─────────────────────────────────────────────────────────
HOSTS = [
    "https://api.payments.internal:8443",
    "https://db-primary.us-east-1.rds.amazonaws.com:5432",
    "https://db-replica.us-east-1.rds.amazonaws.com:5432",
    "https://redis-cluster.cache.internal:6379",
    "https://kafka-broker-1.mq.internal:9092",
    "https://kafka-broker-2.mq.internal:9092",
    "https://es-node-1.search.internal:9200",
    "https://consul.service.internal:8500",
    "https://vault.secrets.internal:8200",
    "https://s3.us-east-1.amazonaws.com",
    "http://10.0.5.12:8080",
    "http://10.0.5.13:8080",
    "http://10.0.5.14:3000",
    "http://172.16.0.50:9090",
    "https://api.stripe.com/v1",
    "https://hooks.slack.com/services/T00/B00/xxx",
    "https://sqs.us-east-1.amazonaws.com/123456789/orders",
    "https://monitoring.grafana.internal:3000",
]

PATHS = [
    "/api/v1/users", "/api/v1/orders", "/api/v1/payments/charge",
    "/api/v1/auth/token", "/api/v1/inventory/check", "/api/v2/search",
    "/api/v1/notifications/send", "/health", "/ready", "/metrics",
    "/api/v1/billing/invoice", "/api/v1/analytics/events",
]

HTTP_CODES_ERROR = [500, 502, 503, 504, 520, 521, 522, 524]

# ── timeout durations ─────────────────────────────────────────────────────────
TIMEOUTS = [
    (30,    "30s"),
    (30,    "30 seconds"),
    (45,    "45s"),
    (60,    "1 minute"),
    (60,    "60s"),
    (60,    "60 seconds"),
    (90,    "90s"),
    (120,   "2 minutes"),
    (180,   "3 minutes"),
    (300,   "5 minutes"),
    (300,   "300s"),
    (300,   "5 min"),
    (600,   "10 minutes"),
]

# ── error templates ───────────────────────────────────────────────────────────

def _app():   return random.choice(APPS)
def _host():  return random.choice(HOSTS)
def _path():  return random.choice(PATHS)
def _thread(): return random.choice(THREADS)
def _code():  return random.choice(HTTP_CODES_ERROR)
def _timeout(): return random.choice(TIMEOUTS)

def gen_timeout_line(ts):
    """Timeout errors with varying durations."""
    secs, label = _timeout()
    templates = [
        f"{ts} ERROR [{_app()}] [{_thread()}] Request to {_host()}{_path()} timed out after {label}",
        f"{ts} ERROR [{_app()}] Database query exceeded deadline of {label} — aborting transaction",
        f"{ts} ERROR [{_app()}] [{_thread()}] Upstream service did not respond within {label}; circuit breaker OPEN",
        f"{ts} ERROR [{_app()}] gRPC deadline exceeded: {secs}s waiting for {_host()}",
        f"{ts} CRITICAL [{_app()}] Connection to {_host()} timed out after {label} — no healthy backends",
        f"{ts} ERROR [{_app()}] [{_thread()}] Timeout waiting for lock on resource orders/{random.randint(1000,9999)} after {label}",
        f"{ts} WARNING [{_app()}] Slow response from {_host()}{_path()}: {secs + random.randint(1,20)}s (deadline {label})",
        f"{ts} ERROR [{_app()}] HTTP request to {_host()}{_path()} failed: read timeout after {label}",
        f"{ts} ERROR [{_app()}] [{_thread()}] Task execution exceeded {label} deadline — cancelled",
        f"{ts} ERROR [{_app()}] Socket timeout after {label} connecting to {_host()}",
    ]
    return random.choice(templates)

def gen_connectivity_line(ts):
    """Connection refused / unreachable / DNS errors."""
    host = _host()
    templates = [
        f"{ts} ERROR [{_app()}] Connection refused by {host} — is the service running?",
        f"{ts} ERROR [{_app()}] [{_thread()}] Failed to connect to {host}: Connection refused (errno 111)",
        f"{ts} CRITICAL [{_app()}] No route to host {host} — network unreachable",
        f"{ts} ERROR [{_app()}] DNS resolution failed for {host.split('//')[1].split(':')[0]}: NXDOMAIN",
        f"{ts} ERROR [{_app()}] [{_thread()}] SSL handshake failed with {host}: certificate has expired",
        f"{ts} ERROR [{_app()}] Connection to {host} reset by peer after {random.randint(1,15)}s",
        f"{ts} ERROR [{_app()}] [{_thread()}] Max retries (3) exhausted for {host}{_path()} — giving up",
        f"{ts} ERROR [{_app()}] TCP connect to {host} failed: Operation timed out",
        f"{ts} CRITICAL [{_app()}] All backends for {host} are DOWN — entering fallback mode",
        f"{ts} ERROR [{_app()}] [{_thread()}] Connection pool exhausted for {host} (max=50, active=50, waiting=120)",
        f"{ts} ERROR [{_app()}] ECONNREFUSED {host}{_path()} — upstream returned nothing",
        f"{ts} ERROR [{_app()}] [{_thread()}] Broken pipe writing to {host} — remote closed connection",
    ]
    return random.choice(templates)

def gen_http_error_line(ts):
    """HTTP 5xx errors."""
    code = _code()
    host = _host()
    path = _path()
    templates = [
        f"{ts} ERROR [{_app()}] [{_thread()}] {code} {host}{path} — upstream error",
        f"{ts} ERROR [{_app()}] HTTP {code} from {host}{path}: service unavailable",
        f"{ts} ERROR [{_app()}] [{_thread()}] POST {host}{path} returned {code} in {random.randint(100,30000)}ms",
        f"{ts} ERROR [{_app()}] Gateway error {code} — {host} did not respond in time",
    ]
    return random.choice(templates)

def gen_exception_line(ts):
    """Application exceptions."""
    exceptions = [
        ("NullPointerException", "at com.example.service.OrderService.process(OrderService.java:{})"),
        ("OutOfMemoryError", "Java heap space — allocating {}MB for result set"),
        ("IllegalStateException", "Transaction already committed on connection pool #{}"),
        ("ConnectionPoolTimeoutException", "Waited {}ms for a connection from pool"),
        ("SocketTimeoutException", "Read timed out after {}ms"),
        ("IOException", "Broken pipe writing response to client"),
        ("RedisConnectionException", "Failed to connect to redis-cluster.cache.internal:6379"),
        ("KafkaProducerException", "Delivery failed for topic orders-events partition {}"),
        ("SQLTransientConnectionException", "Connection to db-primary closed unexpectedly"),
        ("CircuitBreakerOpenException", "Circuit breaker for {} is OPEN — rejecting request"),
    ]
    exc_name, detail_tpl = random.choice(exceptions)
    # only format if there's a placeholder
    detail = detail_tpl.format(random.randint(1, 9999)) if "{}" in detail_tpl else detail_tpl
    return f"{ts} ERROR [{_app()}] [{_thread()}] Exception: {exc_name}: {detail}"

def gen_disk_line(ts):
    """Disk / storage errors."""
    templates = [
        f"{ts} CRITICAL [{_app()}] No space left on device /data — disk usage 100%",
        f"{ts} ERROR [{_app()}] ENOSPC writing to /var/log/{_app()}/app.log",
        f"{ts} ERROR [{_app()}] Disk I/O error on /dev/sda1: read-only file system",
        f"{ts} WARNING [{_app()}] Disk usage at 94% on /data — approaching quota",
        f"{ts} CRITICAL [{_app()}] Inode limit reached on /var/data — cannot create new files",
        f"{ts} ERROR [{_app()}] Write to {_host()}/bucket/backups failed: storage quota exceeded",
    ]
    return random.choice(templates)

def gen_normal_line(ts):
    """Normal INFO/DEBUG lines to mix in."""
    templates = [
        f"{ts} INFO [{_app()}] [{_thread()}] Request completed in {random.randint(1,500)}ms — 200 OK",
        f"{ts} INFO [{_app()}] Processed {random.randint(1,1000)} events in {random.randint(100,5000)}ms",
        f"{ts} DEBUG [{_app()}] [{_thread()}] Cache hit for key user:{random.randint(1,99999)}",
        f"{ts} INFO [{_app()}] Health check passed — all dependencies healthy",
        f"{ts} DEBUG [{_app()}] [{_thread()}] Loaded {random.randint(10,500)} records from db-replica",
        f"{ts} INFO [{_app()}] [{_thread()}] JWT token validated for user {random.randint(1000,9999)}",
        f"{ts} INFO [{_app()}] Scheduled job UserCache_Update completed in {random.randint(1,30)}s",
        f"{ts} DEBUG [{_app()}] Metrics exported: cpu=0.{random.randint(10,95)} mem=0.{random.randint(40,90)}",
    ]
    return random.choice(templates)

# ── weighted line generator ───────────────────────────────────────────────────
# ~35% errors, ~65% normal — feels realistic
GENERATORS = [
    (gen_timeout_line,      15),
    (gen_connectivity_line, 10),
    (gen_http_error_line,    5),
    (gen_exception_line,     3),
    (gen_disk_line,          2),
    (gen_normal_line,       65),
]
_GEN_POOL = []
for fn, weight in GENERATORS:
    _GEN_POOL.extend([fn] * weight)

def generate_line(ts: str) -> str:
    return random.choice(_GEN_POOL)(ts)


# ── main loop ─────────────────────────────────────────────────────────────────

def run(log_path: Path, rate: int):
    current_time = datetime.now()  # only used for rotation reset message
    lines_written = 0
    rotations = 0

    print(f"📝  Writing to {log_path}  (max {MAX_FILE_SIZE // (1024*1024)} MB, {rate} lines/sec)")
    print(f"    Timestamps use real system clock.")
    print(f"    Press Ctrl+C to stop.\n")

    while True:
        # check file size — rotate if over limit
        try:
            size = log_path.stat().st_size if log_path.exists() else 0
        except OSError:
            size = 0

        if size >= MAX_FILE_SIZE:
            rotations += 1
            print(f"\n🔄  File reached {size / (1024*1024):.1f} MB — deleting and restarting (rotation #{rotations})")
            log_path.unlink(missing_ok=True)
            lines_written = 0

        # write a batch
        batch_size = max(1, rate // 10)  # write in small bursts
        try:
            with open(log_path, "a") as f:
                for _ in range(batch_size):
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    line = generate_line(ts)
                    f.write(line + "\n")
                    lines_written += 1
        except OSError as exc:
            print(f"✗  Write error: {exc}", file=sys.stderr)
            time.sleep(1)
            continue

        # progress
        try:
            cur_size = log_path.stat().st_size
        except OSError:
            cur_size = 0
        mb = cur_size / (1024 * 1024)
        pct = (cur_size / MAX_FILE_SIZE) * 100
        sys.stdout.write(
            f"\r  {lines_written:>8,} lines | {mb:>6.1f} MB / {MAX_FILE_SIZE//(1024*1024)} MB ({pct:.0f}%)  "
        )
        sys.stdout.flush()

        # throttle to target rate
        time.sleep(batch_size / rate)


def main():
    parser = argparse.ArgumentParser(description="Generate realistic log data for MCP testing")
    parser.add_argument("logfile", nargs="?", default="test_app.log", help="Path to log file (default: test_app.log)")
    parser.add_argument("--rate", type=int, default=50, help="Lines per second (default: 50)")
    args = parser.parse_args()

    log_path = Path(args.logfile).resolve()

    try:
        run(log_path, args.rate)
    except KeyboardInterrupt:
        try:
            size = log_path.stat().st_size / (1024 * 1024)
        except OSError:
            size = 0
        print(f"\n\n🛑  Stopped. File: {log_path} ({size:.1f} MB)")


if __name__ == "__main__":
    main()


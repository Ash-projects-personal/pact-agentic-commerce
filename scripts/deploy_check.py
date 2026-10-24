"""Deploy check: boot the app exactly the way Render will, then verify it.

Boots `uvicorn pact.main:app --host 0.0.0.0 --port $PORT` (the exact
render.yaml startCommand) against a scratch port and a throwaway SQLite
database, waits for /api/ready, runs the repo's standard smoke suite as a
subprocess, and probes the booted server's endpoints. Prints a PASS/FAIL
summary and exits non zero on any failure.

Always runs in demo mode: PayPal credentials are stripped from the child
environment. No secrets are printed.

Run with:
    cd ~/workspace/projects/pact-agentic-commerce
    .venv/bin/python scripts/deploy_check.py
"""

import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Demo mode: never boot against live PayPal credentials.
DEMO_STRIP = (
    "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID",
    "SELLER_SANDBOX_EMAIL", "BUYER_SANDBOX_EMAIL", "LLM_API_KEY",
    "CHANNEL3_API_KEY",
)


def free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def child_env(db_path, port):
    env = dict(os.environ)
    for var in DEMO_STRIP:
        env.pop(var, None)
    env["PACT_DB_PATH"] = db_path
    env["PORT"] = str(port)
    env["NO_PROXY"] = "localhost,127.0.0.1"
    env["no_proxy"] = "localhost,127.0.0.1"
    return env


def http_get(base, path, timeout=10):
    req = urllib.request.Request(base + path)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers, resp.read().decode("utf-8")


def wait_for_ready(base, deadline_s=90):
    start = time.time()
    last = None
    while time.time() - start < deadline_s:
        try:
            status, _, body = http_get(base, "/api/ready")
            if status == 200:
                parsed = json.loads(body)
                if parsed.get("status") == "ready":
                    return parsed
            last = f"{status}: {body[:120]}"
        except Exception as exc:  # server still booting
            last = repr(exc)
        time.sleep(1.0)
    return None


def main():
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
              + (f" -- {detail}" if detail else ""), flush=True)

    print("Pact deploy check")
    print(f"  project root: {ROOT}")

    port = free_port()
    if port == 8000:
        port = free_port()
    tmpdir = tempfile.mkdtemp(prefix="pact-deploy-check-")
    db_path = os.path.join(tmpdir, "pact.db")
    env = child_env(db_path, port)
    base = f"http://127.0.0.1:{port}"

    # 1. Boot exactly the way render.yaml does.
    print(f"  booting uvicorn on scratch port {port} ...")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "pact.main:app",
         "--host", "0.0.0.0", "--port", str(port)],
        cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        ready = wait_for_ready(base)
        record("server boots and /api/ready answers 200",
               ready is not None,
               f"checks={ready['checks']}" if ready else "never became ready")
        if ready is None:
            record("smoke suite", False, "skipped, server not ready")
        else:
            record("readiness checks name config and database",
                   "config" in ready["checks"] and "database" in ready["checks"])
            # 2. The repo's standard smoke suite as a subprocess. Its
            # TestClient boots its own app instance in process, which
            # exercises the lifespan handler and the persistence
            # middleware against a scratch database.
            print("  running tests/smoke_test.py as subprocess ...")
            smoke_env = child_env(
                os.path.join(tempfile.mkdtemp(prefix="pact-smoke-"),
                             "pact.db"),
                8199)
            proc = subprocess.run(
                [sys.executable, "tests/smoke_test.py"],
                cwd=ROOT, env=smoke_env, capture_output=True, text=True,
                timeout=600,
            )
            record("smoke suite passes",
                   proc.returncode == 0,
                   "exit 0" if proc.returncode == 0
                   else proc.stdout[-2000:] + proc.stderr[-2000:])

            # 3. Probe the Render-style booted server directly.
            for path, label in (("/api/health", "health"),
                                ("/api/scenarios", "scenarios"),
                                ("/api/agents", "agents"),
                                ("/", "static index")):
                try:
                    status, headers, _ = http_get(base, path)
                    record(f"GET {path} -> 200", status == 200,
                           f"got {status}" if status != 200 else "")
                    if status == 200 and path == "/api/health":
                        record(
                            "security headers present",
                            headers.get("X-Content-Type-Options") == "nosniff"
                            and headers.get("X-Frame-Options") == "DENY"
                            and headers.get("Referrer-Policy") == "same-origin"
                            and headers.get("Cross-Origin-Opener-Policy")
                            == "same-origin",
                            "missing header" if not (
                                headers.get("X-Content-Type-Options")
                                == "nosniff") else "",
                        )
                except Exception as exc:
                    record(f"GET {path} -> 200", False, repr(exc))

            # 4. Persistence proof: the booted server must have written a
            # real database file with the seeded agents in it.
            try:
                conn = sqlite3.connect(db_path)
                agents = conn.execute(
                    "SELECT COUNT(*) FROM agents").fetchone()[0]
                deals = conn.execute(
                    "SELECT COUNT(*) FROM deals").fetchone()[0]
                conn.close()
                record("SQLite database written with seeded agents",
                       agents >= 8,
                       f"agents={agents} deals={deals}")
            except Exception as exc:
                record("SQLite database written with seeded agents",
                       False, repr(exc))
    finally:
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("SUMMARY")
    failed = [name for name, ok, _ in results if not ok]
    for name, ok, _ in results:
        print(f"  {'PASS' if ok else 'FAIL'} {name}")
    if failed:
        print(f"DEPLOY CHECK FAILED: {len(failed)} check(s) failed")
        return 1
    print("DEPLOY CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

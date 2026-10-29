#!/usr/bin/env python3
"""PactBench load check: 50 parallel demo-mode deals settled end to end.

Boots a scratch uvicorn server (free port, throwaway SQLite at a temp
PACT_DB_PATH, demo-mode env with PayPal credentials and the LLM key
stripped), waits for /api/ready, then drives 50 deals concurrently with
asyncio + httpx through the full demo lifecycle:

    POST /api/deals -> /negotiate/run -> /pay -> /deliver -> /verify
    (deliver/verify repeat on revision rounds until a terminal state)

Latency is measured client-side with time.perf_counter around each HTTP
operation, and percentiles are computed from the measured values with a
small local helper (no numpy; no number is hand-typed). Every deal must
reach a terminal state ("released" or "refunded"); anything else is an
honest failure recorded in the JSON with its error.

Deal content: scenarios cycle across all 15 scenario ids (order taken
from /api/scenarios); buyer_max / seller_floor / bond_percent are drawn
from random.Random(SEED) so the run is reproducible.

Run with:  NO_PROXY=localhost,127.0.0.1 .venv/bin/python experiments/pactbench_load.py
Writes:    experiments/pactbench_load_results.json
Exits non zero unless the JSON was written and every deal is terminal.

Safety: demo mode only, no real money, never prints any secret.
"""

import asyncio
import json
import math
import os
import random
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import httpx

SEED = 20261023
N_DEALS = 50
CONCURRENCY = 10
REQUEST_TIMEOUT_S = 120.0
READY_DEADLINE_S = 90
MAX_VERIFY_ROUNDS = 6
TERMINAL_STATES = ("released", "refunded")

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = ROOT / "experiments" / "pactbench_load_results.json"

# Demo mode: live mode is when PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET is
# present, so popping these (plus the LLM key) from the server env forces
# demo mode. Popped only; never read, never printed.
DEMO_STRIP = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY")


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
    # This driver settles 50 deals in seconds, far past the demo abuse
    # caps (queue item Z: 30/min per IP). The caps are env-driven and a
    # value of 0 disables them, so the load harness opts out here; the
    # caps themselves are covered by tests/abuse_limit_test.py.
    env["PACT_MAX_DEALS_PER_MINUTE_PER_IP"] = "0"
    env["PACT_MAX_DEALS_PER_MINUTE_GLOBAL"] = "0"
    return env


def http_get(base, path, timeout=10):
    req = urllib.request.Request(base + path)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8")


def wait_for_ready(base, deadline_s=READY_DEADLINE_S):
    start = time.time()
    last = None
    while time.time() - start < deadline_s:
        try:
            status, body = http_get(base, "/api/ready")
            if status == 200:
                parsed = json.loads(body)
                if parsed.get("status") == "ready":
                    return parsed
            last = f"{status}: {body[:120]}"
        except Exception as exc:  # server still booting
            last = repr(exc)
        time.sleep(1.0)
    raise RuntimeError(f"server never became ready: {last}")


def percentile(values, q):
    """Linear-interpolation percentile over a list of measured values."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (q / 100.0) * (len(s) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return s[int(rank)]
    frac = rank - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


def summarize(values):
    n = len(values)
    return {
        "count": n,
        "mean": round(sum(values) / n, 3) if n else None,
        "p50": round(percentile(values, 50), 3) if n else None,
        "p95": round(percentile(values, 95), 3) if n else None,
        "p99": round(percentile(values, 99), 3) if n else None,
        "max": round(max(values), 3) if values else None,
    }


async def timed_post(client, path, body=None, headers=None):
    """POST and return (parsed body, client-side latency in ms)."""
    t0 = time.perf_counter()
    resp = await client.post(path, json=body or {}, headers=headers)
    ms = (time.perf_counter() - t0) * 1000.0
    if resp.status_code != 200:
        raise RuntimeError(
            f"POST {path} -> {resp.status_code}: {resp.text[:400]}")
    return resp.json(), ms


async def run_deal(client, sem, idx, params):
    """Run one deal end to end. Returns a result dict (never raises)."""
    lat = {"create": [], "negotiate": [], "pay": [],
           "deliver": [], "verify": []}
    deal_id = None
    state = "unknown"
    rounds = 0
    e2e_ms = None
    error = None
    t_start = time.perf_counter()
    try:
        async with sem:
            deal, ms = await timed_post(client, "/api/deals", params)
            deal_id = deal["id"]
            lat["create"].append(ms)
            # Queue item W: state-changing endpoints need the per-deal
            # role token in the X-Deal-Token header. The create response
            # carries both tokens; deliver acts as the seller.
            buyer_hdr = {"X-Deal-Token": deal["buyer_token"]}
            seller_hdr = {"X-Deal-Token": deal["seller_token"]}

            deal, ms = await timed_post(
                client, f"/api/deals/{deal_id}/negotiate/run",
                headers=buyer_hdr)
            lat["negotiate"].append(ms)
            state = deal["state"]
            if state != "agreed":
                raise RuntimeError(
                    f"negotiation ended in state {state!r}, not 'agreed'")

            deal, ms = await timed_post(client, f"/api/deals/{deal_id}/pay",
                                        headers=buyer_hdr)
            lat["pay"].append(ms)
            state = deal["state"]
            if state != "paid_held":
                raise RuntimeError(
                    f"pay ended in state {state!r}, not 'paid_held'")

            for rounds in range(1, MAX_VERIFY_ROUNDS + 1):
                deal, ms = await timed_post(
                    client, f"/api/deals/{deal_id}/deliver",
                    {"quality": "auto"}, headers=seller_hdr)
                lat["deliver"].append(ms)
                state = deal["state"]
                if state != "delivered":
                    raise RuntimeError(
                        f"deliver ended in state {state!r}, not 'delivered'")

                deal, ms = await timed_post(
                    client, f"/api/deals/{deal_id}/verify",
                    headers=buyer_hdr)
                lat["verify"].append(ms)
                state = deal["state"]
                if state in TERMINAL_STATES:
                    break
                if state != "revision":
                    raise RuntimeError(
                        f"verify ended in state {state!r} (not terminal "
                        f"and not 'revision')")
            else:
                raise RuntimeError(
                    f"still not terminal after {MAX_VERIFY_ROUNDS} rounds "
                    f"(state {state!r})")

            if state not in TERMINAL_STATES:
                raise RuntimeError(
                    f"finished in non-terminal state {state!r}")
    except Exception as exc:  # noqa: BLE001 -- honest failure capture
        error = f"{type(exc).__name__}: {exc}"
    e2e_ms = (time.perf_counter() - t_start) * 1000.0
    return {
        "index": idx,
        "deal_id": deal_id,
        "scenario_id": params["scenario_id"],
        "params": params,
        "state": state,
        "rounds": rounds,
        "e2e_ms": round(e2e_ms, 3),
        "latencies": lat,
        "error": error,
    }


def make_deal_params(scenario_order, by_id, seed):
    """Deterministic per-deal params: scenario cycles, money randomized."""
    rng = random.Random(seed)
    out = []
    for i in range(N_DEALS):
        sid = scenario_order[i % len(scenario_order)]
        info = by_id[sid]
        body = {"scenario_id": sid}
        if sid == "procurement":
            # Keep the market-grounded defaults: the candidate checks are
            # built from real Channel3 fixture offers at deal creation.
            pass
        else:
            buyer_max = round(
                info["default_buyer_max"] * rng.uniform(0.7, 1.3), 2)
            seller_floor = round(
                info["default_seller_floor"] * rng.uniform(0.7, 1.1), 2)
            if buyer_max < seller_floor * 1.05:
                # Negotiation can only converge when buyer_max >= floor.
                buyer_max = round(seller_floor * 1.2, 2)
            body["buyer_max"] = buyer_max
            body["seller_floor"] = seller_floor
        body["bond_percent"] = round(rng.uniform(5.0, 40.0), 1)
        out.append(body)
    return out


async def drive(base, params_list):
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
    timeout = httpx.Timeout(REQUEST_TIMEOUT_S)
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(base_url=base, limits=limits,
                                timeout=timeout,
                                # The sandbox has proxy env vars set and
                                # NO_PROXY=localhost,127.0.0.1 on this run;
                                # the scratch server is on 127.0.0.1 anyway,
                                # so skip env proxy resolution entirely.
                                trust_env=False) as client:
        tasks = [run_deal(client, sem, idx, p)
                 for idx, p in enumerate(params_list)]
        return await asyncio.gather(*tasks)


def main():
    print("PactBench load check: 50 parallel demo-mode deals", flush=True)
    port = free_port()
    if port == 8000:
        port = free_port()
    tmpdir = tempfile.mkdtemp(prefix="pact-load-check-")
    db_path = os.path.join(tmpdir, "pact.db")
    env = child_env(db_path, port)
    base = f"http://127.0.0.1:{port}"

    print(f"  booting scratch uvicorn on port {port} (demo env, "
          f"throwaway db) ...", flush=True)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "pact.main:app",
         "--host", "0.0.0.0", "--port", str(port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        ready = wait_for_ready(base)
        print(f"  ready: checks={ready['checks']}", flush=True)
        status, body = http_get(base, "/api/health")
        health = json.loads(body)
        mode = health.get("mode")
        if mode != "demo":
            raise RuntimeError(
                f"REFUSING TO RUN: server mode is {mode!r}, not 'demo'")
        rail = (health.get("agent_toolkit") or {}).get("orders_rail")
        print(f"  health: mode={mode}, orders_rail={rail}", flush=True)

        status, body = http_get(base, "/api/scenarios")
        scenarios = json.loads(body)
        scenario_order = [s["id"] for s in scenarios]
        by_id = {s["id"]: s for s in scenarios}
        print(f"  scenarios: {len(scenario_order)} "
              f"({', '.join(scenario_order)})", flush=True)
        assert len(scenario_order) == 14, scenario_order

        params_list = make_deal_params(scenario_order, by_id, SEED)

        print(f"  driving {N_DEALS} deals (seed {SEED}, "
              f"concurrency {CONCURRENCY}) ...", flush=True)
        wall_t0 = time.perf_counter()
        results = asyncio.run(drive(base, params_list))
        wall_s = time.perf_counter() - wall_t0
        print(f"  all coroutines done in {wall_s:.1f}s wall", flush=True)

        per_op = {"create": [], "negotiate": [], "pay": [],
                  "deliver": [], "verify": []}
        e2e = []
        terminal = {}
        failures = []
        for r in results:
            for op, vals in r["latencies"].items():
                per_op[op].extend(vals)
            e2e.append(r["e2e_ms"])
            terminal[r["state"]] = terminal.get(r["state"], 0) + 1
            entry = {
                "index": r["index"],
                "deal_id": r["deal_id"],
                "scenario_id": r["scenario_id"],
                "buyer_max": r["params"].get("buyer_max"),
                "seller_floor": r["params"].get("seller_floor"),
                "bond_percent": r["params"]["bond_percent"],
                "state": r["state"],
                "verify_rounds": r["rounds"],
                "e2e_ms": r["e2e_ms"],
            }
            if r["error"] or r["state"] not in TERMINAL_STATES:
                failures.append({**entry, "error": r["error"]
                                 or f"non-terminal state {r['state']!r}"})

        payload = {
            "n_deals": N_DEALS,
            "seed": SEED,
            "concurrency": CONCURRENCY,
            "server": {
                "mode": mode,
                "orders_rail": rail,
                "scratch_port": port,
                "scratch_db": True,
            },
            "scenario_order": scenario_order,
            "per_operation_latency_ms": {
                op: summarize(vals) for op, vals in per_op.items()},
            "end_to_end_latency_ms": summarize(e2e),
            "terminal_states": terminal,
            "failures": failures,
            "total_wall_time_s": round(wall_s, 3),
            "deals": [d for r in results for d in [{
                "index": r["index"],
                "deal_id": r["deal_id"],
                "scenario_id": r["scenario_id"],
                "state": r["state"],
                "e2e_ms": r["e2e_ms"],
            }]],
            "method": (
                "Scratch uvicorn server on a free port with a throwaway "
                "SQLite DB (PACT_DB_PATH), PayPal client id/secret and the "
                "LLM key popped from the server env so the app boots in "
                f"demo mode (verified via /api/health mode={mode}). "
                f"{N_DEALS} deals driven concurrently (semaphore "
                f"{CONCURRENCY}) with asyncio + httpx through create, "
                "negotiate/run, pay, deliver, verify, repeating "
                "deliver/verify on revision rounds until a terminal state "
                "(released/refunded). Latency measured client-side with "
                "time.perf_counter around each HTTP op; percentiles are "
                "linear-interpolation over the measured values. Deal "
                "params from random.Random(seed): scenario cycles the 14 "
                "ids, buyer_max = default * U(0.7,1.3), seller_floor = "
                "default * U(0.7,1.1) (buyer_max floored at 1.2x floor so "
                "negotiation converges), bond_percent = U(5,40); the "
                "procurement scenario keeps its market-grounded defaults. "
                "The live dev server and data/pact.db were not touched."
            ),
        }
        RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"  wrote {RESULTS_PATH}", flush=True)

        print("  per-operation latency (ms):", flush=True)
        for op, s in payload["per_operation_latency_ms"].items():
            print(f"    {op:10s} p50={s['p50']} p95={s['p95']} "
                  f"p99={s['p99']} max={s['max']} mean={s['mean']} "
                  f"(n={s['count']})", flush=True)
        e2e_s = payload["end_to_end_latency_ms"]
        print(f"  end-to-end per deal (ms): p50={e2e_s['p50']} "
              f"p95={e2e_s['p95']} p99={e2e_s['p99']} max={e2e_s['max']} "
              f"mean={e2e_s['mean']}", flush=True)
        print(f"  terminal states: {terminal}", flush=True)
        print(f"  failures: {len(failures)}", flush=True)
        for f in failures:
            print(f"    deal {f['index']} ({f['scenario_id']}): "
                  f"{f['error']}", flush=True)

        if failures:
            print("LOAD CHECK FAILED: not all deals reached a terminal "
                  "state", flush=True)
            return 1
        if sum(terminal.values()) != N_DEALS:
            print("LOAD CHECK FAILED: terminal count mismatch", flush=True)
            return 1
        print("LOAD CHECK PASSED", flush=True)
        return 0
    finally:
        # Kill the exact child process; never pkill -f patterns.
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())

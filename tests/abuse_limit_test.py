"""Abuse limit tests (queue item Z).

Deal creation carries two sliding-window rate caps: per client address
and global, env-driven with demo-friendly defaults (30/min per IP,
120/min global, 60s window). The negotiation and delivery endpoints
carry a 64KB request-body size cap. Over-limit calls get the clean
error envelope {"error": {"code", "message", "correlation_id"}}: 429
RATE_LIMITED with a Retry-After header, 413 PAYLOAD_TOO_LARGE.

The module clock is poked to fake the window passing; no test sleeps.
The rate window counters are reset between sections.

Run with: NO_PROXY=localhost,127.0.0.1 python tests/abuse_limit_test.py
Exits non zero on the first failed assertion. Demo mode only.
"""

import os
import re
import sys
import tempfile
import time
from pathlib import Path

# Force demo mode before the app modules read the environment.
for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

# Isolate persistence: the middleware writes the store to SQLite after
# every response, so point the test run at a throwaway database that
# never touches the real dev database at data/pact.db.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-abuse.db")

# Start from the shipped defaults; each test overrides what it needs
# and restores them after.
CAP_VARS = ("PACT_MAX_DEALS_PER_MINUTE_PER_IP",
            "PACT_MAX_DEALS_PER_MINUTE_GLOBAL",
            "PACT_RATE_WINDOW_SECONDS",
            "PACT_MAX_REQUEST_BYTES")
for var in CAP_VARS:
    os.environ.pop(var, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pact import abuse_limits  # noqa: E402
from pact.main import app  # noqa: E402

TOKEN_HEADER = "X-Deal-Token"

CHECKS = 0


def check(name, cond, detail=""):
    """One counted check. Fails loudly on the first violation."""
    global CHECKS
    CHECKS += 1
    print(f"  {'PASS' if cond else 'FAIL'} {name}"
          f"{'' if cond else ' ' + str(detail)}")
    if not cond:
        raise AssertionError(f"FAILED: {name} {detail}")


def clean_envelope(resp, code, status):
    """The clean error envelope: only the error key, the expected
    code, a human sentence, and a correlation id. No raw internals."""
    if resp.status_code != status:
        return False
    try:
        body = resp.json()
    except Exception:
        return False
    if set(body.keys()) != {"error"}:
        return False
    err = body["error"]
    if err.get("code") != code:
        return False
    if not (isinstance(err.get("message"), str)
            and len(err["message"]) > 10):
        return False
    cid = err.get("correlation_id")
    if not (isinstance(cid, str) and len(cid) >= 16):
        return False
    banned = ("Traceback", "KeyError", "ValueError", 'File "',
              "token_urlsafe", "secrets.")
    return not any(b in resp.text for b in banned)


# Demo client token store (queue item W): state-changing deal endpoints
# require the per-deal role token in the X-Deal-Token header. The create
# response carries both tokens, so this helper remembers them per deal
# id and attaches the right one, the way a real client would. Deliver
# acts as the seller; everything else here acts as the buyer.
_DEAL_TOKENS = {}


def post(client, path, body=None, raw=None):
    m = re.match(r"^/api/deals/([^/]+)/", path)
    headers = None
    if m:
        role = ("seller" if path.rstrip("/").endswith("/deliver")
                else "buyer")
        tok = _DEAL_TOKENS.get(m.group(1), {}).get(role)
        if tok:
            headers = {TOKEN_HEADER: tok}
    if raw is not None:
        resp = client.post(path, content=raw, headers=headers)
    else:
        resp = client.post(path, json=body if body is not None else {},
                           headers=headers)
    try:
        data = resp.json()
    except Exception:
        data = resp.text
    if (resp.status_code == 200 and isinstance(data, dict)
            and data.get("id") and data.get("buyer_token")):
        _DEAL_TOKENS[data["id"]] = {
            "buyer": data.get("buyer_token"),
            "seller": data.get("seller_token"),
        }
    return resp, data


def create(client, **kwargs):
    resp, data = post(client, "/api/deals",
                      {"scenario_id": "logo_brand_kit", **kwargs})
    return resp, data


def set_caps(per_ip=None, glob=None, window=None, max_bytes=None):
    for var, val in (("PACT_MAX_DEALS_PER_MINUTE_PER_IP", per_ip),
                     ("PACT_MAX_DEALS_PER_MINUTE_GLOBAL", glob),
                     ("PACT_RATE_WINDOW_SECONDS", window),
                     ("PACT_MAX_REQUEST_BYTES", max_bytes)):
        if val is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = str(val)


def fresh_state(clock_t=None):
    """Back to the shipped defaults, empty windows, real or poked clock."""
    set_caps()
    abuse_limits.reset_counters()
    if clock_t is None:
        abuse_limits._now = time.monotonic
    else:
        box = {"t": clock_t}
        abuse_limits._now = lambda: box["t"]  # noqa: E731
        return box


def test_per_ip_burst(client):
    print("Z1 per-IP burst hits the cap with a clean 429")
    set_caps(per_ip=3, glob=1000, window=60)
    abuse_limits.reset_counters()
    try:
        tbox = {"t": 1000.0}
        abuse_limits._now = lambda: tbox["t"]  # noqa: E731
        for i in range(3):
            resp, _ = create(client)
            check(f"create {i + 1} of 3 allowed",
                  resp.status_code == 200,
                  f"-> {resp.status_code}: {resp.text[:200]}")
        resp, _ = create(client)
        check("4th create refused", resp.status_code == 429,
              f"-> {resp.status_code}: {resp.text[:200]}")
        check("429 carries the clean RATE_LIMITED envelope",
              clean_envelope(resp, "RATE_LIMITED", 429), resp.text[:200])
        err = resp.json()["error"]
        check("429 message is the human sentence",
              err["message"] == "Too many deals created. "
                               "Wait a moment and try again.",
              err["message"])
        retry = resp.headers.get("retry-after")
        check("429 carries a Retry-After hint",
              retry is not None and retry.isdigit() and int(retry) >= 1,
              f"retry-after={retry!r}")
        check("Retry-After names the window (60s at a frozen clock)",
              retry == "60", f"retry-after={retry!r}")
        # A refused call is not recorded, so it does not extend the
        # penalty: the next attempt is refused the same way.
        resp2, _ = create(client)
        check("a refused call stays refused, same Retry-After",
              resp2.status_code == 429
              and resp2.headers.get("retry-after") == retry,
              f"-> {resp2.status_code}")
    finally:
        fresh_state()


def test_window_recovery(client):
    print("Z2 creation works again after the window passes")
    try:
        set_caps(per_ip=2, glob=1000, window=60)
        abuse_limits.reset_counters()
        tbox = {"t": 2000.0}
        abuse_limits._now = lambda: tbox["t"]  # noqa: E731
        for i in range(2):
            resp, _ = create(client)
            check(f"create {i + 1} of 2 allowed", resp.status_code == 200,
                  f"-> {resp.status_code}")
        resp, _ = create(client)
        check("3rd create refused", resp.status_code == 429,
              f"-> {resp.status_code}")
        tbox["t"] = 2000.0 + 61
        resp, _ = create(client)
        check("create works again after the window passes",
              resp.status_code == 200, f"-> {resp.status_code}")
        # The window length itself is env-driven: with a 600s window
        # the same 61s jump must still refuse.
        set_caps(per_ip=2, glob=1000, window=600)
        abuse_limits.reset_counters()
        tbox["t"] = 5000.0
        for i in range(2):
            resp, _ = create(client)
            check(f"window=600 create {i + 1} allowed",
                  resp.status_code == 200, f"-> {resp.status_code}")
        resp, _ = create(client)
        check("window=600 3rd create refused", resp.status_code == 429,
              f"-> {resp.status_code}")
        tbox["t"] = 5000.0 + 61
        resp, _ = create(client)
        check("window=600 still refuses at +61s",
              resp.status_code == 429, f"-> {resp.status_code}")
        tbox["t"] = 5000.0 + 601
        resp, _ = create(client)
        check("window=600 allows at +601s", resp.status_code == 200,
              f"-> {resp.status_code}")
    finally:
        fresh_state()


def test_global_cap(client):
    print("Z3 global cap trips with a clean 429")
    try:
        set_caps(per_ip=1000, glob=2, window=60)
        abuse_limits.reset_counters()
        tbox = {"t": 3000.0}
        abuse_limits._now = lambda: tbox["t"]  # noqa: E731
        for i in range(2):
            resp, _ = create(client)
            check(f"create {i + 1} of 2 allowed", resp.status_code == 200,
                  f"-> {resp.status_code}")
        resp, _ = create(client)
        check("3rd create refused by the global cap",
              resp.status_code == 429, f"-> {resp.status_code}")
        check("429 carries the clean RATE_LIMITED envelope",
              clean_envelope(resp, "RATE_LIMITED", 429), resp.text[:200])
        retry = resp.headers.get("retry-after")
        check("429 carries a Retry-After hint",
              retry is not None and retry.isdigit() and int(retry) >= 1,
              f"retry-after={retry!r}")
    finally:
        fresh_state()


def full_demo_flow(client):
    """One complete deal lifecycle in demo mode, token-carrying."""
    resp, deal = create(client)
    assert resp.status_code == 200, f"create -> {resp.status_code}"
    deal_id = deal["id"]
    resp, deal = post(client, f"/api/deals/{deal_id}/negotiate/run")
    assert resp.status_code == 200, f"negotiate -> {resp.status_code}"
    assert deal["state"] == "agreed", deal["state"]
    resp, deal = post(client, f"/api/deals/{deal_id}/pay")
    assert resp.status_code == 200, f"pay -> {resp.status_code}"
    resp, deal = post(client, f"/api/deals/{deal_id}/deliver",
                      {"quality": "auto"})
    assert resp.status_code == 200, f"deliver -> {resp.status_code}"
    resp, deal = post(client, f"/api/deals/{deal_id}/verify")
    assert resp.status_code == 200, f"verify -> {resp.status_code}"
    return deal


def test_demo_flow_clean(client):
    print("Z4 the normal demo flow never trips either cap")
    try:
        fresh_state()
        deal = full_demo_flow(client)
        check("first demo deal settles released", deal["state"] == "released",
              deal["state"])
        deal = full_demo_flow(client)
        check("second demo deal settles released", deal["state"] == "released",
              deal["state"])
    finally:
        fresh_state()


def test_oversize_deliver(client):
    print("Z5 oversize delivery body gets a clean 413")
    try:
        fresh_state()
        resp, deal = create(client)
        assert resp.status_code == 200, f"create -> {resp.status_code}"
        deal_id = deal["id"]
        resp, _ = post(client, f"/api/deals/{deal_id}/negotiate/run")
        assert resp.status_code == 200, f"negotiate -> {resp.status_code}"
        resp, _ = post(client, f"/api/deals/{deal_id}/pay")
        assert resp.status_code == 200, f"pay -> {resp.status_code}"
        big = {"quality": "auto", "pad": "x" * 70000}
        resp, _ = post(client, f"/api/deals/{deal_id}/deliver", body=big)
        check("oversize delivery refused", resp.status_code == 413,
              f"-> {resp.status_code}")
        check("413 carries the clean PAYLOAD_TOO_LARGE envelope",
              clean_envelope(resp, "PAYLOAD_TOO_LARGE", 413),
              resp.text[:200])
        # The deal is untouched: still waiting for a real delivery.
        resp = client.get(f"/api/deals/{deal_id}")
        fresh = resp.json()
        check("deal still paid_held after the 413",
              fresh["state"] == "paid_held", fresh["state"])
        check("no delivery recorded after the 413",
              not fresh.get("deliverable"), fresh.get("deliverable"))
        # A normal-size delivery on the same deal still works.
        resp, deal = post(client, f"/api/deals/{deal_id}/deliver",
                          {"quality": "auto"})
        check("normal delivery still accepted", resp.status_code == 200,
              f"-> {resp.status_code}: {resp.text[:200]}")
    finally:
        fresh_state()


def test_oversize_negotiate(client):
    print("Z6 oversize negotiation body gets a clean 413")
    try:
        fresh_state()
        resp, deal = create(client)
        assert resp.status_code == 200, f"create -> {resp.status_code}"
        deal_id = deal["id"]
        url = f"/api/deals/{deal_id}/negotiate/run"
        resp, _ = post(client, url, raw=b"x" * 70000)
        check("oversize negotiation refused", resp.status_code == 413,
              f"-> {resp.status_code}")
        check("413 carries the clean PAYLOAD_TOO_LARGE envelope",
              clean_envelope(resp, "PAYLOAD_TOO_LARGE", 413),
              resp.text[:200])
        resp = client.get(f"/api/deals/{deal_id}")
        check("deal still negotiating after the 413",
              resp.json()["state"] == "negotiating",
              resp.json()["state"])
        # Exactly at the cap is allowed: the body is not over the limit.
        resp, deal = post(client, url, raw=b"x" * 65536)
        check("body exactly at the 64KB cap is accepted",
              resp.status_code == 200,
              f"-> {resp.status_code}: {resp.text[:200]}")
        check("negotiation ran after the boundary body",
              deal["state"] == "agreed", deal["state"])
    finally:
        fresh_state()


def main():
    with TestClient(app) as client:
        resp = client.get("/api/health")
        check("health answers", resp.status_code == 200,
              f"-> {resp.status_code}")
        check("demo mode (no sandbox credentials in this run)",
              resp.json()["mode"] == "demo",
              f"mode={resp.json().get('mode')} - refusing to run")
        test_per_ip_burst(client)
        test_window_recovery(client)
        test_global_cap(client)
        test_demo_flow_clean(client)
        test_oversize_deliver(client)
        test_oversize_negotiate(client)
    print(f"abuse_limit checks={CHECKS} PASS")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"ABUSE LIMIT TEST FAILED: {exc}")
        raise SystemExit(1)

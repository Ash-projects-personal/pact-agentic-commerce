"""Webhook endpoint tests.

Covers three configurations of POST /webhooks/paypal:
1. No webhook ID configured: the event is recorded and labeled
   not_configured.
2. Configured, and PayPal answers SUCCESS (mocked client call): the
   event is accepted as verified.
3. Configured, and PayPal answers FAILURE (mocked client call): the
   event is rejected with a 400.

The PayPal verification call itself is mocked because it needs a real
webhook and a real signed event; the endpoint logic around it is what
this test owns. A webhook can never move money in Pact: settlement runs
on direct API responses, so test 1 also asserts a forged event naming a
real deal changes nothing about that deal's money state.
"""

import os
import sys
import tempfile
from pathlib import Path

for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY",
            "PAYPAL_WEBHOOK_ID"):
    os.environ.pop(var, None)

# Isolate persistence: the middleware writes the store to SQLite after
# every response, so point the test run at a throwaway database that
# never touches the real dev database at data/pact.db.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail if not cond else ''}")
    if not cond:
        FAILURES.append(name)


def main():
    from fastapi.testclient import TestClient

    import pact.main as main_mod
    from pact.config import SETTINGS
    from pact.main import app

    client = TestClient(app)

    # Demo client token store (queue item W): state-changing deal
    # endpoints require the per-deal role token in the X-Deal-Token
    # header. The create response carries both tokens.
    def token_headers(deal, role="buyer"):
        return {"X-Deal-Token": deal[f"{role}_token"]}

    print("PART 1 unconfigured webhook is recorded, moves no money")
    deal = client.post("/api/deals", json={"scenario_id": "logo_brand_kit"}).json()
    deal = client.post(f"/api/deals/{deal['id']}/negotiate/run",
                       headers=token_headers(deal)).json()
    deal = client.post(f"/api/deals/{deal['id']}/pay",
                       headers=token_headers(deal)).json()
    order_id = deal["payment"]["order_id"]
    before_state = deal["state"]
    resp = client.post("/webhooks/paypal", json={
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {"id": order_id},
    })
    body = resp.json()
    check("unconfigured returns 200", resp.status_code == 200, resp.status_code)
    check("labeled not_configured",
          body["signature_verification"] == "not_configured", body)
    check("matched to the deal", body["matched_deal"] == deal["id"], body)
    after = client.get(f"/api/deals/{deal['id']}").json()
    check("deal state unchanged by webhook",
          after["state"] == before_state, after["state"])
    check("payment status unchanged by webhook",
          after["payment"]["status"] == deal["payment"]["status"],
          after["payment"]["status"])

    print("PART 2 configured and verified")
    SETTINGS.paypal_client_id = "test-id"
    SETTINGS.paypal_client_secret = "test-secret"
    SETTINGS.paypal_webhook_id = "WH-TEST"
    calls = {}

    async def fake_success(self, headers, event):
        calls["headers"] = headers
        return "SUCCESS"

    original = main_mod.PayPalClient.verify_webhook_signature
    main_mod.PayPalClient.verify_webhook_signature = fake_success
    try:
        resp = client.post("/webhooks/paypal",
                           json={"event_type": "PAYMENT.CAPTURE.COMPLETED",
                                 "resource": {"id": order_id}},
                           headers={"paypal-transmission-id": "t-1",
                                    "paypal-auth-algo": "SHA256withRSA",
                                    "paypal-cert-url": "https://api-m.sandbox.paypal.com/certs/1",
                                    "paypal-transmission-sig": "sig",
                                    "paypal-transmission-time": "2026-10-22T00:00:00Z"})
        body = resp.json()
        check("verified returns 200", resp.status_code == 200, resp.status_code)
        check("labeled verified", body["signature_verification"] == "verified", body)
        check("headers reached the verifier",
              calls["headers"].get("paypal-transmission-id") == "t-1", calls)
    finally:
        main_mod.PayPalClient.verify_webhook_signature = original

    print("PART 3 configured and failed verification is rejected")

    async def fake_failure(self, headers, event):
        return "FAILURE"

    main_mod.PayPalClient.verify_webhook_signature = fake_failure
    try:
        resp = client.post("/webhooks/paypal",
                           json={"event_type": "PAYMENT.CAPTURE.COMPLETED",
                                 "resource": {"id": order_id}},
                           headers={"paypal-transmission-id": "t-2"})
        body = resp.json()
        check("failed verification returns 400", resp.status_code == 400,
              resp.status_code)
        check("failed verification not received",
              body["received"] is False, body)
        after = client.get(f"/api/deals/{deal['id']}").json()
        check("rejection logged on the deal ledger",
              any(e["event_type"] == "webhook_rejected" for e in after["ledger"]),
              [e["event_type"] for e in after["ledger"]])
    finally:
        main_mod.PayPalClient.verify_webhook_signature = original
        SETTINGS.paypal_client_id = ""
        SETTINGS.paypal_client_secret = ""
        SETTINGS.paypal_webhook_id = ""

    print()
    if FAILURES:
        print(f"WEBHOOK TESTS FAILED: {FAILURES}")
        return 1
    print("ALL WEBHOOK TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

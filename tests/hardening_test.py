"""Hardening regression tests (batch 1).

Each part maps to a finding from research/red-team-round2.md or
research/paypal-platform-expert-review.md:

A. Non finite and absurd money inputs are rejected at deal creation
   (red team 3), and so are prices under the 1.00 USD floor (red team 2).
B. A settled bond under 0.50 USD fails the deal cleanly instead of
   silently rounding to zero (red team 2).
C. Unknown delivery quality values are rejected with 400 (red team 12),
   while the demo quality knob keeps working in demo mode.
D. In live sandbox mode the caller's quality choice cannot force a poor
   delivery: deliver always uses the scenario's seller behavior and logs
   that the knob was ignored (red team 1).
E. Idempotency keys are deterministic per deal and leg and are stored
   on the deal records (PayPal review gap 1).
F. A capture with no capture id or a non COMPLETED status raises a
   payment error and never writes a held event (PayPal review gap 5).
G. A webhook whose signature verification call errors returns 503 and
   records nothing (PayPal review gap 4).
H. The fallback ledger table in app.js no longer injects raw ledger
   text through innerHTML (red team 7).
I. Settlement is resumable: each settlement leg is recorded as it
   completes, a failed second leg leaves the deal in a resumable
   "verifying" state, a later verify runs only the missing legs under
   the same deterministic idempotency keys, and no leg runs twice
   (queue item B, red team 10 / PayPal gap 2).
J. A per deal asyncio lock serializes the state changing endpoints, so
   parallel negotiate or pay calls yield exactly one success and 409s
   for the rest, with no duplicate orders or interleaved moves
   (queue item C, red team 9).
K. Payout status follow through (queue item D, PayPal gap 3): a payout
   is only a batch acceptance, so each payout leg is read back. A
   PENDING batch keeps the deal in verifying with a payout_pending
   ledger event and nothing marked released; a later verify finalizes
   on SUCCESS. A DENIED batch writes a correcting payout_failed event,
   marks the leg failed, and retries with a fresh idempotency key. Demo
   mode still resolves instantly.
L. Approval payer check (queue item E, red team 8): at pay/confirm in
   live mode the price order's payer must match the buyer sandbox
   identity and the bond order's payer the seller sandbox identity,
   read back with get_order_details before capture. A mismatch, a
   missing payer, or unconfigured expected identities refuse capture
   with a payer_mismatch ledger event and leave the deal awaiting
   approval. Demo mode skips the check.

Run with: python tests/hardening_test.py
"""

import os
import re
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

# This driver intentionally creates 30+ deals in under a minute, past
# the demo abuse caps (queue item Z: 30/min per IP). The caps are
# env-driven and a value of 0 disables them, so the test harness opts
# out here. The caps themselves are covered by
# tests/abuse_limit_test.py.
os.environ["PACT_MAX_DEALS_PER_MINUTE_PER_IP"] = "0"
os.environ["PACT_MAX_DEALS_PER_MINUTE_GLOBAL"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail if not cond else ''}")
    if not cond:
        FAILURES.append(name)


def main():
    from fastapi.testclient import TestClient

    import pact.main as main_mod
    from pact.main import app
    from pact.payments import DemoSimulator, PaymentError, PayPalClient
    from pact.store import DEALS, GLOBAL_EVENTS

    # One shared portal for the whole session. Without the context
    # manager every client.post would spin up its own event loop, and
    # the per deal asyncio locks in pact.main would be awaited from
    # different loops, which asyncio.Lock does not support. The shared
    # portal matches production, where uvicorn runs every request on
    # one loop.
    with TestClient(app, raise_server_exceptions=False) as client:
        return _run(client)


def _run(client):
    import pact.main as main_mod
    from pact.payments import DemoSimulator, PaymentError, PayPalClient
    from pact.store import DEALS, GLOBAL_EVENTS

    # Demo client token store (queue item W): state-changing deal
    # endpoints require the per-deal role token in the X-Deal-Token
    # header. The create response carries both tokens, so this helper
    # remembers them per deal id and attaches the right one, the way a
    # real client would. Deliver acts as the seller; everything else
    # here acts as the buyer.
    deal_tokens = {}

    def token_headers(path):
        m = re.match(r"^/api/deals/([^/]+)/", path)
        if not m:
            return None
        role = "seller" if path.rstrip("/").endswith("/deliver") else "buyer"
        tok = deal_tokens.get(m.group(1), {}).get(role)
        return {"X-Deal-Token": tok} if tok else None

    def remember_tokens(resp):
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                return
            if (isinstance(data, dict) and data.get("id")
                    and data.get("buyer_token")):
                deal_tokens[data["id"]] = {
                    "buyer": data.get("buyer_token"),
                    "seller": data.get("seller_token"),
                }

    def post(path, body=None):
        resp = client.post(path, json=body or {},
                           headers=token_headers(path))
        remember_tokens(resp)
        return resp

    def post_raw(path, raw):
        return client.post(path, content=raw,
                           headers={"Content-Type": "application/json"})

    def run_to_paid(scenario_id="logo_brand_kit", **kwargs):
        deal = post("/api/deals", {"scenario_id": scenario_id, **kwargs}).json()
        deal = post(f"/api/deals/{deal['id']}/negotiate/run").json()
        deal = post(f"/api/deals/{deal['id']}/pay").json()
        return deal

    print("PART A money input validation at creation")
    before = len(DEALS)
    resp = post_raw("/api/deals",
                    '{"scenario_id": "logo_brand_kit", "buyer_max": 1e999,'
                    ' "seller_floor": 100}')
    check("infinite buyer_max rejected 400", resp.status_code == 400,
          resp.status_code)
    resp = post_raw("/api/deals",
                    '{"scenario_id": "logo_brand_kit", "buyer_max": NaN,'
                    ' "seller_floor": 100}')
    check("NaN buyer_max rejected 400", resp.status_code == 400,
          resp.status_code)
    resp = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "buyer_max": 2000000})
    check("buyer_max above the cap rejected 400", resp.status_code == 400,
          resp.status_code)
    resp = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "seller_floor": 2000000})
    check("seller_floor above the cap rejected 400", resp.status_code == 400,
          resp.status_code)
    resp = post_raw("/api/deals",
                    '{"scenario_id": "logo_brand_kit",'
                    ' "bond_percent": 1e999}')
    check("infinite bond_percent rejected 400", resp.status_code == 400,
          resp.status_code)
    resp = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "buyer_max": 0.03, "seller_floor": 0.01})
    check("tiny prices rejected 400 (bond would round to zero)",
          resp.status_code == 400, resp.status_code)
    resp = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "buyer_max": 300, "seller_floor": 0.50})
    check("seller_floor under the price floor rejected 400",
          resp.status_code == 400, resp.status_code)
    check("rejected creates stored no deal records", len(DEALS) == before,
          f"{before} -> {len(DEALS)}")
    resp = post("/api/deals", {"scenario_id": "logo_brand_kit"})
    check("normal create still works", resp.status_code == 200,
          resp.status_code)

    print("PART B settled bond floor")
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "buyer_max": 2.0, "seller_floor": 1.0}).json()
    resp = post(f"/api/deals/{deal['id']}/negotiate/run")
    check("tiny settled bond fails negotiation with 400",
          resp.status_code == 400, f"{resp.status_code}: {resp.text}")
    after = client.get(f"/api/deals/{deal['id']}").json()
    check("deal is marked failed, not agreed",
          after["state"] == "failed", after["state"])
    check("spec bond really was under the floor",
          after["spec"]["bond_amount"] < 0.50, after["spec"]["bond_amount"])
    check("bond_too_small event logged",
          any(e["event_type"] == "bond_too_small" for e in after["ledger"]))
    check("no payment was made on the failed deal",
          after["payment"]["status"] == "not_started",
          after["payment"]["status"])
    deal = post("/api/deals", {"scenario_id": "amazon_listing"}).json()
    resp = post(f"/api/deals/{deal['id']}/negotiate/run")
    check("normal scenario negotiation unaffected",
          resp.status_code == 200 and resp.json()["state"] == "agreed",
          resp.status_code)
    check("normal bond is above the floor",
          resp.json()["spec"]["bond_amount"] >= 0.50,
          resp.json()["spec"]["bond_amount"])

    print("PART C delivery quality validation in demo mode")
    deal = run_to_paid()
    resp = post(f"/api/deals/{deal['id']}/deliver",
                {"quality": "whatever-i-want"})
    check("unknown quality rejected 400", resp.status_code == 400,
          resp.status_code)
    after = client.get(f"/api/deals/{deal['id']}").json()
    check("deal still paid_held after the rejected deliver",
          after["state"] == "paid_held", after["state"])
    check("no deliverable recorded for the rejected deliver",
          after["deliverable"] is None)
    resp = post(f"/api/deals/{deal['id']}/deliver", {"quality": "poor"})
    check("demo poor knob still works in demo mode",
          resp.status_code == 200 and resp.json()["state"] == "delivered",
          resp.status_code)
    check("poor delivery is the thin text",
          len(resp.json()["deliverable"]["content"].split()) < 40,
          len(resp.json()["deliverable"]["content"].split()))

    print("PART D live mode ignores the quality knob")

    class LiveStub:
        """Sandbox mode service backed by the local simulator's ids."""

        mode = "sandbox"

        def __init__(self):
            self._sim = DemoSimulator()

        async def create_order(self, *a, **k):
            return await self._sim.create_order(*a, **k)

        async def capture_order(self, *a, **k):
            return await self._sim.capture_order(*a, **k)

        async def payout(self, *a, **k):
            return await self._sim.payout(*a, **k)

        async def refund(self, *a, **k):
            return await self._sim.refund(*a, **k)

        async def get_payout_status(self, payout_batch_id):
            return await self._sim.get_payout_status(payout_batch_id)

    original_service = main_mod.get_agent_payment_service
    main_mod.get_agent_payment_service = lambda: LiveStub()
    try:
        deal = run_to_paid()
        check("live stub deal reaches paid_held",
              deal["state"] == "paid_held", deal["state"])
        resp = post(f"/api/deals/{deal['id']}/deliver", {"quality": "poor"})
        body = resp.json()
        check("live deliver with poor still returns 200",
              resp.status_code == 200, resp.status_code)
        check("live deliverable quality recorded as auto, not poor",
              body["deliverable"]["quality"] == "auto",
              body["deliverable"]["quality"])
        check("live delivery is the honest build, not the thin text",
              len(body["deliverable"]["content"].split()) > 100,
              len(body["deliverable"]["content"].split()))
        check("quality_knob_ignored event logged",
              any(e["event_type"] == "quality_knob_ignored"
                  for e in body["ledger"]))
        resp = post(f"/api/deals/{deal['id']}/verify")
        check("live deal settles as released, buyer cannot force a fail",
              resp.status_code == 200 and resp.json()["state"] == "released",
              f"{resp.status_code}: {resp.json().get('state')}")
        deal = run_to_paid()
        resp = post(f"/api/deals/{deal['id']}/deliver",
                    {"quality": "nonsense"})
        check("unknown quality still rejected 400 in live mode",
              resp.status_code == 400, resp.status_code)
    finally:
        main_mod.get_agent_payment_service = original_service

    print("PART E deterministic idempotency keys")
    deal = run_to_paid()
    did = deal["id"]
    check("price order key stored",
          deal["payment"]["order_request_id"] == f"{did}-price-order",
          deal["payment"].get("order_request_id"))
    check("bond order key stored",
          deal["bond"]["order_request_id"] == f"{did}-bond-order",
          deal["bond"].get("order_request_id"))
    check("price capture key stored",
          deal["payment"]["capture_request_id"] == f"{did}-price-capture",
          deal["payment"].get("capture_request_id"))
    check("bond capture key stored",
          deal["bond"]["capture_request_id"] == f"{did}-bond-capture",
          deal["bond"].get("capture_request_id"))
    deal = post(f"/api/deals/{did}/deliver", {"quality": "auto"}).json()
    deal = post(f"/api/deals/{did}/verify").json()
    check("price payout key stored",
          deal["settlement"]["payout_request_id"] == f"{did}-price-payout",
          deal["settlement"].get("payout_request_id"))
    check("bond return key stored",
          deal["settlement"]["bond_payout_request_id"]
          == f"{did}-bond-return",
          deal["settlement"].get("bond_payout_request_id"))
    held = next(e for e in deal["ledger"]
                if e["event_type"] == "payment_held")
    check("capture key written into the held ledger event",
          held["data"].get("capture_request_id") == f"{did}-price-capture",
          held["data"])

    deal = run_to_paid()
    did = deal["id"]
    post(f"/api/deals/{did}/deliver", {"quality": "poor"})
    deal = post(f"/api/deals/{did}/verify").json()
    check("refund key stored",
          deal["settlement"]["refund_request_id"] == f"{did}-price-refund",
          deal["settlement"].get("refund_request_id"))
    check("bond slash key stored",
          deal["settlement"]["bond_slash_request_id"] == f"{did}-bond-slash",
          deal["settlement"].get("bond_slash_request_id"))

    import asyncio

    recorded = {}

    async def fake_request(self, method, path, json_body=None,
                           request_id=None):
        recorded.setdefault("request_ids", []).append(request_id)
        recorded["json_body"] = json_body
        if path == "/v2/checkout/orders":
            return {"id": "ORD-1", "status": "CREATED", "links": []}
        if path.endswith("/capture"):
            return {"status": "COMPLETED",
                    "purchase_units": [{"payments": {"captures": [
                        {"id": "CAP-1", "status": "COMPLETED"}]}}]}
        if path == "/v1/payments/payouts":
            return {"batch_header": {"payout_batch_id": "PB-1",
                                     "batch_status": "PENDING"}}
        raise AssertionError(path)

    rest = PayPalClient.__new__(PayPalClient)
    original_request = PayPalClient._request
    PayPalClient._request = fake_request
    try:
        asyncio.run(rest.create_order(1000, "USD", "deal-x price",
                                      request_id="deal-x-price-order"))
        asyncio.run(rest.create_order(1000, "USD", "deal-x price",
                                      request_id="deal-x-price-order"))
        check("REST create reuses the caller supplied request id on retry",
              recorded["request_ids"] == ["deal-x-price-order"] * 2,
              recorded["request_ids"])
        asyncio.run(rest.capture_order("ORD-1",
                                       request_id="deal-x-price-capture"))
        check("REST capture carries the deterministic request id",
              recorded["request_ids"][-1] == "deal-x-price-capture",
              recorded["request_ids"])
        asyncio.run(rest.payout("seller@example.com", 1000, "USD", "note",
                                request_id="deal-x-price-payout"))
        check("payout sender_batch_id is the deterministic leg key",
              recorded["json_body"]["sender_batch_header"]["sender_batch_id"]
              == "deal-x-price-payout", recorded["json_body"])
    finally:
        PayPalClient._request = original_request

    print("PART F capture validation")

    async def fake_request_no_capture(self, method, path, json_body=None,
                                      request_id=None):
        return {"status": "COMPLETED",
                "purchase_units": [{"payments": {"captures": []}}]}

    async def fake_request_declined(self, method, path, json_body=None,
                                    request_id=None):
        return {"status": "COMPLETED",
                "purchase_units": [{"payments": {"captures": [
                    {"id": "CAP-9", "status": "DECLINED"}]}}]}

    PayPalClient._request = fake_request_no_capture
    try:
        try:
            asyncio.run(rest.capture_order("ORD-2"))
            raised = False
        except PaymentError:
            raised = True
        check("REST capture with no capture id raises PaymentError", raised)
    finally:
        PayPalClient._request = original_request
    PayPalClient._request = fake_request_declined
    try:
        try:
            asyncio.run(rest.capture_order("ORD-2"))
            raised = False
        except PaymentError:
            raised = True
        check("REST capture with DECLINED status raises PaymentError",
              raised)
    finally:
        PayPalClient._request = original_request

    class BadCaptureStub(LiveStub):
        mode = "sandbox"
        result = {"capture_id": None, "status": "COMPLETED", "rail": "stub"}

        async def capture_order(self, *a, **k):
            return dict(self.result)

    main_mod.get_agent_payment_service = lambda: BadCaptureStub()
    try:
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{deal['id']}/negotiate/run")
        resp = post(f"/api/deals/{deal['id']}/pay")
        check("pay with a null capture returns 502",
              resp.status_code == 502, resp.status_code)
        after = client.get(f"/api/deals/{deal['id']}").json()
        types = [e["event_type"] for e in after["ledger"]]
        check("payment_error event written for the bad capture",
              "payment_error" in types, types)
        check("no payment_held event written for the bad capture",
              "payment_held" not in types, types)
        check("payment not marked held",
              after["payment"]["status"] != "held",
              after["payment"]["status"])
        messages = " ".join(e["message"] for e in after["ledger"]
                             if e["event_type"] in ("payment_held",
                                                    "bond_posted"))
        check("no success message can contain a null capture",
              "capture None" not in messages, messages)
        BadCaptureStub.result = {"capture_id": "CAP-7",
                                 "status": "DECLINED", "rail": "stub"}
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{deal['id']}/negotiate/run")
        resp = post(f"/api/deals/{deal['id']}/pay")
        check("pay with a DECLINED capture returns 502",
              resp.status_code == 502, resp.status_code)
        after = client.get(f"/api/deals/{deal['id']}").json()
        check("declined capture also writes payment_error, never held",
              any(e["event_type"] == "payment_error" for e in after["ledger"])
              and after["payment"]["status"] != "held",
              after["payment"]["status"])
    finally:
        main_mod.get_agent_payment_service = original_service

    print("PART G webhook verification error fails closed")
    from pact.config import SETTINGS

    deal = run_to_paid()
    order_id = deal["payment"]["order_id"]
    SETTINGS.paypal_client_id = "test-id"
    SETTINGS.paypal_client_secret = "test-secret"
    SETTINGS.paypal_webhook_id = "WH-TEST"

    async def fake_error(self, headers, event):
        raise PaymentError("PayPal verification endpoint unreachable")

    original_verify = main_mod.PayPalClient.verify_webhook_signature
    main_mod.PayPalClient.verify_webhook_signature = fake_error
    ledger_before = len(client.get(f"/api/deals/{deal['id']}").json()
                          ["ledger"])
    global_before = len(GLOBAL_EVENTS)
    try:
        resp = client.post("/webhooks/paypal", json={
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": order_id},
        })
        check("verification error returns 503", resp.status_code == 503,
              resp.status_code)
        body = resp.json()
        check("503 body says not received and verification errored",
              body["received"] is False
              and body["signature_verification"] == "error", body)
        after = client.get(f"/api/deals/{deal['id']}").json()
        check("nothing recorded on the deal ledger",
              len(after["ledger"]) == ledger_before,
              f"{ledger_before} -> {len(after['ledger'])}")
        check("nothing recorded in the global webhook log",
              len(GLOBAL_EVENTS) == global_before,
              f"{global_before} -> {len(GLOBAL_EVENTS)}")
    finally:
        main_mod.PayPalClient.verify_webhook_signature = original_verify
        SETTINGS.paypal_client_id = ""
        SETTINGS.paypal_client_secret = ""
        SETTINGS.paypal_webhook_id = ""

    print("PART H fallback ledger table escapes attacker text")
    app_js = (Path(__file__).resolve().parent.parent
              / "pact" / "static" / "app.js").read_text()
    check("old raw innerHTML row concatenation is gone",
          '"<tr><td>" + r.timestamp' not in app_js)
    check("fallback branch builds cells with textContent",
          "td.textContent" in app_js and "table.className" in app_js)

    print("PART I settlement resumability (queue item B)")

    class FailLegStub:
        """Demo shaped service that can fail one named settlement leg."""

        mode = "demo"

        def __init__(self, fail_suffix=None):
            self._sim = DemoSimulator()
            self.fail_suffix = fail_suffix
            self.calls = []

        async def create_order(self, *a, **k):
            return await self._sim.create_order(*a, **k)

        async def capture_order(self, *a, **k):
            return await self._sim.capture_order(*a, **k)

        async def refund(self, capture_id, amount, currency, request_id=None):
            self.calls.append(("refund", request_id))
            if (self.fail_suffix and request_id
                    and request_id.endswith(self.fail_suffix)):
                raise PaymentError(f"injected failure on {request_id}")
            return await self._sim.refund(capture_id, amount, currency,
                                          request_id=request_id)

        async def payout(self, receiver_email, amount, currency, note,
                         request_id=None):
            self.calls.append(("payout", request_id))
            if (self.fail_suffix and request_id
                    and request_id.endswith(self.fail_suffix)):
                raise PaymentError(f"injected failure on {request_id}")
            return await self._sim.payout(receiver_email, amount, currency,
                                          note, request_id=request_id)

        async def get_payout_status(self, payout_batch_id):
            return await self._sim.get_payout_status(payout_batch_id)

    # Release path: fail the second leg (bond return), then resume.
    stub = FailLegStub(fail_suffix="bond-return")
    main_mod.get_agent_payment_service = lambda: stub
    try:
        deal = run_to_paid()
        did = deal["id"]
        post(f"/api/deals/{did}/deliver", {"quality": "auto"})
        resp = post(f"/api/deals/{did}/verify")
        check("verify with a failed bond leg returns 502",
              resp.status_code == 502, resp.status_code)
        after = client.get(f"/api/deals/{did}").json()
        check("deal stays in verifying after the failed leg",
              after["state"] == "verifying", after["state"])
        legs = after["settlement"]["legs"]
        check("price payout leg recorded done",
              legs["price_payout"]["status"] == "done", legs["price_payout"])
        check("failed bond leg recorded failed, not pending",
              legs["bond_return"]["status"] == "failed", legs["bond_return"])
        check("settlement path recorded as release",
              after["settlement"]["path"] == "release",
              after["settlement"]["path"])
        check("payment marked released after its leg",
              after["payment"]["status"] == "released",
              after["payment"]["status"])
        check("bond not marked returned while its leg is missing",
              after["bond"]["status"] != "returned", after["bond"]["status"])
        price_calls = [c for c in stub.calls if c[1].endswith("price-payout")]
        check("price payout leg ran exactly once", len(price_calls) == 1,
              stub.calls)
        first_bond_key = [c[1] for c in stub.calls
                          if c[1].endswith("bond-return")][0]
        check("failed leg used the deterministic idempotency key",
              first_bond_key == f"{did}-bond-return", first_bond_key)
        check("no reputation moved before settlement finished",
              not any(e["event_type"] == "reputation_change"
                      for e in after["ledger"]))
        # A second verify against the still failing service keeps failing
        # cleanly instead of wedging or duplicating.
        resp = post(f"/api/deals/{did}/verify")
        check("second failing verify still returns 502, not a wedge",
              resp.status_code == 502, resp.status_code)
        after = client.get(f"/api/deals/{did}").json()
        check("deal still verifying after the second failure",
              after["state"] == "verifying", after["state"])
        check("verification events logged exactly once across retries",
              sum(1 for e in after["ledger"]
                  if e["event_type"] == "verification_summary") == 1,
              [e["event_type"] for e in after["ledger"]])
    finally:
        main_mod.get_agent_payment_service = original_service
    # Resume with a healthy service.
    stub2 = FailLegStub()
    main_mod.get_agent_payment_service = lambda: stub2
    try:
        resp = post(f"/api/deals/{did}/verify")
        check("resumed verify returns 200", resp.status_code == 200,
              resp.status_code)
        after = resp.json()
        check("deal released after the resume", after["state"] == "released",
              after["state"])
        legs = after["settlement"]["legs"]
        check("both release legs done",
              all(legs[l]["status"] == "done"
                  for l in ("price_payout", "bond_return")), legs)
        check("price payout not rerun on resume",
              not any(c[1].endswith("price-payout") for c in stub2.calls),
              stub2.calls)
        retried_key = [c[1] for c in stub2.calls
                       if c[1].endswith("bond-return")][0]
        check("retry reused the same deterministic idempotency key",
              retried_key == first_bond_key, retried_key)
        check("exactly one payment_released ledger event",
              sum(1 for e in after["ledger"]
                  if e["event_type"] == "payment_released") == 1)
        check("exactly one bond_returned ledger event",
              sum(1 for e in after["ledger"]
                  if e["event_type"] == "bond_returned") == 1)
        rep_moves = [e for e in after["ledger"]
                     if e["event_type"] == "reputation_change"]
        check("reputation applied exactly once (seller +6, buyer +3)",
              sorted(e["data"]["delta"] for e in rep_moves) == [3, 6],
              [e["data"]["delta"] for e in rep_moves])
        resp = post(f"/api/deals/{did}/verify")
        check("verify after release is a 409, not a second settlement",
              resp.status_code == 409, resp.status_code)
    finally:
        main_mod.get_agent_payment_service = original_service

    # Refund path: fail the second leg (bond slash), then resume.
    stub3 = FailLegStub(fail_suffix="bond-slash")
    main_mod.get_agent_payment_service = lambda: stub3
    try:
        deal = run_to_paid()
        did = deal["id"]
        post(f"/api/deals/{did}/deliver", {"quality": "poor"})
        resp = post(f"/api/deals/{did}/verify")
        check("refund path verify with a failed slash returns 502",
              resp.status_code == 502, resp.status_code)
        after = client.get(f"/api/deals/{did}").json()
        check("refund deal stays verifying after the failed leg",
              after["state"] == "verifying", after["state"])
        legs = after["settlement"]["legs"]
        check("price refund leg recorded done",
              legs["price_refund"]["status"] == "done", legs["price_refund"])
        check("failed slash leg recorded failed",
              legs["bond_slash"]["status"] == "failed", legs["bond_slash"])
        check("refund settlement path recorded",
              after["settlement"]["path"] == "refund",
              after["settlement"]["path"])
        check("revision was skipped, not re-entered on resume path",
              any(e["event_type"] == "revision_skipped"
                  for e in after["ledger"]))
    finally:
        main_mod.get_agent_payment_service = original_service
    stub4 = FailLegStub()
    main_mod.get_agent_payment_service = lambda: stub4
    try:
        resp = post(f"/api/deals/{did}/verify")
        check("resumed refund verify returns 200", resp.status_code == 200,
              resp.status_code)
        after = resp.json()
        check("deal refunded after the resume", after["state"] == "refunded",
              after["state"])
        check("refund leg not rerun on resume",
              not any(c[1].endswith("price-refund") for c in stub4.calls),
              stub4.calls)
        check("exactly one buyer_refunded and one bond_slashed event",
              sum(1 for e in after["ledger"]
                  if e["event_type"] == "buyer_refunded") == 1
              and sum(1 for e in after["ledger"]
                      if e["event_type"] == "bond_slashed") == 1)
        check("refund reputation applied exactly once",
              sorted(e["data"]["delta"] for e in after["ledger"]
                     if e["event_type"] == "reputation_change")
              == [-20, -12, 1],
              [e["data"]["delta"] for e in after["ledger"]
               if e["event_type"] == "reputation_change"])
    finally:
        main_mod.get_agent_payment_service = original_service

    print("PART J per deal lock (queue item C)")
    import threading

    # Parallel negotiate calls in demo mode: exactly one wins.
    control = post("/api/deals",
                   {"scenario_id": "logo_brand_kit"}).json()
    control = post(f"/api/deals/{control['id']}/negotiate/run").json()
    control_moves = len(control["moves"])
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    did = deal["id"]
    statuses = []

    def call_negotiate():
        statuses.append(post(f"/api/deals/{did}/negotiate/run").status_code)

    workers = [threading.Thread(target=call_negotiate) for _ in range(6)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    check("exactly one parallel negotiate succeeds", statuses.count(200) == 1,
          statuses)
    check("the rest get 409", statuses.count(409) == 5, statuses)
    after = client.get(f"/api/deals/{did}").json()
    check("negotiation moves written exactly once, never interleaved",
          len(after["moves"]) == control_moves,
          f"{len(after['moves'])} vs {control_moves}")

    # Parallel pay in a live shaped flow with a slow order creation: the
    # lock serializes the calls, so only one payment_held event exists.
    class SlowCreateStub(FailLegStub):
        mode = "sandbox"

        async def create_order(self, *a, **k):
            await asyncio.sleep(0.3)
            return await self._sim.create_order(*a, **k)

    slow = SlowCreateStub()
    main_mod.get_agent_payment_service = lambda: slow
    try:
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{deal['id']}/negotiate/run")
        did = deal["id"]
        pay_statuses = []

        def call_pay():
            pay_statuses.append(post(f"/api/deals/{did}/pay").status_code)

        workers = [threading.Thread(target=call_pay) for _ in range(6)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        check("exactly one parallel pay succeeds", pay_statuses.count(200) == 1,
              pay_statuses)
        check("the rest get 409", pay_statuses.count(409) == 5,
              pay_statuses)
        after = client.get(f"/api/deals/{did}").json()
        check("exactly one payment_held ledger event",
              sum(1 for e in after["ledger"]
                  if e["event_type"] == "payment_held") == 1,
              [e["event_type"] for e in after["ledger"]])
        check("exactly one bond_posted ledger event",
              sum(1 for e in after["ledger"]
                  if e["event_type"] == "bond_posted") == 1)
        check("payment has a single order id",
              after["payment"]["order_id"] is not None
              and after["payment"]["order_id"].startswith("DEMO-ORDER-"),
              after["payment"]["order_id"])
    finally:
        main_mod.get_agent_payment_service = original_service

    print("PART K payout status follow through (queue item D)")

    class PayoutStatusStub:
        """Demo shaped service with scripted payout batch statuses."""

        mode = "demo"

        def __init__(self):
            self._sim = DemoSimulator()
            self.calls = []
            # request id suffix -> list of batch statuses to return
            # in order on get_payout_status; exhausted means SUCCESS.
            self.status_scripts = {}
            self.batch_scripts = {}

        def script(self, suffix, *statuses):
            self.status_scripts[suffix] = list(statuses)

        async def create_order(self, *a, **k):
            return await self._sim.create_order(*a, **k)

        async def capture_order(self, *a, **k):
            return await self._sim.capture_order(*a, **k)

        async def refund(self, *a, **k):
            return await self._sim.refund(*a, **k)

        async def payout(self, receiver_email, amount, currency, note,
                         request_id=None):
            self.calls.append(("payout", request_id))
            result = await self._sim.payout(receiver_email, amount, currency,
                                            note, request_id=request_id)
            for suffix, script in self.status_scripts.items():
                if request_id and request_id.endswith(suffix):
                    self.batch_scripts[result["payout_batch_id"]] = script
            return result

        async def get_payout_status(self, payout_batch_id):
            script = self.batch_scripts.get(payout_batch_id)
            status = script.pop(0) if script else "SUCCESS"
            return {"batch_status": status, "items": []}

    # Pending then success: nothing is marked released on a pending batch.
    stub = PayoutStatusStub()
    stub.script("price-payout", "PENDING")
    stub.script("bond-return", "PENDING")
    main_mod.get_agent_payment_service = lambda: stub
    try:
        deal = run_to_paid()
        did = deal["id"]
        post(f"/api/deals/{did}/deliver", {"quality": "auto"})
        resp = post(f"/api/deals/{did}/verify")
        check("verify with a pending payout returns 200, not an error",
              resp.status_code == 200, resp.status_code)
        after = resp.json()
        check("deal stays verifying while the payout is pending",
              after["state"] == "verifying", after["state"])
        legs = after["settlement"]["legs"]
        check("price payout leg is sent, not done",
              legs["price_payout"]["status"] == "sent",
              legs["price_payout"]["status"])
        check("leg payout status recorded as pending",
              legs["price_payout"]["payout_status"] == "pending",
              legs["price_payout"])
        check("payment record shows the payout pending",
              after["payment"]["payout_status"] == "pending",
              after["payment"]["payout_status"])
        check("payment not marked released on a pending payout",
              after["payment"]["status"] != "released",
              after["payment"]["status"])
        check("payout_pending ledger event written",
              any(e["event_type"] == "payout_pending"
                  for e in after["ledger"]))
        check("no payment_released event on a pending payout",
              not any(e["event_type"] == "payment_released"
                      for e in after["ledger"]))
        check("bond leg not sent while the price payout is pending",
              legs["bond_return"]["status"] == "pending",
              legs["bond_return"]["status"])
        # The scripts are exhausted, so the next reads say SUCCESS.
        resp = post(f"/api/deals/{did}/verify")
        check("second verify still verifying: bond payout still pending",
              resp.status_code == 200
              and resp.json()["state"] == "verifying",
              f"{resp.status_code}: {resp.json()['state']}")
        after = resp.json()
        check("price leg done, bond leg sent",
              after["settlement"]["legs"]["price_payout"]["status"] == "done"
              and after["settlement"]["legs"]["bond_return"]["status"]
              == "sent",
              after["settlement"]["legs"])
        check("payout_pending logged once per leg, never duplicated",
              sum(1 for e in after["ledger"]
                  if e["event_type"] == "payout_pending") == 2,
              [e["event_type"] for e in after["ledger"]])
        resp = post(f"/api/deals/{did}/verify")
        check("third verify after success returns 200",
              resp.status_code == 200, resp.status_code)
        after = resp.json()
        check("deal released once both payouts confirm",
              after["state"] == "released", after["state"])
        check("exactly one payment_released event after confirmation",
              sum(1 for e in after["ledger"]
                  if e["event_type"] == "payment_released") == 1)
        check("price payout sent exactly once across the resume",
              sum(1 for c in stub.calls if c[1].endswith("price-payout"))
              == 1, stub.calls)
        check("payment payout status success",
              after["payment"]["payout_status"] == "success",
              after["payment"]["payout_status"])
    finally:
        main_mod.get_agent_payment_service = original_service

    # Denied then retry: the correcting event is written and the retry
    # uses a fresh idempotency key.
    stub2 = PayoutStatusStub()
    stub2.script("price-payout", "DENIED")
    main_mod.get_agent_payment_service = lambda: stub2
    try:
        deal = run_to_paid()
        did = deal["id"]
        post(f"/api/deals/{did}/deliver", {"quality": "auto"})
        resp = post(f"/api/deals/{did}/verify")
        check("verify with a denied payout returns 502",
              resp.status_code == 502, resp.status_code)
        after = client.get(f"/api/deals/{did}").json()
        check("deal stays verifying after the denied payout",
              after["state"] == "verifying", after["state"])
        legs = after["settlement"]["legs"]
        check("denied leg marked failed",
              legs["price_payout"]["status"] == "failed",
              legs["price_payout"]["status"])
        check("denied leg attempt bumped for the retry",
              legs["price_payout"]["attempt"] == 2,
              legs["price_payout"]["attempt"])
        check("denied status recorded on the payment",
              after["payment"]["payout_status"] == "denied",
              after["payment"]["payout_status"])
        check("correcting payout_failed ledger event written",
              any(e["event_type"] == "payout_failed"
                  for e in after["ledger"]))
        check("no payment_released event on a denied payout",
              not any(e["event_type"] == "payment_released"
                      for e in after["ledger"]))
        first_key = legs["price_payout"]["request_id"]
        check("first attempt used the legacy idempotency key",
              first_key == f"{did}-price-payout", first_key)
        resp = post(f"/api/deals/{did}/verify")
        check("resumed verify after the retry returns 200",
              resp.status_code == 200, resp.status_code)
        after = resp.json()
        check("deal released after the payout retry succeeds",
              after["state"] == "released", after["state"])
        retry_key = after["settlement"]["legs"]["price_payout"]["request_id"]
        check("retry used a fresh idempotency key",
              retry_key == f"{did}-price-payout-attempt2", retry_key)
        check("exactly one payment_released event across denial and retry",
              sum(1 for e in after["ledger"]
                  if e["event_type"] == "payment_released") == 1)
    finally:
        main_mod.get_agent_payment_service = original_service

    print("PART L approval payer check (queue item E)")

    class ApprovalStub:
        """Sandbox or demo shaped service with scripted order payers."""

        def __init__(self, mode="sandbox", payer_by_kind=None):
            self._sim = DemoSimulator()
            self.mode = mode
            # kind ("price"/"bond") -> payer email; None means the order
            # carries no payer information (not approved).
            self.payer_by_kind = payer_by_kind or {}
            self.kind_by_order = {}
            self.captures = []

        async def create_order(self, amount, currency, reference,
                               request_id=None, contract_tag=None):
            order_id = "STUB-ORDER-" + reference.replace(" ", "-")
            kind = "price" if reference.endswith(" price") else "bond"
            self.kind_by_order[order_id] = kind
            return {"order_id": order_id, "status": "CREATED",
                    "rail": "stub",
                    "hash_field": "stub" if contract_tag else None,
                    "contract_tag": contract_tag,
                    "approval_url":
                        f"https://example.com/approve/{order_id}"}

        async def get_order_details(self, order_id):
            if self.mode == "demo":
                raise PaymentError("no real orders exist in demo mode")
            email = self.payer_by_kind.get(
                self.kind_by_order.get(order_id))
            if email is None:
                return {"id": order_id, "status": "APPROVED"}
            return {"id": order_id, "status": "APPROVED",
                    "payer": {"email_address": email}}

        async def capture_order(self, order_id, request_id=None):
            self.captures.append(order_id)
            return {"capture_id": f"STUB-CAP-{order_id}",
                    "status": "COMPLETED", "rail": "stub"}

        async def payout(self, *a, **k):
            return await self._sim.payout(*a, **k)

        async def refund(self, *a, **k):
            return await self._sim.refund(*a, **k)

        async def get_payout_status(self, payout_batch_id):
            return await self._sim.get_payout_status(payout_batch_id)

    from pact.config import SETTINGS
    old_buyer_email = SETTINGS.buyer_sandbox_email
    old_seller_email = SETTINGS.seller_sandbox_email
    SETTINGS.buyer_sandbox_email = "buyer@example.com"
    SETTINGS.seller_sandbox_email = "seller@example.com"

    def run_to_approval(stub):
        main_mod.get_agent_payment_service = lambda: stub
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{deal['id']}/negotiate/run")
        deal = post(f"/api/deals/{deal['id']}/pay").json()
        return deal

    try:
        # Matching payers: capture proceeds.
        stub = ApprovalStub(payer_by_kind={"price": "buyer@example.com",
                                           "bond": "seller@example.com"})
        deal = run_to_approval(stub)
        did = deal["id"]
        check("sandbox deal waits in awaiting_approval",
              deal["state"] == "awaiting_approval", deal["state"])
        resp = post(f"/api/deals/{did}/pay/confirm")
        check("confirm with matching payers returns 200",
              resp.status_code == 200, resp.status_code)
        check("deal moves to paid_held", resp.json()["state"] == "paid_held",
              resp.json()["state"])
        check("both orders captured", len(stub.captures) == 2,
              stub.captures)
        check("payers_verified event logged",
              any(e["event_type"] == "payers_verified"
                  for e in resp.json()["ledger"]))

        # Wrong buyer payer: capture refused, retry works after approval.
        stub = ApprovalStub(payer_by_kind={"price": "mallory@example.com",
                                           "bond": "seller@example.com"})
        deal = run_to_approval(stub)
        did = deal["id"]
        resp = post(f"/api/deals/{did}/pay/confirm")
        check("confirm with the wrong buyer payer returns 409",
              resp.status_code == 409, resp.status_code)
        after = client.get(f"/api/deals/{did}").json()
        check("deal stays awaiting_approval after the refusal",
              after["state"] == "awaiting_approval", after["state"])
        check("no capture ran on the refused confirm",
              stub.captures == [], stub.captures)
        check("payer_mismatch event logged with both payers",
              any(e["event_type"] == "payer_mismatch"
                  and e["data"].get("price_payer") == "mallory@example.com"
                  for e in after["ledger"]),
              [e["event_type"] for e in after["ledger"]])
        stub.payer_by_kind["price"] = "buyer@example.com"
        resp = post(f"/api/deals/{did}/pay/confirm")
        check("confirm succeeds after the right account approves",
              resp.status_code == 200
              and resp.json()["state"] == "paid_held",
              f"{resp.status_code}: {resp.json()['state']}")

        # Order with no payer info (never approved): refused.
        stub = ApprovalStub(payer_by_kind={"price": None,
                                           "bond": "seller@example.com"})
        deal = run_to_approval(stub)
        did = deal["id"]
        resp = post(f"/api/deals/{did}/pay/confirm")
        check("confirm with an unapproved price order returns 409",
              resp.status_code == 409, resp.status_code)
        check("no capture ran", stub.captures == [], stub.captures)

        # Missing expected identities: fail closed.
        SETTINGS.buyer_sandbox_email = ""
        SETTINGS.seller_sandbox_email = ""
        stub = ApprovalStub(payer_by_kind={"price": "buyer@example.com",
                                           "bond": "seller@example.com"})
        deal = run_to_approval(stub)
        did = deal["id"]
        resp = post(f"/api/deals/{did}/pay/confirm")
        check("confirm without configured payer identities returns 409",
              resp.status_code == 409, resp.status_code)
        check("no capture ran", stub.captures == [], stub.captures)
        SETTINGS.buyer_sandbox_email = "buyer@example.com"
        SETTINGS.seller_sandbox_email = "seller@example.com"

        # Demo mode skips the check entirely.
        stub = ApprovalStub(mode="demo")
        deal = run_to_approval(stub)
        did = deal["id"]
        check("demo deal with approval urls waits in awaiting_approval",
              deal["state"] == "awaiting_approval", deal["state"])
        resp = post(f"/api/deals/{did}/pay/confirm")
        check("demo confirm skips the payer check and captures",
              resp.status_code == 200
              and resp.json()["state"] == "paid_held",
              f"{resp.status_code}: {resp.json()['state']}")
        check("demo captures ran without any order read",
              len(stub.captures) == 2, stub.captures)
    finally:
        main_mod.get_agent_payment_service = original_service
        SETTINGS.buyer_sandbox_email = old_buyer_email
        SETTINGS.seller_sandbox_email = old_seller_email

    print("PART M contract hash travels with the money (queue item L)")
    import asyncio
    import copy
    import json as json_mod
    from pact.negotiation import spec_hash

    def mutate_one_check(spec, idx):
        m = copy.deepcopy(spec)
        chk = m["acceptance_checks"][idx]
        v = chk.get("value")
        if isinstance(v, bool):
            v = None
        if isinstance(v, (int, float)):
            chk["value"] = v + 1
        elif isinstance(v, str) and v:
            chk["value"] = v + "X"
        else:
            for k, val in chk.items():
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    chk[k] = val + 1
                    break
            else:
                raise AssertionError(f"no mutable value in check {idx}")
        return m

    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    did = deal["id"]
    post(f"/api/deals/{did}/negotiate/run")
    deal = client.get(f"/api/deals/{did}").json()
    h = deal.get("contract_hash")
    check("contract hash recorded at agreement", bool(h) and len(h) == 64,
          str(h)[:16])
    # The hash commits to the stored frozen spec (integer cents
    # internally, queue item V), so hash the internal record, not the
    # dollar-denominated API view.
    from pact.store import DEALS
    stored_spec = DEALS[did]["spec"]
    check("hash equals the hash of the frozen spec",
          h == spec_hash(stored_spec))
    check("hash is deterministic across recomputes",
          spec_hash(stored_spec) == spec_hash(stored_spec))
    check("contract_written event carries the hash",
          any(e["event_type"] == "contract_written"
              and e["data"].get("contract_hash") == h
              for e in deal["ledger"]),
          [e["event_type"] for e in deal["ledger"]])
    n_checks = len(stored_spec["acceptance_checks"])
    check("spec has checks to mutate", n_checks > 0, n_checks)
    all_differ = True
    for i in range(n_checks):
        if spec_hash(mutate_one_check(stored_spec, i)) == h:
            all_differ = False
    check("hash changes when any single check changes", all_differ,
          n_checks)

    # Full demo flow: the tag on both orders equals deal id + spec hash.
    deal = post(f"/api/deals/{did}/pay").json()
    expected_tag = f"{did}:{h}"
    check("price order carries the contract tag",
          deal["payment"].get("contract_tag") == expected_tag,
          deal["payment"].get("contract_tag"))
    check("bond order carries the contract tag",
          deal["bond"].get("contract_tag") == expected_tag,
          deal["bond"].get("contract_tag"))
    check("demo hash_field reported honestly",
          deal["payment"].get("hash_field") == "demo_result"
          and deal["bond"].get("hash_field") == "demo_result",
          (deal["payment"].get("hash_field"),
           deal["bond"].get("hash_field")))

    # Sandbox shaped flow: the approval events record the hash and the
    # field that carried it. (Demo mode captures at pay time, so these
    # events never fire there.)
    class HashStub:
        mode = "sandbox"

        def __init__(self):
            self._sim = DemoSimulator()

        async def create_order(self, amount, currency, reference,
                               request_id=None, contract_tag=None):
            return {"order_id": "STUB-HASH-ORDER", "status": "CREATED",
                    "rail": "stub",
                    "hash_field": "stub" if contract_tag else None,
                    "contract_tag": contract_tag,
                    "approval_url": "https://example.com/approve/x"}

        async def capture_order(self, *a, **k):
            return await self._sim.capture_order(*a, **k)

        async def payout(self, *a, **k):
            return await self._sim.payout(*a, **k)

        async def refund(self, *a, **k):
            return await self._sim.refund(*a, **k)

        async def get_payout_status(self, payout_batch_id):
            return await self._sim.get_payout_status(payout_batch_id)

    real_service = main_mod.get_agent_payment_service
    main_mod.get_agent_payment_service = lambda: HashStub()
    try:
        d2 = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{d2['id']}/negotiate/run")
        d2 = post(f"/api/deals/{d2['id']}/pay").json()
    finally:
        main_mod.get_agent_payment_service = real_service
    h2 = d2.get("contract_hash")
    check("payment approval event records the hash",
          any(e["event_type"] == "payment_approval_requested"
              and e["data"].get("contract_hash") == h2
              and e["data"].get("hash_field") == "stub"
              for e in d2["ledger"]),
          [e["event_type"] for e in d2["ledger"]])
    check("bond approval event records the hash",
          any(e["event_type"] == "bond_approval_requested"
              and e["data"].get("contract_hash") == h2
              for e in d2["ledger"]))

    # REST rail: the tag lands in purchase_units[].custom_id.
    captured = {}

    async def fake_request(self, method, path, json_body=None,
                           request_id=None):
        captured["body"] = json_body
        return {"id": "ORDER-TEST", "status": "CREATED", "links": []}

    rest = PayPalClient.__new__(PayPalClient)
    old_request = PayPalClient._request
    PayPalClient._request = fake_request
    try:
        tag = f"{did}:" + "ab" * 32
        res = asyncio.run(rest.create_order(100.0, "USD", f"{did} price",
                                            contract_tag=tag))
        pu = captured["body"]["purchase_units"][0]
        check("REST custom_id carries deal id and hash",
              pu.get("custom_id") == tag, pu.get("custom_id"))
        check("REST reference_id untouched",
              pu.get("reference_id") == f"{did} price",
              pu.get("reference_id"))
        check("REST hash_field is custom_id",
              res.get("hash_field") == "custom_id", res.get("hash_field"))
        captured.clear()
        res = asyncio.run(rest.create_order(100.0, "USD", f"{did} price"))
        check("no custom_id without a tag",
              "custom_id" not in captured["body"]["purchase_units"][0])
        check("hash_field is None without a tag",
              res.get("hash_field") is None, res.get("hash_field"))
    finally:
        PayPalClient._request = old_request

    # Toolkit rail: no custom_id exists, so the item name carries the tag.
    from pact.paypal_agents import ToolkitOrders

    class FakeToolkitAPI:
        def __init__(self):
            self.last = None

        def run(self, tool, params):
            self.last = (tool, params)
            return json_mod.dumps({"id": "TK-ORDER-1", "status": "CREATED",
                                   "links": []})

    tk = ToolkitOrders.__new__(ToolkitOrders)
    tk._api = FakeToolkitAPI()
    tag = f"{did}:" + "cd" * 32
    res = asyncio.run(tk.create_order(100.0, "USD", f"{did} price",
                                      contract_tag=tag))
    check("toolkit item name carries deal id and hash",
          tk._api.last[1]["items"][0]["name"]
          == f"{did} price | contract {tag}",
          tk._api.last[1]["items"][0]["name"])
    check("toolkit hash_field is item_name",
          res.get("hash_field") == "item_name", res.get("hash_field"))

    # Verification summary records the same hash the orders carried.
    # (Demo mode captures at pay time, so there is no confirm step here.)
    # Deliver with the honest builder, not the empty one, so the deal
    # releases and the verification summary is written.
    resp = post(f"/api/deals/{did}/deliver", {"quality": "auto"})
    deal = post(f"/api/deals/{did}/verify").json()
    check("verification_summary records the contract hash",
          any(e["event_type"] == "verification_summary"
              and e["data"].get("contract_hash") == h
              for e in deal["ledger"]),
          [e["event_type"] for e in deal["ledger"]
           if e["event_type"] == "verification_summary"])
    check("contract hash never changed across the deal lifecycle",
          deal.get("contract_hash") == h, deal.get("contract_hash"))

    print()
    if FAILURES:
        print(f"HARDENING TESTS FAILED: {FAILURES}")
        return 1
    print("ALL HARDENING TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

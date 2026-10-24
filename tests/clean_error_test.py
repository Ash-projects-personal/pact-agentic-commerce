"""Clean error surfaces (queue item X).

Every money endpoint is forced to fail with a stubbed PayPal failure
whose raw body carries distinctive marker strings. Each test asserts:
the status code, the clean error envelope
{"error": {"code", "message", "correlation_id"}}, that none of the
marker strings appears anywhere in the response body, and that a
ledger event on the deal carries the same correlation id with the full
upstream detail recorded there only. A log capture proves the server
log line carries the id and the detail too.

Run with: NO_PROXY=localhost,127.0.0.1 python tests/clean_error_test.py
"""

import logging
import os
import re
import sys
import tempfile
from pathlib import Path

for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY",
            "PAYPAL_WEBHOOK_ID"):
    os.environ.pop(var, None)

# Isolate persistence: the middleware writes the store to SQLite after
# every response, so point the test run at a throwaway database.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail if not cond else ''}")
    if not cond:
        FAILURES.append(name)


MARKERS = {
    "create": "__raw_stub_marker__: ORDER-CREATE-FAIL",
    "capture": "__raw_stub_marker__: CAPTURE-FAIL",
    "payout": "__raw_stub_marker__: PAYOUT-FAIL",
    "refund": "__raw_stub_marker__: REFUND-FAIL",
    "order_read": "__raw_stub_marker__: ORDER-READ-FAIL",
    "grounding": "__raw_stub_marker__: GROUNDING-FAIL",
    "webhook": "__raw_stub_marker__: WEBHOOK-VERIFY-FAIL",
    "boom": "__raw_stub_marker__: UNEXPECTED-BOOM",
}
ALL_MARKER_STRINGS = list(MARKERS.values()) + [
    "stack_trace_stub_xyz", "debug_id_xyz",
]


def raw_body(marker):
    return ('{"__raw_stub_marker__": "%s", "debug_id": "debug_id_xyz", '
            '"name": "UNPROCESSABLE_ENTITY", '
            '"stack_trace_stub_xyz": "Traceback (most recent call last): '
            '... paypal rest 400 ..."}' % marker)


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


def main():
    from fastapi.testclient import TestClient

    import pact.main as main_mod
    from pact.main import app
    from pact.payments import DemoSimulator, PaymentError

    with TestClient(app, raise_server_exceptions=False) as client:
        _run(client, main_mod, DemoSimulator, PaymentError)


def _run(client, main_mod, DemoSimulator, PaymentError):
    from pact.store import DEALS

    capture = LogCapture()
    logging.getLogger("pact.upstream").addHandler(capture)
    # The generic 500 handler in main.py logs through pact.access.
    logging.getLogger("pact.access").addHandler(capture)

    original_service = main_mod.get_agent_payment_service

    # Demo client token store (queue item W): state-changing deal
    # endpoints require the per-deal role token in X-Deal-Token.
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

    def deal_ledger(deal_id):
        return client.get(f"/api/deals/{deal_id}").json()["ledger"]

    def assert_clean_envelope(name, resp, expected_code, expected_status,
                              markers):
        body = resp.json()
        check(f"{name}: status {expected_status}", resp.status_code == expected_status,
              f"got {resp.status_code}: {resp.text[:200]}")
        err = body.get("error") if isinstance(body, dict) else None
        check(f"{name}: clean envelope shape",
              isinstance(err, dict)
              and set(err.keys()) == {"code", "message", "correlation_id"},
              str(body)[:200])
        check(f"{name}: code {expected_code}",
              err and err.get("code") == expected_code,
              str(err)[:200])
        check(f"{name}: human message, no markers",
              err and isinstance(err.get("message"), str)
              and len(err["message"]) > 10
              and not any(m in err["message"] for m in markers),
              str(err)[:200])
        cid = err.get("correlation_id") if err else None
        check(f"{name}: correlation id looks like a uuid hex",
              isinstance(cid, str) and re.fullmatch(r"[0-9a-f]{32}", cid),
              str(cid))
        check(f"{name}: no marker string anywhere in the response body",
              not any(m in resp.text for m in markers), resp.text[:200])
        return cid

    def find_event(ledger, event_type, cid):
        for e in ledger:
            if (e["event_type"] == event_type
                    and e.get("data", {}).get("correlation_id") == cid):
                return e
        return None

    print("PART A order creation failure on POST pay")
    class FailCreateStub(DemoSimulator):
        async def create_order(self, *a, **k):
            raise PaymentError(raw_body(MARKERS["create"]))

    main_mod.get_agent_payment_service = lambda: FailCreateStub()
    try:
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{deal['id']}/negotiate/run")
        resp = post(f"/api/deals/{deal['id']}/pay")
        cid = assert_clean_envelope("pay/create failure", resp,
                                    "ORDER_CREATION_FAILED", 502,
                                    ALL_MARKER_STRINGS)
        ledger = deal_ledger(deal["id"])
        event = find_event(ledger, "payment_error", cid)
        check("pay/create: payment_error ledger event carries the same id",
              event is not None)
        check("pay/create: full detail recorded in the ledger event only",
              event is not None
              and MARKERS["create"] in event["data"].get("upstream_detail", ""),
              str(event["data"])[:160] if event else "no event")
        check("pay/create: deal state unchanged (still agreed)",
              client.get(f"/api/deals/{deal['id']}").json()["state"] == "agreed")
        check("pay/create: server log line carries the id and the detail",
              any(cid in r and MARKERS["create"] in r for r in capture.records))
    finally:
        main_mod.get_agent_payment_service = original_service

    print("PART B capture failure on POST pay")
    class FailCaptureStub(DemoSimulator):
        async def capture_order(self, *a, **k):
            raise PaymentError(raw_body(MARKERS["capture"]))

    main_mod.get_agent_payment_service = lambda: FailCaptureStub()
    try:
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{deal['id']}/negotiate/run")
        resp = post(f"/api/deals/{deal['id']}/pay")
        cid = assert_clean_envelope("pay/capture failure", resp,
                                    "CAPTURE_FAILED", 502, ALL_MARKER_STRINGS)
        after = client.get(f"/api/deals/{deal['id']}").json()
        event = find_event(after["ledger"], "payment_error", cid)
        check("pay/capture: payment_error ledger event carries the same id",
              event is not None)
        check("pay/capture: full detail recorded in the ledger event only",
              event is not None
              and MARKERS["capture"] in event["data"].get("upstream_detail", ""))
        check("pay/capture: payment not marked held",
              after["payment"]["status"] != "held", after["payment"]["status"])
    finally:
        main_mod.get_agent_payment_service = original_service

    print("PART C settlement payout failure on POST verify (release path)")
    class FailPayoutStub(DemoSimulator):
        async def payout(self, *a, **k):
            raise PaymentError(raw_body(MARKERS["payout"]))

    main_mod.get_agent_payment_service = lambda: FailPayoutStub()
    try:
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{deal['id']}/negotiate/run")
        post(f"/api/deals/{deal['id']}/pay")
        post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
        resp = post(f"/api/deals/{deal['id']}/verify")
        cid = assert_clean_envelope("verify/payout failure", resp,
                                    "PAYOUT_FAILED", 502, ALL_MARKER_STRINGS)
        after = client.get(f"/api/deals/{deal['id']}").json()
        event = find_event(after["ledger"], "payment_error", cid)
        check("verify/payout: payment_error ledger event carries the same id",
              event is not None)
        check("verify/payout: full detail recorded in the ledger event only",
              event is not None
              and MARKERS["payout"] in event["data"].get("upstream_detail", ""))
        check("verify/payout: deal stays verifying for a resume",
              after["state"] == "verifying", after["state"])
        check("verify/payout: leg entry records the code and the id",
              after["settlement"]["legs"]["price_payout"].get("error_code")
              == "PAYOUT_FAILED"
              and after["settlement"]["legs"]["price_payout"].get(
                  "correlation_id") == cid)
    finally:
        main_mod.get_agent_payment_service = original_service
    # Resume with a working service: the failed leg runs once, the deal
    # releases, and nothing is sent twice.
    resp = post(f"/api/deals/{deal['id']}/verify")
    check("verify/payout: resume after the clean error releases the deal",
          resp.status_code == 200
          and resp.json()["state"] == "released", resp.status_code)
    after = client.get(f"/api/deals/{deal['id']}").json()
    check("verify/payout: resumed payout leg ran exactly once",
          after["settlement"]["legs"]["price_payout"]["status"] == "done"
          and after["settlement"]["legs"]["price_payout"].get("attempt", 1) == 1)

    print("PART D settlement refund failure on POST verify (refund path)")
    class FailRefundStub(DemoSimulator):
        async def refund(self, *a, **k):
            raise PaymentError(raw_body(MARKERS["refund"]))

    main_mod.get_agent_payment_service = lambda: FailRefundStub()
    try:
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{deal['id']}/negotiate/run")
        post(f"/api/deals/{deal['id']}/pay")
        post(f"/api/deals/{deal['id']}/deliver", {"quality": "cheat"})
        resp = post(f"/api/deals/{deal['id']}/verify")
        cid = assert_clean_envelope("verify/refund failure", resp,
                                    "REFUND_FAILED", 502, ALL_MARKER_STRINGS)
        after = client.get(f"/api/deals/{deal['id']}").json()
        event = find_event(after["ledger"], "payment_error", cid)
        check("verify/refund: payment_error ledger event carries the same id",
              event is not None)
        check("verify/refund: full detail recorded in the ledger event only",
              event is not None
              and MARKERS["refund"] in event["data"].get("upstream_detail", ""))
        check("verify/refund: deal stays verifying for a resume",
              after["state"] == "verifying", after["state"])
    finally:
        main_mod.get_agent_payment_service = original_service
    resp = post(f"/api/deals/{deal['id']}/verify")
    check("verify/refund: resume after the clean error refunds the deal",
          resp.status_code == 200
          and resp.json()["state"] == "refunded", resp.status_code)

    print("PART E order read-back failure at pay/confirm (payer gate)")
    from pact.config import SETTINGS
    old_buyer, old_seller = (SETTINGS.buyer_sandbox_email,
                             SETTINGS.seller_sandbox_email)
    SETTINGS.buyer_sandbox_email = "buyer@example.com"
    SETTINGS.seller_sandbox_email = "seller@example.com"

    class FailOrderReadStub(DemoSimulator):
        mode = "sandbox"

        async def create_order(self, amount, currency, reference,
                               request_id=None, contract_tag=None):
            return {"order_id": "ORD-STUB-1", "status": "CREATED",
                    "approval_url": "https://sandbox.paypal.example/approve",
                    "demo": False, "rail": "stub",
                    "hash_field": None, "contract_tag": contract_tag}

        async def get_order_details(self, order_id):
            raise PaymentError(raw_body(MARKERS["order_read"]))

    main_mod.get_agent_payment_service = lambda: FailOrderReadStub()
    try:
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        post(f"/api/deals/{deal['id']}/negotiate/run")
        paid = post(f"/api/deals/{deal['id']}/pay").json()
        check("pay/confirm setup: deal is awaiting approval",
              paid["state"] == "awaiting_approval", paid["state"])
        resp = post(f"/api/deals/{deal['id']}/pay/confirm")
        cid = assert_clean_envelope("pay/confirm order read failure", resp,
                                    "ORDER_READ_FAILED", 502,
                                    ALL_MARKER_STRINGS)
        after = client.get(f"/api/deals/{deal['id']}").json()
        event = find_event(after["ledger"], "payer_mismatch", cid)
        check("pay/confirm: payer_mismatch ledger event carries the same id",
              event is not None)
        check("pay/confirm: full detail recorded in the ledger event only",
              event is not None
              and MARKERS["order_read"] in event["data"].get("upstream_detail", ""))
        check("pay/confirm: deal still awaiting approval",
              after["state"] == "awaiting_approval", after["state"])
    finally:
        main_mod.get_agent_payment_service = original_service
        SETTINGS.buyer_sandbox_email = old_buyer
        SETTINGS.seller_sandbox_email = old_seller

    print("PART F market grounding failure at deal creation")
    from pact.channel3 import Channel3Error
    before = len(DEALS)
    original_grounding = main_mod.get_grounding

    async def fail_grounding(query):
        raise Channel3Error(raw_body(MARKERS["grounding"]))

    main_mod.get_grounding = fail_grounding
    try:
        resp = post("/api/deals", {"scenario_id": "procurement"})
        cid = assert_clean_envelope("create/grounding failure", resp,
                                    "MARKET_GROUNDING_FAILED", 502,
                                    ALL_MARKER_STRINGS)
        check("create/grounding: no deal record stored", len(DEALS) == before,
              f"{before} -> {len(DEALS)}")
        check("create/grounding: server log line carries the id and detail",
              any(cid in r and MARKERS["grounding"] in r
                  for r in capture.records))
    finally:
        main_mod.get_grounding = original_grounding

    print("PART G webhook signature verification failure stays clean")
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    post(f"/api/deals/{deal['id']}/negotiate/run")
    deal = post(f"/api/deals/{deal['id']}/pay").json()
    order_id = deal["payment"]["order_id"]
    SETTINGS.paypal_client_id = "test-id"
    SETTINGS.paypal_client_secret = "test-secret"
    SETTINGS.paypal_webhook_id = "WH-TEST"

    async def fake_verify_error(self, headers, event):
        raise PaymentError(raw_body(MARKERS["webhook"]))

    original_verify = main_mod.PayPalClient.verify_webhook_signature
    main_mod.PayPalClient.verify_webhook_signature = fake_verify_error
    try:
        resp = client.post("/webhooks/paypal", json={
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": order_id},
        })
        check("webhook verify failure: 503", resp.status_code == 503,
              resp.status_code)
        body = resp.json()
        check("webhook verify failure: still reports not received",
              body.get("received") is False
              and body.get("signature_verification") == "error", body)
        check("webhook verify failure: no marker in the body",
              not any(m in resp.text for m in ALL_MARKER_STRINGS),
              resp.text[:200])
        check("webhook verify failure: carries a correlation id",
              isinstance(body.get("correlation_id"), str)
              and re.fullmatch(r"[0-9a-f]{32}", body["correlation_id"]),
              str(body.get("correlation_id")))
    finally:
        main_mod.PayPalClient.verify_webhook_signature = original_verify
        SETTINGS.paypal_client_id = ""
        SETTINGS.paypal_client_secret = ""
        SETTINGS.paypal_webhook_id = ""

    print("PART H unexpected exceptions get the clean 500 envelope")
    original_negotiate = main_mod.run_negotiation

    async def boom(deal, scenario, **kwargs):
        raise RuntimeError(raw_body(MARKERS["boom"]))

    main_mod.run_negotiation = boom
    try:
        deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
        resp = post(f"/api/deals/{deal['id']}/negotiate/run")
        cid = assert_clean_envelope("unexpected exception", resp,
                                    "INTERNAL_ERROR", 500, ALL_MARKER_STRINGS)
        check("unexpected exception: server log line carries the id",
              any(cid in r for r in capture.records))
    finally:
        main_mod.run_negotiation = original_negotiate

    print("PART I per-deal token 403s keep their clean shape")
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    resp = client.post(f"/api/deals/{deal['id']}/negotiate/run")
    check("missing token: 403", resp.status_code == 403, resp.status_code)
    body = resp.json()
    check("missing token: clean detail shape, human sentence",
          isinstance(body.get("detail"), str)
          and "X-Deal-Token" in body["detail"], str(body)[:160])
    check("missing token: no internal strings leak",
          not any(s in resp.text for s in
                  ("Traceback", "token_urlsafe", "compare_digest",
                   "UpstreamFailure", "__raw_stub_marker__")),
          resp.text[:200])
    resp = client.post(f"/api/deals/{deal['id']}/negotiate/run",
                       headers={"X-Deal-Token": "wrong-token"})
    check("wrong token: 403", resp.status_code == 403, resp.status_code)

    print(f"\n{len(FAILURES)} failures")
    if FAILURES:
        print("FAILED:", FAILURES)
        sys.exit(1)
    print("CLEAN ERROR TESTS: ALL PASSED")


if __name__ == "__main__":
    main()

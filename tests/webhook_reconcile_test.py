"""Webhook reconciliation tests (queue item Y).

Verified webhook events may ADVANCE reconciliation state, but never
authorize a settlement decision:

Y1. A payout-completion event for a pending payout leg resolves it
    through the same item-D follow-through path (the batch status is
    read back from PayPal; the event content is not trusted). The leg
    becomes done, one ledger event names the webhook event id, and the
    deal stays in "verifying": it leaves that state only through
    /verify. A later verify then settles the deal with no double money
    effect.
Y2. The same event id delivered twice is a pure idempotent ack: one
    reconciliation ledger event, no second finalize.
Y3. Out-of-order convergence: a deal that receives the payout event
    before its local status read ends in exactly the same final state
    as a deal that verifies first.
Y4. Unknown-resource webhooks are logged and ignored cleanly: a payout
    event naming a batch the deal never sent changes no leg, and an
    event for a completely unknown resource lands in the global webhook
    log touching no deal.
Y5. Capture/order/refund events that match the local record are
    ledger-logged no-ops: no state change, no money movement.
Y6. In live mode an unverified event is recorded but NOT reconciled.

Every case runs inside its own `with TestClient(app) as client:` block
(one shared event loop, per the checkpoint lesson). Demo mode only:
credentials are popped before import, persistence points at a throwaway
temp dir, and the simulator moves no real money.

Run with: NO_PROXY=localhost,127.0.0.1 .venv/bin/python \\
    tests/webhook_reconcile_test.py
Exits non-zero on the first failed assertion.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

# Force demo mode before the app modules read the environment.
for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY",
            "PAYPAL_WEBHOOK_ID"):
    os.environ.pop(var, None)

# Isolate persistence: the middleware writes the store to SQLite after
# every response, so point the test run at a throwaway database that
# never touches the real dev database at data/pact.db.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS_COUNT = 0
CASES_DONE = []


def check(name, cond, detail=""):
    """Fail fast: exits non-zero on the first failed assertion."""
    global PASS_COUNT
    if cond:
        PASS_COUNT += 1
        print(f"  PASS {name}")
        return
    print(f"  FAIL {name} {detail}")
    print()
    print(f"WEBHOOK RECONCILE TESTS FAILED at check: {name}")
    print(f"cases completed: {len(CASES_DONE)} "
          f"({', '.join(CASES_DONE) if CASES_DONE else 'none'})")
    print(f"checks passed before the failure: {PASS_COUNT}")
    raise SystemExit(1)


def case_done(name):
    CASES_DONE.append(name)
    print(f"  -> case {name} complete")


from fastapi.testclient import TestClient  # noqa: E402

from pact.config import SETTINGS  # noqa: E402
from pact.main import app  # noqa: E402
from pact.payments import DemoSimulator  # noqa: E402


class PendingPayout:
    """Make the simulator report every payout batch as PENDING.

    The payout create call still succeeds, so a settlement leg reaches
    the "sent" state and the deal waits in "verifying", exactly like a
    live payout batch that has not resolved yet. Restores the instant
    SUCCESS behavior on exit.
    """

    def __init__(self):
        self._orig = DemoSimulator.get_payout_status

    def __enter__(self):
        async def pending(self_, payout_batch_id):
            return {"batch_status": "PENDING", "items": []}

        DemoSimulator.get_payout_status = pending
        return self

    def __exit__(self, *exc):
        DemoSimulator.get_payout_status = self._orig
        return False


# Demo client token store (queue item W): state-changing deal endpoints
# require the per-deal role token in the X-Deal-Token header. Deliver
# acts as the seller; everything else here acts as the buyer.
_DEAL_TOKENS = {}


def post(client, path, body=None):
    m = re.match(r"^/api/deals/([^/]+)/", path)
    headers = None
    if m:
        role = "seller" if path.rstrip("/").endswith("/deliver") else "buyer"
        tok = _DEAL_TOKENS.get(m.group(1), {}).get(role)
        if tok:
            headers = {"X-Deal-Token": tok}
    resp = client.post(path, json=body or {}, headers=headers)
    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            data = None
        if (isinstance(data, dict) and data.get("id")
                and data.get("buyer_token")):
            _DEAL_TOKENS[data["id"]] = {
                "buyer": data.get("buyer_token"),
                "seller": data.get("seller_token"),
            }
    return resp


def get_deal(client, did):
    return client.get(f"/api/deals/{did}").json()


def count_events(deal, event_type):
    return sum(1 for e in deal["ledger"]
               if e["event_type"] == event_type)


def rep_deltas(deal):
    return sorted(e["data"]["delta"] for e in deal["ledger"]
                  if e["event_type"] == "reputation_change")


def reconcile_events(deal, event_id=None):
    events = [e for e in deal["ledger"]
              if e["event_type"] == "webhook_reconcile"]
    if event_id is not None:
        events = [e for e in events
                  if e["data"].get("webhook_event_id") == event_id]
    return events


def run_to_verifying_pending(client, scenario_id="logo_brand_kit"):
    """Drive a deal to verifying with the price payout leg sent but PENDING.

    The caller must hold a PendingPayout context so the simulator
    reports the batch pending; the first verify then leaves the leg
    "sent" and the deal "verifying". Returns the deal dict.
    """
    deal = post(client, "/api/deals", {"scenario_id": scenario_id}).json()
    did = deal["id"]
    post(client, f"/api/deals/{did}/negotiate/run")
    post(client, f"/api/deals/{did}/pay")
    post(client, f"/api/deals/{did}/deliver", {"quality": "auto"})
    deal = post(client, f"/api/deals/{did}/verify").json()
    assert deal["state"] == "verifying", deal["state"]
    assert (deal["settlement"]["legs"]["price_payout"]["status"] == "sent"
            ), deal["settlement"]["legs"]["price_payout"]["status"]
    return deal


def payout_event_body(event_id, batch_id):
    return {"id": event_id,
            "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
            "resource": {"payout_batch_id": batch_id,
                         "payout_item_id": "ITEM-1",
                         "transaction_status": "SUCCESS"}}


# ----------------------------------------------------------------------
# Y1: a payout event resolves a pending leg through the item-D read-back.
# ----------------------------------------------------------------------

def y1_payout_event_resolves_pending_leg():
    print("Y1 payout event resolves a pending payout leg, deal stays "
          "verifying")
    with TestClient(app, raise_server_exceptions=False) as client:
        with PendingPayout():
            deal = run_to_verifying_pending(client)
        did = deal["id"]
        batch_id = deal["settlement"]["legs"]["price_payout"]["result_id"]
        check("batch id recorded on the sent leg", bool(batch_id), batch_id)

        resp = client.post("/webhooks/paypal",
                           json=payout_event_body("WH-Y1-1", batch_id))
        check("payout event returns 200", resp.status_code == 200,
              resp.status_code)
        check("payout event matched the deal",
              resp.json()["matched_deal"] == did, resp.json())

        after = get_deal(client, did)
        legs = after["settlement"]["legs"]
        check("price payout leg resolved to done by the event",
              legs["price_payout"]["status"] == "done",
              legs["price_payout"]["status"])
        check("payment marked released on the confirmed leg",
              after["payment"]["status"] == "released",
              after["payment"]["status"])
        check("bond return leg untouched, still pending",
              legs["bond_return"]["status"] == "pending",
              legs["bond_return"]["status"])
        recs = reconcile_events(after, "WH-Y1-1")
        check("exactly one webhook_reconcile event naming the event id",
              len(recs) == 1, len(recs))
        check("reconcile event records the leg_confirmed action",
              recs[0]["data"].get("action") == "leg_confirmed",
              recs[0]["data"])
        check("exactly one payment_released money event",
              count_events(after, "payment_released") == 1,
              count_events(after, "payment_released"))
        check("deal does NOT leave verifying on a webhook alone",
              after["state"] == "verifying", after["state"])

        # The later verify finishes the deal with no double money effect.
        deal = post(client, f"/api/deals/{did}/verify").json()
        check("later verify settles the deal to released",
              deal["state"] == "released", deal["state"])
        check("payment released exactly once across webhook and verify",
              count_events(deal, "payment_released") == 1,
              count_events(deal, "payment_released"))
        check("bond returned exactly once",
              count_events(deal, "bond_returned") == 1,
              count_events(deal, "bond_returned"))
        check("release reputation applied exactly once",
              rep_deltas(deal) == [3, 6], rep_deltas(deal))
    case_done("Y1")


# ----------------------------------------------------------------------
# Y2: a duplicate event id is a pure idempotent ack.
# ----------------------------------------------------------------------

def y2_duplicate_event_id_is_idempotent():
    print("Y2 duplicate delivery of the same event id is idempotent")
    with TestClient(app, raise_server_exceptions=False) as client:
        with PendingPayout():
            deal = run_to_verifying_pending(client)
        did = deal["id"]
        batch_id = deal["settlement"]["legs"]["price_payout"]["result_id"]
        body = payout_event_body("WH-Y2-1", batch_id)

        resp1 = client.post("/webhooks/paypal", json=body)
        check("first delivery returns 200", resp1.status_code == 200,
              resp1.status_code)
        resp2 = client.post("/webhooks/paypal", json=body)
        check("second delivery returns 200, not an error",
              resp2.status_code == 200, resp2.status_code)
        check("second delivery is flagged a duplicate",
              resp2.json().get("duplicate") is True, resp2.json())

        after = get_deal(client, did)
        check("one reconcile event for the event id, not two",
              len(reconcile_events(after, "WH-Y2-1")) == 1,
              len(reconcile_events(after, "WH-Y2-1")))
        check("leg confirmed exactly once",
              count_events(after, "payment_released") == 1,
              count_events(after, "payment_released"))
        check("deal still verifying after the duplicate",
              after["state"] == "verifying", after["state"])

        # A DIFFERENT event id carrying the same payout news converges to
        # the same final state without moving money twice.
        resp3 = client.post(
            "/webhooks/paypal", json=payout_event_body("WH-Y2-2", batch_id))
        check("second event id returns 200", resp3.status_code == 200,
              resp3.status_code)
        after = get_deal(client, did)
        recs = reconcile_events(after, "WH-Y2-2")
        check("second event id logged as already_done",
              len(recs) == 1 and recs[0]["data"].get("action") == "already_done",
              [e["data"] for e in recs])
        check("still exactly one payment_released",
              count_events(after, "payment_released") == 1,
              count_events(after, "payment_released"))
        check("deal still verifying", after["state"] == "verifying",
              after["state"])
    case_done("Y2")


# ----------------------------------------------------------------------
# Y3: webhook-before-read vs verify-first converge to the same state.
# ----------------------------------------------------------------------

def y3_out_of_order_converges():
    print("Y3 webhook-first and verify-first converge to the same state")
    with TestClient(app, raise_server_exceptions=False) as client:
        # Deal A: the control. Pending leg resolved by a plain verify.
        with PendingPayout():
            deal_a = run_to_verifying_pending(client)
        did_a = deal_a["id"]
        deal_a = post(client, f"/api/deals/{did_a}/verify").json()
        check("control deal released", deal_a["state"] == "released",
              deal_a["state"])

        # Deal B: the payout event arrives before the local status read.
        with PendingPayout():
            deal_b = run_to_verifying_pending(client)
        did_b = deal_b["id"]
        batch_b = deal_b["settlement"]["legs"]["price_payout"]["result_id"]
        resp = client.post("/webhooks/paypal",
                           json=payout_event_body("WH-Y3-1", batch_b))
        check("event before the read returns 200", resp.status_code == 200,
              resp.status_code)
        deal_b = post(client, f"/api/deals/{did_b}/verify").json()
        check("event-first deal released", deal_b["state"] == "released",
              deal_b["state"])

        for key in ("state",):
            check(f"final {key} matches",
                  deal_b[key] == deal_a[key], (deal_a[key], deal_b[key]))
        for key in ("payment", "bond"):
            check(f"final {key} status matches",
                  deal_b[key]["status"] == deal_a[key]["status"],
                  (deal_a[key]["status"], deal_b[key]["status"]))
        for leg, entry in deal_a["settlement"]["legs"].items():
            check(f"final leg {leg} status matches",
                  deal_b["settlement"]["legs"][leg]["status"]
                  == entry["status"],
                  (entry["status"],
                   deal_b["settlement"]["legs"][leg]["status"]))
        for etype in ("payment_released", "bond_returned",
                      "reputation_change"):
            check(f"final {etype} count matches",
                  count_events(deal_b, etype) == count_events(deal_a, etype),
                  (count_events(deal_a, etype),
                   count_events(deal_b, etype)))
        check("final reputation deltas match",
              rep_deltas(deal_b) == rep_deltas(deal_a), rep_deltas(deal_b))
    case_done("Y3")


# ----------------------------------------------------------------------
# Y4: unknown-resource webhooks are logged and ignored cleanly.
# ----------------------------------------------------------------------

def y4_unknown_resource_ignored():
    print("Y4 unknown-resource webhooks are logged and ignored cleanly")
    with TestClient(app, raise_server_exceptions=False) as client:
        with PendingPayout():
            deal = run_to_verifying_pending(client)
        did = deal["id"]
        legs_before = {leg: dict(entry)
                       for leg, entry
                       in deal["settlement"]["legs"].items()}
        ledger_before = len(deal["ledger"])

        # A payout event naming a batch this deal never sent. The payload
        # also names the deal's order id (as a real PayPal payload would
        # carry other deal identifiers), so the event matches the deal
        # and the reconciliation path logs it as unknown.
        order_id = deal["payment"]["order_id"]
        resp = client.post(
            "/webhooks/paypal",
            json={"id": "WH-Y4-1",
                  "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
                  "resource": {"payout_batch_id": "BATCH-NEVER-SENT-1",
                               "payout_item_id": "ITEM-9",
                               "order_id": order_id}})
        check("unknown batch event returns 200", resp.status_code == 200,
              resp.status_code)
        check("unknown batch event matched the deal",
              resp.json()["matched_deal"] == did, resp.json())
        after = get_deal(client, did)
        recs = reconcile_events(after, "WH-Y4-1")
        check("unknown batch logged with the unknown_batch action",
              len(recs) == 1 and recs[0]["data"].get("action") == "unknown_batch",
              [e["data"] for e in recs])
        for leg, entry in legs_before.items():
            check(f"leg {leg} untouched by the unknown batch",
                  after["settlement"]["legs"][leg]["status"]
                  == entry["status"],
                  after["settlement"]["legs"][leg]["status"])
        check("no money events from the unknown batch",
              count_events(after, "payment_released") == 0
              and count_events(after, "payout_failed") == 0)
        check("deal still verifying", after["state"] == "verifying",
              after["state"])

        # An event for a completely unknown resource touches no deal.
        global_before = len(client.get("/api/webhooks").json())
        resp = client.post("/webhooks/paypal", json={
            "id": "WH-Y4-2",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": "UNKNOWN-CAPTURE-999"},
        })
        check("unknown capture event returns 200", resp.status_code == 200,
              resp.status_code)
        check("unknown capture event matched no deal",
              resp.json()["matched_deal"] is None, resp.json())
        global_after = client.get("/api/webhooks").json()
        check("unknown capture event recorded once in the global log",
              len(global_after) == global_before + 1,
              f"{global_before} -> {len(global_after)}")
        after = get_deal(client, did)
        check("deal ledger gained only the recorded-event entries",
              len(after["ledger"]) == ledger_before + 2,
              f"{ledger_before} -> {len(after['ledger'])}")
        check("deal state still verifying", after["state"] == "verifying",
              after["state"])
    case_done("Y4")


# ----------------------------------------------------------------------
# Y5: record events matching the local record are logged no-ops.
# ----------------------------------------------------------------------

def y5_record_events_are_noops():
    print("Y5 capture/order events matching the local record are no-ops")
    with TestClient(app, raise_server_exceptions=False) as client:
        deal = post(client, "/api/deals",
                    {"scenario_id": "logo_brand_kit"}).json()
        did = deal["id"]
        post(client, f"/api/deals/{did}/negotiate/run")
        deal = post(client, f"/api/deals/{did}/pay").json()
        check("deal paid and held", deal["state"] == "paid_held",
              deal["state"])
        order_id = deal["payment"]["order_id"]
        capture_id = deal["payment"]["capture_id"]

        # A capture event for the capture the deal flow already made.
        resp = client.post("/webhooks/paypal", json={
            "id": "WH-Y5-1",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": capture_id, "status": "COMPLETED"},
        })
        check("capture event returns 200", resp.status_code == 200,
              resp.status_code)
        after = get_deal(client, did)
        recs = reconcile_events(after, "WH-Y5-1")
        check("capture event logged as already_recorded",
              len(recs) == 1
              and recs[0]["data"].get("action") == "already_recorded",
              [e["data"] for e in recs])
        check("deal state unchanged", after["state"] == "paid_held",
              after["state"])
        check("payment status unchanged",
              after["payment"]["status"] == "held",
              after["payment"]["status"])

        # An order-approved event for the order the deal flow created.
        resp = client.post("/webhooks/paypal", json={
            "id": "WH-Y5-2",
            "event_type": "CHECKOUT.ORDER.APPROVED",
            "resource": {"id": order_id, "status": "APPROVED"},
        })
        check("order event returns 200", resp.status_code == 200,
              resp.status_code)
        after = get_deal(client, did)
        recs = reconcile_events(after, "WH-Y5-2")
        check("order event logged as already_recorded",
              len(recs) == 1
              and recs[0]["data"].get("action") == "already_recorded",
              [e["data"] for e in recs])
        check("no settlement leg fabricated by the record events",
              all(v["status"] == "pending"
                  for v in after["settlement"]["legs"].values()),
              after["settlement"]["legs"])
        check("no money events from the record events",
              count_events(after, "payment_released") == 0
              and count_events(after, "buyer_refunded") == 0)
    case_done("Y5")


# ----------------------------------------------------------------------
# Y6: an unverified event in live mode is recorded, never reconciled.
# ----------------------------------------------------------------------

def y6_live_unverified_event_not_reconciled():
    print("Y6 live-mode unverified event is recorded but not reconciled")
    with TestClient(app, raise_server_exceptions=False) as client:
        with PendingPayout():
            deal = run_to_verifying_pending(client)
        did = deal["id"]
        batch_id = deal["settlement"]["legs"]["price_payout"]["result_id"]

        # Pretend live mode for the gate check only: dummy credentials
        # flip paypal_live True while no webhook id is configured, so the
        # event stays not_configured. The deal flow stays demo (no real
        # money anywhere in this test).
        old_id, old_secret = (SETTINGS.paypal_client_id,
                              SETTINGS.paypal_client_secret)
        SETTINGS.paypal_client_id = "test-id"
        SETTINGS.paypal_client_secret = "test-secret"
        try:
            resp = client.post(
                "/webhooks/paypal",
                json=payout_event_body("WH-Y6-1", batch_id))
        finally:
            SETTINGS.paypal_client_id = old_id
            SETTINGS.paypal_client_secret = old_secret
        check("event returns 200", resp.status_code == 200, resp.status_code)
        body = resp.json()
        check("event labeled not_configured",
              body["signature_verification"] == "not_configured", body)
        check("event matched the deal", body["matched_deal"] == did, body)

        after = get_deal(client, did)
        check("no reconcile event for the unverified live event",
              reconcile_events(after, "WH-Y6-1") == [],
              len(reconcile_events(after, "WH-Y6-1")))
        check("leg still sent, never read back",
              after["settlement"]["legs"]["price_payout"]["status"] == "sent",
              after["settlement"]["legs"]["price_payout"]["status"])
        check("no money event from the unverified live event",
              count_events(after, "payment_released") == 0)
        check("deal still verifying", after["state"] == "verifying",
              after["state"])
    case_done("Y6")


def main():
    y1_payout_event_resolves_pending_leg()
    y2_duplicate_event_id_is_idempotent()
    y3_out_of_order_converges()
    y4_unknown_resource_ignored()
    y5_record_events_are_noops()
    y6_live_unverified_event_not_reconciled()
    print()
    print(f"ALL WEBHOOK RECONCILE TESTS PASSED: {len(CASES_DONE)} cases, "
          f"{PASS_COUNT} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

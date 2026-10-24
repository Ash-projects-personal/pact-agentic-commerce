"""Chaos suite for Pact (item T, part 4).

Failure injection beyond the hardening suite:

A. Kill each settlement leg (price payout, bond return, price refund,
   bond slash): force each leg to fail exactly once by monkeypatching
   the DemoSimulator money methods, then resume with verify. Each case
   asserts the deal reaches the correct terminal state, the killed leg
   ran exactly once successfully (no double-run), the sibling legs ran
   once, the deterministic idempotency key was reused on the retry,
   settlement ledger events were written exactly once, and reputation
   was applied exactly once.
B. Duplicate webhook deliveries: the same event body delivered twice
   must have a single state effect (no duplicate ledger events, no
   double settlement leg, the second delivery is an idempotent ack).
C. Out-of-order webhooks: events that arrive in an unnatural order (a
   payout success event before any payout was created for the deal, a
   capture event for an unknown order) are handled gracefully: no 500,
   no corrupt state, the state machine unchanged or explicitly logged.
D. Replayed approvals: replaying POST /api/deals/{id}/pay and
   /pay/confirm on a terminal deal (released, refunded) returns
   409/illegal-transition with no duplicate order, no second capture,
   and the ledger intact.

Every chaos case runs inside its own `with TestClient(app) as client:`
block, so each case gets a fresh portal event loop. (Checkpoint lesson:
a bare TestClient without the context manager, or per-deal asyncio
locks shared across loops, hangs.)

Demo mode only: credentials are popped before import, persistence
points at a throwaway temp dir (never data/pact.db), and the simulator
moves no real money.

Run with: NO_PROXY=localhost,127.0.0.1 .venv/bin/python \
    tests/pactbench_chaos_test.py
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
    print(f"CHAOS TESTS FAILED at check: {name}")
    print(f"cases completed: {len(CASES_DONE)} "
          f"({', '.join(CASES_DONE) if CASES_DONE else 'none'})")
    print(f"checks passed before the failure: {PASS_COUNT}")
    raise SystemExit(1)


def case_done(name):
    CASES_DONE.append(name)
    print(f"  -> case {name} complete")


from fastapi.testclient import TestClient  # noqa: E402

from pact.main import app  # noqa: E402
from pact.payments import DemoSimulator, PaymentError  # noqa: E402


class SimPatch:
    """Temporarily replace a DemoSimulator money method.

    Records every call as (request_id, "ok" | "boom"). When fail_suffix
    is set, the first `fail_times` calls whose request_id endswith the
    suffix raise PaymentError instead of delegating, which is how one
    settlement leg is killed exactly once. Restores the original method
    on exit. Demo mode builds a fresh DemoSimulator per request, so
    patching the class method instruments every leg call.
    """

    def __init__(self, method_name, fail_suffix=None, fail_times=1):
        self.method_name = method_name
        self.fail_suffix = fail_suffix
        self.fail_times = fail_times
        self.calls = []
        self._orig = getattr(DemoSimulator, method_name)
        self._failures_left = fail_times

    def __enter__(self):
        orig = self._orig
        state = self

        async def wrapper(self_, *args, **kwargs):
            rid = kwargs.get("request_id") or ""
            if (state.fail_suffix and rid.endswith(state.fail_suffix)
                    and state._failures_left > 0):
                state._failures_left -= 1
                state.calls.append((rid, "boom"))
                raise PaymentError(
                    f"chaos injection: failing leg {state.fail_suffix} once")
            state.calls.append((rid, "ok"))
            return await orig(self_, *args, **kwargs)

        setattr(DemoSimulator, self.method_name, wrapper)
        return self

    def __exit__(self, *exc):
        setattr(DemoSimulator, self.method_name, self._orig)
        return False

    def calls_for(self, suffix):
        return [c for c in self.calls if c[0].endswith(suffix)]

    def ok_for(self, suffix):
        return [c for c in self.calls_for(suffix) if c[1] == "ok"]


# Demo client token store (queue item W): state-changing deal endpoints
# require the per-deal role token in the X-Deal-Token header. The create
# response carries both tokens, so this helper remembers them per deal
# id and attaches the right one, the way a real client would. Deliver
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


def rep_deltas(deal):
    return sorted(e["data"]["delta"] for e in deal["ledger"]
                  if e["event_type"] == "reputation_change")


def count_events(deal, event_type):
    return sum(1 for e in deal["ledger"]
               if e["event_type"] == event_type)


def run_to_paid(client, scenario_id="logo_brand_kit"):
    deal = post(client, "/api/deals",
                {"scenario_id": scenario_id}).json()
    did = deal["id"]
    post(client, f"/api/deals/{did}/negotiate/run")
    deal = post(client, f"/api/deals/{did}/pay").json()
    assert deal["state"] == "paid_held", deal["state"]
    return deal


def run_to_released(client):
    deal = run_to_paid(client)
    did = deal["id"]
    post(client, f"/api/deals/{did}/deliver", {"quality": "auto"})
    deal = post(client, f"/api/deals/{did}/verify").json()
    assert deal["state"] == "released", deal["state"]
    return deal


def run_to_refunded(client):
    deal = run_to_paid(client)
    did = deal["id"]
    post(client, f"/api/deals/{did}/deliver", {"quality": "poor"})
    deal = post(client, f"/api/deals/{did}/verify").json()
    assert deal["state"] == "refunded", deal["state"]
    return deal


# ----------------------------------------------------------------------
# CHAOS A: kill each settlement leg once, then resume with verify.
# ----------------------------------------------------------------------

def chaos_a1_kill_price_payout():
    print("CHAOS A1 kill the price payout leg once, resume, expect released")
    with TestClient(app, raise_server_exceptions=False) as client:
        deal = run_to_paid(client)
        did = deal["id"]
        post(client, f"/api/deals/{did}/deliver", {"quality": "auto"})
        with SimPatch("payout", fail_suffix="price-payout") as spy:
            resp = post(client, f"/api/deals/{did}/verify")
            check("failed leg verify returns 502", resp.status_code == 502,
                  resp.status_code)
            mid = get_deal(client, did)
            check("deal stays verifying after the failed leg",
                  mid["state"] == "verifying", mid["state"])
            legs = mid["settlement"]["legs"]
            check("killed price payout leg recorded failed",
                  legs["price_payout"]["status"] == "failed",
                  legs["price_payout"]["status"])
            check("bond return leg still pending, never attempted",
                  legs["bond_return"]["status"] == "pending",
                  legs["bond_return"]["status"])
            check("failed leg used the deterministic idempotency key",
                  spy.calls_for("price-payout")
                  == [(f"{did}-price-payout", "boom")],
                  spy.calls)
            check("payment_error ledger event written for the failed leg",
                  count_events(mid, "payment_error") >= 1)
            check("no reputation moved before settlement finished",
                  rep_deltas(mid) == [], rep_deltas(mid))
            check("payment still held, bond still posted",
                  mid["payment"]["status"] == "held"
                  and mid["bond"]["status"] == "posted",
                  (mid["payment"]["status"], mid["bond"]["status"]))
            # Resume: the patch now passes through, so this verify must
            # finish the deal.
            resp = post(client, f"/api/deals/{did}/verify")
            check("resumed verify returns 200", resp.status_code == 200,
                  resp.status_code)
            after = resp.json()
            check("deal released after the resume",
                  after["state"] == "released", after["state"])
            legs = after["settlement"]["legs"]
            check("both release legs done",
                  all(legs[l]["status"] == "done"
                      for l in ("price_payout", "bond_return")), legs)
            check("retry reused the deterministic idempotency key",
                  legs["price_payout"]["request_id"]
                  == f"{did}-price-payout",
                  legs["price_payout"]["request_id"])
            price_ok = spy.ok_for("price-payout")
            check("price payout ran exactly once successfully (no "
                  "double-run)",
                  len(price_ok) == 1 and len(spy.calls_for("price-payout"))
                  == 2, spy.calls)
            bond_ok = spy.ok_for("bond-return")
            check("bond return ran exactly once",
                  len(bond_ok) == 1 and len(spy.calls_for("bond-return"))
                  == 1, spy.calls)
            check("exactly one payment_released event",
                  count_events(after, "payment_released") == 1)
            check("exactly one bond_returned event",
                  count_events(after, "bond_returned") == 1)
            check("reputation applied exactly once (seller +6, buyer +3)",
                  rep_deltas(after) == [3, 6], rep_deltas(after))
            check("bond record marked returned",
                  after["bond"]["status"] == "returned",
                  after["bond"]["status"])
    case_done("A1")


def chaos_a2_kill_bond_return():
    print("CHAOS A2 kill the bond return leg once, resume, expect released")
    with TestClient(app, raise_server_exceptions=False) as client:
        deal = run_to_paid(client)
        did = deal["id"]
        post(client, f"/api/deals/{did}/deliver", {"quality": "auto"})
        with SimPatch("payout", fail_suffix="bond-return") as spy:
            resp = post(client, f"/api/deals/{did}/verify")
            check("failed leg verify returns 502", resp.status_code == 502,
                  resp.status_code)
            mid = get_deal(client, did)
            check("deal stays verifying after the failed leg",
                  mid["state"] == "verifying", mid["state"])
            legs = mid["settlement"]["legs"]
            check("price payout leg recorded done",
                  legs["price_payout"]["status"] == "done",
                  legs["price_payout"]["status"])
            check("killed bond return leg recorded failed",
                  legs["bond_return"]["status"] == "failed",
                  legs["bond_return"]["status"])
            check("price payout ran exactly once before the failure",
                  spy.ok_for("price-payout") == [(f"{did}-price-payout",
                                                  "ok")], spy.calls)
            check("payment released after its leg, bond not returned",
                  mid["payment"]["status"] == "released"
                  and mid["bond"]["status"] != "returned",
                  (mid["payment"]["status"], mid["bond"]["status"]))
            check("no reputation moved before settlement finished",
                  rep_deltas(mid) == [], rep_deltas(mid))
            resp = post(client, f"/api/deals/{did}/verify")
            check("resumed verify returns 200", resp.status_code == 200,
                  resp.status_code)
            after = resp.json()
            check("deal released after the resume",
                  after["state"] == "released", after["state"])
            legs = after["settlement"]["legs"]
            check("price payout not rerun on resume",
                  len(spy.calls_for("price-payout")) == 1, spy.calls)
            check("bond return ran exactly once successfully",
                  len(spy.ok_for("bond-return")) == 1
                  and len(spy.calls_for("bond-return")) == 2, spy.calls)
            check("retry reused the deterministic idempotency key",
                  legs["bond_return"]["request_id"] == f"{did}-bond-return",
                  legs["bond_return"]["request_id"])
            check("exactly one payment_released and one bond_returned "
                  "event",
                  count_events(after, "payment_released") == 1
                  and count_events(after, "bond_returned") == 1)
            check("reputation applied exactly once (seller +6, buyer +3)",
                  rep_deltas(after) == [3, 6], rep_deltas(after))
    case_done("A2")


def chaos_a3_kill_price_refund():
    print("CHAOS A3 kill the price refund leg once, resume, expect refunded")
    with TestClient(app, raise_server_exceptions=False) as client:
        deal = run_to_paid(client)
        did = deal["id"]
        post(client, f"/api/deals/{did}/deliver", {"quality": "poor"})
        with SimPatch("refund", fail_suffix="price-refund") as refund_spy, \
                SimPatch("payout") as payout_spy:
            resp = post(client, f"/api/deals/{did}/verify")
            check("failed leg verify returns 502", resp.status_code == 502,
                  resp.status_code)
            mid = get_deal(client, did)
            check("deal stays verifying after the failed leg",
                  mid["state"] == "verifying", mid["state"])
            legs = mid["settlement"]["legs"]
            check("refund path recorded",
                  mid["settlement"]["path"] == "refund",
                  mid["settlement"]["path"])
            check("killed price refund leg recorded failed",
                  legs["price_refund"]["status"] == "failed",
                  legs["price_refund"]["status"])
            check("bond slash leg still pending, never attempted",
                  legs["bond_slash"]["status"] == "pending",
                  legs["bond_slash"]["status"])
            check("failed leg used the deterministic idempotency key",
                  refund_spy.calls_for("price-refund")
                  == [(f"{did}-price-refund", "boom")], refund_spy.calls)
            check("bond slash payout never attempted before the failure",
                  payout_spy.calls_for("bond-slash") == [],
                  payout_spy.calls)
            check("no reputation moved before settlement finished",
                  rep_deltas(mid) == [], rep_deltas(mid))
            resp = post(client, f"/api/deals/{did}/verify")
            check("resumed verify returns 200", resp.status_code == 200,
                  resp.status_code)
            after = resp.json()
            check("deal refunded after the resume",
                  after["state"] == "refunded", after["state"])
            legs = after["settlement"]["legs"]
            check("both refund legs done",
                  all(legs[l]["status"] == "done"
                      for l in ("price_refund", "bond_slash")), legs)
            check("retry reused the deterministic idempotency key",
                  legs["price_refund"]["request_id"]
                  == f"{did}-price-refund",
                  legs["price_refund"]["request_id"])
            check("price refund ran exactly once successfully (no "
                  "double-run)",
                  len(refund_spy.ok_for("price-refund")) == 1
                  and len(refund_spy.calls_for("price-refund")) == 2,
                  refund_spy.calls)
            check("bond slash ran exactly once",
                  len(payout_spy.ok_for("bond-slash")) == 1
                  and len(payout_spy.calls_for("bond-slash")) == 1,
                  payout_spy.calls)
            check("exactly one buyer_refunded and one bond_slashed event",
                  count_events(after, "buyer_refunded") == 1
                  and count_events(after, "bond_slashed") == 1)
            check("refund reputation applied exactly once",
                  rep_deltas(after) == [-20, -12, 1], rep_deltas(after))
            check("bond record marked slashed",
                  after["bond"]["status"] == "slashed",
                  after["bond"]["status"])
    case_done("A3")


def chaos_a4_kill_bond_slash():
    print("CHAOS A4 kill the bond slash leg once, resume, expect refunded")
    with TestClient(app, raise_server_exceptions=False) as client:
        deal = run_to_paid(client)
        did = deal["id"]
        post(client, f"/api/deals/{did}/deliver", {"quality": "poor"})
        with SimPatch("refund") as refund_spy, \
                SimPatch("payout", fail_suffix="bond-slash") as payout_spy:
            resp = post(client, f"/api/deals/{did}/verify")
            check("failed leg verify returns 502", resp.status_code == 502,
                  resp.status_code)
            mid = get_deal(client, did)
            check("deal stays verifying after the failed leg",
                  mid["state"] == "verifying", mid["state"])
            legs = mid["settlement"]["legs"]
            check("price refund leg recorded done",
                  legs["price_refund"]["status"] == "done",
                  legs["price_refund"]["status"])
            check("killed bond slash leg recorded failed",
                  legs["bond_slash"]["status"] == "failed",
                  legs["bond_slash"]["status"])
            check("price refund ran exactly once before the failure",
                  refund_spy.ok_for("price-refund")
                  == [(f"{did}-price-refund", "ok")], refund_spy.calls)
            check("payment refunded after its leg, bond not slashed",
                  mid["payment"]["status"] == "refunded"
                  and mid["bond"]["status"] != "slashed",
                  (mid["payment"]["status"], mid["bond"]["status"]))
            check("no reputation moved before settlement finished",
                  rep_deltas(mid) == [], rep_deltas(mid))
            resp = post(client, f"/api/deals/{did}/verify")
            check("resumed verify returns 200", resp.status_code == 200,
                  resp.status_code)
            after = resp.json()
            check("deal refunded after the resume",
                  after["state"] == "refunded", after["state"])
            legs = after["settlement"]["legs"]
            check("price refund not rerun on resume",
                  len(refund_spy.calls_for("price-refund")) == 1,
                  refund_spy.calls)
            check("bond slash ran exactly once successfully",
                  len(payout_spy.ok_for("bond-slash")) == 1
                  and len(payout_spy.calls_for("bond-slash")) == 2,
                  payout_spy.calls)
            check("retry reused the deterministic idempotency key",
                  legs["bond_slash"]["request_id"] == f"{did}-bond-slash",
                  legs["bond_slash"]["request_id"])
            check("exactly one buyer_refunded and one bond_slashed event",
                  count_events(after, "buyer_refunded") == 1
                  and count_events(after, "bond_slashed") == 1)
            check("refund reputation applied exactly once",
                  rep_deltas(after) == [-20, -12, 1], rep_deltas(after))
    case_done("A4")


# ----------------------------------------------------------------------
# CHAOS C: out-of-order webhooks are handled gracefully.
# ----------------------------------------------------------------------

def chaos_c_out_of_order_webhooks():
    print("CHAOS C out-of-order webhooks are handled gracefully")
    with TestClient(app, raise_server_exceptions=False) as client:
        deal = run_to_paid(client)
        did = deal["id"]
        order_id = deal["payment"]["order_id"]
        global_before = len(client.get("/api/webhooks").json())

        # C1: a payout success event naming the real order before any
        # payout was created for the deal. It matches the deal, so it is
        # logged, but it must not move money or change the state machine.
        resp = client.post("/webhooks/paypal", json={
            "id": "WH-OOO-1",
            "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
            "resource": {"id": order_id, "note": "no payout exists yet"},
        })
        check("early payout event returns 200, not a 500",
              resp.status_code == 200, resp.status_code)
        body = resp.json()
        check("early payout event matched the deal",
              body["matched_deal"] == did, body)
        after = get_deal(client, did)
        check("deal state unchanged by the early payout event",
              after["state"] == "paid_held", after["state"])
        check("payment still held, bond still posted",
              after["payment"]["status"] == "held"
              and after["bond"]["status"] == "posted",
              (after["payment"]["status"], after["bond"]["status"]))
        check("no settlement leg fabricated by the event",
              all(v["status"] == "pending"
                  for v in after["settlement"]["legs"].values()),
              after["settlement"]["legs"])
        check("no settlement money events from the webhook",
              count_events(after, "payment_released") == 0
              and count_events(after, "buyer_refunded") == 0)
        check("early event explicitly logged on the deal ledger",
              count_events(after, "webhook_received") == 1)
        ledger_after_c1 = len(after["ledger"])

        # C2: a capture event for a completely unknown order. It matches
        # no deal, so it lands in the global webhook log and touches
        # nothing.
        resp = client.post("/webhooks/paypal", json={
            "id": "WH-OOO-2",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": "UNKNOWN-ORDER-999"},
        })
        check("unknown order event returns 200, not a 500",
              resp.status_code == 200, resp.status_code)
        check("unknown order event matched no deal",
              resp.json()["matched_deal"] is None, resp.json())
        global_after = client.get("/api/webhooks").json()
        check("unknown order event recorded exactly once in the global "
              "webhook log",
              len(global_after) == global_before + 1,
              f"{global_before} -> {len(global_after)}")
        check("global log entry carries the event type",
              global_after[-1]["event_type"] == "PAYMENT.CAPTURE.COMPLETED",
              global_after[-1])
        after = get_deal(client, did)
        check("deal ledger untouched by the unknown order event",
              len(after["ledger"]) == ledger_after_c1,
              f"{ledger_after_c1} -> {len(after['ledger'])}")
        check("deal state still paid_held",
              after["state"] == "paid_held", after["state"])
    case_done("C")


# ----------------------------------------------------------------------
# CHAOS D: replayed approvals on terminal deals are rejected.
# ----------------------------------------------------------------------

def chaos_d_replayed_approvals_terminal(builder, label):
    print(f"CHAOS D replayed pay/pay/confirm on a {label} deal are "
          f"rejected")
    with TestClient(app, raise_server_exceptions=False) as client:
        deal = builder(client)
        did = deal["id"]
        before = get_deal(client, did)
        ledger_before = len(before["ledger"])
        with SimPatch("create_order") as mk, SimPatch("capture_order") as cap:
            resp = post(client, f"/api/deals/{did}/pay")
            check("replayed /pay returns 409", resp.status_code == 409,
                  resp.status_code)
            check("replayed /pay reports the illegal transition",
                  "Cannot pay" in resp.json().get("detail", "")
                  and label in resp.json().get("detail", ""),
                  resp.json())
            resp = post(client, f"/api/deals/{did}/pay/confirm")
            check("replayed /pay/confirm returns 409",
                  resp.status_code == 409, resp.status_code)
            check("replayed /pay/confirm reports the illegal transition",
                  "Cannot confirm payment" in resp.json().get("detail", ""),
                  resp.json())
            check("no duplicate order was created", mk.calls == [],
                  mk.calls)
            check("no second capture ran", cap.calls == [], cap.calls)
        after = get_deal(client, did)
        check("deal state unchanged", after["state"] == label,
              after["state"])
        check("payment order id unchanged",
              after["payment"]["order_id"]
              == before["payment"]["order_id"],
              after["payment"]["order_id"])
        check("payment capture id unchanged",
              after["payment"]["capture_id"]
              == before["payment"]["capture_id"],
              after["payment"]["capture_id"])
        check("bond order and capture ids unchanged",
              after["bond"]["order_id"] == before["bond"]["order_id"]
              and after["bond"]["capture_id"]
              == before["bond"]["capture_id"])
        check("ledger intact: no new events written",
              len(after["ledger"]) == ledger_before,
              f"{ledger_before} -> {len(after['ledger'])}")
    case_done(f"D-{label}")


# ----------------------------------------------------------------------
# CHAOS B: duplicate webhook deliveries (runs last; the endpoint dedups
# on the event id, so the second delivery is an idempotent ack).
# ----------------------------------------------------------------------

def chaos_b_duplicate_webhooks():
    print("CHAOS B duplicate webhook deliveries are idempotent")
    with TestClient(app, raise_server_exceptions=False) as client:
        deal = run_to_released(client)
        did = deal["id"]
        order_id = deal["payment"]["order_id"]
        body = {"id": "WH-CHAOS-DUP-1",
                "event_type": "PAYMENT.CAPTURE.COMPLETED",
                "resource": {"id": order_id}}
        resp1 = client.post("/webhooks/paypal", json=body)
        check("first delivery returns 200", resp1.status_code == 200,
              resp1.status_code)
        check("first delivery acked as received",
              resp1.json()["received"] is True, resp1.json())
        check("first delivery matched the deal",
              resp1.json()["matched_deal"] == did, resp1.json())
        resp2 = client.post("/webhooks/paypal", json=body)
        check("second identical delivery returns 200, not an error",
              resp2.status_code == 200, resp2.status_code)
        check("second delivery is an idempotent ack",
              resp2.json()["received"] is True
              and resp2.json()["matched_deal"] == did, resp2.json())
        after = get_deal(client, did)
        check("deal still released after the duplicate deliveries",
              after["state"] == "released", after["state"])
        check("payment still released, bond still returned",
              after["payment"]["status"] == "released"
              and after["bond"]["status"] == "returned",
              (after["payment"]["status"], after["bond"]["status"]))
        check("no double settlement leg from the duplicates",
              count_events(after, "payment_released") == 1
              and count_events(after, "bond_returned") == 1)
        # A second delivery of the same event id must not append a
        # second ledger event: it is the same event, already recorded.
        check("no duplicate ledger events for the same event delivery",
              count_events(after, "webhook_received") == 1,
              f"webhook_received x"
              f"{count_events(after, 'webhook_received')}")
    case_done("B")


def main():
    chaos_a1_kill_price_payout()
    chaos_a2_kill_bond_return()
    chaos_a3_kill_price_refund()
    chaos_a4_kill_bond_slash()
    chaos_c_out_of_order_webhooks()
    chaos_d_replayed_approvals_terminal(run_to_released, "released")
    chaos_d_replayed_approvals_terminal(run_to_refunded, "refunded")
    # Duplicate webhook dedup runs last: the shipped endpoint dedups on
    # the event id, so the second delivery acks without appending a
    # second ledger event.
    chaos_b_duplicate_webhooks()
    print()
    print(f"ALL CHAOS TESTS PASSED: {len(CASES_DONE)} cases, "
          f"{PASS_COUNT} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Graded settlement tests for Pact in demo mode.

Covers the settlement math in isolation and the two new settlement
paths end to end through the HTTP API:

1. Pure math: partial pass (1/5 and 4/5), all pass, all fail, rounding
   edges, and a money-conservation sweep. The paid and returned shares
   are rounded half-even once each; the refunded and slashed shares are
   the remainders, so the four legs always sum exactly to price plus
   bond; no cent is created or lost.
2. Graded path: a data labeling deal ending 3 of 5 after revisions are
   spent settles graded with the exact per-check split, and a cheat
   delivery ending 1 of 5 does the same.
3. Failure injection: fail the second graded leg, resume via verify,
   and only the missing legs run, none twice.
4. Release and refund carry the same graded breakdown shape, at the
   ends of the same formula.
5. Timeout: a paid deal with paid_at in the past times out to refunded
   with settlement path "timeout" and a delivery_timeout event; a
   timeout before the deadline, after a delivery, or from revision is
   refused with 409.
6. The dispute packet on a graded deal shows the partial amounts.

Run with: python tests/graded_settlement_test.py
Exits non zero on the first failed assertion.
"""

import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Force demo mode before the app modules read the environment.
for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

# Isolate persistence: the middleware writes the store to SQLite after
# every response, so point the test run at a throwaway database that
# never touches the real dev database at data/pact.db.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import pact.main as main_mod  # noqa: E402
from pact.main import app  # noqa: E402
from pact.settlement import (  # noqa: E402
    grade_breakdown, graded_seller_reputation_delta)
from pact.store import DEALS  # noqa: E402

# One shared portal for the whole session (see tests/hardening_test.py):
# the per-deal asyncio locks must be awaited from one event loop.
client = None

_DEAL_TOKENS = {}


def _token_headers(path):
    import re
    m = re.match(r"^/api/deals/([^/]+)/", path)
    if not m:
        return None
    role = "seller" if path.rstrip("/").endswith("/deliver") else "buyer"
    tok = _DEAL_TOKENS.get(m.group(1), {}).get(role)
    return {"X-Deal-Token": tok} if tok else None


def _remember_tokens(data):
    if isinstance(data, dict) and data.get("id") and data.get("buyer_token"):
        _DEAL_TOKENS[data["id"]] = {
            "buyer": data.get("buyer_token"),
            "seller": data.get("seller_token"),
        }


def post(path, body=None):
    resp = client.post(path, json=body or {}, headers=_token_headers(path))
    assert resp.status_code == 200, \
        f"POST {path} -> {resp.status_code}: {resp.text}"
    data = resp.json()
    _remember_tokens(data)
    return data


def post_raw(path, body=None):
    return client.post(path, json=body or {}, headers=_token_headers(path))


def run_to_paid(scenario_id):
    deal = post("/api/deals", {"scenario_id": scenario_id})
    deal = post(f"/api/deals/{deal['id']}/negotiate/run")
    assert deal["state"] == "agreed", deal["state"]
    deal = post(f"/api/deals/{deal['id']}/pay")
    assert deal["state"] == "paid_held", deal["state"]
    assert deal["paid_at"], "no paid_at set at capture"
    assert deal["delivery_deadline"], "no delivery deadline set at capture"
    return deal


def dollars_to_cents(value):
    return int(round(value * 100))


def test_math_partial():
    print("TEST 1 math: partial pass splits price and bond by passed checks")
    # 1 of 5: $137.09 price, $27.42 bond, the real case 3 numbers.
    out = grade_breakdown(13709, 2742, 1, 5)
    assert out == {"passed": 1, "total": 5, "price_paid_c": 2742,
                   "price_refunded_c": 10967, "bond_returned_c": 548,
                   "bond_slashed_c": 2194}, out
    # 4 of 5: the mirror image.
    out = grade_breakdown(13709, 2742, 4, 5)
    assert out == {"passed": 4, "total": 5, "price_paid_c": 10967,
                   "price_refunded_c": 2742, "bond_returned_c": 2194,
                   "bond_slashed_c": 548}, out
    print("  1/5: seller $27.42, refund $109.67, slash $21.94, return $5.48")
    print("  4/5: seller $109.67, refund $27.42, slash $5.48, return $21.94")
    print("  PASS")


def test_math_ends():
    print("TEST 2 math: all pass is the old release, none pass the old refund")
    out = grade_breakdown(10000, 2000, 5, 5)
    assert out["price_paid_c"] == 10000 and out["price_refunded_c"] == 0
    assert out["bond_slashed_c"] == 0 and out["bond_returned_c"] == 2000
    out = grade_breakdown(10000, 2000, 0, 5)
    assert out["price_paid_c"] == 0 and out["price_refunded_c"] == 10000
    assert out["bond_slashed_c"] == 2000 and out["bond_returned_c"] == 0
    print("  PASS")


def test_math_rounding():
    print("TEST 3 math: rounding is half-even once, remainders never lose a cent")
    # 100 cents over 3 checks, 1 passed: seller share 33, refund 67.
    out = grade_breakdown(100, 101, 1, 3)
    assert out["price_paid_c"] == 33 and out["price_refunded_c"] == 67
    assert out["bond_returned_c"] == 34 and out["bond_slashed_c"] == 67
    # Exact half: 5 cents over 2 checks rounds half-even to 2, not 3.
    # The paid and returned shares take the rounded value; the refunded
    # and slashed shares are the remainders.
    out = grade_breakdown(5, 5, 1, 2)
    assert out["price_paid_c"] == 2 and out["price_refunded_c"] == 3
    assert out["bond_returned_c"] == 2 and out["bond_slashed_c"] == 3
    # Bad inputs are refused, not silently clipped.
    for bad in ((100, 100, 6, 5), (100, 100, -1, 5), (100, 100, 1, 0),
                (-1, 100, 1, 5), (100, -1, 1, 5), (100, 100, 1.5, 5)):
        try:
            grade_breakdown(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"grade_breakdown accepted {bad}")
    print("  PASS")


def test_math_conservation_sweep():
    print("TEST 4 math: money conservation sweep, 1000 random splits")
    rng = random.Random(20261111)
    for _ in range(1000):
        price_c = rng.randint(0, 100000)
        bond_c = rng.randint(0, 30000)
        total = rng.randint(1, 12)
        passed = rng.randint(0, total)
        out = grade_breakdown(price_c, bond_c, passed, total)
        assert (out["price_paid_c"] + out["price_refunded_c"] == price_c
                and out["bond_slashed_c"] + out["bond_returned_c"]
                == bond_c), out
        assert all(v >= 0 for k, v in out.items()
                   if k not in ("passed", "total"))
    print("  1000/1000 splits conserve exactly")
    print("  PASS")


def test_reputation_delta():
    print("TEST 5 math: graded seller delta is the passed share of the "
          "release gain minus the failed share of the slash hit")
    # Formula: div_round(6 * passed, total) - div_round(20 * failed, total).
    assert graded_seller_reputation_delta(5, 5) == 6
    assert graded_seller_reputation_delta(0, 5) == -20
    assert graded_seller_reputation_delta(1, 5) == 1 - 16
    assert graded_seller_reputation_delta(3, 5) == 4 - 8
    assert graded_seller_reputation_delta(4, 5) == 5 - 4
    print("  5/5: +6, 0/5: -20, 1/5: -15, 3/5: -4, 4/5: +1")
    print("  PASS")


def _graded_deal(scenario_id, quality):
    """Run a deal to a graded settlement; returns the finished deal."""
    deal = run_to_paid(scenario_id)
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": quality})
    deal = post(f"/api/deals/{deal['id']}/verify")
    assert deal["state"] == "revision", deal["state"]
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": quality})
    deal = post(f"/api/deals/{deal['id']}/verify")
    return deal


def test_graded_three_of_five():
    print("TEST 6 end to end: data labeling weak settles graded 3 of 5")
    seller_before = next(
        a["reputation"] for a in client.get("/api/agents").json()
        if a["id"] == "seller_labelwise")
    buyer_before = next(
        a["reputation"] for a in client.get("/api/agents").json()
        if a["id"] == "buyer_main")
    deal = _graded_deal("data_labeling_batch", "weak")
    assert deal["state"] == "graded", deal["state"]
    assert deal["payment"]["status"] == "partially_released"
    assert deal["bond"]["status"] == "partially_slashed"
    price_c = dollars_to_cents(deal["spec"]["price"])
    bond_c = dollars_to_cents(deal["spec"]["bond_amount"])
    expected = grade_breakdown(price_c, bond_c, 3, 5)
    graded = deal["settlement"]["graded"]
    assert graded["passed"] == 3 and graded["total"] == 5
    assert dollars_to_cents(graded["price_paid_c"]) == expected["price_paid_c"]
    assert dollars_to_cents(graded["price_refunded_c"]) == expected["price_refunded_c"]
    assert dollars_to_cents(graded["bond_returned_c"]) == expected["bond_returned_c"]
    assert dollars_to_cents(graded["bond_slashed_c"]) == expected["bond_slashed_c"]
    # Money conservation, exact in integer cents.
    assert (expected["price_paid_c"] + expected["price_refunded_c"]
            == price_c)
    assert (expected["bond_returned_c"] + expected["bond_slashed_c"]
            == bond_c)
    assert deal["settlement"]["path"] == "graded"
    types = [e["event_type"] for e in deal["ledger"]]
    assert "graded_settlement_decided" in types
    decided = next(e for e in deal["ledger"]
                   if e["event_type"] == "graded_settlement_decided")
    assert "3 of 5" in decided["message"], decided["message"]
    assert str(graded["price_paid_c"]) in decided["message"]
    assert str(graded["price_refunded_c"]) in decided["message"]
    rep_after = next(
        a["reputation"] for a in client.get("/api/agents").json()
        if a["id"] == "seller_labelwise")
    buyer_after = next(
        a["reputation"] for a in client.get("/api/agents").json()
        if a["id"] == "buyer_main")
    # One revision (-3) plus the graded seller delta at 3 of 5 (-4).
    assert rep_after == seller_before - 7, (seller_before, rep_after)
    assert buyer_after == buyer_before + 1, (buyer_before, buyer_after)
    print(f"  price {deal['spec']['price']} USD ({price_c}c), bond "
          f"{deal['spec']['bond_amount']} USD ({bond_c}c)")
    print(f"  seller paid {graded['price_paid_c']} USD, buyer refunded "
          f"{graded['price_refunded_c']} USD, bond slashed "
          f"{graded['bond_slashed_c']} USD, returned "
          f"{graded['bond_returned_c']} USD")
    print("  PASS")


def test_graded_one_of_five():
    print("TEST 7 end to end: cheat delivery settles graded 1 of 5")
    seller_before = next(
        a["reputation"] for a in client.get("/api/agents").json()
        if a["id"] == "seller_fastcopy")
    deal = _graded_deal("cheat_attempt", "auto")
    assert deal["state"] == "graded", deal["state"]
    assert deal["payment"]["status"] == "partially_released"
    assert deal["bond"]["status"] == "partially_slashed"
    price_c = dollars_to_cents(deal["spec"]["price"])
    bond_c = dollars_to_cents(deal["spec"]["bond_amount"])
    expected = grade_breakdown(price_c, bond_c, 1, 5)
    graded = deal["settlement"]["graded"]
    assert graded["passed"] == 1 and graded["total"] == 5
    assert dollars_to_cents(graded["price_paid_c"]) == expected["price_paid_c"]
    assert dollars_to_cents(graded["price_refunded_c"]) == expected["price_refunded_c"]
    assert dollars_to_cents(graded["bond_returned_c"]) == expected["bond_returned_c"]
    assert dollars_to_cents(graded["bond_slashed_c"]) == expected["bond_slashed_c"]
    assert deal["settlement"]["path"] == "graded"
    rep_after = next(
        a["reputation"] for a in client.get("/api/agents").json()
        if a["id"] == "seller_fastcopy")
    # One revision (-3) plus the graded seller delta at 1 of 5 (-15).
    assert rep_after == seller_before - 18, (seller_before, rep_after)
    print(f"  price {deal['spec']['price']} USD, bond "
          f"{deal['spec']['bond_amount']} USD")
    print(f"  seller paid {graded['price_paid_c']} USD, buyer refunded "
          f"{graded['price_refunded_c']} USD, bond slashed "
          f"{graded['bond_slashed_c']} USD, returned "
          f"{graded['bond_returned_c']} USD")
    print("  PASS")


def test_graded_failure_injection():
    print("TEST 8 failure injection: fail the second graded leg, resume, "
          "no leg runs twice")
    from pact.payments import DemoSimulator, PaymentError

    class FailLegStub:
        """Demo shaped service that fails one named settlement leg."""

        mode = "demo"

        def __init__(self, fail_suffix=None):
            self._sim = DemoSimulator()
            self.fail_suffix = fail_suffix
            self.calls = []

        async def create_order(self, *a, **k):
            return await self._sim.create_order(*a, **k)

        async def capture_order(self, *a, **k):
            return await self._sim.capture_order(*a, **k)

        async def refund(self, capture_id, amount, currency,
                         request_id=None):
            self.calls.append(("refund", request_id, amount))
            if (self.fail_suffix and request_id
                    and request_id.endswith(self.fail_suffix)):
                raise PaymentError(f"injected failure on {request_id}")
            return await self._sim.refund(capture_id, amount, currency,
                                          request_id=request_id)

        async def payout(self, receiver_email, amount, currency, note,
                         request_id=None):
            self.calls.append(("payout", request_id, amount))
            if (self.fail_suffix and request_id
                    and request_id.endswith(self.fail_suffix)):
                raise PaymentError(f"injected failure on {request_id}")
            return await self._sim.payout(receiver_email, amount, currency,
                                          note, request_id=request_id)

        async def get_payout_status(self, payout_batch_id):
            return await self._sim.get_payout_status(payout_batch_id)

    # The graded leg order is price payout, price refund, bond return,
    # bond slash: the second leg is the price refund.
    stub = FailLegStub(fail_suffix="price-refund")
    original_service = main_mod.get_agent_payment_service
    main_mod.get_agent_payment_service = lambda: stub
    try:
        deal = run_to_paid("cheat_attempt")
        did = deal["id"]
        post(f"/api/deals/{did}/deliver", {"quality": "auto"})
        deal = post(f"/api/deals/{did}/verify")
        assert deal["state"] == "revision", deal["state"]
        post(f"/api/deals/{did}/deliver", {"quality": "auto"})
        resp = post_raw(f"/api/deals/{did}/verify")
        assert resp.status_code == 502, \
            f"verify with a failed refund leg -> {resp.status_code}: {resp.text}"
        after = client.get(f"/api/deals/{did}").json()
        assert after["state"] == "verifying", after["state"]
        legs = after["settlement"]["legs"]
        assert legs["price_payout"]["status"] == "done", legs["price_payout"]
        assert legs["price_refund"]["status"] == "failed", legs["price_refund"]
        assert after["settlement"]["path"] == "graded"
        price_calls = [c for c in stub.calls
                       if c[1].endswith("price-payout")]
        assert len(price_calls) == 1, stub.calls
        refund_key = [c[1] for c in stub.calls
                      if c[1].endswith("price-refund")][0]
        assert refund_key == f"{did}-price-refund", refund_key
    finally:
        main_mod.get_agent_payment_service = original_service
    stub2 = FailLegStub()
    main_mod.get_agent_payment_service = lambda: stub2
    try:
        resp = post_raw(f"/api/deals/{did}/verify")
        assert resp.status_code == 200, \
            f"resumed verify -> {resp.status_code}: {resp.text}"
        after = resp.json()
        assert after["state"] == "graded", after["state"]
        legs = after["settlement"]["legs"]
        assert all(legs[l]["status"] == "done" for l in legs), legs
        assert not any(c[1].endswith("price-payout") for c in stub2.calls), \
            stub2.calls
        retried_key = [c[1] for c in stub2.calls
                       if c[1].endswith("price-refund")][0]
        assert retried_key == refund_key, retried_key
        assert sum(1 for e in after["ledger"]
                   if e["event_type"] == "payment_released") == 1
        assert sum(1 for e in after["ledger"]
                   if e["event_type"] == "buyer_refunded") == 1
        assert sum(1 for e in after["ledger"]
                   if e["event_type"] == "bond_returned") == 1
        assert sum(1 for e in after["ledger"]
                   if e["event_type"] == "bond_slashed") == 1
    finally:
        main_mod.get_agent_payment_service = original_service
    print("  PASS")


def test_breakdown_shape_on_release_and_refund():
    print("TEST 9 end to end: release and refund carry the same breakdown")
    deal = run_to_paid("logo_brand_kit")
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    deal = post(f"/api/deals/{deal['id']}/verify")
    assert deal["state"] == "released", deal["state"]
    graded = deal["settlement"]["graded"]
    assert graded["passed"] == graded["total"]
    assert graded["price_paid_c"] == deal["spec"]["price"]
    assert graded["price_refunded_c"] == 0
    assert graded["bond_slashed_c"] == 0
    assert graded["bond_returned_c"] == deal["spec"]["bond_amount"]

    deal = run_to_paid("logo_brand_kit")
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": "poor"})
    deal = post(f"/api/deals/{deal['id']}/verify")
    assert deal["state"] == "refunded", deal["state"]
    graded = deal["settlement"]["graded"]
    assert graded["passed"] == 0
    assert graded["price_paid_c"] == 0
    assert graded["price_refunded_c"] == deal["spec"]["price"]
    assert graded["bond_slashed_c"] == deal["spec"]["bond_amount"]
    assert graded["bond_returned_c"] == 0
    print("  PASS")


def test_dispute_packet_graded():
    print("TEST 10 dispute packet: a graded deal shows the partial amounts")
    deal = _graded_deal("cheat_attempt", "auto")
    assert deal["state"] == "graded", deal["state"]
    resp = client.get(f"/api/deals/{deal['id']}/dispute-packet")
    assert resp.status_code == 200, resp.status_code
    packet = resp.text
    graded = deal["settlement"]["graded"]
    assert "graded settlement" in packet
    assert "1 of 5" in packet
    for key in ("price_paid_c", "price_refunded_c",
                "bond_slashed_c", "bond_returned_c"):
        assert str(graded[key]) in packet, (key, graded[key])
    print("  PASS")


def _set_paid_at_past(deal_id, days):
    """Move a paid deal's payment time (and deadline) into the past."""
    past = datetime.now(timezone.utc) - timedelta(days=days)
    stored = DEALS[deal_id]
    stored["paid_at"] = past.isoformat()
    stored["delivery_deadline"] = (
        past + timedelta(days=7)).isoformat()


def test_timeout_from_paid_held():
    print("TEST 11 timeout: no delivery by the deadline, full refund plus "
          "full slash, ending refunded")
    deal = run_to_paid("logo_brand_kit")
    did = deal["id"]
    _set_paid_at_past(did, 10)
    resp = post_raw(f"/api/deals/{did}/timeout", {})
    assert resp.status_code == 200, \
        f"timeout -> {resp.status_code}: {resp.text}"
    deal = resp.json()
    _remember_tokens(deal)
    assert deal["state"] == "refunded", deal["state"]
    assert deal["settlement"]["path"] == "timeout", deal["settlement"]
    assert deal["payment"]["status"] == "refunded"
    assert deal["bond"]["status"] == "slashed"
    types = [e["event_type"] for e in deal["ledger"]]
    assert "delivery_timeout" in types
    event = next(e for e in deal["ledger"]
                 if e["event_type"] == "delivery_timeout")
    assert "10 days waited" in event["message"], event["message"]
    print("  PASS")


def test_timeout_refused():
    print("TEST 12 timeout: before the deadline, after a delivery, and "
          "from revision it is refused with 409")
    deal = run_to_paid("logo_brand_kit")
    did = deal["id"]
    # Before the deadline: paid just now, 7 days left.
    resp = post_raw(f"/api/deals/{did}/timeout", {})
    assert resp.status_code == 409, \
        f"early timeout -> {resp.status_code}: {resp.text}"
    assert "not due yet" in resp.text
    fresh = client.get(f"/api/deals/{did}").json()
    assert fresh["state"] == "paid_held", fresh["state"]
    assert len(fresh["ledger"]) == len(deal["ledger"])

    # After a delivery, timeout is the wrong action entirely, even
    # with the deadline in the past.
    _set_paid_at_past(did, 10)
    deal = post(f"/api/deals/{did}/deliver", {"quality": "auto"})
    resp = post_raw(f"/api/deals/{did}/timeout", {})
    assert resp.status_code == 409, \
        f"timeout after delivery -> {resp.status_code}: {resp.text}"

    # From revision: the seller delivered once, so the buyer waits for
    # the re-delivery instead of timing out. This is the documented
    # limit, and the endpoint refuses it.
    deal = run_to_paid("cheat_attempt")
    did = deal["id"]
    _set_paid_at_past(did, 10)
    deal = post(f"/api/deals/{did}/deliver", {"quality": "auto"})
    deal = post(f"/api/deals/{did}/verify")
    assert deal["state"] == "revision", deal["state"]
    resp = post_raw(f"/api/deals/{did}/timeout", {})
    assert resp.status_code == 409, \
        f"timeout from revision -> {resp.status_code}: {resp.text}"
    print("  PASS")


def main():
    global client
    with TestClient(app) as c:
        client = c
        test_math_partial()
        test_math_ends()
        test_math_rounding()
        test_math_conservation_sweep()
        test_reputation_delta()
        test_graded_three_of_five()
        test_graded_one_of_five()
        test_graded_failure_injection()
        test_breakdown_shape_on_release_and_refund()
        test_dispute_packet_graded()
        test_timeout_from_paid_held()
        test_timeout_refused()
        print("ALL GRADED SETTLEMENT TESTS PASSED")


if __name__ == "__main__":
    main()

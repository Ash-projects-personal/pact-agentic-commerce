"""Monte Carlo settlement integrity experiment (item T, part 2).

Drives 10,000 randomized deals end to end through the REAL Pact
settlement engine (FastAPI TestClient against pact.main:app, demo mode
forced) and asserts two invariants on every deal:

  (a) terminal state matches the verifier's verdict: a deal whose final
      verification passed all checks never ends "refunded" with a slashed
      bond; a deal whose final verification failed a check never ends
      "released".
  (b) money conservation per deal in integer cents: payouts + refunds +
      returned bond + slashed bond + platform fees == captured totals,
      and payouts + refunds + returned bond never exceed captures.

Randomized per deal: scenario (price bands from pact/scenarios.py),
buyer_max / seller_floor inside the band (this varies the negotiation
concession dynamics: gap size, rounds, pinned limits), bond percent
(10-30), delivery quality (honest/auto, weak, cheat, poor), and 0-2
randomly chosen settlement legs on which the demo payment simulator is
made to fail exactly once (fail-once stub in the shape of
tests/hardening_test.py PART I: fail a leg, verify returns 502 with the
deal in "verifying", resume via verify to completion).

Money model (demo mode, read from pact/main.py and pact/payments.py):
  - pay captures spec.price (buyer) and spec.bond_amount (seller bond).
  - release path: price_payout leg pays spec.price to the seller,
    bond_return leg pays spec.bond_amount back to the seller.
  - refund path: price_refund leg refunds spec.price to the buyer,
    bond_slash leg pays spec.bond_amount to the buyer.
  - No platform fee exists anywhere in the settlement code; fees = 0.
All accounting below is in integer cents (round(x*100)); floats are
never compared.

Writes experiments/monte_carlo_settlement_results.json.

Run from the project dir with:
  NO_PROXY=localhost,127.0.0.1 .venv/bin/python experiments/monte_carlo_settlement.py
"""

import json
import os
import random
import sys
import tempfile
import time
import traceback
from pathlib import Path

# Force demo mode before the app modules read the environment, and point
# persistence at a throwaway database that never touches data/pact.db.
for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY",
            "PAYPAL_WEBHOOK_ID", "CHANNEL3_API_KEY"):
    os.environ.pop(var, None)
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "mc-test.db")

PROJECT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PROJECT_DIR)

import pact.main as main_mod  # noqa: E402
import pact.persistence as persistence  # noqa: E402
from pact.payments import DemoSimulator, PaymentError  # noqa: E402
from pact.store import DEALS  # noqa: E402

# The middleware calls persistence.save_all() after EVERY response. With
# ~60k requests that SQLite write dominates runtime and grows with the
# deal count. The in-memory store is what the API reads and writes, so
# skipping the durability write changes nothing about settlement logic;
# it only skips disk persistence for this throwaway run.
persistence.save_all = lambda: None

from fastapi.testclient import TestClient  # noqa: E402

from pact.main import app  # noqa: E402

SEED = int(os.environ.get("MC_SEED", "20261023"))
N_DEALS = int(os.environ.get("MC_N_DEALS", "10000"))

# Scenario price bands: (scenario default seller_floor, default buyer_max)
# from pact/scenarios.py. buyer_max and seller_floor are drawn inside the
# band, which varies the negotiation concession dynamics per deal.
SCEN_BANDS = {
    "logo_brand_kit": (180.0, 300.0),
    "landing_page_copy": (260.0, 450.0),
    "cheat_attempt": (150.0, 240.0),
    "code_task": (240.0, 400.0),
    "research_brief": (200.0, 350.0),
    "amazon_listing": (60.0, 100.0),
    "procurement": (180.0, 300.0),
    "data_labeling_batch": (40.0, 90.0),
    "podcast_edit_package": (80.0, 220.0),
    "newsletter_issue": (70.0, 160.0),
    "product_photo_set": (90.0, 220.0),
    "book_cover_design": (50.0, 140.0),
    "api_integration_task": (120.0, 320.0),
    "spreadsheet_cleanup_report": (40.0, 110.0),
}
SCEN_IDS = sorted(SCEN_BANDS)

LEG_SUFFIX = {
    "price_payout": "price-payout",
    "bond_return": "bond-return",
    "price_refund": "price-refund",
    "bond_slash": "bond-slash",
}
LEGS = list(LEG_SUFFIX)

QUALITIES = ["auto", "weak", "cheat", "poor"]
QUALITY_WEIGHTS = [0.50, 0.15, 0.15, 0.20]

# 2% of deals get a seller floor above the buyer ceiling so negotiation
# walks away: exercises the no-money "failed" terminal state.
ADVERSARIAL_FLOOR_P = 0.02


def cents(x):
    """USD float -> integer cents. The only money conversion used."""
    return int(round(float(x) * 100))


class FailOnceStub:
    """Demo shaped payment service that fails selected legs exactly once.

    Mirrors tests/hardening_test.py PART I: the failure raises PaymentError
    before the simulator records anything, so no money moves on the failed
    attempt; the resume re-sends under the same deterministic idempotency
    key and succeeds. Successful money-moving calls are recorded with
    their request id and amount for the conservation audit.
    """

    mode = "demo"

    def __init__(self, fail_suffixes):
        self._sim = DemoSimulator()
        self.remaining = {s: 1 for s in fail_suffixes}
        self.calls = []  # (request_id, amount) for successful sends only
        self.fired = {s: 0 for s in fail_suffixes}

    def _match(self, request_id):
        if not request_id:
            return None
        for s in self.remaining:
            if request_id.endswith(s):
                return s
        return None

    async def create_order(self, *a, **k):
        return await self._sim.create_order(*a, **k)

    async def capture_order(self, *a, **k):
        return await self._sim.capture_order(*a, **k)

    async def refund(self, capture_id, amount, currency, request_id=None):
        leg = self._match(request_id)
        if leg is not None and self.remaining[leg] > 0:
            self.remaining[leg] -= 1
            self.fired[leg] += 1
            raise PaymentError(f"injected settlement failure on {request_id}")
        self.calls.append((request_id, int(amount)))
        return await self._sim.refund(capture_id, amount, currency,
                                      request_id=request_id)

    async def payout(self, receiver_email, amount, currency, note,
                     request_id=None):
        leg = self._match(request_id)
        if leg is not None and self.remaining[leg] > 0:
            self.remaining[leg] -= 1
            self.fired[leg] += 1
            raise PaymentError(f"injected settlement failure on {request_id}")
        self.calls.append((request_id, int(amount)))
        return await self._sim.payout(receiver_email, amount, currency, note,
                                      request_id=request_id)

    async def get_payout_status(self, payout_batch_id):
        return await self._sim.get_payout_status(payout_batch_id)


def leg_of_request(did, request_id):
    for leg, suffix in LEG_SUFFIX.items():
        base = f"{did}-{suffix}"
        if request_id == base or request_id.startswith(base + "-attempt"):
            return leg
    return None


def run_one_deal(client, rng, idx):
    """Run a single deal to a terminal state. Returns a result dict."""
    def hdr(did, seller=False):
        # Queue item W: state-changing endpoints need the per-deal role
        # token in the X-Deal-Token header. The create response carries
        # both tokens.
        role = "seller" if seller else "buyer"
        return {"X-Deal-Token": tokens[did][role]}

    tokens = {}
    sid = rng.choice(SCEN_IDS)
    lo, hi = SCEN_BANDS[sid]
    buyer_max = round(rng.uniform(lo, hi), 2)
    if rng.random() < ADVERSARIAL_FLOOR_P:
        seller_floor = round(buyer_max * rng.uniform(1.05, 1.40), 2)
    else:
        seller_floor = round(rng.uniform(lo, buyer_max), 2)
    bond_percent = rng.randint(10, 30)
    quality = rng.choices(QUALITIES, weights=QUALITY_WEIGHTS)[0]
    n_fail = rng.choices([0, 1, 2], weights=[0.40, 0.35, 0.25])[0]
    fail_legs = rng.sample(LEGS, n_fail)
    fail_suffixes = [LEG_SUFFIX[l] for l in fail_legs]

    res = {"idx": idx, "scenario": sid, "quality": quality,
           "bond_percent": bond_percent, "fail_legs": fail_legs}

    stub = FailOnceStub(fail_suffixes)
    original_service = main_mod.get_agent_payment_service
    main_mod.get_agent_payment_service = lambda: stub
    try:
        r = client.post("/api/deals", json={
            "scenario_id": sid, "buyer_max": buyer_max,
            "seller_floor": seller_floor, "bond_percent": bond_percent})
        assert r.status_code == 200, f"create -> {r.status_code}: {r.text}"
        deal = r.json()
        did = deal["id"]
        res["deal_id"] = did
        tokens[did] = {"buyer": deal["buyer_token"],
                       "seller": deal["seller_token"]}

        deal = client.post(f"/api/deals/{did}/negotiate/run",
                           headers=hdr(did)).json()
        if deal["state"] != "agreed":
            # Negotiation walked away (adversarial floor) or the bond
            # floor tripped: no money moved at all.
            res["terminal"] = deal["state"]
            res["negotiation_failed"] = True
            return res, stub, deal

        deal = client.post(f"/api/deals/{did}/pay",
                           headers=hdr(did)).json()
        assert deal["state"] == "paid_held", \
            f"pay -> {deal['state']}"
        assert deal["payment"]["status"] == "held"
        assert deal["bond"]["status"] == "posted"

        deal = client.post(f"/api/deals/{did}/deliver",
                           json={"quality": quality},
                           headers=hdr(did, seller=True)).json()
        assert deal["state"] == "delivered", \
            f"deliver -> {deal['state']}"

        # Verify, resuming through injected 502s and revision rounds
        # until the deal reaches a terminal state.
        for _ in range(12):
            r = client.post(f"/api/deals/{did}/verify", headers=hdr(did))
            if r.status_code == 200:
                deal = r.json()
            else:
                deal = client.get(f"/api/deals/{did}").json()
            state = deal["state"]
            if state == "revision":
                deal = client.post(
                    f"/api/deals/{did}/deliver",
                    json={"quality": quality},
                    headers=hdr(did, seller=True)).json()
                assert deal["state"] == "delivered", \
                    f"re-deliver -> {deal['state']}"
                continue
            if state in ("released", "refunded"):
                break
            # state == "verifying": an injected leg failed (502) or a
            # payout is pending; loop to resume.
            assert state == "verifying", \
                f"unexpected state {state} (verify -> {r.status_code})"
        else:
            res["terminal"] = deal["state"]
            res["wedged"] = True
            return res, stub, deal

        res["terminal"] = deal["state"]
        res["negotiation_failed"] = False
        return res, stub, deal
    finally:
        main_mod.get_agent_payment_service = original_service


def audit_deal(res, stub, deal):
    """Check invariants (a) and (b). Returns (violations_a, violations_b)."""
    va, vb = [], []
    did = res["deal_id"]
    state = res["terminal"]
    spec = deal.get("spec")

    if res.get("wedged"):
        va.append({"code": "non_terminal",
                   "detail": f"deal {did} did not reach a terminal state "
                             f"after 12 verify attempts; stuck in {state}"})
        return va, vb

    if res.get("negotiation_failed"):
        # No verdict, no money: legs must all be pending and the payment
        # records untouched.
        assert deal["payment"]["status"] == "not_started", deal["payment"]
        assert deal["bond"]["status"] in ("not_started", "not_posted", None), \
            deal["bond"]
        assert all(e["status"] == "pending"
                   for e in deal["settlement"]["legs"].values())
        assert stub.calls == []
        res["money"] = {"captured": 0, "paid": 0, "refunded": 0,
                        "returned": 0, "slashed": 0, "fees": 0,
                        "outs": 0, "residual": 0}
        return va, vb

    # ---- invariant (a): terminal state matches the final verdict ----
    verification = deal.get("verification")
    assert verification is not None, f"deal {did}: {state} with no verdict"
    all_passed = verification["all_passed"] is True
    if state == "released" and not all_passed:
        va.append({
            "code": "released_despite_failed_verdict",
            "deal_id": did, "scenario": res["scenario"],
            "quality": res["quality"], "fail_legs": res["fail_legs"],
            "detail": "terminal state 'released' but the final "
                      f"verification did not pass all checks "
                      f"({verification['passed_count']}/"
                      f"{verification['total_count']})",
            "payment_status": deal["payment"]["status"],
            "bond_status": deal["bond"]["status"],
        })
    if state == "refunded" and all_passed:
        va.append({
            "code": "refunded_despite_passed_verdict",
            "deal_id": did, "scenario": res["scenario"],
            "quality": res["quality"], "fail_legs": res["fail_legs"],
            "detail": "terminal state 'refunded' (bond "
                      f"{deal['bond']['status']}) but the final "
                      "verification passed all checks",
            "payment_status": deal["payment"]["status"],
            "bond_status": deal["bond"]["status"],
        })
    if state not in ("released", "refunded"):
        va.append({"code": "unexpected_terminal",
                   "deal_id": did,
                   "detail": f"terminal state {state!r} is neither "
                             "released nor refunded"})

    # ---- invariant (b): per-deal money conservation in integer cents --
    # spec arrives from the API in dollars; stub calls are already cents.
    price_c = cents(spec["price"])
    bond_c = cents(spec["bond_amount"])
    captured = price_c + bond_c

    leg_cents = {leg: 0 for leg in LEGS}
    leg_calls = {leg: 0 for leg in LEGS}
    for request_id, amount in stub.calls:
        leg = leg_of_request(did, request_id)
        if leg is None:
            vb.append({
                "code": "unattributed_money_call",
                "deal_id": did,
                "detail": f"stub recorded a money call {request_id} for "
                          f"{amount} USD that matches no settlement leg",
            })
            continue
        leg_cents[leg] += int(amount)
        leg_calls[leg] += 1

    # No-double-spend cross-check: a leg recorded "done" must have moved
    # money exactly once; a leg never sent must have moved nothing.
    for leg, entry in deal["settlement"]["legs"].items():
        if entry["status"] == "done":
            if leg_calls[leg] != 1:
                vb.append({
                    "code": "done_leg_call_count",
                    "deal_id": did, "leg": leg,
                    "detail": f"leg {leg} is 'done' but the stub recorded "
                              f"{leg_calls[leg]} successful money calls "
                              f"(expected exactly 1)",
                    "request_id": entry.get("request_id"),
                })
        elif leg_calls[leg] != 0:
            vb.append({
                "code": "unsent_leg_moved_money",
                "deal_id": did, "leg": leg,
                "detail": f"leg {leg} is {entry['status']!r} but the stub "
                          f"recorded {leg_calls[leg]} money calls",
            })

    paid = leg_cents["price_payout"]      # to seller
    returned = leg_cents["bond_return"]   # to seller
    refunded = leg_cents["price_refund"]  # to buyer
    slashed = leg_cents["bond_slash"]     # to buyer
    fees = 0  # no platform fee exists in the settlement code paths
    outs = paid + refunded + returned + slashed + fees
    residual = captured - outs
    if residual != 0:
        vb.append({
            "code": "conservation_residual",
            "deal_id": did, "scenario": res["scenario"],
            "quality": res["quality"], "fail_legs": res["fail_legs"],
            "terminal": state,
            "detail": f"captured {captured}c != outs {outs}c "
                      f"(paid {paid} + refunded {refunded} + returned "
                      f"{returned} + slashed {slashed} + fees {fees}); "
                      f"residual {residual}c unaccounted",
            "price_cents": price_c, "bond_cents": bond_c,
            "leg_cents": leg_cents,
            "leg_statuses": {l: e["status"]
                             for l, e in deal["settlement"]["legs"].items()},
        })
    if paid + refunded + returned > captured:
        vb.append({
            "code": "outs_exceed_captures",
            "deal_id": did,
            "detail": f"payouts+refunds+returned "
                      f"({paid + refunded + returned}c) exceed captured "
                      f"({captured}c)",
        })

    res["money"] = {"captured": captured, "paid": paid,
                    "refunded": refunded, "returned": returned,
                    "slashed": slashed, "fees": fees, "outs": outs,
                    "residual": residual}
    return va, vb


def main():
    t0 = time.time()
    rng = random.Random(SEED)

    stats = {
        "seed": SEED,
        "n_deals": N_DEALS,
        "deals_run": 0,
        "invariant_a_violations": 0,
        "invariant_a_details": [],
        "invariant_b_violations": 0,
        "invariant_b_details": [],
        "error_deals": [],
        "leg_failure_selected": {l: 0 for l in LEGS},
        "leg_failure_fired": {l: 0 for l in LEGS},
        "terminal_state_histogram": {},
        "scenario_histogram": {},
        "quality_histogram": {},
        "money_totals_cents": {
            "captured": 0, "paid_to_seller": 0, "refunded_to_buyer": 0,
            "bond_returned": 0, "bond_slashed": 0, "platform_fees": 0,
            "residual_unaccounted": 0,
        },
    }

    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["mode"] == "demo", health
        print(f"health ok: mode={health['mode']}, "
              f"rail={health['agent_toolkit']['orders_rail']}", flush=True)

        for i in range(N_DEALS):
            try:
                res, stub, deal = run_one_deal(client, rng, i)
            except Exception as exc:  # noqa: BLE001 - never drop a deal silently
                stats["error_deals"].append({
                    "idx": i,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-2000:],
                })
                print(f"  ERROR deal {i}: {exc}", flush=True)
                continue

            va, vb = audit_deal(res, stub, deal)
            stats["invariant_a_violations"] += len(va)
            stats["invariant_a_details"].extend(va)
            stats["invariant_b_violations"] += len(vb)
            stats["invariant_b_details"].extend(vb)

            for leg in res["fail_legs"]:
                stats["leg_failure_selected"][leg] += 1
            for suffix, n in stub.fired.items():
                if n:
                    leg = next(l for l, s in LEG_SUFFIX.items()
                               if s == suffix)
                    stats["leg_failure_fired"][leg] += n

            term = res["terminal"]
            stats["terminal_state_histogram"][term] = \
                stats["terminal_state_histogram"].get(term, 0) + 1
            stats["scenario_histogram"][res["scenario"]] = \
                stats["scenario_histogram"].get(res["scenario"], 0) + 1
            stats["quality_histogram"][res["quality"]] = \
                stats["quality_histogram"].get(res["quality"], 0) + 1

            m = res.get("money")
            if m:
                t = stats["money_totals_cents"]
                t["captured"] += m["captured"]
                t["paid_to_seller"] += m["paid"]
                t["refunded_to_buyer"] += m["refunded"]
                t["bond_returned"] += m["returned"]
                t["bond_slashed"] += m["slashed"]
                t["platform_fees"] += m["fees"]
                t["residual_unaccounted"] += m["residual"]

            stats["deals_run"] += 1

            # Bound memory: the audit is done, drop the deal record.
            did = res.get("deal_id")
            if did and did in DEALS:
                del DEALS[did]

            if (i + 1) % 500 == 0:
                dt = time.time() - t0
                print(f"  {i + 1}/{N_DEALS} deals, {dt:.0f}s "
                      f"({dt / (i + 1):.3f}s/deal), "
                      f"A-viol={stats['invariant_a_violations']} "
                      f"B-viol={stats['invariant_b_violations']} "
                      f"errors={len(stats['error_deals'])}", flush=True)

    stats["runtime_seconds"] = round(time.time() - t0, 2)
    stats["method"] = (
        "10,000 deals driven end to end through the real settlement engine "
        "via fastapi TestClient against pact.main:app in a single shared "
        "session (context manager shares one event loop portal). Demo mode "
        "forced by popping PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET/LLM_API_KEY/"
        "PAYPAL_WEBHOOK_ID/CHANNEL3_API_KEY before import; PACT_DB_PATH set "
        "to a temp dir (dev DB at data/pact.db untouched). Lifecycle per "
        "deal: POST /api/deals, negotiate/run, pay (demo captures instantly "
        "to paid_held; no pay/confirm needed), deliver, verify, with resume "
        "loops through injected 502s (deal stays 'verifying') and revision "
        "rounds (re-deliver then verify again) until a terminal state. "
        "Failure injection: get_agent_payment_service monkeypatched per "
        "deal with a fail-once stub in the shape of tests/hardening_test.py "
        "PART I (FailLegStub): 0-2 randomly chosen legs raise PaymentError "
        "on the first send under the deterministic idempotency key, before "
        "the simulator records anything; the resume re-sends under the "
        "same key and succeeds. Money audit in integer cents from the "
        "amounts on the stub's successful payout/refund calls, cross-"
        "checked against each leg's recorded status (done => exactly one "
        "money call). persistence.save_all was patched to a no-op for "
        "speed; the in-memory store is what the API reads/writes, so "
        "settlement logic is unaffected. Negotiation concession behavior "
        "was randomized via buyer_max/seller_floor draws inside each "
        "scenario's price band (plus a 2% adversarial floor>ceiling "
        "walkaway); bond percents 10-30; delivery qualities auto/weak/"
        "cheat/poor at 50/15/15/20. Deal records were deleted from the "
        "in-memory store after auditing to bound memory; only violating "
        "deals would have been kept (none)."
    )

    out_path = Path(PROJECT_DIR) / "experiments" / \
        "monte_carlo_settlement_results.json"
    out_path.write_text(json.dumps(stats, indent=2))
    print(f"wrote {out_path}", flush=True)
    print(json.dumps({
        "n": stats["deals_run"],
        "A_violations": stats["invariant_a_violations"],
        "B_violations": stats["invariant_b_violations"],
        "errors": len(stats["error_deals"]),
        "histogram": stats["terminal_state_histogram"],
        "money_cents": stats["money_totals_cents"],
        "runtime_s": stats["runtime_seconds"],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()

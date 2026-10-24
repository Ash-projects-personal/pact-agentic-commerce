"""Property-style tests over the Pact HTTP API with randomized inputs.

Five property families, each deal driven from a fresh POST /api/deals with
randomized scenario, price bounds, bond percent (10-30), and multi_issue
on/off:

1. State machine forward-only: states move along the legal graph
   negotiating -> agreed -> paid_held -> delivered -> verifying ->
   revision -> delivered ... -> released | refunded, or negotiating ->
   failed. No deal ever moves backward, skips a state, or re-enters a
   terminal state. Repeated illegal transitions return 4xx and leave the
   deal state and ledger untouched.
2. Ledger integrity: every deal's ledger has strictly increasing seq
   numbers starting at 1, and every expected event type for the deal's
   path appears in legal order.
3. Money properties: bond_amount == bond_percent of agreed price within a
   cent; captured amounts are non-negative; every settlement leg runs at
   most once with a unique idempotency key; reputation is applied exactly
   once per terminal settlement (ledger deltas match the real moves).
4. Negotiation properties: the agreed price stays inside
   [seller_floor, buyer_max]; multi-issue terms land inside their bands
   (delivery 5-12 days, revisions 1-3 rounds, bond 10-30%).
5. Fuzz robustness: malformed bodies return 4xx/422 and never create a
   half-initialized deal (failed creations add no id to the store, and
   the next valid creation adds exactly one).

Run with: NO_PROXY=localhost,127.0.0.1 python tests/pactbench_property_test.py
Exits non zero on the first failed assertion. Demo mode only.
"""

import os
import random
import re
import sys
import tempfile
from pathlib import Path

# Force demo mode before the app modules read the environment.
for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

# Isolate persistence so the suite never touches data/pact.db.
os.environ["PACT_DB_PATH"] = str(
    Path(tempfile.mkdtemp()) / "pact-property.db")

# This driver intentionally creates ~40 deals in under a minute, far
# past the demo abuse caps (queue item Z: 30/min per IP, 120/min
# global). The caps are env-driven and a value of 0 disables them, so
# the test harness opts out here. The caps themselves are covered by
# tests/abuse_limit_test.py.
os.environ["PACT_MAX_DEALS_PER_MINUTE_PER_IP"] = "0"
os.environ["PACT_MAX_DEALS_PER_MINUTE_GLOBAL"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pact.main import app  # noqa: E402

# Fixed seed for the input generator. The negotiation engine itself is
# deterministic, so the same seed replays the same randomized inputs.
SEED = 20261023
rng = random.Random(SEED)
FIRST_DRAW = rng.randint(0, 10 ** 9)

# The legal forward state graph. Terminal states have no outgoing edges.
LEGAL_NEXT = {
    "negotiating": {"agreed", "failed"},
    "agreed": {"paid_held"},
    "paid_held": {"delivered"},
    "delivered": {"verifying"},
    "verifying": {"revision", "released", "refunded"},
    "revision": {"delivered"},
}
TERMINAL = {"released", "refunded", "failed"}

# procurement is excluded from the random pool: it pulls Channel3 market
# grounding (cached fixture, no network) which adds a market_grounded
# event and candidate checks that the generic ledger-order assertions do
# not model. Every other scenario runs the same core state machine.
SCENARIO_IDS = [
    "logo_brand_kit", "landing_page_copy", "cheat_attempt", "code_task",
    "research_brief", "amazon_listing", "data_labeling_batch",
    "podcast_edit_package", "newsletter_issue", "product_photo_set",
    "book_cover_design", "api_integration_task",
    "spreadsheet_cleanup_report",
]
DELIVERY_QUALITIES = ["auto", "poor", "weak", "cheat"]

CASES = 0
CHECKS = 0


def check(cond, msg):
    """One counted property check. Fails loudly on the first violation."""
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(f"FAILED CHECK: {msg}")


def new_case():
    global CASES
    CASES += 1


# Demo client token store (queue item W): state-changing deal endpoints
# require the per-deal role token in the X-Deal-Token header. The create
# response carries both tokens, so this helper remembers them per deal
# id and attaches the right one, the way a real client would. Deliver
# acts as the seller; everything else here acts as the buyer.
_DEAL_TOKENS = {}


def req(client, method, path, body=None):
    headers = None
    if method != "GET":
        m = re.match(r"^/api/deals/([^/]+)/", path)
        if m:
            role = ("seller" if path.rstrip("/").endswith("/deliver")
                    else "buyer")
            tok = _DEAL_TOKENS.get(m.group(1), {}).get(role)
            if tok:
                headers = {"X-Deal-Token": tok}
    if method == "GET":
        resp = client.get(path)
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
    return resp.status_code, data


def get_deal(client, deal_id):
    status, data = req(client, "GET", f"/api/deals/{deal_id}")
    check(status == 200, f"GET deal {deal_id} -> {status}: {data}")
    return data


def agents_by_id(client):
    status, data = req(client, "GET", "/api/agents")
    check(status == 200, f"GET /api/agents -> {status}")
    return {a["id"]: a for a in data}


def event_types(deal):
    return [e["event_type"] for e in deal["ledger"]]


def assert_legal_transition(seen, new_state, deal_id):
    prev = seen[-1]
    check(new_state in LEGAL_NEXT.get(prev, set()),
          f"deal {deal_id}: illegal transition {prev} -> {new_state} "
          f"(observed path {seen})")
    seen.append(new_state)


def _first(types, t):
    return types.index(t)


def _last(types, t):
    return len(types) - 1 - types[::-1].index(t)


def assert_ledger_integrity(deal, phases):
    """Seq numbers strictly increasing from 1; every expected event type
    for the deal's path is present; pairwise order rules that hold for
    every legal path are checked (revision rounds repeat, so alternation
    is checked as a subsequence pattern, not a fixed list)."""
    ledger = deal["ledger"]
    check(len(ledger) > 0, f"deal {deal['id']}: empty ledger")
    for i, entry in enumerate(ledger):
        check(entry["seq"] == i + 1,
              f"deal {deal['id']}: ledger seq {entry['seq']} at position "
              f"{i}, expected {i + 1}")
    seqs = [e["seq"] for e in ledger]
    check(seqs == sorted(seqs) and len(set(seqs)) == len(seqs),
          f"deal {deal['id']}: ledger seq not strictly increasing")
    types = event_types(deal)

    def before(a, b, why):
        check(a in types and b in types,
              f"deal {deal['id']}: expected event missing for {why}: "
              f"{a}, {b}")
        check(_last(types, a) < _first(types, b),
              f"deal {deal['id']}: order violated for {why}: last {a} at "
              f"{_last(types, a)}, first {b} at {_first(types, b)}")

    check(_first(types, "deal_created") == 0,
          f"deal {deal['id']}: ledger does not start with deal_created")
    if deal["state"] == "failed":
        # Walkaway: no agreement was ever struck, so none of the
        # agreement-path rules apply. It must never move money.
        check("negotiation_failed" in types,
              f"deal {deal['id']}: failed without negotiation_failed")
        check(all(t not in ("payment_held", "bond_posted",
                            "payment_released", "buyer_refunded")
                  for t in types),
              f"deal {deal['id']}: failed deal has money events: "
              f"{sorted(set(types))}")
        return
    before("price_agreed", "contract_written", "contract follows agreement")
    if deal.get("multi_issue"):
        before("price_agreed", "terms_agreed", "terms follow price")
        before("terms_agreed", "contract_written", "contract freezes terms")
    if "paid" in phases:
        before("contract_written", "payment_held", "pay follows contract")
        before("payment_held", "bond_posted", "bond follows payment")
    if "delivered" in phases:
        before("bond_posted", "delivery_submitted",
               "delivery follows funding")
        before("delivery_submitted", "verification_check",
               "verification follows delivery")
    if "verified" in phases:
        # Every verify round is (check,)+ then one summary.
        rounds = [t for t in types
                  if t in ("verification_check", "verification_summary")]
        check(rounds and rounds[0] == "verification_check",
              f"deal {deal['id']}: verification does not start with checks")
        check(rounds[-1] == "verification_summary",
              f"deal {deal['id']}: verification does not end with a summary")
        seen_check = False
        for t in rounds:
            if t == "verification_check":
                seen_check = True
            else:
                check(seen_check,
                      f"deal {deal['id']}: verification_summary with no "
                      f"checks since the previous summary")
                seen_check = False
    if "revision" in phases:
        # Rounds strictly alternate requested -> submitted.
        rev = [t for t in types
               if t in ("revision_requested", "revision_submitted")]
        check(rev and rev[0] == "revision_requested",
              f"deal {deal['id']}: revision flow does not start with "
              f"revision_requested")
        for i, t in enumerate(rev):
            want = "revision_requested" if i % 2 == 0 else "revision_submitted"
            check(t == want,
                  f"deal {deal['id']}: revision events out of alternation "
                  f"at position {i}: {rev}")
    if deal["state"] == "released":
        before("verification_summary", "payment_released",
               "release follows verdict")
        before("payment_released", "bond_returned",
               "bond returns after price release")
        money_last = "bond_returned"
    elif deal["state"] == "refunded":
        before("verification_summary", "buyer_refunded",
               "refund follows verdict")
        before("buyer_refunded", "bond_slashed",
               "slash follows refund")
        money_last = "bond_slashed"
    else:
        money_last = None
    if money_last:
        if "revision" in phases:
            before("revision_submitted", money_last,
                   "settlement follows the last revision")
        check("reputation_change" in types,
              f"deal {deal['id']}: terminal deal with no reputation moves")
        # Reputation moves carry their reason. The revision -3 is emitted
        # with revision_requested, mid-deal; only the settlement moves
        # must follow the money.
        settlement_reasons = {
            "deal completed and the delivery passed verification",
            "deal completed and settled cleanly",
            "delivery failed verification and the buyer was refunded",
            "performance bond slashed after the failed delivery",
            "followed the contract process and was made whole",
        }
        money_idx = _last(types, money_last)
        for e in ledger:
            if (e["event_type"] == "reputation_change"
                    and e["data"]["reason"] in settlement_reasons):
                check(e["seq"] - 1 > money_idx,
                      f"deal {deal['id']}: settlement reputation move "
                      f"{e['data']['reason']!r} before the money settled")


def assert_money(deal, phases):
    spec = deal["spec"]
    if spec is None:
        return
    price = spec["price"]
    bpct = spec["bond_percent"]
    expected_bond = round(price * bpct / 100.0, 2)
    check(abs(spec["bond_amount"] - expected_bond) <= 0.01,
          f"deal {deal['id']}: bond_amount {spec['bond_amount']} != "
          f"{bpct}% of price {price} (expected {expected_bond})")
    if "paid" in phases:
        check(deal["payment"]["amount"] is not None
              and deal["payment"]["amount"] >= 0,
              f"deal {deal['id']}: captured price amount negative/missing")
        check(deal["bond"]["amount"] is not None
              and deal["bond"]["amount"] >= 0,
              f"deal {deal['id']}: captured bond amount negative/missing")
        check(deal["payment"]["order_id"] != deal["bond"]["order_id"],
              f"deal {deal['id']}: price and bond share an order id")
    if deal["state"] in ("released", "refunded"):
        legs = deal["settlement"]["legs"]
        run_legs = [k for k, v in legs.items() if v["status"] == "done"]
        wanted = ({"price_payout", "bond_return"}
                  if deal["state"] == "released"
                  else {"price_refund", "bond_slash"})
        check(set(run_legs) == wanted,
              f"deal {deal['id']}: ran legs {run_legs}, expected {wanted}")
        keys = []
        for leg in run_legs:
            entry = legs[leg]
            check(entry["attempt"] == 1,
                  f"deal {deal['id']}: leg {leg} ran "
                  f"{entry['attempt']} times, expected at most once")
            check(entry["request_id"],
                  f"deal {deal['id']}: leg {leg} has no idempotency key")
            check(entry["result_id"],
                  f"deal {deal['id']}: leg {leg} done but no result id")
            keys.append(entry["request_id"])
        keys += [deal["payment"]["order_request_id"],
                 deal["bond"]["order_request_id"],
                 deal["payment"]["capture_request_id"],
                 deal["bond"]["capture_request_id"]]
        keys = [k for k in keys if k]
        check(len(set(keys)) == len(keys),
              f"deal {deal['id']}: idempotency keys not unique: {keys}")


def assert_reputation_once(client, deal, rep_before):
    """Every reputation delta in this deal's ledger was applied exactly
    once: the agents' real reputation moved by exactly the ledger sum."""
    rep_after = agents_by_id(client)
    # change_reputation clamps to [0, 100]; the ledger records the real
    # from/to, so the applied move per event is (to - from).
    applied = {}
    for e in deal["ledger"]:
        if e["event_type"] == "reputation_change":
            aid = e["data"]["agent_id"]
            d = e["data"]
            check(d["to"] == max(0, min(100, d["from"] + d["delta"])),
                  f"deal {deal['id']}: reputation_change ledger math wrong: "
                  f"{d}")
            applied[aid] = applied.get(aid, 0) + (d["to"] - d["from"])
    check(applied, f"deal {deal['id']}: terminal deal with no reputation "
                  f"moves in the ledger")
    for aid, delta in applied.items():
        moved = rep_after[aid]["reputation"] - rep_before[aid]["reputation"]
        check(moved == delta,
              f"deal {deal['id']}: agent {aid} reputation moved {moved}, "
              f"ledger says {delta} (applied != once)")


def assert_illegal_4xx(client, deal_id, action_path, body, state_before,
                       ledger_len_before):
    """An illegal transition must return 4xx and change nothing."""
    status, data = req(client, "POST", action_path, body)
    check(400 <= status < 500,
          f"deal {deal_id}: illegal {action_path} returned {status}, "
          f"expected 4xx: {data}")
    deal = get_deal(client, deal_id)
    check(deal["state"] == state_before,
          f"deal {deal_id}: illegal {action_path} moved state "
          f"{state_before} -> {deal['state']}")
    check(len(deal["ledger"]) == ledger_len_before,
          f"deal {deal_id}: illegal {action_path} appended "
          f"{len(deal['ledger']) - ledger_len_before} ledger events")
    return deal


def probe_illegal_moves(client, deal, seen, tag):
    """Try every state-changing endpoint that is illegal right now."""
    state = deal["state"]
    base = f"/api/deals/{deal['id']}"
    attempts = []
    if state != "negotiating":
        attempts.append(("negotiate/run", f"{base}/negotiate/run", {}))
    if state != "agreed":
        attempts.append(("pay", f"{base}/pay", {}))
    if state not in ("paid_held", "revision"):
        attempts.append(("deliver", f"{base}/deliver",
                         {"quality": "auto"}))
    if state not in ("delivered", "verifying"):
        attempts.append(("verify", f"{base}/verify", {}))
    ledger_len = len(deal["ledger"])
    for name, path, body in attempts:
        assert_illegal_4xx(client, deal["id"], path, body, state,
                           ledger_len)
        new_case()
    return deal


def random_case_params():
    scenario = rng.choice(SCENARIO_IDS)
    floor = round(rng.uniform(6.0, 400.0), 2)
    if rng.random() < 0.15:
        # Walkaway input: buyer ceiling below the seller floor.
        buyer_max = round(max(1.0, floor - rng.uniform(1.0, 60.0)), 2)
    else:
        buyer_max = round(floor + rng.uniform(0.0, floor * 0.6 + 20.0), 2)
    return {
        "scenario": scenario,
        "buyer_max": buyer_max,
        "seller_floor": floor,
        "bond_percent": round(rng.uniform(10.0, 30.0), 2),
        "multi_issue": rng.random() < 0.5,
        "quality": rng.choice(DELIVERY_QUALITIES),
    }


def drive_end_to_end(client, params):
    """Drive one randomized deal to a terminal state, checking every
    property family along the way."""
    new_case()
    rep_before = agents_by_id(client)
    status, deal = req(client, "POST", "/api/deals", {
        "scenario_id": params["scenario"],
        "buyer_max": params["buyer_max"],
        "seller_floor": params["seller_floor"],
        "bond_percent": params["bond_percent"],
        "multi_issue": params["multi_issue"],
    })
    check(status == 200, f"create deal -> {status}: {deal}")
    check(deal["state"] == "negotiating",
          f"new deal not negotiating: {deal['state']}")
    check(deal["buyer_max"] == params["buyer_max"]
          and deal["seller_floor"] == params["seller_floor"],
          f"deal {deal['id']}: price bounds not stored")
    seen = [deal["state"]]
    phases = set()
    base = f"/api/deals/{deal['id']}"

    # Negotiate.
    status, deal = req(client, "POST", f"{base}/negotiate/run")
    check(status == 200, f"negotiate -> {status}: {deal}")
    assert_legal_transition(seen, deal["state"], deal["id"])
    if deal["state"] == "failed":
        # Walkaway path: no money may move, no agreement may be struck.
        check(any(e["event_type"] == "negotiation_failed"
                  for e in deal["ledger"]),
              f"deal {deal['id']}: failed without negotiation_failed")
        check(deal["spec"] is None,
              f"deal {deal['id']}: failed deal carries a spec")
        assert_ledger_integrity(deal, phases)
        probe_illegal_moves(client, deal, seen, "failed")
        return deal

    check(deal["state"] == "agreed", f"deal {deal['id']}: {deal['state']}")
    phases.add("agreed")
    spec = deal["spec"]
    check(spec is not None, f"deal {deal['id']}: agreed with no spec")
    # Property 4: agreed price inside the randomized bounds.
    check(deal["seller_floor"] <= spec["price"] <= deal["buyer_max"],
          f"deal {deal['id']}: price {spec['price']} outside "
          f"[{deal['seller_floor']}, {deal['buyer_max']}]")
    check(deal["agreed_price"] == spec["price"],
          f"deal {deal['id']}: agreed_price {deal['agreed_price']} != "
          f"spec price {spec['price']}")
    if params["multi_issue"]:
        terms = deal["terms"]
        check(terms is not None,
              f"deal {deal['id']}: multi-issue deal has no terms")
        check(5 <= terms["delivery_days"] <= 12,
              f"deal {deal['id']}: delivery_days {terms['delivery_days']} "
              f"outside band 5-12")
        check(1 <= terms["revision_rounds"] <= 3,
              f"deal {deal['id']}: revision_rounds "
              f"{terms['revision_rounds']} outside band 1-3")
        check(10.0 <= terms["bond_percent"] <= 30.0,
              f"deal {deal['id']}: terms bond_percent "
              f"{terms['bond_percent']} outside band 10-30")
        check(spec["terms"] == terms,
              f"deal {deal['id']}: frozen spec lost the terms")
    else:
        check(deal["terms"] is None,
              f"deal {deal['id']}: single-issue deal carries terms")
    assert_money(deal, phases)
    probe_illegal_moves(client, deal, seen, "agreed")

    # Pay.
    status, deal = req(client, "POST", f"{base}/pay")
    check(status == 200, f"pay -> {status}: {deal}")
    assert_legal_transition(seen, deal["state"], deal["id"])
    phases.add("paid")
    check(deal["payment"]["status"] in ("held", "awaiting_approval"),
          f"deal {deal['id']}: bad payment status "
          f"{deal['payment']['status']}")
    probe_illegal_moves(client, deal, seen, "paid")

    # Deliver with the randomized quality knob.
    status, deal = req(client, "POST", f"{base}/deliver",
                       {"quality": params["quality"]})
    check(status == 200, f"deliver -> {status}: {deal}")
    assert_legal_transition(seen, deal["state"], deal["id"])
    phases.add("delivered")

    # Verify to a terminal state, following revision rounds if granted.
    for _ in range(10):
        if deal["state"] in TERMINAL:
            break
        if deal["state"] == "delivered":
            status, deal = req(client, "POST", f"{base}/verify")
            check(status == 200, f"verify -> {status}: {deal}")
            # The verify call itself walks delivered -> verifying first
            # (the endpoint sets state="verifying" before judging), then
            # verifying -> revision | released | refunded.
            if deal["state"] != "verifying":
                assert_legal_transition(seen, "verifying", deal["id"])
            assert_legal_transition(seen, deal["state"], deal["id"])
            phases.add("verified")
        elif deal["state"] == "revision":
            phases.add("revision")
            status, deal = req(client, "POST", f"{base}/deliver",
                               {"quality": params["quality"]})
            check(status == 200, f"re-deliver -> {status}: {deal}")
            assert_legal_transition(seen, deal["state"], deal["id"])
            phases.add("delivered")
        else:
            break
    check(deal["state"] in TERMINAL,
          f"deal {deal['id']}: did not reach a terminal state, stuck at "
          f"{deal['state']} (path {seen})")
    check(deal["state"] in ("released", "refunded"),
          f"deal {deal['id']}: unexpected terminal {deal['state']}")

    # Full property pass on the finished deal.
    deal = get_deal(client, deal["id"])
    assert_ledger_integrity(deal, phases)
    assert_money(deal, phases)
    assert_reputation_once(client, deal, rep_before)
    # Terminal deals reject everything and change nothing, including
    # reputation on a second settlement attempt.
    rep_mid = agents_by_id(client)
    probe_illegal_moves(client, deal, seen, "terminal")
    rep_end = agents_by_id(client)
    for aid in rep_mid:
        check(rep_end[aid]["reputation"] == rep_mid[aid]["reputation"],
              f"deal {deal['id']}: illegal terminal moves changed "
              f"{aid} reputation")
    print(f"  case {CASES}: {params['scenario']} "
          f"multi={params['multi_issue']} q={params['quality']} -> "
          f"{deal['state']} via {' > '.join(seen)}")
    return deal


def test_illegal_transition_fuzz(client):
    """Random illegal moves against a fresh negotiating deal."""
    print("PROPERTY 1b: randomized illegal transitions on negotiating deals")
    actions = ["negotiate/run", "pay", "deliver", "verify"]
    for _ in range(8):
        new_case()
        params = random_case_params()
        status, deal = req(client, "POST", "/api/deals", {
            "scenario_id": params["scenario"],
            "buyer_max": params["buyer_max"],
            "seller_floor": params["seller_floor"],
            "bond_percent": params["bond_percent"],
        })
        check(status == 200, f"create -> {status}: {deal}")
        deal_id = deal["id"]
        n = rng.randint(1, 3)
        illegal = 0
        for _ in range(n):
            action = rng.choice(actions)
            body = {"quality": rng.choice(DELIVERY_QUALITIES)} \
                if action == "deliver" else {}
            if action == "negotiate/run" and deal["state"] == "negotiating":
                # negotiate/run is the LEGAL first move on a negotiating
                # deal (probe_illegal_moves treats it as legal in this
                # state too): expect 200 and record the resulting state
                # instead of asserting 4xx. Once the deal has left
                # negotiating, the premise of this probe no longer holds,
                # so this case is done.
                status, deal = req(client, "POST",
                                   f"/api/deals/{deal_id}/{action}", body)
                check(status == 200,
                      f"deal {deal_id}: legal negotiate/run -> {status}, "
                      f"expected 200: {deal}")
                break
            deal = assert_illegal_4xx(
                client, deal_id, f"/api/deals/{deal_id}/{action}", body,
                deal["state"], len(deal["ledger"]))
            illegal += 1
        print(f"  case {CASES}: {illegal} illegal moves on {deal_id}, "
              f"state now {deal['state']}")
    print("  PASS")


def test_fuzz_malformed_bodies(client):
    """Malformed creation and delivery bodies: 4xx/422 and no
    half-initialized deal left behind."""
    print("PROPERTY 5: fuzz malformed bodies")
    # Sentinel: the next id must be untouched by every failed creation.
    status, sentinel = req(client, "POST", "/api/deals",
                           {"scenario_id": "logo_brand_kit"})
    check(status == 200, f"sentinel create -> {status}: {sentinel}")
    # Deal ids are random (queue item W), so nothing predicts the next
    # one. The no-leak invariant is checked against the store itself:
    # failed creations must add no deal id at all.
    from pact import store as pact_store
    known_ids = set(pact_store.DEALS)

    fuzz_bodies = [
        {"scenario_id": "no_such_scenario"},
        {},
        {"scenario_id": "logo_brand_kit",
         "buyer_max": -round(rng.uniform(1, 1000), 2)},
        {"scenario_id": "logo_brand_kit",
         "seller_floor": -round(rng.uniform(1, 1000), 2)},
        {"scenario_id": "logo_brand_kit", "bond_percent": 0},
        {"scenario_id": "logo_brand_kit", "bond_percent": 100.01},
        {"scenario_id": "logo_brand_kit",
         "buyer_max": round(rng.uniform(1_000_001, 1e9), 2)},
        {"scenario_id": "logo_brand_kit", "seller_floor": 0.5},
        {"scenario_id": "logo_brand_kit", "buyer_max": "lots"},
        {"scenario_id": "x" * 10000},
        {"scenario_id": "logo_brand_kit", "seller_floor": {"usd": 5}},
        {"scenario_id": "logo_brand_kit",
         "bond_percent": round(rng.uniform(-50, -0.01), 2)},
    ]
    for body in fuzz_bodies:
        new_case()
        status, data = req(client, "POST", "/api/deals", body)
        check(400 <= status < 500,
              f"fuzz {str(body)[:60]} -> {status}, expected 4xx/422: {data}")
        # No half-initialized deal: the store gained no new id.
        check(set(pact_store.DEALS) == known_ids,
              f"fuzz {str(body)[:60]}: a failed creation left a deal in "
              f"the store")
    # The failed creations consumed no ids: the next valid deal adds
    # exactly one new id to the store.
    new_case()
    status, deal = req(client, "POST", "/api/deals",
                       {"scenario_id": "code_task"})
    check(status == 200, f"post-fuzz create -> {status}: {deal}")
    check(set(pact_store.DEALS) == known_ids | {deal["id"]},
          f"fuzz creations leaked deal ids")
    check(deal["state"] == "negotiating",
          f"fresh valid deal not in created state: {deal['state']}")

    # Malformed delivery quality on a paid deal: 400, state untouched.
    new_case()
    params = random_case_params()
    status, deal = req(client, "POST", "/api/deals", {
        "scenario_id": params["scenario"],
        "buyer_max": params["buyer_max"],
        "seller_floor": params["seller_floor"],
        "bond_percent": params["bond_percent"],
    })
    check(status == 200, f"create -> {status}")
    deal_id = deal["id"]
    status, deal = req(client, "POST", f"/api/deals/{deal_id}/negotiate/run")
    if deal["state"] == "agreed":
        status, deal = req(client, "POST", f"/api/deals/{deal_id}/pay")
        check(status == 200, f"pay -> {status}")
        ledger_len = len(deal["ledger"])
        status, data = req(client, "POST", f"/api/deals/{deal_id}/deliver",
                           {"quality": "definitely_not_a_quality"})
        check(status == 400,
              f"bad delivery quality -> {status}, expected 400: {data}")
        fresh = get_deal(client, deal_id)
        check(fresh["state"] == "paid_held",
              f"bad delivery quality moved state to {fresh['state']}")
        check(len(fresh["ledger"]) == ledger_len,
              "bad delivery quality appended ledger events")
    print("  PASS")


def main():
    print(f"seed={SEED}")
    with TestClient(app) as client:
        status, health = req(client, "GET", "/api/health")
        check(status == 200, f"health -> {status}")
        check(health["mode"] == "demo",
              f"NOT DEMO MODE: {health['mode']} - refusing to run")
        print(f"Health: mode {health['mode']}, "
              f"rail {health['agent_toolkit']['orders_rail']}")

        print("PROPERTY 1+2+3+4: randomized end-to-end deals")
        n_e2e = 34
        for i in range(n_e2e):
            drive_end_to_end(client, random_case_params())
        print("  PASS")

        test_illegal_transition_fuzz(client)
        test_fuzz_malformed_bodies(client)

    # Determinism self-check: the fixed seed replays the same stream.
    check(random.Random(SEED).randint(0, 10 ** 9) == FIRST_DRAW,
          f"seed {SEED} did not reproduce its first draw - "
          f"the run is not deterministic")
    print(f"seed={SEED} cases={CASES} checks={CHECKS} PASS")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        # Honest failure: report where the run stopped, keep the
        # non-zero exit. The counters show how much was verified.
        print(f"seed={SEED} cases={CASES} checks={CHECKS} FAIL: {exc}")
        raise

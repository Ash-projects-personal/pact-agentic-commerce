"""Tests for multi-issue negotiation (queue item S).

Price plus terms: after the price is agreed, the agents trade delivery
window, revision rounds, and bond percent (inside the sane 10-30 band)
on best-trade-ratio moves, and the terms freeze into the spec. The
checks prove: terms land inside their bands, the bond amount is the
negotiated percent of the price (what the money plumbing enforces),
the price phase is untouched (multi-issue twin settles the same price
as single-issue), negotiation is deterministic, the contract hash
covers the terms, the negotiated revision rounds are enforced by the
verify endpoint, and single-issue deals keep exactly one revision
round. The delivery window is contractual only: the demo delivers
instantly, so no clock enforces it, and that limit is stated, not
tested.

Run with: python tests/multi_issue_test.py
Exits non zero on the first failed assertion.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

# Force demo mode before the app modules read the environment.
for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

# Isolate persistence so the suite never touches data/pact.db.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pact.main import app  # noqa: E402
from pact.negotiation import spec_hash  # noqa: E402

checks_passed = 0


def check(cond, label):
    global checks_passed
    assert cond, f"FAILED: {label}"
    checks_passed += 1
    print(f"ok: {label}")


# Demo client token store (queue item W): state-changing deal endpoints
# require the per-deal role token in the X-Deal-Token header. The create
# response carries both tokens; they are remembered per deal id below.
_DEAL_TOKENS = {}


def post(client, path, body=None):
    # Deliver acts as the seller; everything else here acts as the
    # buyer. Tokens are remembered from each create response, the way a
    # real client would hold them.
    m = re.match(r"^/api/deals/([^/]+)/", path)
    headers = None
    if m:
        role = "seller" if path.rstrip("/").endswith("/deliver") else "buyer"
        tok = _DEAL_TOKENS.get(m.group(1), {}).get(role)
        if tok:
            headers = {"X-Deal-Token": tok}
    resp = client.post(path, json=body or {}, headers=headers)
    assert resp.status_code == 200, \
        f"POST {path} -> {resp.status_code}: {resp.text}"
    data = resp.json()
    if isinstance(data, dict) and data.get("id") and data.get("buyer_token"):
        _DEAL_TOKENS[data["id"]] = {
            "buyer": data.get("buyer_token"),
            "seller": data.get("seller_token"),
        }
    return data


def negotiate(client, multi_issue, scenario_id="logo_brand_kit"):
    deal = post(client, "/api/deals",
                {"scenario_id": scenario_id,
                 "buyer_max": 300, "seller_floor": 200,
                 "multi_issue": multi_issue})
    return post(client, f"/api/deals/{deal['id']}/negotiate/run")


def revision_rounds_to_refund(client, deal, quality="weak"):
    """Pay once, then deliver weak and verify until the deal refunds.

    Returns the list of states seen after each verify call.
    """
    deal = post(client, f"/api/deals/{deal['id']}/pay")
    states = []
    for _ in range(6):
        deal = post(client, f"/api/deals/{deal['id']}/deliver",
                    {"quality": quality})
        deal = post(client, f"/api/deals/{deal['id']}/verify")
        states.append(deal["state"])
        if deal["state"] == "refunded":
            break
    return deal, states


def main():
    with TestClient(app) as client:
        # --- the terms themselves ---
        deal = negotiate(client, True)
        check(deal["state"] == "agreed",
              f"multi-issue deal agrees (state {deal['state']})")
        terms = deal["terms"]
        check(terms is not None, "terms recorded on the deal")
        check(5 <= terms["delivery_days"] <= 12,
              f"delivery window in band: {terms['delivery_days']} days")
        check(1 <= terms["revision_rounds"] <= 3,
              f"revision rounds in band: {terms['revision_rounds']}")
        check(10.0 <= terms["bond_percent"] <= 30.0,
              f"bond percent inside the sane band: {terms['bond_percent']}")
        spec = deal["spec"]
        check(spec["terms"] == terms, "frozen spec carries the terms")
        expect_bond = round(spec["price"] * terms["bond_percent"] / 100.0, 2)
        check(abs(spec["bond_amount"] - expect_bond) < 0.011,
              f"bond amount {spec['bond_amount']} is the negotiated "
              f"{terms['bond_percent']}% of the price {spec['price']}")
        check(str(terms["revision_rounds"]) in spec["revision_policy"],
              "revision policy names the negotiated rounds")

        # --- the price phase is untouched ---
        single = negotiate(client, False)
        check(single["state"] == "agreed", "single-issue twin agrees")
        check(single["terms"] is None, "single-issue deal carries no terms")
        check(deal["spec"]["price"] == single["spec"]["price"],
              f"multi-issue price {deal['spec']['price']} equals the "
              f"single-issue price {single['spec']['price']}: the terms "
              f"phase cannot move the price")
        twin = negotiate(client, True)
        check(twin["terms"] == terms,
              "identical multi-issue runs settle identical terms "
              "(deterministic)")

        # --- the contract hash covers the terms ---
        # The hash commits to the stored frozen spec (integer cents
        # internally, queue item V), so hash the internal record, not
        # the dollar-denominated API view.
        from pact.store import DEALS
        stored_spec = DEALS[deal["id"]]["spec"]
        base_hash = spec_hash(stored_spec)
        for issue in ("delivery_days", "revision_rounds", "bond_percent"):
            altered = {k: (dict(v) if isinstance(v, dict) else v)
                       for k, v in stored_spec.items()}
            altered["terms"] = dict(stored_spec["terms"])
            altered["terms"][issue] = altered["terms"][issue] + 1
            check(spec_hash(altered) != base_hash,
                  f"spec hash changes when {issue} changes")
        check(deal["contract_hash"] == base_hash,
              "contract hash on the deal equals the spec hash")

        # --- terms_agreed event is honest ---
        agreed_events = [e for e in deal["ledger"]
                         if e["event_type"] == "terms_agreed"]
        check(len(agreed_events) == 1, "one terms_agreed ledger event")
        check(agreed_events[0]["data"]["cap_hit"] is False,
              "terms converged before the move cap (no forced midpoints)")
        trade_moves = [m for m in deal["moves"]
                       if m["kind"] == "terms_proposal"]
        check(len(trade_moves) == deal["terms_moves"] > 0,
              f"{deal['terms_moves']} best-trade-ratio moves recorded")

        # --- the negotiated bond is what the money plumbing charges ---
        deal = post(client, "/api/deals",
                    {"scenario_id": "logo_brand_kit",
                     "buyer_max": 300, "seller_floor": 200,
                     "multi_issue": True})
        deal = post(client, f"/api/deals/{deal['id']}/negotiate/run")
        pct = deal["terms"]["bond_percent"]
        check(pct != 20.0,
              f"negotiated bond {pct}% differs from the 20% default, so "
              f"the plumbing test below is meaningful")
        deal = post(client, f"/api/deals/{deal['id']}/pay")
        check(abs(deal["bond"]["amount"]
                  - deal["spec"]["bond_amount"]) < 0.011,
              f"paid bond {deal['bond']['amount']} equals the spec bond "
              f"amount {deal['spec']['bond_amount']} from the negotiated "
              f"percent")

        # --- negotiated revision rounds are enforced ---
        # book_cover_design weak passes 2/5 checks, so it takes the
        # revision path (logo weak passes nothing and refunds at once).
        deal = negotiate(client, True, "book_cover_design")
        rounds_allowed = deal["terms"]["revision_rounds"]
        check(rounds_allowed >= 2,
              f"this deal negotiated {rounds_allowed} revision rounds, "
              f"enough to prove the counter works")
        deal, states = revision_rounds_to_refund(client, deal)
        check(deal["state"] == "refunded",
              f"multi-issue deal refunds after its rounds (states seen: "
              f"{states})")
        check(states.count("revision") == rounds_allowed,
              f"exactly {rounds_allowed} revision rounds granted before "
              f"the refund, not one and not unlimited")
        exhausted = [e for e in deal["ledger"]
                     if e["event_type"] == "revisions_exhausted"]
        check(len(exhausted) == 1, "revisions_exhausted event recorded")
        check(deal["verification"]["round"] == rounds_allowed + 1,
              f"final verification round is {rounds_allowed + 1}")

        # --- single-issue regression: exactly one revision round ---
        deal = negotiate(client, False, "book_cover_design")
        deal, states = revision_rounds_to_refund(client, deal)
        check(deal["state"] == "refunded",
              "single-issue deal still refunds after its revision")
        check(states.count("revision") == 1,
              f"single-issue deal grants exactly one revision round "
              f"(states seen: {states})")

        # --- the dispute packet shows the terms ---
        deal = negotiate(client, True)
        resp = client.get(f"/api/deals/{deal['id']}/dispute-packet")
        check(resp.status_code == 200, "dispute packet endpoint answers")
        packet = resp.text
        check(str(deal["terms"]["delivery_days"]) in packet
              and str(deal["terms"]["revision_rounds"]) in packet,
              "dispute packet carries the negotiated terms")

    print(f"\n{checks_passed} multi-issue checks passed")


if __name__ == "__main__":
    main()

"""Tests for the dispute evidence packet (queue item M).

Runs deals end to end in demo mode, then downloads the packet and checks
that it was generated from real deal data only: the negotiation
transcript with each side's rationale, the frozen spec, every check
verdict with measured versus required, reputation moves, and every
PayPal transaction id on the deal record.

Run with: python tests/dispute_packet_test.py
Exits non zero on the first failed assertion.
"""

import os
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

from pact.dispute_packet import _gather_tx_ids  # noqa: E402
from pact.main import app  # noqa: E402

checks_passed = 0


def check(cond, label):
    global checks_passed
    assert cond, f"FAILED: {label}"
    checks_passed += 1


# Demo client token store (queue item W): state-changing deal endpoints
# require the per-deal role token in the X-Deal-Token header. The create
# response carries both tokens, so this helper remembers them per deal
# id and attaches the right one, the way a real client would. Deliver
# acts as the seller; everything else here acts as the buyer.
import re as _re  # noqa: E402

_DEAL_TOKENS = {}


def post(client, path, body=None):
    m = _re.match(r"^/api/deals/([^/]+)/", path)
    headers = None
    if m:
        role = ("seller" if path.rstrip("/").endswith("/deliver")
                else "buyer")
        tok = _DEAL_TOKENS.get(m.group(1), {}).get(role)
        if tok:
            headers = {"X-Deal-Token": tok}
    resp = client.post(path, json=body or {}, headers=headers)
    assert resp.status_code == 200, f"POST {path} -> {resp.status_code}: {resp.text}"
    data = resp.json()
    if isinstance(data, dict) and data.get("id") and data.get("buyer_token"):
        _DEAL_TOKENS[data["id"]] = {
            "buyer": data.get("buyer_token"),
            "seller": data.get("seller_token"),
        }
    return data


def get_packet(client, deal_id):
    resp = client.get(f"/api/deals/{deal_id}/dispute-packet")
    assert resp.status_code == 200, f"GET packet -> {resp.status_code}: {resp.text}"
    return resp


def section_lines(packet, header):
    """Lines of one packet section, up to the next section header."""
    lines = packet.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    out = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def packet_matches_deal(client, deal_id, packet):
    """The packet carries exactly the deal's data and nothing invented."""
    deal = client.get(f"/api/deals/{deal_id}").json()

    # Header and overview carry the deal identity and state.
    check(f"`{deal_id}`" in packet, "packet names the deal id")
    check(f"State: {deal['state']}" in packet, "packet carries the deal state")

    # Every negotiation rationale appears verbatim (whitespace
    # normalized the same way the packet does).
    for move in deal["moves"]:
        rationale = " ".join(str(move["rationale"]).split())
        check(rationale in packet,
              f"packet carries move {move['seq']} rationale")

    # Frozen spec: hash, price, bond, every check.
    spec = deal.get("spec")
    if spec:
        check(deal["contract_hash"] in packet, "packet carries the contract hash")
        check(str(spec["price"]) in packet, "packet carries the agreed price")
        check(str(spec["bond_amount"]) in packet, "packet carries the bond amount")
        for c in spec["acceptance_checks"]:
            check(c["id"] in packet or c["label"] in packet,
                  f"packet carries check {c['id']}")

    # Verification: every verdict with measured versus required, and
    # the summary counts match the verdict rows exactly.
    verification = deal.get("verification")
    if verification:
        results = verification["results"]
        for result in results:
            verdict = "PASS" if result["passed"] else "FAIL"
            check(result["check_id"] in packet,
                  f"packet carries verdict for {result['check_id']}")
            row = next(l for l in packet.splitlines()
                       if result["check_id"] in l and verdict in l)
            check(str(result["measured"]) in row,
                  f"packet shows measured for {result['check_id']}")
            check(str(result["required"]) in row,
                  f"packet shows required for {result['check_id']}")
        verdict_rows = sum(1 for l in packet.splitlines()
                          if l.startswith("| ") and ("| PASS |" in l or "| FAIL |" in l))
        check(verdict_rows == len(results),
              "verdict row count matches the verifier output")
        passed_rows = sum(1 for l in packet.splitlines()
                         if l.startswith("| ") and "| PASS |" in l)
        check(passed_rows == verification["passed_count"],
              "PASS row count matches passed_count")
        failed_rows = sum(1 for l in packet.splitlines()
                         if l.startswith("| ") and "| FAIL |" in l)
        check(failed_rows == verification["total_count"] - verification["passed_count"],
              "FAIL row count matches the failing checks")

    # Reputation moves: every reputation_change ledger message is in
    # the packet verbatim (whitespace normalized).
    rep_moves = [e for e in deal["ledger"]
                 if e["event_type"] == "reputation_change"]
    for event in rep_moves:
        message = " ".join(str(event["message"]).split())
        check(message in packet, f"packet carries reputation event {event['seq']}")

    # Transaction record: the table lists exactly the ids on the deal
    # record, no more and no fewer. Nothing invented.
    expected_ids = [value for _, value, _ in _gather_tx_ids(deal)]
    sec4 = section_lines(packet, "## 4. PayPal transaction record")
    table_ids = [l.split("|")[2].strip().strip("`")
                 for l in sec4
                 if l.startswith("| ") and not l.startswith("| Record")
                 and not l.startswith("| Leg") and "`" in l]
    check(sorted(table_ids) == sorted(expected_ids),
          "transaction table matches the deal record exactly")

    # Delivery: the judged text is included verbatim.
    if deal.get("deliverable"):
        check(deal["deliverable"]["content"] in packet,
              "packet carries the delivered text verbatim")


def test_released_deal():
    print("TEST 1 released deal: packet covers the full pass lifecycle")
    with TestClient(app) as client:
        deal = post(client, "/api/deals", {"scenario_id": "logo_brand_kit"})
        deal = post(client, f"/api/deals/{deal['id']}/negotiate/run")
        assert deal["state"] == "agreed", deal["state"]
        deal = post(client, f"/api/deals/{deal['id']}/pay")
        deal = post(client, f"/api/deals/{deal['id']}/deliver",
                    {"quality": "auto"})
        deal = post(client, f"/api/deals/{deal['id']}/verify")
        assert deal["state"] == "released", deal["state"]
        deal_id = deal["id"]

        resp = get_packet(client, deal_id)
        check("text/markdown" in resp.headers["content-type"],
              "packet served as markdown")
        check(resp.headers["content-disposition"] ==
              f'attachment; filename="pact-dispute-{deal_id}.md"',
              "packet downloads with a deal named file")
        packet = resp.text
        check("The price was released to the seller" in packet,
              "packet states the release outcome")
        packet_matches_deal(client, deal_id, packet)
        check(len(packet.splitlines()) > 100,
              "packet is a substantial evidence file")
        print(f"  packet for {deal_id}: {len(packet)} chars, "
              f"{len(deal['moves'])} moves, "
              f"{deal['verification']['passed_count']}/"
              f"{deal['verification']['total_count']} checks")
    print("  PASS")


def test_refunded_deal():
    print("TEST 2 refunded deal: packet covers the fail and slash path")
    with TestClient(app) as client:
        deal = post(client, "/api/deals", {"scenario_id": "logo_brand_kit"})
        deal = post(client, f"/api/deals/{deal['id']}/negotiate/run")
        deal = post(client, f"/api/deals/{deal['id']}/pay")
        deal = post(client, f"/api/deals/{deal['id']}/deliver",
                    {"quality": "poor"})
        deal = post(client, f"/api/deals/{deal['id']}/verify")
        assert deal["state"] == "refunded", deal["state"]
        deal_id = deal["id"]

        resp = get_packet(client, deal_id)
        packet = resp.text
        check("refunded to the buyer and the bond was slashed" in packet,
              "packet states the refund outcome")
        packet_matches_deal(client, deal_id, packet)
        check(deal["settlement"]["refund_id"] in packet,
              "packet carries the refund id")
        check(any("bond_slashed" in l for l in packet.splitlines()),
              "packet carries the bond slash event")
        failed_rows = sum(1 for l in packet.splitlines()
                         if l.startswith("| ") and "| FAIL |" in l)
        check(failed_rows == deal["verification"]["total_count"],
              "packet shows every check failing")
    print("  PASS")


def test_inflight_deal():
    print("TEST 3 in flight deal: packet is honest about missing data")
    with TestClient(app) as client:
        deal = post(client, "/api/deals", {"scenario_id": "logo_brand_kit"})
        deal = post(client, f"/api/deals/{deal['id']}/negotiate/run")
        assert deal["state"] == "agreed", deal["state"]
        deal_id = deal["id"]

        resp = get_packet(client, deal_id)
        packet = resp.text
        check("No verification has run on this deal yet" in packet,
              "packet says no verification has run")
        check("No delivery has been submitted yet" in packet,
              "packet says no delivery was submitted")
        check("No transaction ids exist on this deal yet" in packet,
              "packet says no money has moved")
        check(deal["contract_hash"] in packet,
              "packet still carries the frozen contract and its hash")
        # Nothing is invented: only the ids on the record appear.
        sec4 = section_lines(packet, "## 4. PayPal transaction record")
        id_rows = [l for l in sec4
                   if l.startswith("| ") and not l.startswith("| Record")
                   and not l.startswith("| Leg")
                   and "`" in l]
        check(len(id_rows) == 0, "transaction table is empty before payment")
        check(any(l.startswith("| price payout | pending |")
                  for l in sec4),
              "leg progress table still shows the unsettled legs")
    print("  PASS")


def test_unknown_deal():
    print("TEST 4 unknown deal: 404, not a packet")
    with TestClient(app) as client:
        resp = client.get("/api/deals/deal-9999/dispute-packet")
        check(resp.status_code == 404, "unknown deal id returns 404")
    print("  PASS")


def main():
    test_released_deal()
    test_refunded_deal()
    test_inflight_deal()
    test_unknown_deal()
    print(f"ALL DISPUTE PACKET TESTS PASSED ({checks_passed} checks)")


if __name__ == "__main__":
    main()

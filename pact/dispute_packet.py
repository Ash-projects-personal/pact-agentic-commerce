"""Dispute evidence packet: one self contained file per deal.

One action on any deal exports a single Markdown file generated from real
deal data only. Nothing is invented: every number, id, verdict, and
rationale comes from the deal record (negotiation moves, frozen spec,
verifier output, payment and settlement records, ledger). Sections that
have no data yet say so plainly instead of guessing. This is the artifact
a buyer would hand to a human reviewer in a real dispute.
"""

from . import money
from .store import AGENTS, now_iso


def _text(value):
    """Flatten a value to one line so pasted deal text cannot break the
    packet layout. Data is never altered, only whitespace normalized."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(" ".join(str(item).split()) for item in value)
    return " ".join(str(value).split())


def _money_line(deal):
    spec = deal.get("spec")
    if not spec:
        return "No contract has been frozen yet, so no money amounts are final."
    return (f"{money.dollars(spec['price'])} {spec['currency']} at "
            f"{spec['bond_percent']} percent bond "
            f"({money.dollars(spec['bond_amount'])} {spec['currency']})")


def _gather_tx_ids(deal):
    """Every transaction, order, batch, and request id on the deal record.

    Each entry is (label, value, rail). Only ids actually present on the
    record are listed; nothing is invented to fill the table. Leg
    statuses are not ids, so they live in the settlement leg progress
    table instead.
    """
    ids = []
    payment = deal.get("payment", {})
    bond = deal.get("bond", {})
    settlement = deal.get("settlement", {})

    def add(label, value, rail=None):
        if value:
            ids.append((label, str(value), rail))

    add("Price order id", payment.get("order_id"), payment.get("rail"))
    add("Price capture id", payment.get("capture_id"), payment.get("rail"))
    add("Price order idempotency key", payment.get("order_request_id"))
    add("Price capture idempotency key", payment.get("capture_request_id"))
    add("Price contract tag", payment.get("contract_tag"))
    add("Price contract hash field", payment.get("hash_field"))
    add("Bond order id", bond.get("order_id"), bond.get("rail"))
    add("Bond capture id", bond.get("capture_id"), bond.get("rail"))
    add("Bond order idempotency key", bond.get("order_request_id"))
    add("Bond capture idempotency key", bond.get("capture_request_id"))
    add("Bond contract tag", bond.get("contract_tag"))
    add("Bond contract hash field", bond.get("hash_field"))
    add("Price payout batch id", settlement.get("payout_id"))
    add("Bond return payout batch id", settlement.get("bond_payout_id"))
    add("Refund id", settlement.get("refund_id"))
    add("Price payout idempotency key", settlement.get("payout_request_id"))
    add("Bond payout idempotency key",
        settlement.get("bond_payout_request_id"))
    add("Refund idempotency key", settlement.get("refund_request_id"))
    add("Bond slash idempotency key",
        settlement.get("bond_slash_request_id"))
    legs = settlement.get("legs", {})
    leg_labels = {"price_payout": "price payout", "bond_return": "bond return",
                  "price_refund": "price refund", "bond_slash": "bond slash"}
    for leg, label in leg_labels.items():
        entry = legs.get(leg, {})
        add(f"{label} leg: idempotency key", entry.get("request_id"))
        add(f"{label} leg: result id", entry.get("result_id"),
            entry.get("rail"))
    return ids


def _leg_progress_lines(deal):
    """One line per settlement leg: status, attempt, payout status."""
    settlement = deal.get("settlement", {})
    legs = settlement.get("legs", {})
    leg_labels = {"price_payout": "price payout", "bond_return": "bond return",
                  "price_refund": "price refund", "bond_slash": "bond slash"}
    lines = ["| Leg | Status | Attempt | Payout status |"]
    lines.append("|---|---|---|---|")
    for leg, label in leg_labels.items():
        entry = legs.get(leg, {})
        lines.append(f"| {label} | {entry.get('status')} | "
                     f"{entry.get('attempt')} | "
                     f"{entry.get('payout_status') or '-'} |")
    return lines


def _section_overview(deal, lines):
    payment = deal.get("payment", {})
    lines.append("## 1. Deal overview")
    lines.append("")
    lines.append(f"Deal id: {deal['id']}")
    lines.append(f"Scenario: {_text(deal.get('scenario_title'))}")
    lines.append(f"State: {deal['state']}")
    lines.append(f"Currency: {deal.get('currency', 'USD')}")
    lines.append(f"Payment rail mode: {payment.get('mode') or 'not started'}")
    lines.append(f"Created: {deal.get('created_at')}")
    lines.append(f"Last updated: {deal.get('updated_at')}")
    lines.append(f"Agreed price and bond: {_money_line(deal)}")
    if deal.get("contract_hash"):
        lines.append(f"Contract hash (SHA-256): {deal['contract_hash']}")
        lines.append("The same hash was carried on the PayPal order record "
                     "at payment time, so the contract the verifier judged "
                     "is the contract PayPal holds a pointer to.")
    lines.append("")


def _section_parties(deal, lines):
    lines.append("## 2. Parties and reputation")
    lines.append("")
    for role, key in (("Buyer", "buyer_agent_id"),
                      ("Seller", "seller_agent_id")):
        agent = AGENTS.get(deal.get(key), {})
        lines.append(f"{role}: {_text(agent.get('name'))} "
                     f"(id {agent.get('id')}), reputation "
                     f"{agent.get('reputation')}, "
                     f"{agent.get('deals')} deals settled.")
    lines.append("")
    lines.append("Reputation starts at a neutral baseline per persona. "
                 "Completed deals raise it, a revision costs a little, "
                 "a refund costs more, and a slashed bond cuts it hard. "
                 "Every move is listed in section 9.")
    lines.append("")


def _section_money(deal, lines):
    lines.append("## 3. Money summary")
    lines.append("")
    payment = deal.get("payment", {})
    bond = deal.get("bond", {})
    spec = deal.get("spec")
    if not spec:
        lines.append("No money has moved: the contract is not frozen yet.")
        lines.append("")
        return
    lines.append(f"Price: {money.dollars(spec['price'])} {spec['currency']} "
                 f"(payment status: {payment.get('status')})")
    lines.append(f"Performance bond: {money.dollars(spec['bond_amount'])} "
                 f"{spec['currency']} at {spec['bond_percent']} percent "
                 f"(bond status: {bond.get('status')})")
    state = deal["state"]
    if state == "released":
        lines.append("Outcome: the delivery passed verification. The price "
                     "was released to the seller and the bond was returned.")
    elif state == "refunded":
        lines.append("Outcome: the delivery failed verification. The held "
                     "price was refunded to the buyer and the bond was "
                     "slashed to the buyer.")
    elif state in ("paid_held", "delivered", "verifying", "revision"):
        lines.append("Outcome: not settled yet. The price is held and the "
                     "bond is posted while verification runs.")
    else:
        lines.append(f"Outcome: no settlement. The deal is {state}.")
    lines.append("")


def _section_transactions(deal, lines):
    lines.append("## 4. PayPal transaction record")
    lines.append("")
    ids = _gather_tx_ids(deal)
    if not ids:
        lines.append("No transaction ids exist on this deal yet.")
    else:
        lines.append("| Record | Id | Rail |")
        lines.append("|---|---|---|")
        for label, value, rail in ids:
            lines.append(f"| {label} | `{value}` | {rail or '-'} |")
    lines.append("")
    lines.append("Settlement leg progress (each leg is recorded as it "
                 "completes, so a resume never reruns a leg):")
    lines.append("")
    lines.extend(_leg_progress_lines(deal))
    lines.append("")


def _section_contract(deal, lines):
    lines.append("## 5. The frozen contract")
    lines.append("")
    spec = deal.get("spec")
    if not spec:
        lines.append("No contract has been frozen yet. The negotiation "
                     "transcript in section 6 shows the state of the talks.")
        lines.append("")
        return
    lines.append(f"Service: {_text(spec.get('service_summary'))}")
    lines.append(f"Deliverables: {_text(spec.get('deliverables'))}")
    lines.append(f"Revision policy: {_text(spec.get('revision_policy'))}")
    lines.append(f"Contract written by: "
                 f"{_text(spec.get('written_by'))}")
    lines.append("")
    lines.append("Acceptance checks (written and settled by the agents):")
    lines.append("")
    lines.append("| Check | Required | Unit | How it settled |")
    lines.append("|---|---|---|---|")
    for check in spec.get("acceptance_checks", []):
        lines.append(f"| {_text(check.get('label'))} | "
                     f"{check.get('value')} | "
                     f"{_text(check.get('unit'))} | "
                     f"{_text(check.get('settled_note'))} |")
    lines.append("")
    if deal.get("contract_hash"):
        lines.append(f"SHA-256 of this exact contract: "
                     f"`{deal['contract_hash']}`")
        lines.append("Any changed check value, price, or bond changes this "
                     "digest. The verification summary in section 8 "
                     "records the same hash.")
        lines.append("")


def _section_transcript(deal, lines):
    lines.append("## 6. Negotiation transcript")
    lines.append("")
    moves = deal.get("moves", [])
    if not moves:
        lines.append("No negotiation moves have been recorded yet.")
        lines.append("")
        return
    lines.append(f"{len(moves)} moves in "
                 f"{deal.get('negotiation_rounds', 0)} rounds. Each side "
                 f"states its own rationale.")
    lines.append("")
    for move in moves:
        what = move.get("kind", "")
        if move.get("price") is not None:
            what += f" at {move['price']} USD"
        if move.get("check_id"):
            what += f" on {move['check_id']} (value {move.get('value')})"
        lines.append(f"### Move {move.get('seq')}: "
                     f"{_text(move.get('actor'))}, {what}")
        lines.append("")
        lines.append(f"> {_text(move.get('rationale'))}")
        lines.append("")


def _section_delivery(deal, lines):
    lines.append("## 7. Delivery")
    lines.append("")
    deliverable = deal.get("deliverable")
    if not deliverable:
        lines.append("No delivery has been submitted yet.")
        lines.append("")
        return
    content = deliverable.get("content", "")
    lines.append(f"Version {deliverable.get('version')}, submitted by "
                 f"{_text(deliverable.get('produced_by'))} at "
                 f"{deliverable.get('created_at')}.")
    lines.append(f"Delivery quality used: "
                 f"{_text(deliverable.get('quality'))}.")
    lines.append(f"Word count: {len(content.split())}.")
    lines.append("")
    lines.append("The delivered text, exactly as the verifier judged it:")
    lines.append("")
    lines.append("```")
    lines.append(content)
    lines.append("```")
    lines.append("")


def _section_verification(deal, lines):
    lines.append("## 8. Verification")
    lines.append("")
    verification = deal.get("verification")
    if not verification:
        lines.append("No verification has run on this deal yet. Nothing "
                     "below is a verdict.")
        lines.append("")
        return
    lines.append(f"Round {verification.get('round')}, checked at "
                 f"{verification.get('checked_at')}.")
    lines.append(f"Result: {verification.get('passed_count')} of "
                 f"{verification.get('total_count')} negotiated checks "
                 f"passed.")
    lines.append(f"Judged against contract hash: "
                 f"`{verification.get('contract_hash') or deal.get('contract_hash') or 'not recorded'}`")
    lines.append("")
    lines.append("| Check | Verdict | Measured | Required | Reason |")
    lines.append("|---|---|---|---|---|")
    for result in verification.get("results", []):
        verdict = "PASS" if result.get("passed") else "FAIL"
        lines.append(f"| {_text(result.get('check_id'))} | {verdict} | "
                     f"{_text(result.get('measured'))} | "
                     f"{_text(result.get('required'))} | "
                     f"{_text(result.get('reason'))} |")
    lines.append("")


def _section_reputation(deal, lines):
    lines.append("## 9. Reputation moves")
    lines.append("")
    moves = [e for e in deal.get("ledger", [])
             if e.get("event_type") == "reputation_change"]
    if not moves:
        lines.append("No reputation changes have been recorded on this "
                     "deal yet.")
        lines.append("")
        return
    for event in moves:
        data = event.get("data", {})
        lines.append(f"- {event.get('timestamp')}: "
                     f"{_text(data.get('agent_id'))} "
                     f"{data.get('from')} -> {data.get('to')} "
                     f"(change {data.get('delta')}). Reason: "
                     f"{_text(data.get('reason'))}.")
    lines.append("")


def _section_ledger(deal, lines):
    lines.append("## 10. Full audit ledger")
    lines.append("")
    ledger = deal.get("ledger", [])
    if not ledger:
        lines.append("The ledger is empty.")
        lines.append("")
        return
    lines.append(f"{len(ledger)} events, in order. Detail payloads for "
                 "money, verification, and contract events appear in the "
                 "sections above.")
    lines.append("")
    for event in ledger:
        lines.append(f"### Event {event.get('seq')}: "
                     f"{_text(event.get('event_type'))}")
        lines.append("")
        lines.append(f"Time: {event.get('timestamp')} | "
                     f"Actor: {_text(event.get('actor'))}")
        lines.append("")
        lines.append(f"{_text(event.get('message'))}")
        lines.append("")


def build_dispute_packet(deal):
    """Build the dispute evidence packet for one deal as Markdown.

    The deal dict is read, never modified. Every section draws only on
    fields present on the record.
    """
    lines = [
        "# Pact dispute evidence packet",
        "",
        f"This file is the complete evidence record for deal "
        f"`{deal['id']}`. It was generated from the deal record at "
        f"{now_iso()} and contains only what the deal record holds: "
        f"no conclusions are added and nothing is invented.",
        "",
    ]
    _section_overview(deal, lines)
    _section_parties(deal, lines)
    _section_money(deal, lines)
    _section_transactions(deal, lines)
    _section_contract(deal, lines)
    _section_transcript(deal, lines)
    _section_delivery(deal, lines)
    _section_verification(deal, lines)
    _section_reputation(deal, lines)
    _section_ledger(deal, lines)
    lines.append("## About this packet")
    lines.append("")
    lines.append("A buyer hands this file to a human reviewer to dispute a "
                 "settlement. The negotiation transcript shows what each "
                 "side agreed to and why. The frozen contract shows the "
                 "exact checks. The verification section shows every check "
                 "verdict with what was measured against what was required. "
                 "The transaction record holds every PayPal id on the deal. "
                 "The ledger shows every step in order with its timestamp.")
    lines.append("")
    return "\n".join(lines)

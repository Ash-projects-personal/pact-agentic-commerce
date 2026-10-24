"""Deterministic negotiation engine with agent written contract terms.

Two phases run in order, plus an optional terms phase.

Phase one is price. The buyer opens below its ceiling, the seller opens above
its floor, and each side concedes a share of the remaining gap on its turn.
The walk away rule is real: if the seller floor sits above the buyer ceiling
the gap never closes, the round cap hits, and the deal fails with no payment.

Phase one-and-a-half is terms (multi_issue=True only). The sides trade
delivery window, revision rounds, and bond percent (inside a sane band)
with simple linear utility weights, conceding on the issue with the best
trade ratio each turn: the most utility for the other side per unit of
their own given up. It runs after the price is locked, so it can never
undo a price agreement. Agreed terms are frozen into the spec.

Phase two is the contract. The acceptance checks are not a fixed template.
The buyer agent proposes a value for each candidate check, the seller agent
accepts or counters, and numeric counters settle at the midpoint. The settled
checks are frozen into the deal spec and the verifier judges against exactly
those values.
"""

from . import llm
from . import money
from .store import add_event

import hashlib
import json

MAX_PRICE_MOVES = 26
CONCESSION = 0.45

# Multi-issue terms (queue item S). After the price is agreed, and only
# when multi_issue=True, the sides negotiate three terms with declared
# positions and simple linear utility weights. The positions are the
# opening demands; each side concedes its own positions toward the
# other side. The bond percent negotiates inside the sane band
# BOND_BAND: outside it a bond is either too weak to punish a cheat or
# so large the seller walks away.
#
# The issues, buyer ideal first:
#   delivery_days:   buyer 5 days,  seller 12 days
#   revision_rounds: buyer 3 rounds, seller 1 round
#   bond_percent:    buyer 30.0 pct, seller 10.0 pct (band 10 to 30)
#
# Utility weights per side (price is already settled at 0.50 and is
# recorded only, it does not move in the terms phase):
BUYER_TERM_WEIGHTS = {"delivery_days": 0.20, "revision_rounds": 0.15,
                      "bond_percent": 0.15}
SELLER_TERM_WEIGHTS = {"delivery_days": 0.25, "revision_rounds": 0.10,
                       "bond_percent": 0.15}
PRICE_WEIGHT = 0.50
BOND_BAND = (10.0, 30.0)
MAX_TERM_MOVES = 40
TERM_CONCESSION = 0.25
# Gap under which an issue counts as converged: one day, half a
# revision round, half a bond point.
TERM_THRESHOLDS = {"delivery_days": 1.0, "revision_rounds": 0.5,
                   "bond_percent": 0.5}
_TERM_ORDER = ["delivery_days", "revision_rounds", "bond_percent"]


def _term_ideals():
    return {
        "delivery_days": (5, 12),
        "revision_rounds": (3, 1),
        "bond_percent": (30.0, 10.0),
    }


def _term_utility(side, issue, value):
    """Linear utility of one issue for one side, 0 at the opponent's
    ideal and 1 at its own ideal."""
    buyer_ideal, seller_ideal = _term_ideals()[issue]
    if side == "buyer":
        own, other = buyer_ideal, seller_ideal
    else:
        own, other = seller_ideal, buyer_ideal
    lo, hi = (own, other) if own < other else (other, own)
    span = hi - lo
    raw = (value - lo) / span if span else 1.0
    # own < other: the side's ideal is the low end, so utility falls as
    # the value rises (1 - raw). own > other: the ideal is the high
    # end, so utility rises with the value (raw).
    return (1.0 - raw) if own < other else raw


async def _run_terms_negotiation(deal):
    """Phase one-and-a-half: price is settled, now trade terms.

    On each turn the side whose turn it is looks at every open issue
    and asks: if I concede a step on this issue, how much utility does
    the other side gain for each unit of utility I lose? It concedes on
    the issue with the best trade ratio, so concessions trade across
    issues instead of grinding on one. When every gap is under its
    threshold the issue settles at the midpoint of the two positions.
    The terms phase can never fail a deal the price phase agreed: if
    the move cap hits, the remaining issues settle at their midpoints
    and that is recorded honestly.
    """
    ideals = _term_ideals()
    bpos = {i: float(ideals[i][0]) for i in _TERM_ORDER}
    spos = {i: float(ideals[i][1]) for i in _TERM_ORDER}
    waits = {"buyer": BUYER_TERM_WEIGHTS, "seller": SELLER_TERM_WEIGHTS}

    def open_issues():
        return [i for i in _TERM_ORDER
                if abs(bpos[i] - spos[i]) > TERM_THRESHOLDS[i]]

    def describe(issue, value):
        if issue == "delivery_days":
            return f"a delivery window of {int(round(value))} days"
        if issue == "revision_rounds":
            return f"{int(round(value))} revision rounds"
        return f"a performance bond of {_pct(value)} percent"

    terms_moves = 0
    cap_hit = False
    turn = "buyer"
    while open_issues() and terms_moves < MAX_TERM_MOVES:
        weights_self = waits[turn]
        other = "seller" if turn == "buyer" else "buyer"
        weights_other = waits[other]
        pos_self = bpos if turn == "buyer" else spos
        pos_other = spos if turn == "buyer" else bpos
        best_issue = None
        best_ratio = -1.0
        best_new = None
        for issue in open_issues():
            here = pos_self[issue]
            target = pos_other[issue]
            step = here + (target - here) * TERM_CONCESSION
            own_loss = (weights_self[issue]
                        * (_term_utility(turn, issue, here)
                           - _term_utility(turn, issue, step)))
            opp_gain = (weights_other[issue]
                        * (_term_utility(other, issue, step)
                           - _term_utility(other, issue, here)))
            ratio = opp_gain / max(own_loss, 1e-9)
            if ratio > best_ratio + 1e-12:
                best_ratio = ratio
                best_issue = issue
                best_new = step
        pos_self[best_issue] = best_new
        terms_moves += 1
        await _add_move(
            deal, turn, "terms_proposal",
            f"I will move to {describe(best_issue, best_new)}. That is "
            f"the issue where my concession buys you the most for the "
            f"least I give up, so it is the fair trade to make next.",
            check_id=best_issue, value=_pct(best_new))
        turn = other

    if open_issues():
        # The move cap hit before every issue converged. Settle the
        # open issues at the midpoint of the two positions and record
        # it honestly; the deal itself still stands.
        cap_hit = True
        for issue in open_issues():
            mid = (bpos[issue] + spos[issue]) / 2
            bpos[issue] = mid
            spos[issue] = mid

    terms = {
        "delivery_days": int(round((bpos["delivery_days"]
                                    + spos["delivery_days"]) / 2)),
        "revision_rounds": int(round((bpos["revision_rounds"]
                                      + spos["revision_rounds"]) / 2)),
        "bond_percent": _pct((bpos["bond_percent"]
                              + spos["bond_percent"]) / 2),
    }
    terms["bond_percent"] = min(max(terms["bond_percent"], BOND_BAND[0]),
                                BOND_BAND[1])
    deal["terms"] = terms
    deal["terms_moves"] = terms_moves
    deal["bond_percent"] = terms["bond_percent"]
    await _add_move(
        deal, "buyer", "terms_settle",
        f"Terms agreed: delivery in {terms['delivery_days']} days, "
        f"{terms['revision_rounds']} revision rounds, bond at "
        f"{terms['bond_percent']} percent of the price. Each side gave "
        f"where the trade was cheapest for it, and every term is now "
        f"written into the frozen contract.")
    add_event(deal, "terms_agreed", "system",
              f"Multi-issue terms settled in {terms_moves} moves: "
              f"{terms['delivery_days']} day delivery, "
              f"{terms['revision_rounds']} revision rounds, "
              f"{terms['bond_percent']}% bond. Concessions traded across "
              f"issues on best-trade-ratio moves."
              + (" The move cap was hit; open issues settled at "
                 "midpoints." if cap_hit else ""),
              {"terms": terms, "terms_moves": terms_moves,
               "cap_hit": cap_hit,
               "buyer_weights": BUYER_TERM_WEIGHTS,
               "seller_weights": SELLER_TERM_WEIGHTS,
               "price_weight": PRICE_WEIGHT})
    return terms


def _pct(value):
    """Two-decimal rounding for percents and rates only, never money.

    Bond percent, concession rates, and term positions are parameters,
    not amounts: they keep the exact 2-decimal semantics the old
    _money() gave them. Every money amount (offers, asks, prices, bond
    amounts) is an integer number of cents computed with pact.money.
    """
    return round(float(value), 2)


def spec_hash(spec):
    """SHA-256 over the frozen spec, canonical JSON with sorted keys.

    The hash is computed over every field of the spec except a
    "contract_hash" key itself, so storing the hash on the deal can
    never change the value it commits to. Any single changed check
    value, price, or bond changes the digest.
    """
    body = {k: v for k, v in spec.items() if k != "contract_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _add_move(deal, actor, kind, rationale, price=None, check_id=None,
                    value=None):
    move = {
        "seq": len(deal["moves"]) + 1,
        "actor": actor,
        "kind": kind,
        "price": price,
        "check_id": check_id,
        "value": value,
        "rationale": rationale,
    }
    context = f"{deal['scenario_title']} negotiation, move kind {kind}"
    move["rationale"] = await llm.polish(rationale, context)
    deal["moves"].append(move)
    label = f"price {price}" if price is not None else (check_id or kind)
    add_event(deal, "negotiation_move", actor,
              f"{actor} move {move['seq']} ({kind}, {label}): {move['rationale']}",
              {"move_seq": move["seq"], "kind": kind, "price": price,
               "check_id": check_id, "value": value})
    return move


def _settle_mid(offer_c, ask_c, floor_c, buyer_max_c):
    """Midpoint of the two positions, pulled into the agreed zone.

    All four inputs are integer cents. The ceiling and the floor are
    the binding commitments: any price between them is acceptable to
    both sides by declaration. When the raw midpoint lands a hair
    outside the zone (the two sides approach from unequal distances,
    so it happens near the edges), the nearest point inside the zone
    is the fair settle.
    """
    mid_c = money.div_round(offer_c + ask_c, 2)
    return min(max(mid_c, floor_c), buyer_max_c)


async def run_negotiation(deal, scenario, multi_issue=False):
    # Money inside the deal record is integer cents (queue item V):
    # buyer_max, seller_floor, and every offer, ask, and settled price
    # below are cents. pact.money does the exact arithmetic; dollars
    # appear only in the human-readable rationales and move labels.
    buyer_max_c = deal["buyer_max"]
    floor_c = deal["seller_floor"]
    buyer_name = "buyer"
    seller_name = "seller"

    offer_c = money.pct_of(buyer_max_c, 60)
    ask_c = money.pct_of(floor_c, 135)

    await _add_move(
        deal, buyer_name, "price",
        f"I open at {money.dollars(offer_c)} USD for this scope. That "
        f"leaves me room to move if the terms are right, and it reflects "
        f"what a first version of this work is worth to me.",
        price=money.dollars(offer_c))
    await _add_move(
        deal, seller_name, "price",
        f"My price is {money.dollars(ask_c)} USD. That covers senior time "
        f"on the work and one round of polish. I can move a little if "
        f"the scope stays tight.",
        price=money.dollars(ask_c))

    settled_c = None
    price_moves = 2
    rounds = 0
    buyer_pinned = False
    seller_pinned = False
    while price_moves < MAX_PRICE_MOVES and not (buyer_pinned and seller_pinned):
        rounds += 1
        gap_c = ask_c - offer_c
        threshold_c = max(500, money.pct_of(ask_c, 5))
        if gap_c <= threshold_c and floor_c <= buyer_max_c:
            settled_c = _settle_mid(offer_c, ask_c, floor_c, buyer_max_c)
            break
        # Buyer turn: concede a share of the gap, never above the ceiling.
        # A buyer who cannot move is pinned, not a reason to end the deal:
        # the seller may still close the gap alone.
        if not buyer_pinned:
            new_offer_c = min(buyer_max_c,
                              money.add_scaled(offer_c, gap_c, CONCESSION))
            if new_offer_c <= offer_c:
                buyer_pinned = True
            else:
                offer_c = new_offer_c
                price_moves += 1
                await _add_move(
                    deal, buyer_name, "price",
                    f"I will move up to {money.dollars(offer_c)} USD. I "
                    f"closed part of the gap because the scope is clear "
                    f"and I want this scheduled. I still need the contract "
                    f"checks to be written down before I pay.",
                    price=money.dollars(offer_c))
                gap_c = ask_c - offer_c
                if gap_c <= threshold_c and floor_c <= buyer_max_c:
                    settled_c = _settle_mid(offer_c, ask_c, floor_c,
                                            buyer_max_c)
                    break
        if price_moves >= MAX_PRICE_MOVES:
            break
        # Seller turn: concede a share of the gap, never below the floor.
        if not seller_pinned:
            new_ask_c = max(floor_c,
                            money.add_scaled(ask_c, -gap_c, CONCESSION))
            if new_ask_c >= ask_c:
                seller_pinned = True
            else:
                ask_c = new_ask_c
                price_moves += 1
                await _add_move(
                    deal, seller_name, "price",
                    f"I can come down to {money.dollars(ask_c)} USD. I am "
                    f"trading price for a clean brief and a firm list of "
                    f"checks I will be judged against, which protects me "
                    f"from open ended revision requests.",
                    price=money.dollars(ask_c))

    if settled_c is None and floor_c <= buyer_max_c:
        # Final check for the pinned case: both sides ended at their
        # declared limits, so the clamped midpoint settles the deal.
        settled_c = _settle_mid(offer_c, ask_c, floor_c, buyer_max_c)

    deal["negotiation_rounds"] = rounds

    if settled_c is None:
        deal["state"] = "failed"
        await _add_move(
            deal, buyer_name, "walkaway",
            f"I am walking away. After {rounds} rounds our positions never "
            f"met. My ceiling is {money.dollars(buyer_max_c)} USD and the "
            f"seller would not go below {money.dollars(ask_c)} USD, so "
            f"there is no honest deal here.")
        add_event(deal, "negotiation_failed", "system",
                  "Negotiation ended with no agreement. No payment was made "
                  "and no bond was posted.")
        return deal

    deal["agreed_price"] = settled_c
    add_event(deal, "price_agreed", "system",
              f"Price agreed at {money.dollars(settled_c)} USD after "
              f"{rounds} rounds. The agents now write the contract checks."
              + (" First they trade the terms." if multi_issue else ""))

    if multi_issue:
        # Phase one-and-a-half: trade delivery window, revision rounds,
        # and bond percent on best-trade-ratio moves. This runs after
        # the price is locked, so it can never undo a price agreement.
        await _run_terms_negotiation(deal)

    # Phase two: the agents write the acceptance checks themselves.
    settled_checks = []
    for cand in scenario["candidate_checks"]:
        cid = cand["id"]
        if cand["kind"] == "max_price":
            # A price ceiling settles at the agreed price itself: the
            # buyer will not reimburse a purchase above what the two
            # sides just settled, and the seller accepts that cap
            # because the market grounding already proved a real offer
            # exists at or under it. The check value is integer cents;
            # the verifier parses the stated price to cents too, so the
            # comparison never touches a float.
            await _add_move(
                deal, buyer_name, "check_proposal",
                f"Contract check: the price paid must come in at or "
                f"under the {money.dollars(settled_c)} USD we just agreed. "
                f"The report has to state the exact price paid, and "
                f"anything above the agreed price fails.",
                check_id=cid, value=settled_c)
            await _add_move(
                deal, seller_name, "check_response",
                f"Accepted at {money.dollars(settled_c)} USD. I buy at the "
                f"grounded offer or cheaper, and the report shows the "
                f"price I paid so the verifier can test it.",
                check_id=cid, value=settled_c)
            settled_checks.append({
                "id": cid, "label": cand["label"], "kind": "max_price",
                "value": settled_c, "unit": cand.get("unit", "USD"),
                "settled_note": ("Ceiling set to the agreed price "
                                  f"{money.dollars(settled_c)}"),
            })
            continue
        if cand["kind"] == "contains":
            await _add_move(
                deal, buyer_name, "check_proposal",
                f"Contract check: the delivery must include {cand['label'].lower()}. "
                f"This is core to the job, so it is a pass or fail item for me.",
                check_id=cid, value=cand["needle"])
            await _add_move(
                deal, seller_name, "check_response",
                f"Accepted as written. {cand['label']} will be in the "
                f"delivery and the verifier can test for it directly.",
                check_id=cid, value=cand["needle"])
            settled_checks.append({
                "id": cid, "label": cand["label"], "kind": "contains",
                "value": cand["needle"], "settled_note": "Accepted as proposed",
            })
            continue
        demand = cand["buyer_demand"]
        seller_offer = cand["seller_offer"]
        unit = cand.get("unit", "")
        await _add_move(
            deal, buyer_name, "check_proposal",
            f"Contract check: I want at least {demand} {unit} for "
            f"{cand['label'].lower()}. That is the level where this work "
            f"actually does its job for me.",
            check_id=cid, value=demand)
        if seller_offer == demand:
            await _add_move(
                deal, seller_name, "check_response",
                f"Accepted at {demand} {unit}. That is fair for the price "
                f"we settled on.",
                check_id=cid, value=demand)
            settled = demand
            note = "Accepted as proposed"
        else:
            await _add_move(
                deal, seller_name, "check_response",
                f"I counter at {seller_offer} {unit}. At the agreed price "
                f"that is the level I can deliver well. More than that and "
                f"quality drops or the price has to rise.",
                check_id=cid, value=seller_offer)
            settled = int((demand + seller_offer) / 2 + 0.5)
            await _add_move(
                deal, buyer_name, "check_settle",
                f"Settled at {settled} {unit}. We both moved, and the "
                f"number is now written into the contract where the "
                f"verifier can hold us to it.",
                check_id=cid, value=settled)
            note = f"Proposed {demand}, countered {seller_offer}, settled {settled}"
        check = {
            "id": cid, "label": cand["label"], "kind": cand["kind"],
            "value": settled, "unit": unit, "settled_note": note,
        }
        if cand["kind"] == "min_items":
            check["marker"] = cand["marker"]
        settled_checks.append(check)

    # The bond is exact integer-cent math: settled cents times the
    # negotiated percent, rounded half-even once. No float is involved.
    bond_amount_c = money.pct_of(settled_c, deal["bond_percent"])
    revision_policy = (
        "One revision round when some checks pass and some fail. "
        "A delivery that passes nothing is refunded at once."
    )
    spec = {
        "scenario_id": scenario["id"],
        "title": scenario["title"],
        "service_summary": scenario["service_summary"],
        "deliverables": scenario["deliverables"],
        "acceptance_checks": settled_checks,
        "price": settled_c,
        "currency": "USD",
        "bond_percent": deal["bond_percent"],
        "bond_amount": bond_amount_c,
        "revision_policy": revision_policy,
        "written_by": "The buyer and seller agents during negotiation",
    }
    if multi_issue:
        # The negotiated terms are part of the frozen contract, covered
        # by the spec hash like every check. The bond amount above is
        # recomputed from the negotiated bond percent, so the money
        # plumbing enforces it. The revision rounds are enforced by the
        # verify endpoint's revision counter. The delivery window is
        # contractual: the demo delivers instantly, so no clock enforces
        # it here; a production deployment would start the clock at
        # capture and fail late deliveries.
        spec["terms"] = dict(deal["terms"])
        spec["bond_percent"] = deal["bond_percent"]
        spec["bond_amount"] = bond_amount_c
        spec["revision_policy"] = (
            f"{deal['terms']['revision_rounds']} revision rounds when "
            f"some checks pass and some fail. A delivery that passes "
            f"nothing is refunded at once. Delivery is due within "
            f"{deal['terms']['delivery_days']} days of payment."
        )
    if scenario.get("grounding"):
        # Market grounded scenarios (procurement) carry the evidence
        # their checks were built from into the frozen spec, so the
        # delivery builder and any reader of the spec can see exactly
        # which real offers the contract rests on.
        spec["grounding"] = scenario["grounding"]
    deal["spec"] = spec
    deal["state"] = "agreed"
    deal["contract_hash"] = spec_hash(spec)
    add_event(deal, "contract_written", "system",
              f"Contract frozen. {len(settled_checks)} acceptance checks "
              f"were written by the agents and settled. Price "
              f"{money.dollars(settled_c)} USD. Performance bond "
              f"{money.dollars(bond_amount_c)} USD at "
              f"{deal['bond_percent']} percent of the price. The frozen "
              f"spec hashes to SHA-256 "
              f"{deal['contract_hash'][:16]}..., and the same hash travels "
              f"onto the PayPal orders at payment.",
              {"contract_hash": deal["contract_hash"]})
    return deal

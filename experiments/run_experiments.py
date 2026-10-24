"""Experiment harness for the Pact paper.

Every number in the paper comes out of this file. Four studies:

E1 Verifier accuracy. For each scenario, settle a real spec through the
negotiation, then build deliveries whose per check ground truth is known
by construction: a perfect delivery, one violating variant per check,
and neutral variants that must not change any verdict. Adds named trap
cases (hex codes offered as hashtags, 8 digit hex, markers hidden in
longer words). Reports per check and per delivery accuracy.

E2 Negotiation sweep. Buyer ceiling and seller floor grid crossed with
four concession rates. Reports agreement rate where a zone exists,
correct walk aways where it does not, rounds used, and where the
settled price lands inside the zone.

E3 Settlement oracle. Full deals in demo mode across scenarios and
delivery paths, each compared against the outcome the rules promise:
final state, payment and bond status, reputation deltas.

E4 Live sandbox evidence. The four deals actually settled on the
PayPal sandbox on 2026-10-22, with their transaction IDs, recorded
here as the systems validation table.

Run with: .venv/bin/python experiments/run_experiments.py
Writes experiments/results.json and prints the headline numbers.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pact.negotiation as negotiation  # noqa: E402
from pact.money import dollars, to_cents  # noqa: E402
from pact.negotiation import run_negotiation  # noqa: E402
from pact.scenarios import SCENARIO_BY_ID, build_delivery, _pad_words  # noqa: E402
from pact.store import new_deal  # noqa: E402
from pact.verifier import evaluate_check, verify_delivery  # noqa: E402

OUT = Path(__file__).resolve().parent / "results.json"

# A wide pool of varied padding sentences for constructed deliveries.
# It avoids every scenario needle, marker, hashtag, and hex pattern on
# purpose, so padding can never satisfy or break another check.
PAD_POOL = [
    "The work follows the brief the buyer approved before the deal was signed.",
    "Every section was drafted for this client and checked against the notes twice.",
    "The tone stays plain and direct from the opening line to the close.",
    "Nothing here is copied from a template or reused from an older job.",
    "A first time reader should grasp the offer within a few seconds.",
    "The structure follows the order a real customer thinks in, step by step.",
    "Short sentences carry the main points so the page stays easy to scan.",
    "The closing part answers the strongest objection a buyer usually raises.",
    "Care was taken to keep the wording free of jargon and filler phrases.",
    "Each paragraph earns its place and nothing decorative was left in.",
    "The draft was read aloud once to catch lines that sounded stiff.",
    "Facts in this piece come from the material the buyer supplied.",
    "Where a number appears, it matches the figure in the buyer notes.",
    "The piece is ready to use as delivered, with no further edits needed.",
    "If the buyer wants a shorter version later, the structure supports it.",
    "The opening promises only what the rest of the piece can back up.",
    "Transitions were smoothed so the reading never stops and restarts.",
    "The voice matches the samples the buyer pointed to at the start.",
    "No claim in the text depends on a trend that will date quickly.",
    "The layout leaves room for the work to grow in a later round.",
    "Details were favored over general statements wherever the two competed.",
    "The final pass removed repeats and tightened every loose sentence.",
    "A skeptical reader was the test: each line had to survive one.",
    "The result is calm, clear, and built for the audience named in the brief.",
]


def _pad_varied(text, target):
    i = 0
    while len(text.split()) < target:
        text += " " + PAD_POOL[i % len(PAD_POOL)]
        i += 1
    return text


async def settle(scenario_id, buyer_max=None, seller_floor=None):
    scen = SCENARIO_BY_ID[scenario_id]
    deal = new_deal(
        scen,
        # new_deal takes integer cents (queue item V); parse once here.
        to_cents(buyer_max if buyer_max is not None
                 else scen["default_buyer_max"]),
        to_cents(seller_floor if seller_floor is not None
                 else scen["default_seller_floor"]),
        20.0,
    )
    await run_negotiation(deal, scen)
    return deal


def build_text(spec, violate=None, extra_words=0):
    """Build a delivery from the settled spec, check by check.

    Ground truth is known by construction: every check passes, except
    the one named by violate, which is built one unit short (or with
    its needle omitted). Word padding is added last so the min_words
    check is exactly controlled unless it is the violated one.
    """
    parts = []
    words_target = None
    words_violate = False
    for chk in spec["acceptance_checks"]:
        kind = chk["kind"]
        bad = violate == chk["id"]
        if kind == "min_items":
            n = int(chk["value"]) - 1 if bad else int(chk["value"])
            for j in range(n):
                parts.append(f"{chk['marker']}{j + 1}: present and accounted for.")
        elif kind == "min_hex":
            n = int(chk["value"]) - 1 if bad else int(chk["value"])
            codes = ["#A1B2C3", "#D4E5F6", "#123ABC", "#F0E1D2",
                     "#0A0B0C", "#998877", "#345612"]
            for j in range(n):
                parts.append(f"Color {j + 1} is {codes[j % len(codes)]}.")
        elif kind == "min_hashtags":
            n = int(chk["value"]) - 1 if bad else int(chk["value"])
            for j in range(n):
                parts.append(f"#Update{j + 1}")
        elif kind == "contains":
            if not bad:
                parts.append(f"Section: {chk['value']}.")
        elif kind == "min_words":
            words_target = int(chk["value"]) + (0 if not bad else -1)
            words_violate = bad
    text = " ".join(parts)
    if words_target is not None:
        # Pad with a wide pool of varied sentences, so the padding
        # reads like real prose and the anti stuffing screen in the
        # verifier sees a fair text. A narrow rotation or a bare word
        # pad is degenerate, and the screen now flags it, correctly.
        text = _pad_varied(text, words_target)
        if words_violate and len(text.split()) > words_target:
            # The violating case must land exactly one word short.
            text = " ".join(text.split()[:words_target])
    if extra_words:
        text += " " + " ".join(["extra"] * extra_words)
    return text


async def e1_verifier_accuracy():
    cases = []  # (spec, text, {check_id: expected_pass})
    for scen_id in ("logo_brand_kit", "landing_page_copy", "cheat_attempt",
                    "code_task", "research_brief", "amazon_listing"):
        deal = await settle(scen_id)
        spec = deal["spec"]
        ids = [c["id"] for c in spec["acceptance_checks"]]
        perfect = build_text(spec)
        cases.append((spec, perfect, {i: True for i in ids}))
        cases.append((spec, perfect + " A closing note.", {i: True for i in ids}))
        for cid in ids:
            truth = {i: True for i in ids}
            truth[cid] = False
            cases.append((spec, build_text(spec, violate=cid), truth))
        # The scenario's own deliveries, with their known ground truth.
        scen = SCENARIO_BY_ID[scen_id]
        poor = build_delivery(scen, spec, quality="poor")
        cases.append((spec, poor, {i: False for i in ids}))
        if scen["seller_behavior"] == "cheat":
            cheat_truth = {i: False for i in ids}
            cheat_truth["launch_named"] = True
            cases.append((spec, build_delivery(scen, spec), cheat_truth))
            cases.append((spec, build_delivery(scen, spec, revision=True),
                          cheat_truth))
        else:
            honest = build_delivery(scen, spec)
            cases.append((spec, honest, {i: True for i in ids}))

    # Named trap cases on a hashtag check and a hex check.
    tag_check = {"id": "t", "label": "tags", "kind": "min_hashtags", "value": 2}
    hex_check = {"id": "h", "label": "hex", "kind": "min_hex", "value": 1}
    traps = [
        (tag_check, "Colors #AABBCC and #123456 only", False),
        (tag_check, "Real tags #LaunchDay and #NewBrand", True),
        (hex_check, "An 8 digit code #AABBCCDD", False),
        (hex_check, "A color #AABBCC", True),
    ]

    per_check = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    delivery_total = 0
    delivery_right = 0
    for spec, text, truth in cases:
        outcome = verify_delivery(spec, text)
        got = {r["check_id"]: r["passed"] for r in outcome["results"]}
        for cid, expected in truth.items():
            actual = got[cid]
            if actual and expected:
                per_check["tp"] += 1
            elif actual and not expected:
                per_check["fp"] += 1
            elif not actual and not expected:
                per_check["tn"] += 1
            else:
                per_check["fn"] += 1
        delivery_total += 1
        if got == truth:
            delivery_right += 1
    trap_right = 0
    for chk, text, expected in traps:
        if evaluate_check(chk, text)["passed"] == expected:
            trap_right += 1
        else:
            per_check["fp" if not expected else "fn"] += 1
    total_checks = sum(per_check.values())
    return {
        "deliveries": delivery_total,
        "delivery_level_accuracy": delivery_right / delivery_total,
        "checks_judged": total_checks,
        "confusion": per_check,
        "check_level_accuracy": (per_check["tp"] + per_check["tn"]) / total_checks,
        "trap_cases": len(traps),
        "trap_cases_right": trap_right,
    }


async def e2_negotiation_sweep():
    scen = SCENARIO_BY_ID["logo_brand_kit"]
    ceilings = [200, 250, 300, 350, 400, 450, 500]
    floors = [100, 150, 200, 250, 300, 350, 400]
    rates = [0.2, 0.35, 0.45, 0.6]
    rows = []
    original = negotiation.CONCESSION
    try:
        for rate in rates:
            negotiation.CONCESSION = rate
            for ceiling in ceilings:
                for floor in floors:
                    deal = new_deal(scen, to_cents(ceiling), to_cents(floor),
                                    20.0)
                    await run_negotiation(deal, scen)
                    zone = floor <= ceiling
                    agreed = deal["state"] == "agreed"
                    pos = None
                    if agreed and ceiling > floor:
                        # Ratio is unit-free: cents cancel exactly.
                        pos = ((deal["spec"]["price"] - to_cents(floor))
                               / (to_cents(ceiling) - to_cents(floor)))
                    rows.append({
                        "rate": rate, "ceiling": ceiling, "floor": floor,
                        "zone_exists": zone, "agreed": agreed,
                        "price_moves": deal["negotiation_rounds"],
                        "price": (dollars(deal["spec"]["price"])
                                  if agreed else None),
                        "price_position": pos,
                    })
    finally:
        negotiation.CONCESSION = original
    zone_rows = [r for r in rows if r["zone_exists"]]
    no_zone = [r for r in rows if not r["zone_exists"]]
    positions = [r["price_position"] for r in zone_rows
                 if r["price_position"] is not None]
    return {
        "runs": len(rows),
        "agreement_rate_in_zone": sum(r["agreed"] for r in zone_rows) / len(zone_rows),
        "walk_away_correct_rate": sum(not r["agreed"] for r in no_zone) / len(no_zone),
        "mean_price_moves_in_zone": sum(r["price_moves"] for r in zone_rows) / len(zone_rows),
        "mean_price_position": sum(positions) / len(positions),
        "by_rate": {
            str(rate): {
                "agreement_rate_in_zone": (
                    sum(r["agreed"] for r in zone_rows if r["rate"] == rate)
                    / max(1, sum(1 for r in zone_rows if r["rate"] == rate))),
                "mean_price_moves": (
                    sum(r["price_moves"] for r in zone_rows if r["rate"] == rate)
                    / max(1, sum(1 for r in zone_rows if r["rate"] == rate))),
            } for rate in rates
        },
    }


def e3_settlement_oracle():
    import re

    from fastapi.testclient import TestClient
    from pact.main import app
    from pact.store import AGENTS

    client = TestClient(app)

    # Demo client token store (queue item W): state-changing deal
    # endpoints require the per-deal role token in the X-Deal-Token
    # header. The create response carries both tokens, so this helper
    # remembers them per deal id and attaches the right one, the way a
    # real client would. Deliver acts as the seller; everything else
    # here acts as the buyer.
    deal_tokens = {}

    def post(path, body=None):
        m = re.match(r"^/api/deals/([^/]+)/", path)
        headers = None
        if m:
            role = ("seller" if path.rstrip("/").endswith("/deliver")
                    else "buyer")
            tok = deal_tokens.get(m.group(1), {}).get(role)
            if tok:
                headers = {"X-Deal-Token": tok}
        resp = client.post(path, json=body or {}, headers=headers)
        assert resp.status_code == 200, f"POST {path} -> {resp.status_code}: {resp.text}"
        data = resp.json()
        if isinstance(data, dict) and data.get("id") and data.get("buyer_token"):
            deal_tokens[data["id"]] = {
                "buyer": data.get("buyer_token"),
                "seller": data.get("seller_token"),
            }
        return data

    def rep(agent_id):
        return next(a["reputation"] for a in client.get("/api/agents").json()
                    if a["id"] == agent_id)

    # path name, scenario, deliveries (quality list), expected outcome
    # Buyer delta on a refund is +1 by design ("made whole" credit in
    # main.py), and reputation is clamped at zero in the store, so each
    # path resets reputations first to stay independent.
    paths = [
        ("logo honest", "logo_brand_kit", ["auto"],
         ("released", "released", "returned", 6, 3)),
        ("landing honest", "landing_page_copy", ["auto"],
         ("released", "released", "returned", 6, 3)),
        ("code task honest", "code_task", ["auto"],
         ("released", "released", "returned", 6, 3)),
        ("research brief honest", "research_brief", ["auto"],
         ("released", "released", "returned", 6, 3)),
        ("listing honest", "amazon_listing", ["auto"],
         ("released", "released", "returned", 6, 3)),
        ("logo poor", "logo_brand_kit", ["poor"],
         ("refunded", "refunded", "slashed", -32, 1)),
        ("landing poor", "landing_page_copy", ["poor"],
         ("refunded", "refunded", "slashed", -32, 1)),
        ("cheat recycled twice", "cheat_attempt", ["auto", "auto"],
         ("refunded", "refunded", "slashed", -35, 1)),
        ("cheat poor", "cheat_attempt", ["poor"],
         ("refunded", "refunded", "slashed", -32, 1)),
    ]
    initial_rep = {aid: a["reputation"] for aid, a in AGENTS.items()}
    results = []
    for name, scen_id, qualities, expected in paths:
        for aid, value in initial_rep.items():
            AGENTS[aid]["reputation"] = value
        deal = post("/api/deals", {"scenario_id": scen_id})
        seller = deal["seller_agent_id"]
        buyer = deal["buyer_agent_id"]
        s_before, b_before = rep(seller), rep(buyer)
        deal = post(f"/api/deals/{deal['id']}/negotiate/run")
        deal = post(f"/api/deals/{deal['id']}/pay")
        for q in qualities:
            deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": q})
            deal = post(f"/api/deals/{deal['id']}/verify")
        got = (deal["state"], deal["payment"]["status"], deal["bond"]["status"],
               rep(seller) - s_before, rep(buyer) - b_before)
        results.append({"path": name, "expected": expected, "got": got,
                        "match": tuple(expected) == got,
                        "ledger_events": len(deal["ledger"])})
    # Walk away path: no agreement, no money, no reputation change.
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "buyer_max": 10, "seller_floor": 900})
    deal = post(f"/api/deals/{deal['id']}/negotiate/run")
    results.append({"path": "walk away", "expected": ("failed", "not_started", "not_posted"),
                    "got": (deal["state"], deal["payment"]["status"], deal["bond"]["status"]),
                    "match": deal["state"] == "failed"
                    and deal["payment"]["status"] == "not_started",
                    "ledger_events": len(deal["ledger"])})
    return {
        "paths": len(results),
        "paths_matching_oracle": sum(1 for r in results if r["match"]),
        "detail": results,
        "total_ledger_events": sum(r["ledger_events"] for r in results),
    }


def e4_live_evidence():
    """The four deals settled on the PayPal sandbox on 2026-10-22.

    Static record of live runs, kept here so the paper's systems
    validation table has one source. IDs are PayPal sandbox object IDs.
    """
    return {
        "date": "2026-10-22",
        "environment": "PayPal sandbox, api-m.sandbox.paypal.com",
        "deals": [
            {"deal": "deal-0001", "scenario": "logo_brand_kit", "price": 222.17,
             "bond": 44.43, "outcome": "released", "checks": "5/5",
             "payment_capture": "2XX57477S7535341X",
             "bond_capture": "76U34250RE4380745",
             "payout": "DZNF5GE6AEUHN", "bond_return_payout": "Y4BT2Q3N8QR7J",
             "refund": None},
            {"deal": "deal-0002", "scenario": "landing_page_copy", "price": 324.21,
             "bond": 64.84, "outcome": "released", "checks": "5/5",
             "payment_capture": "5V6374204C639882V",
             "bond_capture": "0FJ792206C854335V",
             "payout": "A2EXK2WL4D4BG", "bond_return_payout": "L35MAUZEMNY92",
             "refund": None},
            {"deal": "deal-0003", "scenario": "logo_brand_kit, poor delivery",
             "price": 222.17, "bond": 44.43, "outcome": "refunded, bond slashed",
             "checks": "0/5",
             "payment_capture": "0X9062287L385133Y",
             "bond_capture": "3AP59378SU264272M",
             "payout": None, "bond_return_payout": None,
             "refund": "02S348440D980433R", "slash_payout": "PWMV585KHNEM6"},
            {"deal": "deal-0004", "scenario": "cheat_attempt",
             "price": 180.96, "bond": 36.19, "outcome": "refunded, bond slashed",
             "checks": "1/5 then 1/5",
             "payment_capture": "60E66083JP1219234",
             "bond_capture": "4P1624176C9319628",
             "payout": None, "bond_return_payout": None,
             "refund": "9VH98649B6022315A", "slash_payout": "X3BT5KNKEF8CL"},
        ],
    }


async def main():
    results = {
        "E1_verifier_accuracy": await e1_verifier_accuracy(),
        "E2_negotiation_sweep": await e2_negotiation_sweep(),
        "E3_settlement_oracle": e3_settlement_oracle(),
        "E4_live_sandbox_evidence": e4_live_evidence(),
    }
    OUT.write_text(json.dumps(results, indent=1))
    e1, e2, e3 = (results["E1_verifier_accuracy"], results["E2_negotiation_sweep"],
                  results["E3_settlement_oracle"])
    print(f"E1 verifier: {e1['deliveries']} deliveries, "
          f"{e1['checks_judged']} checks judged, "
          f"check accuracy {e1['check_level_accuracy']:.4f}, "
          f"delivery accuracy {e1['delivery_level_accuracy']:.4f}, "
          f"traps {e1['trap_cases_right']}/{e1['trap_cases']}")
    print(f"E2 negotiation: {e2['runs']} runs, "
          f"agreement in zone {e2['agreement_rate_in_zone']:.4f}, "
          f"walk away correct {e2['walk_away_correct_rate']:.4f}, "
          f"mean price position {e2['mean_price_position']:.4f}")
    print(f"E3 settlement: {e3['paths_matching_oracle']}/{e3['paths']} "
          f"paths match the oracle")
    print(f"E4 live: 4 deals settled on the PayPal sandbox 2026-10-22")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

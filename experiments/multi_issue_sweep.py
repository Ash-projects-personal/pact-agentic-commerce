"""E2 multi-issue sweep (queue item S).

The E2 grid from experiments/run_experiments.py, run with
multi_issue=True: price plus delivery window, revision rounds, and bond
percent negotiated on best-trade-ratio moves. The frozen single-issue
sweep in experiments/results.json stays the headline; this file is the
multi-issue evidence.

Each grid cell also runs the single-issue flow, so the destabilization
check is exact: the terms phase runs after the price is locked and must
never change whether a deal agrees or walks away. If the agreement
match rate is not 1.0, multi-issue ships as an experiment only.

Run with: .venv/bin/python experiments/multi_issue_sweep.py
Writes experiments/results_multi_issue.json and prints the headline numbers.
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
from pact.negotiation import run_negotiation  # noqa: E402
from pact.scenarios import SCENARIO_BY_ID  # noqa: E402
from pact.money import dollars, pct_of, to_cents  # noqa: E402
from pact.store import new_deal  # noqa: E402

OUT = Path(__file__).resolve().parent / "results_multi_issue.json"


async def sweep():
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
                    zone = floor <= ceiling
                    # Multi-issue run.
                    deal_m = new_deal(scen, to_cents(ceiling),
                                      to_cents(floor), 20.0,
                                      multi_issue=True)
                    await run_negotiation(deal_m, scen, multi_issue=True)
                    # Single-issue twin for the destabilization check.
                    deal_s = new_deal(scen, to_cents(ceiling),
                                      to_cents(floor), 20.0)
                    await run_negotiation(deal_s, scen)
                    agreed_m = deal_m["state"] == "agreed"
                    agreed_s = deal_s["state"] == "agreed"
                    row = {
                        "rate": rate, "ceiling": ceiling, "floor": floor,
                        "zone_exists": zone,
                        "agreed_multi": agreed_m,
                        "agreed_single": agreed_s,
                        "agreement_match": agreed_m == agreed_s,
                        "price_moves": deal_m["negotiation_rounds"],
                        "price": (dollars(deal_m["spec"]["price"])
                                  if agreed_m else None),
                        "terms": deal_m["terms"] if agreed_m else None,
                        "terms_moves": deal_m.get("terms_moves", 0)
                        if agreed_m else None,
                        "contract_hash": deal_m.get("contract_hash")
                        if agreed_m else None,
                    }
                    if agreed_m:
                        row["bond_amount"] = dollars(
                            deal_m["spec"]["bond_amount"])
                        # The bond amount must be the negotiated percent of
                        # the price: this is what the money plumbing enforces.
                        # Compared in integer cents, exactly.
                        expect_c = pct_of(deal_m["spec"]["price"],
                                          deal_m["terms"]["bond_percent"])
                        row["bond_consistent"] = (
                            deal_m["spec"]["bond_amount"] == expect_c)
                        cap = next((e for e in deal_m["ledger"]
                                    if e.get("event_type") == "terms_agreed"),
                                   None)
                        row["cap_hit"] = (cap["data"]["cap_hit"]
                                          if cap else None)
                    rows.append(row)
    finally:
        negotiation.CONCESSION = original

    zone_rows = [r for r in rows if r["zone_exists"]]
    no_zone = [r for r in rows if not r["zone_exists"]]
    agreed = [r for r in zone_rows if r["agreed_multi"]]
    terms = [r["terms"] for r in agreed]
    return {
        "mode": "multi-issue",
        "scenario": "logo_brand_kit",
        "runs": len(rows),
        "agreement_rate_in_zone": sum(r["agreed_multi"] for r in zone_rows)
        / len(zone_rows),
        "agreement_match_vs_single_issue":
            sum(r["agreement_match"] for r in rows) / len(rows),
        "walk_away_correct_rate": sum(not r["agreed_multi"]
                                      for r in no_zone) / len(no_zone),
        "mean_price_moves_in_zone": sum(r["price_moves"] for r in zone_rows)
        / len(zone_rows),
        "mean_terms_moves_in_zone": sum(r["terms_moves"] for r in agreed)
        / max(1, len(agreed)),
        "bond_consistent_rate": sum(r.get("bond_consistent", False)
                                    for r in agreed) / max(1, len(agreed)),
        "cap_hit_rate": sum(1 for r in agreed if r.get("cap_hit"))
        / max(1, len(agreed)),
        "mean_settled_terms": {
            issue: sum(t[issue] for t in terms) / max(1, len(terms))
            for issue in ("delivery_days", "revision_rounds",
                          "bond_percent")
        },
        "settled_terms_ranges": {
            issue: {"min": min(t[issue] for t in terms),
                    "max": max(t[issue] for t in terms)}
            for issue in ("delivery_days", "revision_rounds",
                          "bond_percent")
        } if terms else {},
        "note": ("The terms phase runs after the price is locked and cannot "
                 "undo a price agreement: agreement_match_vs_single_issue "
                 "must be 1.0. The frozen single-issue E2 sweep in "
                 "results.json stays the headline until this file exists."),
    }


async def main():
    results = await sweep()
    OUT.write_text(json.dumps(results, indent=2))
    print(f"Multi-issue sweep: {results['runs']} runs, "
          f"agreement in zone {results['agreement_rate_in_zone']:.4f}, "
          f"match vs single {results['agreement_match_vs_single_issue']:.4f}, "
          f"walk away correct {results['walk_away_correct_rate']:.4f}, "
          f"bond consistent {results['bond_consistent_rate']:.4f}")
    print("mean settled terms:", results["mean_settled_terms"])
    print("saved to", OUT)


if __name__ == "__main__":
    asyncio.run(main())

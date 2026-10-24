"""Item V: prove the property-test check count delta (4936 -> 4935) is a
negotiation hairline, not a regression.

Replicates the property test's deterministic RNG draws (seed 20261023),
runs the OLD float price-phase math and the NEW integer-cent engine on
each case's bounds, and reports any move-count differences. A move-count
difference changes the ledger event count, which changes the per-event
check count in assert_ledger_integrity by the same amount.
"""

import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pact.money import to_cents
from pact.negotiation import run_negotiation
from pact.scenarios import SCENARIO_BY_ID
from pact.store import new_deal

SEED = 20261023
MAX_PRICE_MOVES = 26
CONCESSION = 0.45


def old_price_moves(buyer_max, floor):
    """Old float price phase; returns the number of price moves."""
    offer = round(buyer_max * 0.60, 2)
    ask = round(floor * 1.35, 2)
    moves = 2
    buyer_pinned = False
    seller_pinned = False
    while moves < MAX_PRICE_MOVES and not (buyer_pinned and seller_pinned):
        gap = round(ask - offer, 2)
        threshold = max(5.0, round(0.05 * ask, 2))
        if gap <= threshold and floor <= buyer_max:
            break
        if not buyer_pinned:
            new_offer = min(buyer_max, round(offer + gap * CONCESSION, 2))
            if new_offer <= offer:
                buyer_pinned = True
            else:
                offer = new_offer
                moves += 1
                gap = round(ask - offer, 2)
                if gap <= threshold and floor <= buyer_max:
                    break
        if moves >= MAX_PRICE_MOVES:
            break
        if not seller_pinned:
            new_ask = max(floor, round(ask - gap * CONCESSION, 2))
            if new_ask >= ask:
                seller_pinned = True
            else:
                ask = new_ask
                moves += 1
    return moves


async def main():
    rng = random.Random(SEED)
    rng.randint(0, 10 ** 9)  # FIRST_DRAW
    scenario_ids = [
        "logo_brand_kit", "landing_page_copy", "cheat_attempt", "code_task",
        "research_brief", "amazon_listing", "data_labeling_batch",
        "podcast_edit_package", "newsletter_issue", "product_photo_set",
        "book_cover_design", "api_integration_task",
        "spreadsheet_cleanup_report",
    ]
    qualities = ["auto", "poor", "weak", "cheat"]
    diffs = []
    for case in range(342):
        scenario = rng.choice(scenario_ids)
        floor = round(rng.uniform(6.0, 400.0), 2)
        if rng.random() < 0.15:
            buyer_max = round(max(1.0, floor - rng.uniform(1.0, 60.0)), 2)
        else:
            buyer_max = round(floor + rng.uniform(0.0, floor * 0.6 + 20.0), 2)
        rng.uniform(10.0, 30.0)  # bond_percent
        rng.random()  # multi_issue
        rng.choice(qualities)  # quality
        old_moves = old_price_moves(buyer_max, floor)
        scen = SCENARIO_BY_ID[scenario]
        deal = new_deal(scen, to_cents(buyer_max), to_cents(floor), 20.0)
        await run_negotiation(deal, scen)
        new_moves = deal["negotiation_rounds"] and sum(
            1 for m in deal["moves"] if m["kind"] == "price")
        # negotiation_rounds counts loop rounds; price moves are the
        # "price"-kind moves (2 opening + concessions).
        if old_moves != new_moves:
            diffs.append((case, scenario, buyer_max, floor,
                          old_moves, new_moves,
                          deal["state"]))
    print(f"342 cases replicated; move-count diffs: {len(diffs)}")
    for d in diffs:
        print(f"  case {d[0]} {d[1]} max={d[2]} floor={d[3]}: "
              f"old moves={d[4]} new moves={d[5]} state={d[6]}")
    if not diffs:
        print("no move-count differences found")


if __name__ == "__main__":
    asyncio.run(main())

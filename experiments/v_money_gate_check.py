"""Item V gate check: replicate the OLD float price-phase math exactly and
compare every E2 settled price against the NEW integer-cent engine.

The old formulas (from pact/negotiation.py before the migration):
  offer = round(buyer_max * 0.60, 2); ask = round(floor * 1.35, 2)
  gap = round(ask - offer, 2); threshold = max(5.0, round(0.05 * ask, 2))
  buyer:  new_offer = min(buyer_max, round(offer + gap * CONCESSION, 2))
  seller: new_ask   = max(floor,     round(ask - gap * CONCESSION, 2))
  settle: mid = round((offer + ask) / 2, 2); min(max(mid, floor), buyer_max)
Any settled price that moves by even one cent is a regression.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pact.negotiation as negotiation
from pact.money import to_cents
from pact.negotiation import run_negotiation
from pact.scenarios import SCENARIO_BY_ID
from pact.store import new_deal

MAX_PRICE_MOVES = 26


def old_settle_price(buyer_max, floor, concession):
    offer = round(buyer_max * 0.60, 2)
    ask = round(floor * 1.35, 2)
    settled = None
    price_moves = 2
    buyer_pinned = False
    seller_pinned = False
    while price_moves < MAX_PRICE_MOVES and not (buyer_pinned and seller_pinned):
        gap = round(ask - offer, 2)
        threshold = max(5.0, round(0.05 * ask, 2))
        if gap <= threshold and floor <= buyer_max:
            settled = min(max(round((offer + ask) / 2, 2), floor), buyer_max)
            break
        if not buyer_pinned:
            step = gap * concession
            new_offer = min(buyer_max, round(offer + step, 2))
            if new_offer <= offer:
                buyer_pinned = True
            else:
                offer = new_offer
                price_moves += 1
                gap = round(ask - offer, 2)
                if gap <= threshold and floor <= buyer_max:
                    settled = min(max(round((offer + ask) / 2, 2), floor),
                                    buyer_max)
                    break
        if price_moves >= MAX_PRICE_MOVES:
            break
        if not seller_pinned:
            step = gap * concession
            new_ask = max(floor, round(ask - step, 2))
            if new_ask >= ask:
                seller_pinned = True
            else:
                ask = new_ask
                price_moves += 1
    if settled is None and floor <= buyer_max:
        settled = min(max(round((offer + ask) / 2, 2), floor), buyer_max)
    return settled


async def main():
    scen = SCENARIO_BY_ID["logo_brand_kit"]
    ceilings = [200, 250, 300, 350, 400, 450, 500]
    floors = [100, 150, 200, 250, 300, 350, 400]
    rates = [0.2, 0.35, 0.45, 0.6]
    mismatches = []
    total = 0
    for rate in rates:
        for ceiling in ceilings:
            for floor in floors:
                total += 1
                old_price = old_settle_price(float(ceiling), float(floor), rate)
                deal = new_deal(scen, to_cents(ceiling), to_cents(floor), 20.0)
                orig = negotiation.CONCESSION
                negotiation.CONCESSION = rate
                try:
                    await run_negotiation(deal, scen)
                finally:
                    negotiation.CONCESSION = orig
                if old_price is None:
                    if deal["state"] == "agreed":
                        mismatches.append((rate, ceiling, floor, None,
                                           deal["spec"]["price"]))
                    continue
                if deal["state"] != "agreed":
                    mismatches.append((rate, ceiling, floor, old_price, None))
                    continue
                new_cents = deal["spec"]["price"]
                old_cents = to_cents(old_price)
                if new_cents != old_cents:
                    mismatches.append((rate, ceiling, floor, old_cents,
                                       new_cents))
    print(f"compared {total} E2 grid runs")
    if mismatches:
        print(f"MISMATCHES: {len(mismatches)}")
        for m in mismatches[:20]:
            print(f"  rate={m[0]} ceiling={m[1]} floor={m[2]}: "
                  f"old={m[3]}c new={m[4]}c")
        sys.exit(1)
    print("EVERY SETTLED PRICE IDENTICAL TO THE CENT. Gate holds.")


if __name__ == "__main__":
    asyncio.run(main())

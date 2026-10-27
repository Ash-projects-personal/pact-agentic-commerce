"""Real market cases: Pact deals shaped and priced from live listings.

The deal shapes and price bands come from public marketplace data
gathered 2026-10-22 (see research/real-deal-data.md in this repo for
the sources): Fiverr and Upwork listing prices for logo kits, listing
copy, social packs, Python fixes, and research briefs, plus the
protection terms those platforms actually offer. Five later cases
use fresh listing sweeps: the podcast edit package (Part 17) and
the data labeling batch (Part 18) from 2026-10-24, the email
newsletter issue (Part 19) from 2026-10-25, the book cover
design package (Part 20) from 2026-10-26, and the product
photography set (Part 22) from 2026-10-27.

Each case runs end to end in demo mode and records the negotiated
price, the bond, the check outcomes, and the settlement, next to what
the same dispute would cost on today's rails: Upwork binding
arbitration is $675 in total ($337.50 per party) and takes about 30
days; Fiverr takes 20 percent from the seller and lets its support
team judge; a plain PayPal payment excludes services from Purchase
Protection entirely.

The translation case is a verifier level limit case on purpose: it
shows a cheat that counting checks cannot catch, recorded as such.

Run with: .venv/bin/python experiments/real_cases.py
Writes experiments/real_cases_results.json.
"""

import json
import os
import sys
from pathlib import Path

for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = Path(__file__).resolve().parent / "real_cases_results.json"


def run_cases():
    import re

    from fastapi.testclient import TestClient
    from pact.main import app
    from pact.store import AGENTS, DEALS

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

    def run_deal(scenario_id, buyer_max=None, seller_floor=None,
                 qualities=("auto",), inject=None, multi_issue=False):
        body = {"scenario_id": scenario_id}
        if buyer_max is not None:
            body["buyer_max"] = buyer_max
        if seller_floor is not None:
            body["seller_floor"] = seller_floor
        if multi_issue:
            body["multi_issue"] = True
        deal = post("/api/deals", body)
        deal = post(f"/api/deals/{deal['id']}/negotiate/run")
        deal = post(f"/api/deals/{deal['id']}/pay")
        for i, q in enumerate(qualities):
            deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": q})
            if inject is not None and i == 0:
                DEALS[deal["id"]]["deliverable"]["content"] = inject
            deal = post(f"/api/deals/{deal['id']}/verify")
        return deal

    def summarize(case, market, deal, today, date=None):
        spec = deal["spec"]
        row = {
            "case": case,
            "market_reference": market,
            "negotiated_price": spec["price"],
            "bond": spec["bond_amount"],
            "checks": (f"{deal['verification']['passed_count']}/"
                       f"{deal['verification']['total_count']}"),
            "outcome": deal["state"],
            "payment_status": deal["payment"]["status"],
            "bond_status": deal["bond"]["status"],
            "seller_reputation": AGENTS[deal["seller_agent_id"]]["reputation"],
            "same_deal_today": today,
        }
        if date is not None:
            row["date"] = date
        return row

    cases = []

    deal = run_deal("amazon_listing")
    cases.append(summarize(
        "Amazon listing copy, honest seller",
        "Upwork catalog listings charge $40 to $120 per listing; common "
        "tiers $50, $80, $120 (research/real-deal-data.md, Part 1.7)",
        deal,
        "On Fiverr the seller loses 20 percent commission and waits about "
        "14 days to withdraw. A quality fight goes to a support queue. On "
        "a plain PayPal payment, services sit outside Purchase Protection."))

    partial = (
        "Title\nTrailPeak Bottle\n\n"
        "Bullet 1: Keeps drinks cold all day long.\n"
        "Bullet 2: Fits your car cup holder well.\n"
        "Bullet 3: Seals tight and never leaks.\n\n"
        "Description\nA good bottle for daily use at work or the gym.\n\n"
        "Search terms\nbottle steel gym"
    )
    deal = run_deal("amazon_listing", qualities=("auto", "poor"),
                    inject=partial)
    cases.append(summarize(
        "Amazon listing copy, under delivered then abandoned",
        "Same listing market as above. The seller delivered 3 of the "
        "agreed bullets, no keyword set, and a short description, then "
        "sent a thin draft again on the revision round.",
        deal,
        "On Upwork, a binding decision on this $80 job costs $675 in "
        "arbitration fees split between the parties, about 30 days. Most "
        "buyers write the money off instead."))

    deal = run_deal("cheat_attempt", buyer_max=190.0, seller_floor=110.0,
                    qualities=("auto", "auto"))
    cases.append(summarize(
        "Social pack, recycled copy cheat",
        "Upwork catalog: $150 for a 20 post pack; $250 to $650 tiers with "
        "hashtag research (Part 1.3)",
        deal,
        "The buyer argues with the seller and a support team over whether "
        "recycled posts count as delivery. The seller risks nothing but "
        "the refund itself."))

    deal = run_deal("logo_brand_kit", buyer_max=160.0, seller_floor=100.0)
    cases.append(summarize(
        "Logo and brand kit, honest studio",
        "Fiverr: standard logo packages $60 to $130; logo plus small "
        "brand kit $130 to $420 (Part 1.1)",
        deal,
        "Escrow on a marketplace, release on the buyer's word or after 14 "
        "days of silence, quality judged by the buyer alone."))

    deal = run_deal("code_task", buyer_max=70.0, seller_floor=40.0)
    cases.append(summarize(
        "Python script task at bug fix prices",
        "Fiverr Python bug fixing $5 to $95; Upwork catalog tiers $15, "
        "$50, $120 (Part 1.4)",
        deal,
        "Same escrow and support queue pattern, on a job worth less than "
        "one hour of a dispute specialist's time."))

    deal = run_deal("research_brief", buyer_max=120.0, seller_floor=60.0)
    cases.append(summarize(
        "Market research brief, honest shop",
        "Upwork catalog: $45, $85, $145 for summary research reports "
        "(Part 1.5)",
        deal,
        "A brief with no sources is a judgment call for a support agent. "
        "Here the source count is a contract check, so it is arithmetic."))

    # A weak first draft that passes some checks but not all: the
    # Competitors and Risks sections are present, but it cites only 3
    # sources, gives only 2 data points, and runs short. That earns the
    # one contractual revision round instead of an instant refund, and
    # the honest second delivery settles the deal.
    weak_first_draft = (
        "Market Brief: mid range espresso machines for home use\n\n"
        "Competitors\n"
        "Breville and DeLonghi dominate the home espresso shelf, with "
        "Breville winning on grinder integration and DeLonghi on price. "
        "Smaller brands compete on design and compact footprints.\n\n"
        "Risks\n"
        "Supply chain delays on heating elements could push prices up "
        "in the next quarter. Counterfeit pods remain a support burden "
        "for all three brands.\n\n"
        "Source 1: retailer category page with current prices\n"
        "Source 2: manufacturer spec sheet for the lead model\n"
        "Source 3: review aggregator scores for the top five\n\n"
        "Data point 1: average street price 349 dollars across trackers\n"
        "Data point 2: review volume up 18 percent year over year\n"
    )
    deal = run_deal("research_brief", buyer_max=100.0, seller_floor=50.0,
                    qualities=("auto", "auto"), inject=weak_first_draft)
    cases.append(summarize(
        "Market research brief, weak first draft rescued on revision",
        "Upwork catalog: $45, $85, $145 for summary research reports "
        "(Part 1.5). First delivery passed 2 of 5 checks, revision "
        "round honest.",
        deal,
        "On a marketplace a weak first draft goes back and forth in "
        "messages with no enforcement. Here the revision round is "
        "contractual: the second delivery is re-verified against the "
        "same frozen checks, and only then is the seller paid."))

    # The first procurement case: the deal is grounded in a real
    # Channel3 live API capture (Sony WH-1000XM5, 5 offers, $239.97 to
    # $336.99, median $298.00, captured 2026-10-22; shipped fixture,
    # ledger labels it as cached with its capture date). The seller
    # agent buys at the grounded lowest offer and files the report.
    deal = run_deal("procurement")
    cases.append(summarize(
        "Procurement: Sony WH-1000XM5, honest buyer and seller",
        "Channel3 live API capture 2026-10-22 (Part 1.9): 5 offers "
        "$239.97 to $336.99, median $298.00. Buyer ceiling at the "
        "median, seller floor at the lowest offer; the chosen offer's "
        "product, retailer, buy link, and a price ceiling became "
        "contract checks.",
        deal,
        "No bonded escrow exists today for an agent buying a physical "
        "product on your behalf: it pays first and you hope. Here "
        "overpaying fails verification and costs the seller its bond."))

    # The first multi-issue real case: a new scenario (podcast edit
    # package, honest seller) where the terms phase (queue item S)
    # negotiates price, delivery window, revision rounds, and bond
    # percent. The terms phase is price-grid independent, so it
    # settles at 12 days, 3 revision rounds, and a 23.54% bond on the
    # negotiated price. The honest delivery passes 5 of 5 checks and
    # the deal releases.
    deal = run_deal("podcast_edit_package", buyer_max=220.0,
                    seller_floor=80.0, multi_issue=True)
    cases.append(summarize(
        "Podcast edit package, multi-issue negotiated, honest editor",
        "Live listing sweep 2026-10-24 (Part 1.17): Upwork catalog "
        "tiers $66/$88/$120, $70/$105/$140 by episode length, "
        "$90/$140/$170 for edit plus show notes. Buyer max $220, "
        "seller floor $80. Price, delivery window, revision rounds, "
        "and bond percent all negotiated.",
        deal,
        "A podcast edit dispute over chapters or show notes today "
        "goes to a support queue with no written spec. Here the "
        "frozen spec counts the chapters, timestamps, and words, "
        "and the negotiated terms are written into the same frozen "
        "contract.",
        date="2026-10-24"))

    # The tenth case, and the second new scenario covered by a real
    # market case: a labeled batch of product titles, honest seller.
    # The checks count labeled rows, require the guide and the
    # distribution summary, count flagged ambiguous rows, and require
    # batch notes of a minimum length, so a batch of guessed labels
    # with no guide and no flags fails on its own terms.
    deal = run_deal("data_labeling_batch")
    cases.append(summarize(
        "Data labeling batch, honest labeler",
        "Live listing sweep 2026-10-24 (Part 1.18): Upwork "
        "annotation catalog tiers $10/$50/$100, $40/$100/$200, "
        "$70/$100/$150, $40/$100/$250, $35/$75/$140. Buyer max $90, "
        "seller floor $40, the scenario defaults.",
        deal,
        "A labeling dispute today is a support ticket over whether "
        "the labels were right, judged with no written guide in the "
        "record. Here the guide, the row count, the flagged rows, "
        "and the distribution summary are all contract checks, so "
        "the verdict is arithmetic.",
        date="2026-10-24"))

    # The eleventh case, and the third new scenario covered by a real
    # market case: one written newsletter issue (subject line, four
    # sections, calls to action, unsubscribe footer), honest seller.
    # The checks count sections and calls to action, require the
    # subject line and the unsubscribe line, and require a minimum
    # word count, so a two-paragraph generic blurb fails on its own
    # terms.
    deal = run_deal("newsletter_issue")
    cases.append(summarize(
        "Email newsletter issue, honest writer",
        "Live listing sweep 2026-10-25 (Part 1.19): Upwork "
        "newsletter catalog tiers $10/$30/$40 for single emails, "
        "$50/$150/$300 for a designed newsletter with copy, "
        "$190/$320/$635 for a curated weekly newsletter. Buyer max "
        "$160, seller floor $70, the scenario defaults.",
        deal,
        "A newsletter dispute today is a support ticket over whether "
        "the copy was usable, judged with no written spec in the "
        "record. Here the subject line, the section count, the calls "
        "to action, the unsubscribe line, and the length are all "
        "contract checks, so the verdict is arithmetic.",
        date="2026-10-25"))

    # The twelfth case, and the fourth new scenario covered by a real
    # market case: a book cover design package (concept directions,
    # spine design, back cover layout, color palette, typography
    # pairing), honest seller. The checks count the concept
    # directions, require the spine and back cover sections, and
    # require the palette and typography sections, so a single JPG
    # sold as a full kit fails on its own terms.
    deal = run_deal("book_cover_design")
    cases.append(summarize(
        "Book cover design package, honest designer",
        "Live listing sweep 2026-10-26 (Part 20): Upwork "
        "book cover catalog tiers $5/$10/$15, $40/$60/$80, "
        "$65/$85/$95, $10/$20/$28, and $400/$700/$1,200; Fiverr "
        "gigs from $10 to $20 with paid reviews at $50 and "
        "$200 to $400. Buyer max $140, seller floor $50, the "
        "scenario defaults.",
        deal,
        "A book cover dispute today is a support ticket over whether "
        "the cover was usable, judged with no written spec in the "
        "record. Here the concept count, the spine and back cover "
        "sections, the palette, and the typography pairing are all "
        "contract checks, so the verdict is arithmetic.",
        date="2026-10-26"))

    # The thirteenth case, and the fifth new scenario covered by a
    # real market case: a product photography set (shot manifest,
    # one hero shot, resolution and background per photo, retouch
    # notes, usage license), honest seller. The checks count the
    # listed photos, require the hero shot, the license, and the
    # retouch notes, so a folder of unedited phone snaps with no
    # manifest fails on its own terms.
    deal = run_deal("product_photo_set")
    cases.append(summarize(
        "Product photography set, honest photographer",
        "Live listing sweep 2026-10-27 (Part 22): Upwork "
        "product photography catalog tiers $55/$150/$250, "
        "$50/$120/$200, $125/$240/$450, $80/$200/$500, "
        "$5/$10/$30, $150/$300/$950, $60/$85/$110, and "
        "$95/$800/$1,450; Fiverr photo editing $5 to $100. "
        "Buyer max $220, seller floor $90, the scenario "
        "defaults.",
        deal,
        "A photography dispute today is a support ticket over "
        "whether the photos were usable, judged with no written "
        "spec in the record. Here the photo count, the hero shot, "
        "the license, and the retouch notes are all contract "
        "checks, so the verdict is arithmetic.",
        date="2026-10-27"))

    return cases


def translation_limit_case():
    """A cheat that counting cannot catch, recorded on purpose."""
    from pact.scenarios import build_delivery
    from pact.money import to_cents
    from pact.store import new_deal
    from pact.verifier import verify_delivery
    import asyncio

    from pact.negotiation import run_negotiation
    from pact.scenarios import SCENARIO_BY_ID

    async def settled_spec(sid):
        scen = SCENARIO_BY_ID[sid]
        deal = new_deal(scen, to_cents(scen["default_buyer_max"]),
                        to_cents(scen["default_seller_floor"]), 20.0)
        await run_negotiation(deal, scen)
        return scen, deal["spec"]

    async def build():
        parts = []
        for sid in ("research_brief", "amazon_listing", "landing_page_copy"):
            scen, spec = await settled_spec(sid)
            parts.append(build_delivery(scen, spec))
        return "\n".join(parts)

    source = asyncio.run(build())
    honest = " ".join(source.split()[:1150])

    def scramble(sentence):
        words = sentence.split()
        return " ".join(words[::2] + words[1::2])

    machine = ". ".join(scramble(s) for s in honest.split(". "))

    spec = {"acceptance_checks": [
        {"id": "length", "label": "Translated length", "kind": "min_words",
         "value": 1000, "unit": "words"},
        {"id": "term", "label": "Required term present", "kind": "contains",
         "value": "subscription", "unit": "term"},
    ]}
    out = {}
    for name, text in (("careful translation sample", honest),
                       ("word for word machine style sample", machine)):
        result = verify_delivery(spec, text)
        out[name] = {"words": len(text.split()),
                     "passed_all_checks": result["all_passed"]}
    return {
        "case": "Translation, 1,000 words at the $10 Fiverr tier",
        "market_reference": "Fiverr gig: $10 per 1,000 words (Part 1.8). "
                            "The standard cheat in this market is raw "
                            "machine output sold as manual translation. "
                            "The two samples here are built from the "
                            "same varied source text: one intact, one "
                            "with the word order inside every sentence "
                            "scrambled, which is what word for word "
                            "machine output does to a text.",
        "results": out,
        "finding": "Both samples pass every check, including the anti "
                   "stuffing screen: scrambled word order keeps natural "
                   "text statistics, because varied words in the wrong "
                   "order are still varied words. Counting proves length "
                   "and term presence; it cannot judge translation "
                   "quality. This is the honest limit of the rule based "
                   "verifier, and it is why the paper frames the checks "
                   "as proof of delivery shape, not proof of craft.",
    }


def main():
    cases = run_cases()
    limit = translation_limit_case()
    expected = {
        "Amazon listing copy, honest seller": "released",
        "Amazon listing copy, under delivered then abandoned": "refunded",
        "Social pack, recycled copy cheat": "refunded",
        "Logo and brand kit, honest studio": "released",
        "Python script task at bug fix prices": "released",
        "Market research brief, honest shop": "released",
        "Market research brief, weak first draft rescued on revision": "released",
        "Procurement: Sony WH-1000XM5, honest buyer and seller": "released",
        "Podcast edit package, multi-issue negotiated, honest editor": "released",
        "Data labeling batch, honest labeler": "released",
        "Email newsletter issue, honest writer": "released",
        "Book cover design package, honest designer": "released",
        "Product photography set, honest photographer": "released",
    }
    failures = []
    for row in cases:
        want = expected[row["case"]]
        mark = "ok" if row["outcome"] == want else "MISMATCH"
        if row["outcome"] != want:
            failures.append(row["case"])
        print(f"{mark} {row['case']}: price ${row['negotiated_price']}, "
              f"bond ${row['bond']}, checks {row['checks']}, "
              f"outcome {row['outcome']}")
    print(f"limit case: translation samples both pass = "
          f"{all(v['passed_all_checks'] for v in limit['results'].values())} "
          f"(expected, and reported as a limit)")
    OUT.write_text(json.dumps({"cases": cases, "limit_case": limit}, indent=1))
    print(f"Wrote {OUT}")
    if failures:
        print(f"FAILURES: {failures}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

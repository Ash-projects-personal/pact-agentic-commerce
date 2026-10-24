"""Channel3 procurement scenario tests.

Runs fully offline in demo mode: no PayPal credentials and no
CHANNEL3_API_KEY, so procurement grounding comes from the cached
Channel3 response shipped at pact/fixtures/. Every expected number
below is derived from that real captured response:

- The grounded product is "WH-1000XM5 Wireless Noise Canceling
  Headphones" with 5 offers: 239.97, 298.00, 298.00, 299.95, 336.99.
- Lowest 239.97 (skybygramophone.com), median 298.00, highest 336.99.
- Grounded buyer ceiling is the median, 298.00. Grounded seller floor
  is the lowest offer, 239.97.

Coverage:
1. Grounding math from the captured response.
2. Candidate checks built from the grounded offer.
3. The max_price verifier kind on honest and cheating reports.
4. End to end honest deal: grounded, negotiated, paid, delivered,
   verified, released.
5. End to end poor deal: refunded with the bond slashed.
6. The live client errors clearly when no API key is configured.

Run with: python tests/channel3_test.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Force demo mode and the cached Channel3 path before app modules load.
for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY",
            "PAYPAL_WEBHOOK_ID", "CHANNEL3_API_KEY"):
    os.environ.pop(var, None)

# Isolate persistence: the middleware writes the store to SQLite after
# every response, so point the test run at a throwaway database that
# never touches the real dev database at data/pact.db.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pact import channel3  # noqa: E402
from pact.main import app  # noqa: E402
from pact.verifier import evaluate_check  # noqa: E402

client = TestClient(app)

FAILURES = []

# Demo client token store (queue item W): state-changing deal endpoints
# require the per-deal role token in the X-Deal-Token header. The create
# response carries both tokens; they are remembered per deal id below.
_DEAL_TOKENS = {}


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'} {name} "
          f"{detail if not cond else ''}")
    if not cond:
        FAILURES.append(name)


def post(path, body=None):
    import re

    m = re.match(r"^/api/deals/([^/]+)/", path)
    headers = None
    if m:
        # Demo client token store (queue item W): state-changing deal
        # endpoints require the per-deal role token in the X-Deal-Token
        # header. The create response carries both tokens, so this
        # helper remembers them per deal id and attaches the right one,
        # the way a real client would. Deliver acts as the seller;
        # everything else here acts as the buyer.
        role = "seller" if path.rstrip("/").endswith("/deliver") else "buyer"
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


def test_grounding_math():
    print("TEST 1 grounding math from the captured Channel3 response")
    grounding = channel3.load_fixture_grounding()
    check("source is the labeled cache", grounding["source"] == "cached_fixture",
          grounding["source"])
    check("capture date recorded", grounding["captured_at"] == "2026-10-22",
          grounding["captured_at"])
    check("provider named", grounding["provider"] == "Channel3")
    check("grounded product title",
          grounding["product_title"] == "WH-1000XM5 Wireless Noise Canceling Headphones",
          grounding["product_title"])
    check("five offers for the grounded product", grounding["offer_count"] == 5,
          grounding["offer_count"])
    prices = [o["price"] for o in grounding["offers"]]
    check("offers sorted by price", prices == sorted(prices), prices)
    check("lowest price", grounding["lowest_price"] == 23997,
          grounding["lowest_price"])
    check("median price", grounding["median_price"] == 29800,
          grounding["median_price"])
    check("highest price", grounding["highest_price"] == 33699,
          grounding["highest_price"])
    check("buyer ceiling is the median", grounding["buyer_max"] == 29800,
          grounding["buyer_max"])
    check("seller floor is the lowest offer", grounding["seller_floor"] == 23997,
          grounding["seller_floor"])
    chosen = grounding["chosen_offer"]
    check("chosen offer is the lowest", chosen["price"] == 23997, chosen)
    check("chosen retailer", chosen["domain"] == "skybygramophone.com", chosen)
    check("chosen offer has a buy link", bool(chosen["url"]))
    check("all offers are USD with links",
          all(o["currency"] == "USD" and o["url"] and o["title"]
              for o in grounding["offers"]))


def test_candidate_checks():
    print("TEST 2 candidate checks built from the grounded offer")
    grounding = channel3.load_fixture_grounding()
    checks = {c["id"]: c for c in channel3.build_candidate_checks(grounding)}
    chosen = grounding["chosen_offer"]
    check("five checks built", len(checks) == 5, list(checks))
    check("title check is the exact grounded title",
          checks["product_title"]["kind"] == "contains"
          and checks["product_title"]["needle"] == chosen["title"],
          checks.get("product_title"))
    check("retailer check names the grounded retailer",
          checks["retailer_named"]["needle"] == chosen["retailer_name"],
          checks.get("retailer_named"))
    check("link check carries the buy link",
          checks["product_link"]["needle"] == chosen["url"],
          checks.get("product_link"))
    check("price ceiling check kind",
          checks["price_ceiling"]["kind"] == "max_price",
          checks.get("price_ceiling"))
    check("report length is a negotiated word check",
          checks["report_length"]["kind"] == "min_words"
          and checks["report_length"]["buyer_demand"] == 140
          and checks["report_length"]["seller_offer"] == 90,
          checks.get("report_length"))


def test_max_price_verifier():
    print("TEST 3 max_price verifier kind")
    ceiling = {"id": "price_ceiling", "label": "Purchase price ceiling",
               "kind": "max_price", "value": 26000, "unit": "USD"}
    ok = evaluate_check(ceiling, "Report. Price paid: 239.97 USD. Done.")
    check("price under ceiling passes", ok["passed"] is True
          and ok["measured"] == 239.97, ok)
    at = evaluate_check(ceiling, "Price paid: 260.00 USD")
    check("price at ceiling passes", at["passed"] is True, at)
    over = evaluate_check(ceiling, "Price paid: 319.99 USD")
    check("price over ceiling fails with measured value",
          over["passed"] is False and over["measured"] == 319.99, over)
    missing = evaluate_check(ceiling, "Bought the headphones. Receipt soon.")
    check("missing price line fails", missing["passed"] is False
          and missing["measured"] is None, missing)


def run_to_paid():
    deal = post("/api/deals", {"scenario_id": "procurement"})
    deal = post(f"/api/deals/{deal['id']}/negotiate/run")
    assert deal["state"] == "agreed", deal["state"]
    deal = post(f"/api/deals/{deal['id']}/pay")
    assert deal["state"] == "paid_held", deal["state"]
    return deal


def test_honest_deal():
    print("TEST 4 honest procurement deal settles released")
    deal = post("/api/deals", {"scenario_id": "procurement"})
    market = deal.get("market") or {}
    check("deal carries the grounding", market.get("provider") == "Channel3",
          list(deal.keys()))
    check("grounding labeled cached", market.get("source") == "cached_fixture",
          market.get("source"))
    check("deal ceiling grounded at the median", deal["buyer_max"] == 298.00,
          deal["buyer_max"])
    check("deal floor grounded at the lowest offer",
          deal["seller_floor"] == 239.97, deal["seller_floor"])
    check("offers visible in the deal view",
          len((market.get("offers") or [])) == 5
          and all({"title", "retailer", "price"} <= set(o)
                  for o in market["offers"]),
          market.get("offers"))
    events = [e for e in deal["ledger"] if e["event_type"] == "market_grounded"]
    check("ledger names the grounding", len(events) == 1, deal["ledger"])
    if events:
        msg = events[0]["message"]
        check("ledger event names Channel3 and the cache date",
              "Channel3" in msg and "cached" in msg and "2026-10-22" in msg,
              msg)
    deal = post(f"/api/deals/{deal['id']}/negotiate/run")
    check("negotiation agrees", deal["state"] == "agreed", deal["state"])
    spec = deal["spec"]
    settled = {c["id"]: c for c in spec["acceptance_checks"]}
    check("spec carries the grounding evidence",
          (spec.get("grounding") or {}).get("provider") == "Channel3",
          spec.get("grounding"))
    check("price ceiling settled at the agreed price",
          settled["price_ceiling"]["kind"] == "max_price"
          and settled["price_ceiling"]["value"] == spec["price"],
          settled.get("price_ceiling"))
    check("agreed price inside the grounded zone",
          deal["seller_floor"] <= spec["price"] <= deal["buyer_max"],
          spec["price"])
    check("grounded lowest offer fits under the agreed price",
          market["lowest_price"] <= spec["price"], spec["price"])
    deal = post(f"/api/deals/{deal['id']}/pay")
    check("paid and held", deal["state"] == "paid_held", deal["state"])
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    content = deal["deliverable"]["content"]
    check("report states the grounded price",
          "Price paid: 239.97 USD" in content, content[:200])
    deal = post(f"/api/deals/{deal['id']}/verify")
    check("honest deal released", deal["state"] == "released", deal["state"])
    check("every check passed",
          deal["verification"]["all_passed"] is True
          and deal["verification"]["passed_count"]
          == deal["verification"]["total_count"],
          deal["verification"])
    price_result = next(r for r in deal["verification"]["results"]
                        if r["check_id"] == "price_ceiling")
    check("price check measured the real offer price",
          price_result["measured"] == 239.97
          and price_result["required"] == spec["price"], price_result)


def test_poor_deal():
    print("TEST 5 poor procurement delivery is refunded, bond slashed")
    deal = run_to_paid()
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": "poor"})
    deal = post(f"/api/deals/{deal['id']}/verify")
    check("no checks pass on the thin delivery",
          deal["verification"]["passed_count"] == 0, deal["verification"])
    check("deal refunded", deal["state"] == "refunded", deal["state"])
    check("bond slashed", deal["bond"]["status"] == "slashed", deal["bond"])


def test_bad_report_fails_checks():
    print("TEST 6 a cheating report fails the grounded checks")
    deal = run_to_paid()
    spec = deal["spec"]
    from pact.verifier import verify_delivery
    bad = (
        "Procurement Report\n"
        "Product: Generic Wireless Headphones, own brand\n"
        "Retailer: Some other store (otherstore.example.com)\n"
        "Price paid: 999.99 USD\n"
        "Order reference: PACT-00000000\n"
        "Notes: bought a similar item from a different shop at a "
        "higher price and kept the change."
    )
    outcome = verify_delivery(spec, bad)
    by_id = {r["check_id"]: r for r in outcome["results"]}
    check("wrong product fails", by_id["product_title"]["passed"] is False,
          by_id["product_title"])
    check("wrong retailer fails", by_id["retailer_named"]["passed"] is False,
          by_id["retailer_named"])
    check("price over ceiling fails",
          by_id["price_ceiling"]["passed"] is False
          and by_id["price_ceiling"]["measured"] == 999.99,
          by_id["price_ceiling"])
    check("missing buy link fails", by_id["product_link"]["passed"] is False,
          by_id["product_link"])
    check("cheating report does not pass overall",
          outcome["all_passed"] is False, outcome["passed_count"])


def test_live_client_needs_key():
    print("TEST 7 live search without a key errors clearly")
    try:
        asyncio.run(channel3.search_products("anything"))
        check("missing key raises", False, "no exception")
    except channel3.Channel3Error as exc:
        check("missing key raises", "CHANNEL3_API_KEY" in str(exc), str(exc))


def main():
    health = client.get("/api/health").json()
    assert health["mode"] == "demo", health
    ids = [s["id"] for s in client.get("/api/scenarios").json()]
    check("procurement scenario is listed", "procurement" in ids, ids)
    test_grounding_math()
    test_candidate_checks()
    test_max_price_verifier()
    test_honest_deal()
    test_poor_deal()
    test_bad_report_fails_checks()
    test_live_client_needs_key()
    if FAILURES:
        print(f"CHANNEL3 TESTS FAILED: {FAILURES}")
        sys.exit(1)
    print("ALL CHANNEL3 TESTS PASSED")


if __name__ == "__main__":
    main()

"""Channel3 product search client and market grounding for procurement.

Channel3 is a product data API: one search returns real retail products,
each with offers across merchants (price, buy link, availability). Pact
uses it as the market layer for the procurement scenario. Before a
procurement deal is created, one search runs for the product the buyer
wants. The returned offers ground the deal:

- the buyer ceiling is the median live offer price for the product,
- the seller floor is the lowest live offer price for the product,
- the lowest offer is the chosen offer, and its title, retailer, and buy
  link become frozen contract checks at negotiation time.

When no CHANNEL3_API_KEY is configured the client falls back to a cached
response that was captured from the live API and ships in the repo at
pact/fixtures/channel3_procurement_search.json. The fallback is always
labeled as cached, with its capture date, in the grounding record and in
the deal ledger. Cached data is never presented as live.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import money
from .config import SETTINGS

FIXTURE_PATH = (Path(__file__).resolve().parent / "fixtures"
                / "channel3_procurement_search.json")

# Display names for retailer domains Channel3 returns often. An unknown
# domain is shown as the domain itself; a name is never invented.
RETAILER_NAMES = {
    "walmart.com": "Walmart",
    "amazon.com": "Amazon",
    "bestbuy.com": "Best Buy",
    "target.com": "Target",
    "macys.com": "Macy's",
    "adorama.com": "Adorama",
    "hsn.com": "HSN",
    "qvc.com": "QVC",
    "cdw.com": "CDW",
    "backmarket.com": "Back Market",
    "beachcamera.com": "Beach Camera",
    "focuscamera.com": "Focus Camera",
    "bhphotovideo.com": "B&H",
    "newegg.com": "Newegg",
    "costco.com": "Costco",
    "sony.com": "Sony",
}


class Channel3Error(Exception):
    """Raised when Channel3 cannot supply market data."""


def retailer_name(domain):
    return RETAILER_NAMES.get(domain, domain)


async def search_products(query, limit=10):
    """Run one live Channel3 search and return the raw response.

    Raises Channel3Error with a plain message when no API key is
    configured, so a caller never has to guess why live mode failed.
    """
    if not SETTINGS.channel3_api_key:
        raise Channel3Error(
            "CHANNEL3_API_KEY is not set, so the Channel3 API cannot be "
            "called. Set it in the environment (see .env) to run live "
            "market searches, or run without it and procurement deals "
            "will use the cached Channel3 response shipped in the repo.")
    url = f"{SETTINGS.channel3_base_url}/v1/search"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                json={"query": query, "limit": limit},
                headers={"x-api-key": SETTINGS.channel3_api_key,
                         "Content-Type": "application/json"})
    except httpx.HTTPError as exc:
        raise Channel3Error(f"Channel3 search failed: {exc}") from exc
    if resp.status_code != 200:
        detail = ""
        try:
            detail = str(resp.json().get("detail", ""))[:200]
        except Exception:
            detail = resp.text[:200]
        raise Channel3Error(
            f"Channel3 search returned HTTP {resp.status_code}. {detail}")
    return resp.json()


def normalize_offers(response):
    """Flatten a Channel3 search response into offer records.

    One record per merchant offer: the product title and brand from the
    product, and the retailer domain, price, currency, buy link, and
    image from the offer. Offers without a usable USD price or a buy
    link are dropped, because a deal cannot be grounded on them.

    Prices are parsed to integer cents here, once, at the market-data
    boundary (queue item V): money.to_cents() is the only conversion.
    """
    offers = []
    for product in response.get("products") or []:
        title = (product.get("title") or "").strip()
        brands = product.get("brands") or []
        brand = brands[0]["name"] if brands else None
        image = None
        images = product.get("images") or []
        if images:
            image = images[0].get("cleaned_url") or images[0].get("url")
        for offer in product.get("offers") or []:
            price_obj = offer.get("price") or {}
            price = price_obj.get("price")
            url = offer.get("url")
            if price is None or not url or not title:
                continue
            if price_obj.get("currency", "USD") != "USD":
                continue
            domain = offer.get("domain") or ""
            offers.append({
                "product_id": product.get("id"),
                "title": title,
                "brand": brand,
                "retailer": domain,
                "retailer_name": retailer_name(domain),
                "domain": domain,
                "price": money.to_cents(price),
                "currency": "USD",
                "url": url,
                "image": image,
                "availability": offer.get("availability"),
            })
    return offers


def _grounding_from_offers(offers, query, source, captured_at):
    """Derive the negotiation bounds and the chosen offer from offers.

    Offers are grouped by product. The product with the most offers is
    the grounded product, because it carries the widest live market
    view; ties break to the group with the lowest price. The chosen
    offer is that product's lowest offer. The buyer ceiling is the
    median offer price and the floor is the lowest offer price, so the
    settled contract price always sits at or above a real price the
    seller can actually buy at.

    Every price in the returned grounding record (offers, lowest,
    median, highest, buyer_max, seller_floor, chosen_offer) is an
    integer number of US cents.
    """
    if not offers:
        raise Channel3Error(
            "Channel3 returned no usable USD offers for this product, "
            "so there is no market to ground a deal on.")
    groups = {}
    for offer in offers:
        groups.setdefault(offer["product_id"], []).append(offer)
    product_id, group = max(
        groups.items(),
        key=lambda kv: (len(kv[1]), -min(o["price"] for o in kv[1])))
    group = sorted(group, key=lambda o: o["price"])
    prices = [o["price"] for o in group]
    lowest = prices[0]
    # Median of integer cents, rounded half-even when the count is even.
    if len(prices) % 2:
        median = prices[len(prices) // 2]
    else:
        median = money.div_round(prices[len(prices) // 2 - 1]
                                 + prices[len(prices) // 2], 2)
    buyer_max = median
    if buyer_max <= lowest:
        buyer_max = money.pct_of(lowest, 110)
    if buyer_max - lowest < 100:
        buyer_max = lowest + 100
    chosen = group[0]
    return {
        "provider": "Channel3",
        "source": source,
        "query": query,
        "captured_at": captured_at,
        "product_id": product_id,
        "product_title": chosen["title"],
        "offers": group,
        "offers_considered": len(offers),
        "offer_count": len(group),
        "lowest_price": lowest,
        "median_price": median,
        "highest_price": prices[-1],
        "buyer_max": buyer_max,
        "seller_floor": lowest,
        "chosen_offer": chosen,
    }


def grounding_from_response(response, query, source, captured_at):
    """Ground a deal from a raw Channel3 search response."""
    return _grounding_from_offers(
        normalize_offers(response), query, source, captured_at)


def load_fixture():
    """Read the cached Channel3 response shipped in the repo."""
    try:
        data = json.loads(FIXTURE_PATH.read_text())
    except OSError as exc:
        raise Channel3Error(
            f"The cached Channel3 response at {FIXTURE_PATH} could not "
            f"be read: {exc}") from exc
    return data


def load_fixture_grounding():
    """Grounding derived from the cached response, labeled as cached."""
    fixture = load_fixture()
    return grounding_from_response(
        fixture["response"], fixture["query"], source="cached_fixture",
        captured_at=fixture["captured_at"])


async def get_grounding(query):
    """Ground a procurement deal for a product query.

    Live mode: one Channel3 search, grounding labeled live with the
    capture time. No key configured: the cached response shipped in
    the repo, grounding labeled cached with its capture date.
    """
    if SETTINGS.channel3_api_key:
        response = await search_products(query)
        captured = datetime.now(timezone.utc).date().isoformat()
        return grounding_from_response(
            response, query, source="live", captured_at=captured)
    return load_fixture_grounding()


def build_candidate_checks(grounding):
    """Build the candidate contract checks from a grounded offer.

    The exact product title, the retailer, and the buy link come from
    the chosen live offer, so the frozen contract names the real
    product the buyer is paying for. The price ceiling is a max_price
    check: its value is set at negotiation time to the agreed contract
    price. The report length is a normal negotiated min_words check.
    """
    chosen = grounding["chosen_offer"]
    checks = [
        {
            "id": "product_title",
            "label": "Exact product from the grounded offer",
            "kind": "contains",
            "needle": chosen["title"],
        },
        {
            "id": "retailer_named",
            "label": "Retailer from the grounded offer",
            "kind": "contains",
            "needle": chosen["retailer_name"],
        },
    ]
    if chosen.get("url"):
        checks.append({
            "id": "product_link",
            "label": "Buy link from the grounded offer",
            "kind": "contains",
            "needle": chosen["url"],
        })
    checks.append({
        "id": "price_ceiling",
        "label": "Purchase price ceiling",
        "kind": "max_price",
        "unit": "USD",
    })
    checks.append({
        "id": "report_length",
        "label": "Procurement report length",
        "kind": "min_words",
        "unit": "words",
        "buyer_demand": 140,
        "seller_offer": 90,
    })
    return checks

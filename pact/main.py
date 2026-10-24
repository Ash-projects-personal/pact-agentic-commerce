"""Pact API: agent to agent commerce with verified settlement.

Flow: two agents negotiate price and write the contract checks themselves,
the spec freezes, the buyer pays into a hold through PayPal, the seller posts
a performance bond the same way, the seller delivers, a verifier agent judges
the delivery against the negotiated checks, and the money settles. Pass means
the seller is paid and the bond comes back. Fail after one revision round
means the buyer is refunded and the bond is slashed to the buyer.
"""

import asyncio
import json
import logging
import math
import secrets
import threading
import time
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import persistence
from . import money
from .abuse_limits import (check_payload_size, check_rate_limit,
                           client_key, sized_path)
from .channel3 import Channel3Error, build_candidate_checks, get_grounding
from .config import SETTINGS, validate_config
from .dispute_packet import build_dispute_packet
from .errors import (ERROR_CODES, UpstreamFailure, build_error_response,
                     raise_upstream, redact_upstream)
from .negotiation import run_negotiation, spec_hash
from .payments import PaymentError, PayPalClient
from .paypal_agents import get_agent_payment_service, toolkit_status
from .scenarios import SCENARIO_BY_ID, SCENARIOS, build_delivery
from .store import (AGENTS, DEALS, GLOBAL_EVENTS, add_event, change_reputation,
                    claim_webhook_event, get_webhook_record, new_deal,
                    now_iso, public_deal, public_grounding,
                    set_webhook_verification, unclaim_webhook_event)
from .verifier import verify_delivery

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

log = logging.getLogger("pact.access")


@asynccontextmanager
async def lifespan(app):
    # Startup: refuse to boot misconfigured in live mode, then restore
    # persisted state. A RuntimeError here stops uvicorn before serving.
    validate_config(SETTINGS)
    persistence.load_all()
    yield
    # Shutdown: one last durable write so nothing is lost.
    try:
        persistence.save_all()
    except Exception as exc:
        log.warning("persistence save on shutdown failed: %s", exc)


app = FastAPI(title="Pact", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(Exception)
async def _clean_internal_error(request: Request, exc: Exception):
    """Last resort error surface (queue item X).

    Any exception the endpoints did not handle becomes the clean error
    envelope, never a stack trace or an internal string. The full
    detail goes to the server log under the correlation id the
    response carries. More specific handlers (HTTPException, request
    validation) keep their own behavior; this only catches the rest.
    """
    import uuid as _uuid
    correlation_id = _uuid.uuid4().hex
    log.error(json.dumps({
        "correlation_id": correlation_id,
        "code": "INTERNAL_ERROR",
        "path": request.url.path,
        "exception": redact_upstream(f"{type(exc).__name__}: {exc}"),
    }))
    status, message = ERROR_CODES["INTERNAL_ERROR"]
    return JSONResponse(
        status_code=status,
        content={"error": {
            "code": "INTERNAL_ERROR",
            "message": message,
            "correlation_id": correlation_id,
        }},
    )


@app.middleware("http")
async def pact_middleware(request: Request, call_next):
    """One middleware for four deploy concerns.

    1. Abuse limits (queue item Z): the negotiation and delivery
       endpoints carry a request-body size cap, checked here before the
       route handler runs so an oversized body is rejected before any
       parsing or state work. The response still gets the standard
       headers, the access log line, and the persistence pass below.
    2. Security headers on every response.
    3. One structured JSON access log line per request on stdout.
       No request bodies and no secrets are logged.
    4. Persist the working store to SQLite after every response, so a
       restart or a Render sleep cycle never wipes a deal.
    """
    oversize = None
    if request.method == "POST" and sized_path(request.url.path):
        oversize = check_payload_size(request)
    started = time.perf_counter()
    response = oversize if oversize is not None else await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    log.info(json.dumps({
        "timestamp": now_iso(),
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
    }))
    try:
        persistence.save_all()
    except Exception as exc:
        log.warning("persistence save failed: %s", exc)
    return response


class CreateDealRequest(BaseModel):
    scenario_id: str
    buyer_max: Optional[float] = None
    seller_floor: Optional[float] = None
    bond_percent: Optional[float] = None
    # Multi-issue negotiation (queue item S): after the price is agreed
    # the agents also trade delivery window, revision rounds, and bond
    # percent on best-trade-ratio moves. Default off; the frozen
    # single-issue flow stays the headline until the multi-issue sweep
    # data exists.
    multi_issue: bool = False


class DeliverRequest(BaseModel):
    quality: str = "auto"


# Money input bounds for deal creation. Amounts below the price floor can
# round the performance bond to zero, which would make cheating free, and
# non finite or absurd amounts poison the in memory deal record.
MIN_DEAL_PRICE = 1.00
MAX_DEAL_AMOUNT = 1_000_000.0
# A settled bond below this floor is no bond at all: the deal fails
# cleanly instead of settling with a silent zero bond.
MIN_BOND_AMOUNT = 0.50

# Delivery qualities a caller may ask for. "auto" runs the scenario's own
# seller behavior; "poor" is a demo knob that forces the thin delivery so
# the fail path can be shown on demand. Anything else is rejected. In
# live sandbox mode the knob is ignored entirely (see deliver()): a
# caller must never be able to force a failed delivery and collect the
# bond on real money.
ALLOWED_DELIVERY_QUALITIES = {"auto", "poor", "weak", "cheat"}


def _idem_key(deal, leg):
    """Deterministic idempotency key for one money leg of one deal.

    The same logical operation retried later produces the same key, so
    PayPal can dedupe it. Keys are also stored on the deal records.
    """
    return f"{deal['id']}-{leg}"


# Per deal asyncio locks. The state changing endpoints (negotiate, pay,
# pay/confirm, deliver, verify) each hold their deal's lock from the state
# check to the state write, so parallel calls cannot create duplicate
# orders or interleave negotiation moves. A second concurrent call waits
# for the first to finish and then fails the state check with a 409, the
# same behavior sequential double calls already had. Lock entries live for
# the process lifetime; they are tiny and keyed by deal id.
_DEAL_LOCKS = {}
_DEAL_LOCKS_GUARD = threading.Lock()


def _deal_lock(deal_id):
    with _DEAL_LOCKS_GUARD:
        lock = _DEAL_LOCKS.get(deal_id)
        if lock is None:
            lock = asyncio.Lock()
            _DEAL_LOCKS[deal_id] = lock
        return lock


def _deal_or_404(deal_id):
    deal = DEALS.get(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


# Per-deal role tokens (queue item W). State-changing endpoints require
# the token for the acting role in this header. The create response and
# the deal view carry both tokens, and the demo UI sends the right one
# automatically.
DEAL_TOKEN_HEADER = "X-Deal-Token"


def _require_deal_role(deal, request, *roles):
    """Refuse a state-changing call without the right role token.

    Runs after the 404 check and before the lock and the state check, so
    a bad token never waits on a deal lock and never reaches the state
    machine. Deals persisted before tokens shipped carry no tokens at
    all; those are grandfathered past the check so old deals keep
    working. A missing or wrong-role token is a 403 with a clean error
    shape: a human sentence, no internal strings (item X convention).
    """
    if not deal.get("buyer_token") and not deal.get("seller_token"):
        return
    token = request.headers.get(DEAL_TOKEN_HEADER)
    if token:
        for role in roles:
            expected = deal.get(f"{role}_token")
            if expected and secrets.compare_digest(token, expected):
                return
    raise HTTPException(
        status_code=403,
        detail="This action needs the deal's role token. Send it in the "
               "X-Deal-Token header. The create response and the deal view "
               "carry the buyer and seller tokens.")


def _require_state(deal, states, action):
    if deal["state"] not in states:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} while the deal is in state {deal['state']}")


def _mode_label(payments):
    return "DEMO MODE" if payments.mode == "demo" else "PayPal sandbox"


@app.get("/", description="Serves the Pact demo UI.")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health",
         description="Liveness probe. Reports the process is up, the mode "
                     "(demo or PayPal sandbox), and the payment rails in use.")
async def health():
    return {
        "status": "ok",
        "mode": SETTINGS.mode,
        "mode_label": "DEMO MODE" if SETTINGS.mode == "demo" else "PayPal sandbox",
        "paypal_live": SETTINGS.paypal_live,
        "agent_toolkit": toolkit_status(),
        "llm_enabled": SETTINGS.llm_enabled,
        "bond_percent_default": SETTINGS.bond_percent,
    }


@app.get("/api/ready",
         description="Readiness probe, separate from health. Returns 200 "
                     "only when the startup config validates and the "
                     "database passes a write/read probe. Deploys gate on "
                     "this endpoint.")
async def ready():
    """Readiness is separate from health.

    Health says the process is alive. Readiness says it can serve a
    judge: config validates AND the database takes a real write/read
    probe. Render and the deploy check gate on this endpoint.
    """
    checks = {}
    status = "ready"
    try:
        live = validate_config(SETTINGS)
        checks["config"] = "ok"
    except RuntimeError as exc:
        checks["config"] = str(exc)
        status = "not_ready"
        live = False
    checks["mode"] = "sandbox" if live else "demo"
    try:
        persistence.probe()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        status = "not_ready"
    return JSONResponse(
        status_code=200 if status == "ready" else 503,
        content={"status": status, "checks": checks},
    )


@app.get("/api/scenarios",
         description="Lists the 14 deal scenarios with their candidate "
                     "acceptance checks, price bounds, and seller agents.")
async def scenarios():
    out = []
    for s in SCENARIOS:
        seller = AGENTS[s["seller_id"]]
        out.append({
            "id": s["id"],
            "title": s["title"],
            "service_summary": s["service_summary"],
            "deliverables": s["deliverables"],
            "default_buyer_max": s["default_buyer_max"],
            "default_seller_floor": s["default_seller_floor"],
            "seller_behavior": s["seller_behavior"],
            "seller": {"id": seller["id"], "name": seller["name"],
                       "persona": seller["persona"],
                       "reputation": seller["reputation"]},
            "candidate_checks": s["candidate_checks"],
        })
    return out


@app.get("/api/agents",
         description="Lists the buyer and seller agents with their "
                     "reputation scores and deal counts.")
async def agents():
    return list(AGENTS.values())


@app.post("/api/deals",
          description="Creates a deal from a scenario: sets the price "
                      "bounds and bond percent, then the buyer and seller "
                      "agents negotiate and freeze the contract. Procurement "
                      "deals ground the bounds in live Channel3 market data "
                      "first.")
async def create_deal(req: CreateDealRequest, request: Request):
    # Abuse limits (queue item Z): the rate cap is the outermost
    # shield. Over the cap the call is refused with a clean 429 before
    # any deal work happens, and the refusal is not recorded, so a
    # refused burst does not extend its own penalty.
    limited = check_rate_limit(client_key(request))
    if limited is not None:
        return limited
    scenario = SCENARIO_BY_ID.get(req.scenario_id)
    if not scenario:
        raise HTTPException(status_code=400, detail="Unknown scenario")
    grounding = None
    if scenario["id"] == "procurement":
        # One Channel3 search grounds this deal before it exists: the
        # live offers set the price bounds and the contract checks, so
        # the agents negotiate over real market prices, not invented
        # ones. With no API key configured the grounding comes from
        # the cached Channel3 response shipped in the repo, labeled
        # as cached with its capture date.
        try:
            grounding = await get_grounding(scenario["product_query"])
        except Channel3Error as exc:
            # No deal exists yet, so the full detail goes to the server
            # log only; the response carries the clean envelope.
            response, _cid = build_error_response(
                None, "MARKET_GROUNDING_FAILED", exc,
                where="create_deal:channel3_grounding",
                event_type="market_grounding_error")
            return response
    # Parse boundary (queue item V): dollar inputs become integer cents
    # exactly once, here. Grounding bounds arrive already in cents from
    # the Channel3 parse boundary. The deal record never holds a float
    # amount after this point.
    try:
        if grounding is not None:
            buyer_max_c = grounding["buyer_max"]
            seller_floor_c = grounding["seller_floor"]
        else:
            buyer_max_c = money.to_cents(
                req.buyer_max if req.buyer_max is not None
                else scenario["default_buyer_max"])
            seller_floor_c = money.to_cents(
                req.seller_floor if req.seller_floor is not None
                else scenario["default_seller_floor"])
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Price bounds must be finite numbers. NaN and infinity "
                   f"are not money amounts and would corrupt the deal "
                   f"record. ({exc})")
    bond_percent = (req.bond_percent if req.bond_percent is not None
                    else SETTINGS.bond_percent)
    if not math.isfinite(bond_percent):
        raise HTTPException(
            status_code=400,
            detail="bond_percent must be a finite number. NaN and infinity "
                   "are not money amounts and would corrupt the deal "
                   "record.")
    if (buyer_max_c > money.to_cents(MAX_DEAL_AMOUNT)
            or seller_floor_c > money.to_cents(MAX_DEAL_AMOUNT)):
        raise HTTPException(
            status_code=400,
            detail=f"Amounts above {MAX_DEAL_AMOUNT:.0f} USD are not "
                   f"accepted for a deal.")
    if (buyer_max_c < money.to_cents(MIN_DEAL_PRICE)
            or seller_floor_c < money.to_cents(MIN_DEAL_PRICE)):
        raise HTTPException(
            status_code=400,
            detail=f"Prices must be at least {MIN_DEAL_PRICE:.2f} USD. "
                   f"Below that the performance bond rounds to zero and "
                   f"cheating becomes free.")
    if not 0 < bond_percent <= 100:
        raise HTTPException(
            status_code=400,
            detail="Bond percent must be above 0 and at most 100. A zero "
                   "bond would make cheating free, so it is not allowed.")
    deal = new_deal(scenario, buyer_max_c, seller_floor_c, bond_percent,
                    multi_issue=bool(req.multi_issue))
    if grounding is not None:
        deal["market"] = grounding
        deal["candidate_checks"] = build_candidate_checks(grounding)
        chosen = grounding["chosen_offer"]
        if grounding["source"] == "live":
            origin = (f"live Channel3 API search on "
                      f"{grounding['captured_at']}")
        else:
            origin = (f"cached Channel3 response captured on "
                      f"{grounding['captured_at']} (no Channel3 API "
                      f"key is configured, so the live API was not "
                      f"called)")
        add_event(
            deal, "market_grounded", "buyer",
            f"Market data from Channel3 ({origin}): "
            f"{grounding['offer_count']} offers for "
            f"{grounding['product_title']} priced from "
            f"{money.dollars(grounding['lowest_price'])} to "
            f"{money.dollars(grounding['highest_price'])} USD, median "
            f"{money.dollars(grounding['median_price'])} USD. Buyer ceiling "
            f"set to the median offer price "
            f"{money.dollars(grounding['buyer_max'])} USD and seller floor "
            f"to the lowest offer price "
            f"{money.dollars(grounding['seller_floor'])} USD. Chosen offer: "
            f"{chosen['title']} at {chosen['retailer_name']} for "
            f"{money.dollars(chosen['price'])} USD.",
            {"provider": "Channel3", "source": grounding["source"],
             "query": grounding["query"],
             "captured_at": grounding["captured_at"],
             **{k: v for k, v in public_grounding(grounding).items()
                if k in ("offers", "offers_considered", "chosen_offer",
                         "lowest_price", "median_price", "highest_price",
                         "buyer_max", "seller_floor")}})
    return public_deal(deal)


@app.get("/api/deals/{deal_id}",
          description="Returns one deal: state, frozen spec with the SHA-256 "
                      "contract hash, money legs, ledger events, and "
                      "settlement progress.")
async def get_deal(deal_id: str):
    return public_deal(_deal_or_404(deal_id))


@app.get("/api/deals/{deal_id}/dispute-packet",
          description="Downloads the self-contained Markdown evidence file "
                      "for one deal: transcript, frozen spec, check verdicts, "
                      "reputation moves, and every PayPal transaction id.")
async def dispute_packet(deal_id: str):
    """Export the dispute evidence packet for one deal.

    A single self contained Markdown file, generated from real deal data
    only: the negotiation transcript with each side's rationale, the
    frozen spec, every check verdict with measured versus required,
    reputation moves, and every PayPal transaction id on the deal. This
    is the artifact a buyer would hand to a human reviewer in a dispute.
    """
    deal = _deal_or_404(deal_id)
    packet = build_dispute_packet(deal)
    return PlainTextResponse(
        packet,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename="pact-dispute-{deal_id}.md"'
        },
    )


@app.post("/api/deals/{deal_id}/negotiate/run",
           description="Runs the negotiation for a created deal: the price "
                       "phase first, then the multi-issue terms phase when "
                       "the deal was created with multi_issue set.")
async def negotiate(deal_id: str, request: Request):
    deal = _deal_or_404(deal_id)
    _require_deal_role(deal, request, "buyer")
    async with _deal_lock(deal_id):
        _require_state(deal, ["negotiating"], "negotiate")
        scenario = SCENARIO_BY_ID[deal["scenario_id"]]
        if deal.get("candidate_checks"):
            # Market grounded deals carry their own candidate checks,
            # built from the real offers recorded at creation, plus the
            # grounding evidence itself for the frozen spec.
            scenario = {**scenario,
                        "candidate_checks": deal["candidate_checks"]}
            if deal.get("market"):
                scenario["grounding"] = deal["market"]
        await run_negotiation(deal, scenario,
                              multi_issue=deal.get("multi_issue", False))
        if deal["state"] == "agreed" and deal["spec"]:
            bond_amount_c = deal["spec"]["bond_amount"]
            if bond_amount_c < money.to_cents(MIN_BOND_AMOUNT):
                # The percent was legal but the settled price is so small
                # that the bond rounded to almost nothing. Fail cleanly
                # instead of settling a deal whose bond cannot punish a
                # cheat.
                deal["state"] = "failed"
                add_event(deal, "bond_too_small", "system",
                          f"Negotiation settled at "
                          f"{money.dollars(deal['spec']['price'])} USD "
                          f"with a performance bond of "
                          f"{money.dollars(bond_amount_c)} USD, "
                          f"below the {MIN_BOND_AMOUNT:.2f} USD floor. A bond "
                          f"that small cannot punish a cheat, so the deal "
                          f"fails here with no payment made.")
                raise HTTPException(
                    status_code=400,
                    detail=f"The settled performance bond of "
                           f"{money.dollars(bond_amount_c)} USD "
                           f"is below the {MIN_BOND_AMOUNT:.2f} USD floor. "
                           f"Raise the price or the bond percent: a bond that "
                           f"rounds to zero would make cheating free.")
        return public_deal(deal)


@app.post("/api/deals/{deal_id}/pay",
           description="Creates the price order and the bond order and "
                       "returns the approval links. In demo mode the orders "
                       "are simulated; in live mode the buyer and seller "
                       "approve on PayPal.")
async def pay(deal_id: str, request: Request):
    deal = _deal_or_404(deal_id)
    _require_deal_role(deal, request, "buyer")
    async with _deal_lock(deal_id):
        _require_state(deal, ["agreed"], "pay")
        payments = get_agent_payment_service()
        label = _mode_label(payments)
        spec = deal["spec"]
        # Integer cents on the deal record (queue item V); the payment
        # service takes cents and formats the PayPal payload itself.
        price_c = spec["price"]
        bond_amount_c = spec["bond_amount"]
        contract_hash = deal.get("contract_hash")
        if not contract_hash:
            # Deals agreed before the hash shipped have none. The spec is
            # already frozen on an agreed deal, so hashing it now commits
            # to exactly the contract the verifier will judge.
            contract_hash = spec_hash(spec)
            deal["contract_hash"] = contract_hash
            add_event(deal, "contract_hash_backfilled", "system",
                      f"Deal agreed before contract hashing shipped. The "
                      f"frozen spec hashes to SHA-256 "
                      f"{contract_hash[:16]}..., recorded now.",
                      {"contract_hash": contract_hash})
        contract_tag = f"{deal_id}:{contract_hash}"
        deal["payment"]["order_request_id"] = _idem_key(deal, "price-order")
        deal["bond"]["order_request_id"] = _idem_key(deal, "bond-order")
        try:
            order = await payments.create_order(
                price_c, "USD", f"{deal_id} price",
                request_id=deal["payment"]["order_request_id"],
                contract_tag=contract_tag)
            bond_order = await payments.create_order(
                bond_amount_c, "USD", f"{deal_id} bond",
                request_id=deal["bond"]["order_request_id"],
                contract_tag=contract_tag)
        except PaymentError as exc:
            # Clean surface (queue item X): the raw PayPal body lives in
            # the ledger event and the server log under the correlation
            # id, never in the response.
            response, _cid = build_error_response(
                deal, "ORDER_CREATION_FAILED", exc,
                where="pay:create_order", event_type="payment_error")
            return response
        deal["payment"].update({
            "status": "created", "order_id": order["order_id"],
            "amount": price_c,
            "mode": payments.mode, "rail": order.get("rail"),
            "approval_url": order.get("approval_url"),
            "contract_tag": contract_tag,
            "hash_field": order.get("hash_field"),
        })
        deal["bond"].update({
            "status": "created", "order_id": bond_order["order_id"],
            "amount": bond_amount_c, "mode": payments.mode,
            "rail": bond_order.get("rail"),
            "approval_url": bond_order.get("approval_url"),
            "contract_tag": contract_tag,
            "hash_field": bond_order.get("hash_field"),
        })
        if order.get("approval_url") or bond_order.get("approval_url"):
            # PayPal requires the account holder to approve a wallet payment
            # before it can be captured. The agents prepare both orders; the
            # humans behind the buyer and seller accounts approve them; the
            # confirm step then captures. This is PayPal's own design for
            # agentic payments, and Pact keeps that checkpoint on purpose.
            deal["payment"]["status"] = "awaiting_approval"
            deal["bond"]["status"] = "awaiting_approval"
            add_event(deal, "payment_approval_requested", "buyer",
                      f"Buyer agent prepared a PayPal order for "
                      f"{money.dollars(price_c)} USD "
                      f"({label}), order {order['order_id']}. PayPal requires "
                      f"the account holder to approve a wallet payment before "
                      f"capture, so the buyer approves it here: "
                      f"{order.get('approval_url')}",
                      {"order_id": order["order_id"],
                       "amount": money.dollars(price_c),
                       "approval_url": order.get("approval_url"),
                       "mode": payments.mode, "rail": order.get("rail"),
                       "contract_hash": contract_hash,
                       "hash_field": order.get("hash_field")})
            add_event(deal, "bond_approval_requested", "seller",
                      f"Seller agent prepared the performance bond order for "
                      f"{money.dollars(bond_amount_c)} USD ({label}), order "
                      f"{bond_order['order_id']}. The seller approves it here: "
                      f"{bond_order.get('approval_url')}",
                      {"order_id": bond_order["order_id"],
                       "amount": money.dollars(bond_amount_c),
                       "approval_url": bond_order.get("approval_url"),
                       "mode": payments.mode, "rail": bond_order.get("rail"),
                       "contract_hash": contract_hash,
                       "hash_field": bond_order.get("hash_field")})
            deal["state"] = "awaiting_approval"
            return public_deal(deal)
        try:
            await _capture_both(deal, payments, label)
        except UpstreamFailure as failed:
            return failed.response
        deal["state"] = "paid_held"
        return public_deal(deal)


async def _capture_both(deal, payments, label):
    """Capture whichever of the price and bond orders is not captured yet."""
    spec = deal["spec"]
    price_c = spec["price"]
    bond_amount_c = spec["bond_amount"]
    try:
        if deal["payment"].get("status") != "held":
            deal["payment"]["capture_request_id"] = _idem_key(
                deal, "price-capture")
            capture = await payments.capture_order(
                deal["payment"]["order_id"],
                request_id=deal["payment"]["capture_request_id"])
            if (not capture.get("capture_id")
                    or capture.get("status") != "COMPLETED"):
                raise PaymentError(
                    f"Price capture did not complete: status "
                    f"{capture.get('status')}, capture id "
                    f"{capture.get('capture_id')}. No funds are held, so "
                    f"the deal cannot move forward.")
            deal["payment"].update({
                "status": "held", "capture_id": capture["capture_id"],
                "rail": capture.get("rail"),
            })
            add_event(deal, "payment_held", "buyer",
                      f"Buyer paid {money.dollars(price_c)} USD through a "
                      f"PayPal order and the funds are HELD in the deal "
                      f"ledger ({label}). Order "
                      f"{deal['payment']['order_id']}, capture "
                      f"{capture['capture_id']}. Executed through rail: "
                      f"{capture.get('rail')}.",
                      {"order_id": deal["payment"]["order_id"],
                       "capture_id": capture["capture_id"],
                       "amount": money.dollars(price_c),
                       "mode": payments.mode, "rail": capture.get("rail"),
                       "capture_request_id":
                           deal["payment"]["capture_request_id"]})
        if deal["bond"].get("status") != "posted":
            deal["bond"]["capture_request_id"] = _idem_key(
                deal, "bond-capture")
            bond_capture = await payments.capture_order(
                deal["bond"]["order_id"],
                request_id=deal["bond"]["capture_request_id"])
            if (not bond_capture.get("capture_id")
                    or bond_capture.get("status") != "COMPLETED"):
                raise PaymentError(
                    f"Bond capture did not complete: status "
                    f"{bond_capture.get('status')}, capture id "
                    f"{bond_capture.get('capture_id')}. The bond is not "
                    f"posted, so the deal cannot move forward.")
            deal["bond"].update({
                "status": "posted", "capture_id": bond_capture["capture_id"],
                "rail": bond_capture.get("rail"),
            })
            add_event(deal, "bond_posted", "seller",
                      f"Seller posted a performance bond of "
                      f"{money.dollars(bond_amount_c)} USD through a second "
                      f"PayPal order ({label}). Executed through rail: "
                      f"{bond_capture.get('rail')}. Order "
                      f"{deal['bond']['order_id']}, capture "
                      f"{bond_capture['capture_id']}. The bond returns on a "
                      f"pass and is slashed to the buyer on a final fail.",
                      {"order_id": deal["bond"]["order_id"],
                       "capture_id": bond_capture["capture_id"],
                       "amount": money.dollars(bond_amount_c),
                       "mode": payments.mode,
                       "rail": bond_capture.get("rail"),
                       "capture_request_id":
                           deal["bond"]["capture_request_id"]})
    except PaymentError as exc:
        # Clean surface (queue item X): the raw PayPal body lives in the
        # ledger event and the server log under the correlation id, never
        # in the response. The caller catches UpstreamFailure and
        # returns the finished response.
        raise_upstream(deal, "CAPTURE_FAILED", exc,
                       where="_capture_both",
                       event_type="payment_error")


@app.post("/api/deals/{deal_id}/pay/confirm",
           description="Confirms both PayPal orders are approved by the "
                       "expected sandbox buyer and seller identities, then "
                       "captures. Refuses capture with a ledger event when "
                       "a payer does not match. Demo mode skips the check.")
async def pay_confirm(deal_id: str, request: Request):
    deal = _deal_or_404(deal_id)
    _require_deal_role(deal, request, "buyer")
    async with _deal_lock(deal_id):
        _require_state(deal, ["awaiting_approval"], "confirm payment")
        payments = get_agent_payment_service()
        label = _mode_label(payments)
        try:
            if payments.mode != "demo":
                await _check_approval_payers(deal, payments)
            await _capture_both(deal, payments, label)
        except UpstreamFailure as failed:
            return failed.response
        deal["state"] = "paid_held"
        return public_deal(deal)


def _order_payer_email(details):
    """Pull the payer email out of an order details payload.

    The REST rail returns the order object directly; the toolkit rail
    nests it under "raw". Returns None when the order carries no payer
    information, which is also what an unapproved order looks like.
    """
    if not isinstance(details, dict):
        return None
    payer = details.get("payer")
    if not isinstance(payer, dict):
        raw = details.get("raw")
        if isinstance(raw, dict):
            payer = raw.get("payer")
    if not isinstance(payer, dict):
        return None
    email = payer.get("email_address")
    return email.strip().lower() if email else None


async def _check_approval_payers(deal, payments):
    """Refuse capture unless the expected accounts approved the orders.

    The approval links are bearer capabilities: anyone holding them
    could approve. Before capturing, ask PayPal who approved each
    order. The price order must carry the buyer sandbox identity and
    the bond order the seller sandbox identity; anything else, or an
    order with no payer information at all, refuses capture and logs
    a payer_mismatch event. The deal stays in awaiting_approval so
    the right account can approve and the confirm can be retried.
    Demo mode skips this check: there are no real orders there.
    """
    expected_buyer = (SETTINGS.buyer_sandbox_email or "").strip().lower()
    expected_seller = (SETTINGS.seller_sandbox_email or "").strip().lower()
    if not expected_buyer or not expected_seller:
        add_event(deal, "payer_mismatch", "system",
                  "Cannot confirm payment: the buyer and seller sandbox "
                  "emails are not configured, so there is no expected "
                  "payer identity to check the approvals against. Set "
                  "BUYER_SANDBOX_EMAIL and SELLER_SANDBOX_EMAIL before "
                  "confirming.")
        raise HTTPException(
            status_code=409,
            detail="Cannot confirm payment: the expected payer identities "
                   "are not configured (BUYER_SANDBOX_EMAIL and "
                   "SELLER_SANDBOX_EMAIL). Capture is refused until the "
                   "approvals can be checked.")
    try:
        price_details = await payments.get_order_details(
            deal["payment"]["order_id"])
        bond_details = await payments.get_order_details(
            deal["bond"]["order_id"])
    except PaymentError as exc:
        # Clean surface (queue item X): the raw read-back body lives in
        # the ledger event and the server log under the correlation id,
        # never in the response.
        raise_upstream(
            deal, "ORDER_READ_FAILED", exc,
            where="pay_confirm:order_details",
            event_type="payer_mismatch",
            message="Cannot confirm payment: reading the orders back from "
                    "PayPal failed, so the approving payers could not be "
                    "verified. Capture is refused; retry the confirm once "
                    "PayPal answers.")
    price_payer = _order_payer_email(price_details)
    bond_payer = _order_payer_email(bond_details)
    problems = []
    if price_payer != expected_buyer:
        problems.append(
            f"the price order {deal['payment']['order_id']} was approved "
            f"by {price_payer or 'an unknown payer'}, not the expected "
            f"buyer {expected_buyer}")
    if bond_payer != expected_seller:
        problems.append(
            f"the bond order {deal['bond']['order_id']} was approved by "
            f"{bond_payer or 'an unknown payer'}, not the expected "
            f"seller {expected_seller}")
    if problems:
        message = ("Capture refused: " + "; ".join(problems) + ". The "
                   "deal stays awaiting approval so the right accounts "
                   "can approve the orders and the confirm can be retried.")
        add_event(deal, "payer_mismatch", "system", message,
                  {"price_order_id": deal["payment"]["order_id"],
                   "price_payer": price_payer,
                   "expected_buyer": expected_buyer,
                   "bond_order_id": deal["bond"]["order_id"],
                   "bond_payer": bond_payer,
                   "expected_seller": expected_seller})
        raise HTTPException(status_code=409, detail=message)
    add_event(deal, "payers_verified", "system",
              f"Both orders were approved by the expected sandbox "
              f"accounts (buyer {expected_buyer}, seller "
              f"{expected_seller}). Capture proceeds.",
              {"price_order_id": deal["payment"]["order_id"],
               "bond_order_id": deal["bond"]["order_id"]})


@app.post("/api/deals/{deal_id}/deliver",
           description="Submits the seller delivery text against the frozen "
                       "contract. A weak delivery spends one revision round "
                       "instead of settling.")
async def deliver(deal_id: str, request: Request,
                  req: DeliverRequest = DeliverRequest()):
    deal = _deal_or_404(deal_id)
    _require_deal_role(deal, request, "seller")
    async with _deal_lock(deal_id):
        _require_state(deal, ["paid_held", "revision"], "deliver")
        if req.quality not in ALLOWED_DELIVERY_QUALITIES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown delivery quality {req.quality!r}. Allowed "
                       f"values are {sorted(ALLOWED_DELIVERY_QUALITIES)}.")
        scenario = SCENARIO_BY_ID[deal["scenario_id"]]
        is_revision = deal["state"] == "revision"
        payments = get_agent_payment_service()
        effective_quality = req.quality
        if payments.mode != "demo" and req.quality != "auto":
            # Live sandbox money: the quality knob is a demo control. If a
            # caller could force a poor delivery here, a buyer could fail a
            # deal on purpose and collect the seller's bond. In live mode
            # the scenario's own seller behavior always decides.
            effective_quality = "auto"
            add_event(deal, "quality_knob_ignored", "system",
                      f"The caller asked for delivery quality "
                      f"{req.quality!r}, but this deal runs on live PayPal "
                      f"sandbox money, where the demo quality knob is "
                      f"disabled. The seller agent's own behavior decides "
                      f"the delivery, so no caller can force a fail and "
                      f"collect the bond.")
        content = build_delivery(scenario, deal["spec"],
                                 quality=effective_quality,
                                 revision=is_revision)
        version = (1 if not deal["deliverable"]
                   else deal["deliverable"]["version"] + 1)
        deal["deliverable"] = {
            "title": f"{scenario['title']} deliverable",
            "content": content,
            "version": version,
            "quality": effective_quality,
            "produced_by": AGENTS[deal["seller_agent_id"]]["name"],
            "created_at": now_iso(),
        }
        deal["state"] = "delivered"
        kind = "revision_submitted" if is_revision else "delivery_submitted"
        add_event(deal, kind, "seller",
                  f"Seller submitted delivery version {version} "
                  f"({len(content.split())} words). It now goes to the "
                  f"verifier against the negotiated contract checks.",
                  {"version": version, "words": len(content.split())})
        return public_deal(deal)


# Idempotency key suffix per settlement leg. Kept as the legacy
# "<deal id>-price-payout" style values so the keys recorded on older
# ledger entries stay readable.
_SETTLEMENT_LEG_KEYS = {
    "price_payout": "price-payout",
    "bond_return": "bond-return",
    "price_refund": "price-refund",
    "bond_slash": "bond-slash",
}


# Payout batch/item statuses that mean the money has not moved yet and
# the batch may still resolve on a later read.
_PAYOUT_PENDING_STATUSES = {
    "PENDING", "ACKNOWLEDGED", "PROCESSING", "ONHOLD", "UNCLAIMED",
}


def _leg_key(deal, leg):
    """Idempotency key for one attempt of one settlement leg.

    The first attempt keeps the legacy "<deal id>-<leg>" key. A retry
    after PayPal terminally failed the batch (denied, returned, ...)
    must use a fresh key, because PayPal dedupes on the batch id and a
    retry under the old key would just return the dead batch.
    """
    attempt = deal["settlement"]["legs"][leg].get("attempt", 1)
    suffix = _SETTLEMENT_LEG_KEYS[leg]
    if attempt > 1:
        suffix = f"{suffix}-attempt{attempt}"
    return _idem_key(deal, suffix)


async def _send_leg(deal, leg, send):
    """Send one settlement leg unless it was already sent.

    A leg recorded "sent" or "done" is never sent again, so a resumed
    settlement cannot move money twice. The idempotency key is
    deterministic per deal, leg, and attempt (see _leg_key). Returns
    True when the leg has been sent (now or earlier), False when the
    send failed and the deal must be resumed later.
    """
    entry = deal["settlement"]["legs"][leg]
    if entry["status"] in ("sent", "done"):
        return True
    key = _leg_key(deal, leg)
    try:
        result_id = await send(key)
    except PaymentError as exc:
        # Clean surface (queue item X): the raw PayPal body lives in the
        # ledger event and the server log under the correlation id, never
        # in the response. The id and code are stored on the leg entry so
        # the verify endpoint can answer with the same id.
        code = "REFUND_FAILED" if leg == "price_refund" else "PAYOUT_FAILED"
        _response, correlation_id = build_error_response(
            deal, code, exc, where=f"settlement:{leg}",
            event_type="payment_error",
            message=f"Settlement leg {leg} failed. The deal stays in the "
                    f"verifying state, so a later verify call resumes from "
                    f"the legs that are still missing instead of replaying "
                    f"the ones that already succeeded.")
        entry["status"] = "failed"
        entry["error_code"] = code
        entry["correlation_id"] = correlation_id
        return False
    entry["status"] = "sent"
    entry["request_id"] = key
    entry["result_id"] = result_id
    return True


def _set_leg_money_status(deal, leg, status):
    """Mirror a payout leg's confirmation status onto the money record."""
    if leg == "price_payout":
        deal["payment"]["payout_status"] = status
    elif leg in ("bond_return", "bond_slash"):
        deal["bond"]["payout_status"] = status
    deal["settlement"]["legs"][leg]["payout_status"] = status


async def _confirm_payout_leg(deal, payments, leg, finalize):
    """Follow a sent payout through to its terminal PayPal status.

    The payout create call only means PayPal accepted the batch; items
    can later be denied or returned. This reads the batch back: SUCCESS
    finalizes the leg, a pending status keeps the deal in verifying
    until a later verify re-reads it, and a terminal failure writes a
    correcting ledger event and marks the leg failed so the next verify
    retries it with a fresh idempotency key. Returns "done", "pending",
    or "failed".
    """
    entry = deal["settlement"]["legs"][leg]
    if entry["status"] == "done":
        return "done"
    batch_id = entry["result_id"]
    try:
        report = await payments.get_payout_status(batch_id)
    except PaymentError:
        # The status read itself failed; the money may or may not have
        # moved, so the leg stays sent and a later verify re-reads it.
        return "pending"
    statuses = {str(report.get("batch_status") or "").upper()}
    statuses.update(str(item.get("status") or "").upper()
                    for item in report.get("items", []))
    statuses.discard("")
    terminal = statuses - _PAYOUT_PENDING_STATUSES - {"SUCCESS"}
    if terminal:
        failed_status = sorted(terminal)[0].lower()
        entry["status"] = "failed"
        entry["attempt"] = entry.get("attempt", 1) + 1
        _set_leg_money_status(deal, leg, failed_status)
        add_event(deal, "payout_failed", "system",
                  f"Payout batch {batch_id} for settlement leg {leg} came "
                  f"back {failed_status}. The money did not move, so the "
                  f"deal is not marked settled on this payout. The leg is "
                  f"marked failed; a later verify retries it with a fresh "
                  f"idempotency key.")
        return "failed"
    if "SUCCESS" not in statuses:
        # Still in flight (or an unreadable status): record pending once
        # and wait for a later verify to read the status back.
        if entry.get("payout_status") != "pending":
            _set_leg_money_status(deal, leg, "pending")
            seen = sorted(statuses)[0].lower() if statuses else "unknown"
            add_event(deal, "payout_pending", "system",
                      f"Payout batch {batch_id} for settlement leg {leg} "
                      f"is {seen} at PayPal. The deal stays in the "
                      f"verifying state until PayPal reports the batch "
                      f"successful; a later verify call reads the status "
                      f"back. Nothing is marked released on a pending "
                      f"payout.")
        return "pending"
    finalize(entry["request_id"], batch_id)
    entry["status"] = "done"
    _set_leg_money_status(deal, leg, "success")
    return "done"



def _finalize_price_payout(deal, payments, key, batch_id):
    """Record a confirmed price payout leg (queue item D path).

    Module level so the webhook reconciliation path (queue item Y) can
    reuse the exact same follow-through the settlement flow uses: one
    implementation, one ledger shape, no duplicated money logic.
    """
    label = _mode_label(payments)
    price_c = deal["spec"]["price"]
    deal["payment"]["status"] = "released"
    add_event(deal, "payment_released", "system",
              f"Verification passed and PayPal reports the payout "
              f"batch successful. Payment of {money.dollars(price_c)} "
              f"USD released to the seller by payout ({label}). Payout "
              f"batch {batch_id}.",
              {"payout_batch_id": batch_id,
               "amount": money.dollars(price_c),
               "mode": payments.mode,
               "rail": deal["settlement"]["legs"]["price_payout"].get("rail"),
               "request_id": key})


def _finalize_bond_return(deal, payments, key, batch_id):
    """Record a confirmed bond return leg (queue item D path)."""
    label = _mode_label(payments)
    bond_amount_c = deal["spec"]["bond_amount"]
    deal["bond"]["status"] = "returned"
    add_event(deal, "bond_returned", "system",
              f"Performance bond of {money.dollars(bond_amount_c)} USD "
              f"returned to the seller by payout ({label}); PayPal "
              f"reports the batch successful. Payout batch {batch_id}.",
              {"payout_batch_id": batch_id,
               "amount": money.dollars(bond_amount_c),
               "mode": payments.mode,
               "rail": deal["settlement"]["legs"]["bond_return"].get("rail"),
               "request_id": key})


def _finalize_price_refund(deal, payments, key, refund_id):
    """Record a completed price refund leg."""
    label = _mode_label(payments)
    price_c = deal["spec"]["price"]
    deal["payment"]["status"] = "refunded"
    add_event(deal, "buyer_refunded", "system",
              f"Verification failed. The held payment of "
              f"{money.dollars(price_c)} USD was refunded to the buyer "
              f"through the PayPal refund call ({label}). Refund "
              f"{refund_id}.",
              {"refund_id": refund_id,
               "amount": money.dollars(price_c),
               "mode": payments.mode,
               "rail": deal["settlement"]["legs"]["price_refund"].get("rail"),
               "request_id": key})


def _finalize_bond_slash(deal, payments, key, batch_id):
    """Record a confirmed bond slash leg (queue item D path)."""
    label = _mode_label(payments)
    bond_amount_c = deal["spec"]["bond_amount"]
    deal["bond"]["status"] = "slashed"
    add_event(deal, "bond_slashed", "system",
              f"Performance bond of {money.dollars(bond_amount_c)} USD "
              f"slashed and paid to the buyer by payout ({label}); "
              f"PayPal reports the batch successful. Payout batch "
              f"{batch_id}.",
              {"payout_batch_id": batch_id,
               "amount": money.dollars(bond_amount_c),
               "mode": payments.mode,
               "rail": deal["settlement"]["legs"]["bond_slash"].get("rail"),
               "request_id": key})


# Webhook reconciliation (queue item Y). PayPal webhook event types that
# name a payout batch, either on the item or on the batch header.
_PAYOUT_WEBHOOK_TYPES = {
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", "PAYMENT.PAYOUTS-ITEM.FAILED",
    "PAYMENT.PAYOUTS-ITEM.DENIED", "PAYMENT.PAYOUTS-ITEM.RETURNED",
    "PAYMENT.PAYOUTS-ITEM.BLOCKED", "PAYMENT.PAYOUTS-ITEM.REFUNDED",
    "PAYMENT.PAYOUTS-ITEM.HELD", "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
    "PAYMENT.PAYOUTS-ITEM.ONHOLD", "PAYMENT.PAYOUTS-ITEM.PENDING",
    "PAYMENT.PAYOUTSBATCH.SUCCESS", "PAYMENT.PAYOUTSBATCH.DENIED",
    "PAYMENT.PAYOUTSBATCH.PROCESSING",
}

# Settlement legs with an item-D style payout read-back. The price refund
# is a synchronous capture refund, so it has no read-back path: a refund
# event for it is reconcile-checked as already-recorded or unknown.
_PAYOUT_LEG_FINALIZERS = {
    "price_payout": _finalize_price_payout,
    "bond_return": _finalize_bond_return,
    "bond_slash": _finalize_bond_slash,
}


def _webhook_batch_ids(resource):
    """Payout batch ids named by a webhook event's resource payload."""
    ids = []
    if not isinstance(resource, dict):
        return ids
    direct = resource.get("payout_batch_id")
    if direct:
        ids.append(str(direct))
    header = resource.get("batch_header") or {}
    if isinstance(header, dict) and header.get("payout_batch_id"):
        ids.append(str(header["payout_batch_id"]))
    return ids


async def _reconcile_payout_event(deal, event_type, event_id, resource,
                                  payments):
    """Advance payout reconciliation from one accepted payout event.

    For each settlement leg whose recorded batch id the event names, the
    leg is resolved through the exact item-D follow-through path
    (_confirm_payout_leg), which reads the batch back from PayPal itself.
    The event's own content is never trusted for a money decision; it
    only nudges the server to ask PayPal. A leg already done is a no-op.
    Every outcome is recorded as a ledger event naming the webhook event
    id. The deal never leaves "verifying" here: marking released or
    refunded stays the exclusive job of /verify, so a webhook can never
    by itself authorize a settlement decision.
    """
    legs = deal["settlement"]["legs"]
    batch_ids = _webhook_batch_ids(resource)
    named = [leg for leg, entry in legs.items()
             if entry.get("result_id") in batch_ids]
    if not named:
        add_event(deal, "webhook_reconcile", "paypal",
                  f"Webhook {event_id} ({event_type}) names payout batch "
                  f"{batch_ids or 'none'}, which this deal never sent. "
                  f"Logged and ignored; no state changed.",
                  {"webhook_event_id": event_id, "event_type": event_type,
                   "batch_ids": batch_ids, "action": "unknown_batch"})
        return
    for leg in named:
        entry = legs[leg]
        if leg not in _PAYOUT_LEG_FINALIZERS:
            add_event(deal, "webhook_reconcile", "paypal",
                      f"Webhook {event_id} ({event_type}) names the {leg} "
                      f"record (batch {entry.get('result_id')}), which is "
                      f"a synchronous capture refund with no payout "
                      f"read-back path. No state changed.",
                      {"webhook_event_id": event_id, "event_type": event_type,
                       "leg": leg, "action": "no_readback_path"})
            continue
        if entry["status"] == "done":
            add_event(deal, "webhook_reconcile", "paypal",
                      f"Webhook {event_id} ({event_type}) reports on payout "
                      f"batch {entry['result_id']} for leg {leg}, which is "
                      f"already done. No-op: the same final state, no money "
                      f"moved twice.",
                      {"webhook_event_id": event_id, "event_type": event_type,
                       "leg": leg, "action": "already_done"})
            continue
        if entry["status"] != "sent":
            add_event(deal, "webhook_reconcile", "paypal",
                      f"Webhook {event_id} ({event_type}) names payout batch "
                      f"{entry.get('result_id')} for leg {leg}, which is "
                      f"{entry['status']}, not sent. Nothing to read back; "
                      f"the leg is driven by /verify. No state changed.",
                      {"webhook_event_id": event_id, "event_type": event_type,
                       "leg": leg, "action": "not_sent"})
            continue
        result = await _confirm_payout_leg(
            deal, payments, leg,
            partial(_PAYOUT_LEG_FINALIZERS[leg], deal, payments))
        action = {"done": "leg_confirmed", "pending": "still_pending",
                  "failed": "leg_failed"}[result]
        add_event(deal, "webhook_reconcile", "paypal",
                  f"Webhook {event_id} ({event_type}) triggered the payout "
                  f"status read-back for leg {leg} (batch "
                  f"{entry.get('result_id')}). PayPal reports: {result}. "
                  f"The read-back is the authority; the event content was "
                  f"not trusted for the decision. The deal still leaves "
                  f"verifying only through /verify.",
                  {"webhook_event_id": event_id, "event_type": event_type,
                   "leg": leg, "action": action,
                   "batch_id": entry.get("result_id")})


def _reconcile_record_event(deal, event_type, event_id, resource):
    """Reconcile a non-payout event against the local record.

    Capture, refund, and order events carry no money action of their own
    on this path: the named resource is compared to what the deal flow
    already recorded. A match is a ledger-logged no-op; a resource the
    deal does not know is logged as unknown and ignored. A status that
    disagrees with the local record is noted, never acted on: only the
    deal flow moves money.
    """
    rid = resource.get("id") if isinstance(resource, dict) else None
    known = {
        "payment_order": deal["payment"].get("order_id"),
        "payment_capture": deal["payment"].get("capture_id"),
        "bond_order": deal["bond"].get("order_id"),
        "bond_capture": deal["bond"].get("capture_id"),
        "refund": deal["settlement"]["legs"]["price_refund"].get("result_id"),
    }
    if rid and rid in [v for v in known.values() if v]:
        add_event(deal, "webhook_reconcile", "paypal",
                  f"Webhook {event_id} ({event_type}) names {rid}, which "
                  f"the deal already records. No-op: local state already "
                  f"matches.",
                  {"webhook_event_id": event_id, "event_type": event_type,
                   "resource_id": rid, "action": "already_recorded"})
    else:
        add_event(deal, "webhook_reconcile", "paypal",
                  f"Webhook {event_id} ({event_type}) names "
                  f"{rid or 'no resource'}, which this deal does not know. "
                  f"Logged and ignored; no state changed.",
                  {"webhook_event_id": event_id, "event_type": event_type,
                   "resource_id": rid, "action": "unknown_resource"})


async def _reconcile_webhook_event(deal, event_type, event_id, verification,
                                   payload):
    """Advance reconciliation state from one accepted webhook event.

    Runs only for verified events in live mode. In demo mode the local
    simulator is the money authority and demo webhooks are synthetic, so
    they reconcile too (labeled honestly as not_configured demo traffic).
    An unverified event in live mode is only recorded, never reconciled.
    Takes the per-deal lock so a webhook racing /verify cannot interleave
    with settlement.
    """
    if SETTINGS.paypal_live and verification != "verified":
        return
    resource = payload.get("resource") if isinstance(payload, dict) else None
    async with _deal_lock(deal["id"]):
        if event_type in _PAYOUT_WEBHOOK_TYPES:
            payments = get_agent_payment_service()
            await _reconcile_payout_event(deal, event_type, event_id,
                                          resource, payments)
        else:
            _reconcile_record_event(deal, event_type, event_id, resource)




async def _settle_release(deal, payments):
    """Run the release legs in order.

    Each payout is sent, then its batch status is read back before the
    leg counts as done. Returns "settled", "pending", or "failed".
    """
    price_c = deal["spec"]["price"]
    bond_amount_c = deal["spec"]["bond_amount"]

    async def send_price(key):
        payout = await payments.payout(
            SETTINGS.seller_sandbox_email, price_c, "USD",
            f"Pact payment for deal {deal['id']}", request_id=key)
        deal["settlement"]["payout_request_id"] = key
        deal["settlement"]["payout_id"] = payout["payout_batch_id"]
        deal["settlement"]["legs"]["price_payout"]["rail"] = payout.get("rail")
        return payout["payout_batch_id"]

    async def send_bond(key):
        bond_payout = await payments.payout(
            SETTINGS.seller_sandbox_email, bond_amount_c, "USD",
            f"Pact bond return for deal {deal['id']}", request_id=key)
        deal["settlement"]["bond_payout_request_id"] = key
        deal["settlement"]["bond_payout_id"] = bond_payout["payout_batch_id"]
        deal["settlement"]["legs"]["bond_return"]["rail"] = bond_payout.get("rail")
        return bond_payout["payout_batch_id"]

    if not await _send_leg(deal, "price_payout", send_price):
        return "failed"
    result = await _confirm_payout_leg(
        deal, payments, "price_payout",
        partial(_finalize_price_payout, deal, payments))
    if result != "done":
        return result
    if not await _send_leg(deal, "bond_return", send_bond):
        return "failed"
    result = await _confirm_payout_leg(
        deal, payments, "bond_return",
        partial(_finalize_bond_return, deal, payments))
    if result != "done":
        return result
    deal["state"] = "released"
    AGENTS[deal["buyer_agent_id"]]["deals"] += 1
    AGENTS[deal["seller_agent_id"]]["deals"] += 1
    change_reputation(deal, deal["seller_agent_id"], 6,
                      "deal completed and the delivery passed verification")
    change_reputation(deal, deal["buyer_agent_id"], 3,
                      "deal completed and settled cleanly")
    return "settled"


async def _settle_refund(deal, payments):
    """Run the refund legs in order.

    The capture refund is synchronous in this version; the bond slash
    payout is read back before it counts as done. Returns "settled",
    "pending", or "failed".
    """
    price_c = deal["spec"]["price"]
    bond_amount_c = deal["spec"]["bond_amount"]

    async def send_refund(key):
        refund = await payments.refund(
            deal["payment"]["capture_id"], price_c, "USD", request_id=key)
        deal["settlement"]["refund_request_id"] = key
        deal["settlement"]["refund_id"] = refund["refund_id"]
        deal["settlement"]["legs"]["price_refund"]["rail"] = refund.get("rail")
        return refund["refund_id"]

    def finalize_refund(key, refund_id):
        _finalize_price_refund(deal, payments, key, refund_id)

    async def send_slash(key):
        slash = await payments.payout(
            SETTINGS.buyer_sandbox_email, bond_amount_c, "USD",
            f"Pact bond slash for deal {deal['id']}", request_id=key)
        deal["settlement"]["bond_slash_request_id"] = key
        deal["settlement"]["bond_payout_id"] = slash["payout_batch_id"]
        deal["settlement"]["legs"]["bond_slash"]["rail"] = slash.get("rail")
        return slash["payout_batch_id"]

    def finalize_slash(key, batch_id):
        _finalize_bond_slash(deal, payments, key, batch_id)

    refund_entry = deal["settlement"]["legs"]["price_refund"]
    if refund_entry["status"] != "done":
        if not await _send_leg(deal, "price_refund", send_refund):
            return "failed"
        finalize_refund(refund_entry["request_id"], refund_entry["result_id"])
        refund_entry["status"] = "done"
    if not await _send_leg(deal, "bond_slash", send_slash):
        return "failed"
    result = await _confirm_payout_leg(deal, payments, "bond_slash",
                                       finalize_slash)
    if result != "done":
        return result
    deal["state"] = "refunded"
    AGENTS[deal["buyer_agent_id"]]["deals"] += 1
    AGENTS[deal["seller_agent_id"]]["deals"] += 1
    change_reputation(deal, deal["seller_agent_id"], -12,
                      "delivery failed verification and the buyer was refunded")
    change_reputation(deal, deal["seller_agent_id"], -20,
                      "performance bond slashed after the failed delivery")
    change_reputation(deal, deal["buyer_agent_id"], 1,
                      "followed the contract process and was made whole")
    return "settled"



@app.post("/api/deals/{deal_id}/verify",
           description="Runs the deterministic verifier over the delivery "
                       "and settles the deal: release payout or refund plus "
                       "bond slash, recorded leg by leg and resumable after "
                       "a failure.")
async def verify(deal_id: str, request: Request):
    deal = _deal_or_404(deal_id)
    # The verifier action itself stays server side; either side's token
    # is accepted so both the buyer and the seller can trigger it.
    _require_deal_role(deal, request, "buyer", "seller")
    async with _deal_lock(deal_id):
        _require_state(deal, ["delivered", "verifying"], "verify")
        payments = get_agent_payment_service()
        if deal["state"] == "delivered" or deal.get("verification") is None:
            # Fresh verdict. A deal already in "verifying" with no verdict
            # recorded means the verifier itself never finished, so it is
            # re-run rather than resumed.
            deal["state"] = "verifying"
            outcome = verify_delivery(deal["spec"],
                                      deal["deliverable"]["content"])
            deal["verification"] = {
                **outcome,
                # Verification round number follows the revision counter:
                # round 1 is the first delivery, round 2 the first
                # revision, and so on.
                "round": deal.get("revisions_used", 0) + 1,
                "checked_at": now_iso(),
            }
            for result in outcome["results"]:
                verdict = "PASS" if result["passed"] else "FAIL"
                add_event(deal, "verification_check", "verifier",
                          f"Check {result['check_id']}: {verdict}. "
                          f"{result['reason']}",
                          {"check_id": result["check_id"],
                           "passed": result["passed"],
                           "measured": result["measured"],
                           "required": result["required"]})
            add_event(deal, "verification_summary", "verifier",
                      f"Verification round {deal['verification']['round']}: "
                      f"{outcome['passed_count']} of {outcome['total_count']} "
                      f"negotiated checks passed. Judged against the frozen "
                      f"contract {deal.get('contract_hash', '')[:16]}..., "
                      f"the same hash carried on the PayPal order record.",
                      {"passed": outcome["passed_count"],
                       "total": outcome["total_count"],
                       "contract_hash": deal.get("contract_hash")})
        outcome = deal["verification"]
        path = deal["settlement"].get("path")
        # Revision allowance: single-issue deals keep exactly one round
        # (the shipped behavior); multi-issue deals use the negotiated
        # revision rounds from the frozen terms.
        revisions_allowed = (deal["terms"]["revision_rounds"]
                             if deal.get("terms") else 1)
        revisions_used = deal.get("revisions_used", 0)
        if path is None:
            # The settlement path is decided once, on the first verify.
            # Resumes reuse it; the revision branch is never re-entered
            # for a deal whose settlement already started.
            if outcome["all_passed"]:
                path = "release"
            elif revisions_used < revisions_allowed and outcome["any_passed"]:
                deal["revisions_used"] = revisions_used + 1
                deal["revision_used"] = True
                deal["state"] = "revision"
                rounds_word = ("round" if revisions_allowed == 1
                               else "rounds")
                add_event(deal, "revision_requested", "verifier",
                          f"Some checks passed and some failed, so the "
                          f"contract allows {revisions_allowed} revision "
                          f"{rounds_word} (this is revision "
                          f"{revisions_used + 1}). The seller must fix the "
                          f"failed checks and deliver again. A fail after "
                          f"the allowed revision rounds refunds the buyer "
                          f"and slashes the bond.")
                change_reputation(deal, deal["seller_agent_id"], -3,
                                  "delivery needed a revision round")
                return public_deal(deal)
            else:
                if revisions_used == 0 and not outcome["any_passed"]:
                    add_event(deal, "revision_skipped", "verifier",
                              "No checks passed at all, so there is nothing "
                              "to revise against. The contract sends this "
                              "straight to a refund and a bond slash.")
                elif revisions_used >= revisions_allowed:
                    add_event(deal, "revisions_exhausted", "verifier",
                              f"The contract allowed {revisions_allowed} "
                              f"revision round(s) and all were used. The "
                              f"deal goes to a refund and a bond slash.")
                path = "refund"
            deal["settlement"]["path"] = path
        try:
            outcome = (await _settle_release(deal, payments)
                       if path == "release"
                       else await _settle_refund(deal, payments))
        except UpstreamFailure as failed:
            return failed.response
        except PaymentError as exc:
            # Defensive: the leg senders record their own clean errors.
            # Anything escaping them still gets the clean surface.
            raise_upstream(deal, "UPSTREAM_UNAVAILABLE", exc,
                           where="verify:settlement",
                           event_type="payment_error")
        if outcome == "failed":
            # The failing leg already recorded its clean error with a
            # correlation id on its leg entry; answer with the same id
            # so the response, the ledger event, and the log line agree.
            failed_entry = next(
                (e for e in deal["settlement"]["legs"].values()
                 if e.get("status") == "failed"),
                None) or {}
            code = failed_entry.get("error_code") or "PAYOUT_FAILED"
            correlation_id = failed_entry.get("correlation_id")
            if not correlation_id:
                response, correlation_id = build_error_response(
                    deal, code, None, where="verify:settlement",
                    event_type="payment_error")
                return response
            status, message = ERROR_CODES[code]
            return JSONResponse(
                status_code=status,
                content={"error": {
                    "code": code,
                    "message": message,
                    "correlation_id": correlation_id,
                }},
            )
        # "pending" also returns 200: the money calls were accepted and
        # the deal waits in verifying for PayPal to report the payout
        # batches successful. A later verify reads the statuses back.
        return public_deal(deal)


@app.post("/webhooks/paypal",
           description="Receives PayPal webhook events. Verifies the event "
                       "signature when a webhook id is configured; events "
                       "without one are recorded as unverified. A verified "
                       "event can advance reconciliation (a payout event can "
                       "trigger the same payout status read-back the deal "
                       "flow uses), but it never authorizes a settlement "
                       "decision: settlement is driven by direct API "
                       "responses in the deal flow.")
async def paypal_webhook(request: Request):
    """Receive a PayPal webhook and record it on the matching deal.

    When a webhook ID is configured (PAYPAL_WEBHOOK_ID) and the app runs
    with live sandbox credentials, the signature is verified with PayPal
    before the event is accepted, and a failed verification is rejected
    with a 400. Without a webhook ID the event is recorded and plainly
    labeled unverified. Either way this endpoint never authorizes
    settlement: a verified event may advance reconciliation state (for
    example a payout event triggers the same payout status read-back the
    settlement flow uses, reading PayPal itself rather than trusting the
    event content), but the deal leaves "verifying" only through /verify,
    so a forged webhook cannot move money.

    Event-id idempotency: PayPal retries deliveries, so a second arrival
    of an already-recorded event id is acked exactly like the first (200,
    received true, same matched deal, so PayPal stops retrying) but
    appends no second ledger event. The id is claimed before signature
    verification, so even an in-flight first delivery cannot race a
    duplicate; a delivery that is rejected or errors is unclaimed, so its
    retry is verified and recorded like a new delivery.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    event_type = payload.get("event_type", "unknown")
    event_id = payload.get("id")
    if isinstance(event_id, bool) or not isinstance(event_id, (str, int)):
        event_id = None
    else:
        event_id = str(event_id)
    raw = str(payload)
    matched = None
    for deal in DEALS.values():
        ids = [deal["payment"].get("order_id"), deal["payment"].get("capture_id"),
               deal["bond"].get("order_id"), deal["bond"].get("capture_id"),
               deal["settlement"].get("payout_id"),
               deal["settlement"].get("bond_payout_id"),
               deal["settlement"].get("refund_id")]
        for entry in deal["settlement"]["legs"].values():
            ids.append(entry.get("result_id"))
        if any(i and i in raw for i in ids):
            matched = deal
            break

    if event_id and claim_webhook_event(event_id):
        record = get_webhook_record(event_id) or {}
        return {"received": True, "event_type": event_type,
                "matched_deal": matched["id"] if matched else None,
                "signature_verification":
                    record.get("signature_verification") or "not_configured",
                "duplicate": True}

    verification = "not_configured"
    if SETTINGS.paypal_live and SETTINGS.paypal_webhook_id:
        headers = {k.lower(): v for k, v in request.headers.items()}
        try:
            status = await PayPalClient().verify_webhook_signature(headers, payload)
        except PaymentError as exc:
            # The verification call itself failed (PayPal unreachable or
            # erroring). Fail closed with a 503 so PayPal retries later
            # instead of recording an event whose signature was never
            # actually checked. Unclaim the id so the retry re-verifies.
            # The raw failure goes to the server log under a correlation
            # id; the response carries only the clean shape (queue X).
            import uuid as _uuid
            correlation_id = _uuid.uuid4().hex
            log.error(json.dumps({
                "correlation_id": correlation_id,
                "code": "UPSTREAM_UNAVAILABLE",
                "where": "webhook:verify_signature",
                "upstream_detail": redact_upstream(str(exc)),
            }))
            if event_id:
                unclaim_webhook_event(event_id)
            return JSONResponse(
                status_code=503,
                content={"received": False, "event_type": event_type,
                         "matched_deal": matched["id"] if matched else None,
                         "signature_verification": "error",
                         "correlation_id": correlation_id,
                         "detail": "Signature verification could not be "
                                   "completed because PayPal did not "
                                   "answer. The event was not trusted. "
                                   "PayPal should retry this event."})
        if status == "SUCCESS":
            verification = "verified"
        elif status == "FAILURE":
            verification = "failed"
            # Rejected, never recorded: unclaim the id so a later retry
            # is verified and recorded like a new delivery.
            if event_id:
                unclaim_webhook_event(event_id)
            entry = {"timestamp": now_iso(), "event_type": event_type,
                     "payload": payload, "signature_verification": "failed"}
            if matched:
                add_event(matched, "webhook_rejected", "paypal",
                          f"Webhook rejected: {event_type}. PayPal signature "
                          f"verification failed, so the event was not trusted.")
            else:
                GLOBAL_EVENTS.append(entry)
            return JSONResponse(
                status_code=400,
                content={"received": False, "event_type": event_type,
                         "matched_deal": matched["id"] if matched else None,
                         "signature_verification": "failed"})

    entry = {"timestamp": now_iso(), "event_type": event_type,
             "payload": payload, "signature_verification": verification}
    if matched:
        if verification == "verified":
            note = "Signature verified with PayPal."
        elif verification == "not_configured":
            note = ("Recorded without signature verification: no webhook "
                    "ID is configured for this deployment.")
        else:
            note = f"Signature verification status: {verification}."
        add_event(matched, "webhook_received", "paypal",
                  f"Webhook received: {event_type}. {note}")
        # Queue item Y: a verified event may advance reconciliation state
        # through the same read-back paths the deal flow uses (a payout
        # event can resolve a pending payout leg), but it never trusts the
        # event content for a money decision and never authorizes
        # settlement: the deal leaves "verifying" only through /verify.
        await _reconcile_webhook_event(matched, event_type, event_id,
                                       verification, payload)
    else:
        GLOBAL_EVENTS.append(entry)
    if event_id:
        set_webhook_verification(event_id, verification)
    return {"received": True, "event_type": event_type,
            "matched_deal": matched["id"] if matched else None,
            "signature_verification": verification}


@app.get("/api/webhooks",
          description="Lists the PayPal webhook events received so far, "
                      "with their verification status.")
async def webhook_log():
    return GLOBAL_EVENTS

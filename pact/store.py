"""In memory store for deals, the audit ledger, and agent reputation.

State lives in the working dicts below during a run, and pact.persistence
writes them to SQLite after every HTTP response (and on shutdown), so a
restart or a Render sleep cycle never wipes a deal. Every meaningful event
is appended to the deal ledger with a timestamp, and the same ledger backs
the AG Grid table in the UI.

Money convention (queue item V): every money amount on a deal record is
an integer number of US cents. new_deal() takes integer cents for the
price bounds; the spec, the payment/bond records, and the negotiation
all carry cents. Dollars appear only at the public edges: public_deal()
converts the money fields back to dollars for API responses, and
human-readable records (ledger messages, move labels, the dispute
packet) are written in dollars. See pact/money.py for the parse
boundary and the exact-arithmetic helpers.
"""

import itertools
import secrets
import threading
from datetime import datetime, timezone

from . import money as _money

_lock = threading.Lock()
# Legacy deal id counter (queue item W): deal ids are random now (see
# _new_deal_id), so this counter no longer mints ids. It is kept because
# pact.persistence reseeds it from old deal-NNNN ids on startup; the
# reseeding is a no-op for random pact- ids and must stay that way.
_deal_counter = itertools.count(1)

DEALS = {}
GLOBAL_EVENTS = []


def _new_deal_id():
    """Mint a random, unguessable deal id (queue item W).

    Short human readable prefix plus url-safe random bits. Random ids
    mean a neighbor's deal cannot be found by counting up from your own,
    which the old sequential deal-NNNN ids allowed. Collisions are
    retried, not assumed away.
    """
    for _ in range(10):
        candidate = f"pact-{secrets.token_urlsafe(9)}"
        if candidate not in DEALS:
            return candidate
    raise RuntimeError("could not mint a unique deal id")

# Reputation starts at a neutral baseline per persona. Completed deals raise
# it. A triggered revision costs a little. A refund costs more. A slashed
# bond cuts it hard. Every change is written to the deal ledger with a reason.
AGENTS = {
    "buyer_main": {
        "id": "buyer_main",
        "name": "Buyer Agent",
        "role": "buyer",
        "persona": "Represents the buyer principal in every scenario",
        "reputation": 80,
        "deals": 0,
    },
    "seller_forma": {
        "id": "seller_forma",
        "name": "Forma Studio Seller Agent",
        "role": "seller",
        "persona": "Small brand studio that sells logo and brand kit work",
        "reputation": 82,
        "deals": 0,
    },
    "seller_copycraft": {
        "id": "seller_copycraft",
        "name": "Copycraft Seller Agent",
        "role": "seller",
        "persona": "Copywriting studio that sells landing page copy",
        "reputation": 82,
        "deals": 0,
    },
    "seller_fastcopy": {
        "id": "seller_fastcopy",
        "name": "FastCopy Seller Agent",
        "role": "seller",
        "persona": "Volume content shop. Its work does not always match the brief.",
        "reputation": 64,
        "deals": 0,
    },
    "seller_codecraft": {
        "id": "seller_codecraft",
        "name": "Codecraft Seller Agent",
        "role": "seller",
        "persona": "Small dev shop that sells scoped coding tasks",
        "reputation": 82,
        "deals": 0,
    },
    "seller_briefline": {
        "id": "seller_briefline",
        "name": "Briefline Seller Agent",
        "role": "seller",
        "persona": "Research shop that sells sourced market briefs",
        "reputation": 82,
        "deals": 0,
    },
    "seller_listly": {
        "id": "seller_listly",
        "name": "Listly Seller Agent",
        "role": "seller",
        "persona": "Marketplace copy shop that writes product listings",
        "reputation": 82,
        "deals": 0,
    },
    "seller_shopwise": {
        "id": "seller_shopwise",
        "name": "Shopwise Seller Agent",
        "role": "seller",
        "persona": "Procurement agent that buys real retail products "
                   "grounded in Channel3 market offers",
        "reputation": 82,
        "deals": 0,
    },
    "seller_labelwise": {
        "id": "seller_labelwise",
        "name": "Labelwise Seller Agent",
        "role": "seller",
        "persona": "Data labeling shop that ships labeled batches with "
                   "a written guide and flagged rows",
        "reputation": 82,
        "deals": 0,
    },
    "seller_waveform": {
        "id": "seller_waveform",
        "name": "Waveform Seller Agent",
        "role": "seller",
        "persona": "Podcast editor that ships chapters, timestamps, "
                   "transcripts, and show notes",
        "reputation": 82,
        "deals": 0,
    },
    "seller_inboxpress": {
        "id": "seller_inboxpress",
        "name": "Inboxpress Seller Agent",
        "role": "seller",
        "persona": "Newsletter writer that ships full issues with subject "
                   "lines and proper footers",
        "reputation": 82,
        "deals": 0,
    },
    "seller_lenswork": {
        "id": "seller_lenswork",
        "name": "Lenswork Seller Agent",
        "role": "seller",
        "persona": "Product photographer that ships shot manifests with "
                   "specs per photo",
        "reputation": 82,
        "deals": 0,
    },
    "seller_spinebound": {
        "id": "seller_spinebound",
        "name": "Spinebound Seller Agent",
        "role": "seller",
        "persona": "Cover designer that ships concept packages with spine, "
                   "back cover, and palette",
        "reputation": 82,
        "deals": 0,
    },
    "seller_plugwise": {
        "id": "seller_plugwise",
        "name": "Plugwise Seller Agent",
        "role": "seller",
        "persona": "Integration dev that wraps APIs with authentication, "
                   "error handling, and docs",
        "reputation": 82,
        "deals": 0,
    },
    "seller_tidygrid": {
        "id": "seller_tidygrid",
        "name": "Tidygrid Seller Agent",
        "role": "seller",
        "persona": "Data cleaner that ships cleaned sheets with a findings "
                   "report and a change log",
        "reputation": 82,
        "deals": 0,
    },
    "seller_coolair": {
        "id": "seller_coolair",
        "name": "Coolair Seller Agent",
        "role": "seller",
        "persona": "HVAC tech that ships a written service report with "
                   "diagnosis, part, readings, and warranty",
        "reputation": 82,
        "deals": 0,
    },
}

# The deal state machine. A deal moves forward through these states and ends
# in exactly one of released, refunded, or failed. awaiting_approval only
# happens in sandbox mode: PayPal makes the account holder approve each
# order in a browser before it can be captured.
STATES = [
    "negotiating",
    "agreed",
    "awaiting_approval",
    "paid_held",
    "delivered",
    "verifying",
    "revision",
    "released",
    "refunded",
    "failed",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def new_deal(scenario, buyer_max_cents, seller_floor_cents, bond_percent,
             multi_issue=False):
    """Create a deal. buyer_max_cents and seller_floor_cents are integer
    cents (queue item V): callers parse dollar inputs with
    pact.money.to_cents() first, so the deal record never holds a float
    amount. bond_percent is a percent like 20.0, not money.
    """
    for name, value in (("buyer_max_cents", buyer_max_cents),
                        ("seller_floor_cents", seller_floor_cents)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"{name} must be integer cents; parse dollar amounts with "
                f"pact.money.to_cents() first. Got {value!r}.")
    with _lock:
        deal_id = _new_deal_id()
    deal = {
        "id": deal_id,
        # Per-deal role tokens (queue item W): random unguessable bearer
        # tokens issued at creation. State-changing endpoints require the
        # right role's token in the X-Deal-Token header; the demo UI
        # carries them from the create response. This is demo-grade role
        # separation, not full user auth: there are no accounts behind
        # these tokens. Deals persisted before tokens shipped carry no
        # tokens and are grandfathered past the check, so old deals keep
        # working.
        "buyer_token": secrets.token_urlsafe(24),
        "seller_token": secrets.token_urlsafe(24),
        "scenario_id": scenario["id"],
        "scenario_title": scenario["title"],
        "service_summary": scenario["service_summary"],
        "buyer_agent_id": "buyer_main",
        "seller_agent_id": scenario["seller_id"],
        "state": "negotiating",
        "buyer_max": buyer_max_cents,
        "seller_floor": seller_floor_cents,
        "bond_percent": float(bond_percent),
        "currency": "USD",
        # Multi-issue terms negotiation (queue item S). Off by default;
        # the terms phase runs between the price phase and the contract
        # phase and can never undo a price agreement.
        "multi_issue": bool(multi_issue),
        # Negotiated terms once agreed: delivery_days, revision_rounds,
        # bond_percent. None until the terms phase settles.
        "terms": None,
        "terms_moves": 0,
        "moves": [],
        "spec": None,
        "agreed_price": None,
        "negotiation_rounds": 0,
        "payment": {
            "status": "not_started",
            "order_id": None,
            "capture_id": None,
            "amount": None,
            "mode": None,
            "order_request_id": None,
            "capture_request_id": None,
            # Payout follow through (queue item D): None until the price
            # payout is sent, then "pending" until PayPal reports the
            # batch successful, then "success", or the terminal status
            # PayPal reported (denied, returned, ...).
            "payout_status": None,
        },
        "bond": {
            "status": "not_posted",
            "order_id": None,
            "capture_id": None,
            "amount": None,
            "mode": None,
            "order_request_id": None,
            "capture_request_id": None,
            "payout_status": None,
        },
        "settlement": {
            "payout_id": None,
            "bond_payout_id": None,
            "refund_id": None,
            "payout_request_id": None,
            "bond_payout_request_id": None,
            "refund_request_id": None,
            "bond_slash_request_id": None,
            # Settlement runs one leg at a time and records each leg as it
            # completes, so a failed leg can be resumed without rerunning
            # the legs that already succeeded. "path" is "release" or
            # "refund", decided once at the first verify and never
            # re-decided on a resume.
            "path": None,
            "legs": {
                "price_payout": {"status": "pending", "attempt": 1,
                                 "request_id": None, "result_id": None,
                                 "payout_status": None},
                "bond_return": {"status": "pending", "attempt": 1,
                                "request_id": None, "result_id": None,
                                "payout_status": None},
                "price_refund": {"status": "pending", "attempt": 1,
                                 "request_id": None, "result_id": None,
                                 "payout_status": None},
                "bond_slash": {"status": "pending", "attempt": 1,
                               "request_id": None, "result_id": None,
                               "payout_status": None},
            },
        },
        "deliverable": None,
        "verification": None,
        "revision_used": False,
        # Counter for the negotiated revision rounds (queue item S).
        # Single-issue deals allow one round, exactly as before;
        # multi-issue deals allow deal["terms"]["revision_rounds"].
        "revisions_used": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "ledger": [],
    }
    DEALS[deal_id] = deal
    add_event(deal, "deal_created", "system",
              f"Deal created for scenario {scenario['title']}. "
              f"Buyer ceiling and seller floor are set. Negotiation can begin.")
    return deal


def add_event(deal, event_type, actor, message, data=None):
    entry = {
        "seq": len(deal["ledger"]) + 1,
        "timestamp": now_iso(),
        "deal_id": deal["id"],
        "event_type": event_type,
        "actor": actor,
        "message": message,
        "data": data or {},
    }
    deal["ledger"].append(entry)
    deal["updated_at"] = now_iso()
    return entry


def change_reputation(deal, agent_id, delta, reason):
    """Apply a reputation change and record it in the deal ledger."""
    agent = AGENTS[agent_id]
    old = agent["reputation"]
    new = max(0, min(100, old + delta))
    agent["reputation"] = new
    sign = "+" if delta >= 0 else ""
    add_event(
        deal,
        "reputation_change",
        "system",
        f"Reputation for {agent['name']} moved {sign}{delta} from {old} to "
        f"{new}. Reason: {reason}.",
        {"agent_id": agent_id, "delta": delta, "from": old, "to": new,
         "reason": reason},
    )
    return new


def public_grounding(grounding):
    """Copy a Channel3 grounding record with cent prices as dollars.

    The stored grounding keeps integer cents (parsed once in channel3);
    the API shows dollars, like every other money field.
    """
    out = dict(grounding)
    for key in ("lowest_price", "median_price", "highest_price",
                "buyer_max", "seller_floor"):
        if out.get(key) is not None:
            out[key] = _money.dollars(out[key])
    offers = []
    for offer in grounding.get("offers", []) or []:
        offer = dict(offer)
        if offer.get("price") is not None:
            offer["price"] = _money.dollars(offer["price"])
        offers.append(offer)
    out["offers"] = offers
    chosen = grounding.get("chosen_offer")
    if chosen:
        chosen = dict(chosen)
        if chosen.get("price") is not None:
            chosen["price"] = _money.dollars(chosen["price"])
        out["chosen_offer"] = chosen
    return out


def public_deal(deal):
    """Deal view for the API, with live reputation attached to both agents.

    Money fields are integer cents on the stored deal (queue item V);
    this view converts them back to dollars, so the public API keeps
    displaying dollars exactly the way it always has. Shallow copies at
    each converted level keep the stored record untouched.
    """
    out = dict(deal)
    out["buyer_agent"] = AGENTS[deal["buyer_agent_id"]]
    out["seller_agent"] = AGENTS[deal["seller_agent_id"]]
    # Role tokens ride the public view (queue item W) so the demo UI can
    # carry them on state-changing calls. Old tokenless deals report None.
    out["buyer_token"] = deal.get("buyer_token")
    out["seller_token"] = deal.get("seller_token")
    for key in ("buyer_max", "seller_floor", "agreed_price"):
        if out.get(key) is not None:
            out[key] = _money.dollars(out[key])
    for key in ("payment", "bond"):
        sub = dict(out[key])
        if sub.get("amount") is not None:
            sub["amount"] = _money.dollars(sub["amount"])
        out[key] = sub
    spec = out.get("spec")
    if spec:
        spec = dict(spec)
        spec["price"] = _money.dollars(spec["price"])
        spec["bond_amount"] = _money.dollars(spec["bond_amount"])
        checks = []
        for chk in spec["acceptance_checks"]:
            chk = dict(chk)
            if chk.get("kind") == "max_price" and chk.get("value") is not None:
                chk["value"] = _money.dollars(chk["value"])
            checks.append(chk)
        spec["acceptance_checks"] = checks
        out["spec"] = spec
    if out.get("market"):
        out["market"] = public_grounding(out["market"])
    return out


# Webhook event-id dedup (chaos item T, part 4). PayPal retries webhook
# deliveries, so the same event id can arrive twice. Seen event ids live
# here as an insertion-ordered dict {event_id: record}, bounded at
# MAX_SEEN_WEBHOOK_IDS with the oldest ids evicted first, and
# pact.persistence writes them to SQLite after every response, so a
# restart never forgets an id it already recorded. Webhooks never
# authorize settlement; verified events may trigger a reconciliation
# read-back (queue item Y). The dedup exists so the audit trail records
# each event exactly once.
MAX_SEEN_WEBHOOK_IDS = 5000
SEEN_WEBHOOK_IDS = {}


def claim_webhook_event(event_id):
    """Atomically mark a webhook event id as seen.

    Returns True when the id was already seen, meaning this is a
    duplicate delivery the caller must ack without appending another
    ledger event. Returns False on first delivery. The stored record is
    a placeholder until set_webhook_verification fills in the label the
    first delivery was accepted with. Claiming before verification means
    even an in-flight first delivery cannot race a duplicate.
    """
    with _lock:
        if event_id in SEEN_WEBHOOK_IDS:
            return True
        SEEN_WEBHOOK_IDS[event_id] = {
            "seen_at": now_iso(),
            "signature_verification": None,
        }
        while len(SEEN_WEBHOOK_IDS) > MAX_SEEN_WEBHOOK_IDS:
            SEEN_WEBHOOK_IDS.pop(next(iter(SEEN_WEBHOOK_IDS)))
        return False


def get_webhook_record(event_id):
    """Return a copy of the stored record for a seen event id, or None."""
    with _lock:
        record = SEEN_WEBHOOK_IDS.get(event_id)
        return dict(record) if record is not None else None


def set_webhook_verification(event_id, verification):
    """Fill in the verification label on a claimed event id."""
    with _lock:
        record = SEEN_WEBHOOK_IDS.get(event_id)
        if record is not None:
            record["signature_verification"] = verification


def unclaim_webhook_event(event_id):
    """Forget an event id so a later delivery is treated as first.

    Used when the delivery was not accepted (signature verification
    failed or errored): the event was never recorded, so a PayPal retry
    must be verified and recorded like a new delivery.
    """
    with _lock:
        SEEN_WEBHOOK_IDS.pop(event_id, None)


def snapshot_webhook_seen():
    """Ordered (event_id, seen_at, signature_verification) rows for
    persistence. Insertion order is oldest first."""
    with _lock:
        return [(eid, rec["seen_at"], rec["signature_verification"])
                for eid, rec in SEEN_WEBHOOK_IDS.items()]


def restore_webhook_seen(rows):
    """Wholesale replace of the seen event ids (used by load_all)."""
    with _lock:
        SEEN_WEBHOOK_IDS.clear()
        for event_id, seen_at, verification in rows[-MAX_SEEN_WEBHOOK_IDS:]:
            SEEN_WEBHOOK_IDS[event_id] = {
                "seen_at": seen_at,
                "signature_verification": verification,
            }

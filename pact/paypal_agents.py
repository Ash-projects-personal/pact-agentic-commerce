"""Agent facing PayPal layer built on the official PayPal Agent Toolkit.

This is the primary rail the agents in Pact invoke for PayPal actions.

The toolkit (PyPI package paypal-agent-toolkit, from PayPal) ships a set of
named tools and a framework independent dispatch core,
paypal_agent_toolkit.shared.api.PayPalAPI, whose run(method, params) entry
point executes a tool by name. The framework wrappers PayPal publishes for
the OpenAI Agents SDK, LangChain, CrewAI, and Bedrock all sit on top of that
same core. Pact calls the core directly, so creating and capturing orders go
through PayPal's own tool implementations, with PayPal's own parameter
schemas and payload builders, instead of hand rolled request bodies.

What the toolkit covers, and what it does not:

Covered here through the toolkit: create_order and pay_order (the toolkit
name for capture), plus get_order_details for reads.

Not shipped as toolkit tools: payouts and capture refunds. The toolkit tool
list has no payout tool and no capture refund tool (its only refund tool
records a refund against an invoice). Those two actions therefore run
through the direct REST client in payments.py, which is also the fallback
for orders if the toolkit package cannot be imported in a given
environment. Every payment result carries a rail field that names which
path actually ran, and the ledger records it, so the split is never hidden.

Demo mode never touches this layer for money movement. With no credentials
configured the app uses the local simulator from payments.py and labels it.
"""

import asyncio
import json

from . import money
from .config import SETTINGS
from .payments import DemoSimulator, PayPalClient, PaymentError

TOOLKIT_AVAILABLE = False
TOOLKIT_IMPORT_ERROR = None
try:
    from paypal_agent_toolkit.shared.api import PayPalAPI
    from paypal_agent_toolkit.shared.configuration import Configuration, Context

    TOOLKIT_AVAILABLE = True
except Exception as exc:  # package missing or a dependency conflict
    TOOLKIT_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def toolkit_status():
    return {
        "installed": TOOLKIT_AVAILABLE,
        "import_error": TOOLKIT_IMPORT_ERROR,
        "orders_rail": (
            "agent_toolkit" if (SETTINGS.paypal_live and TOOLKIT_AVAILABLE)
            else "rest" if SETTINGS.paypal_live
            else "demo_simulator"
        ),
        "payouts_rail": "rest" if SETTINGS.paypal_live else "demo_simulator",
        "refunds_rail": "rest" if SETTINGS.paypal_live else "demo_simulator",
    }


class ToolkitOrders:
    """Orders through the PayPal Agent Toolkit tool dispatch."""

    def __init__(self, settings=SETTINGS):
        sandbox = "sandbox" in settings.paypal_base_url
        self._configuration = Configuration(
            actions={"orders": {"create": True, "capture": True, "get": True}},
            context=Context(sandbox=sandbox),
        )
        api_kwargs = {"client_id": settings.paypal_client_id,
                      "secret": settings.paypal_client_secret,
                      "context": self._configuration.context}
        self._api = PayPalAPI(**api_kwargs)

    async def create_order(self, amount, currency, reference, request_id=None,
                         contract_tag=None):
        # The toolkit dispatch core exposes no PayPal-Request-Id parameter,
        # so request_id is accepted for interface parity with the REST
        # rail and cannot be forwarded on this path. amount is integer
        # cents (queue item V); the toolkit wants decimal dollars.
        item_name = reference
        if contract_tag:
            # The toolkit's create_order tool exposes no custom_id, so the
            # closest field it supports is the line item name. The deal id
            # and the SHA-256 of the frozen spec ride there instead, and
            # the ledger records honestly which field carried the hash.
            item_name = f"{reference} | contract {contract_tag}"
        params = {
            "currency_code": currency,
            "items": [{
                "name": item_name,
                "quantity": 1,
                "item_cost": money.dollars(amount),
                "item_total": money.dollars(amount),
            }],
        }
        # The toolkit dispatch core raises its own exceptions (for
        # example RuntimeError when PayPal rejects the credentials),
        # not PaymentError. Convert any of them so the app returns a
        # clean payment error instead of a 500. Found live 2026-10-24:
        # a wrong client secret on Render surfaced as INTERNAL_ERROR.
        try:
            raw = await asyncio.to_thread(self._api.run, "create_order", params)
        except Exception as exc:
            raise PaymentError(
                f"Toolkit create_order failed: {type(exc).__name__}: {exc}"
            ) from exc
        data = json.loads(raw)
        if not data.get("id"):
            raise PaymentError(f"Toolkit create_order returned no order id: {raw}")
        approval_url = None
        for link in data.get("links", []):
            if link.get("rel") in ("approve", "payer-action"):
                approval_url = link.get("href")
        return {"order_id": data["id"], "status": data.get("status"),
                "approval_url": approval_url,
                "demo": False, "rail": "agent_toolkit",
                "hash_field": "item_name" if contract_tag else None,
                "contract_tag": contract_tag}

    async def capture_order(self, order_id, request_id=None):
        # request_id accepted for interface parity; the toolkit dispatch
        # core exposes no idempotency parameter for pay_order.
        # Same conversion as create_order: the toolkit raises its own
        # exceptions, and the app must answer with a clean payment
        # error, never a 500.
        try:
            raw = await asyncio.to_thread(self._api.run, "pay_order",
                                          {"order_id": order_id})
        except Exception as exc:
            raise PaymentError(
                f"Toolkit pay_order failed: {type(exc).__name__}: {exc}"
            ) from exc
        data = json.loads(raw)
        capture = {}
        try:
            capture = (data["raw"]["purchase_units"][0]["payments"]
                       ["captures"][0])
        except (KeyError, IndexError, TypeError):
            pass
        capture_id = capture.get("id")
        status = capture.get("status") or data.get("status")
        if not capture_id or status != "COMPLETED":
            raise PaymentError(
                f"PayPal capture for order {order_id} did not complete: "
                f"status {status}, capture id {capture_id}. The funds are "
                f"not held, so the deal cannot move forward.")
        return {"capture_id": capture_id, "status": status,
                "demo": False, "rail": "agent_toolkit"}

    async def get_order_details(self, order_id):
        try:
            raw = await asyncio.to_thread(self._api.run, "get_order_details",
                                          {"order_id": order_id})
        except Exception as exc:
            raise PaymentError(
                f"Toolkit get_order_details failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return json.loads(raw)


class AgentPaymentService:
    """One interface for the app. Routes each action to its proper rail.

    Orders go through the Agent Toolkit when it is importable, and fall
    back to the direct REST client when it is not. Payouts and refunds go
    through the direct REST client because the toolkit ships no tool for
    them. Demo mode routes everything to the local simulator.
    """

    def __init__(self, settings=SETTINGS):
        self.settings = settings
        if not settings.paypal_live:
            self.mode = "demo"
            self._sim = DemoSimulator()
            self._rest = None
            self._toolkit = None
            return
        self.mode = "sandbox"
        self._sim = None
        self._rest = PayPalClient(settings)
        self._toolkit = ToolkitOrders(settings) if TOOLKIT_AVAILABLE else None

    async def create_order(self, amount, currency, reference, request_id=None,
                         contract_tag=None):
        if self._sim:
            return await self._sim.create_order(amount, currency, reference,
                                                request_id=request_id,
                                                contract_tag=contract_tag)
        if self._toolkit:
            return await self._toolkit.create_order(amount, currency, reference,
                                                    request_id=request_id,
                                                    contract_tag=contract_tag)
        return await self._rest.create_order(amount, currency, reference,
                                             request_id=request_id,
                                             contract_tag=contract_tag)

    async def capture_order(self, order_id, request_id=None):
        if self._sim:
            return await self._sim.capture_order(order_id,
                                                 request_id=request_id)
        if self._toolkit:
            return await self._toolkit.capture_order(order_id,
                                                     request_id=request_id)
        return await self._rest.capture_order(order_id, request_id=request_id)

    async def payout(self, receiver_email, amount, currency, note,
                     request_id=None):
        if self._sim:
            return await self._sim.payout(receiver_email, amount, currency,
                                          note, request_id=request_id)
        return await self._rest.payout(receiver_email, amount, currency, note,
                                       request_id=request_id)

    async def refund(self, capture_id, amount, currency, request_id=None):
        if self._sim:
            return await self._sim.refund(capture_id, amount, currency,
                                          request_id=request_id)
        return await self._rest.refund(capture_id, amount, currency,
                                       request_id=request_id)

    async def get_payout_status(self, payout_batch_id):
        if self._sim:
            return await self._sim.get_payout_status(payout_batch_id)
        return await self._rest.get_payout_status(payout_batch_id)

    async def get_order_details(self, order_id):
        # Demo mode has no real orders, so there is nothing to read
        # back; the approval payer check skips demo mode entirely.
        if self._sim:
            raise PaymentError("no real orders exist in demo mode")
        if self._toolkit:
            return await self._toolkit.get_order_details(order_id)
        return await self._rest.get_order_details(order_id)


def get_agent_payment_service():
    return AgentPaymentService()

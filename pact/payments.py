"""Payment rails for Pact.

Two implementations share one interface.

PayPalClient talks to the real PayPal sandbox REST API with httpx: OAuth
token, Orders create and capture, Payouts create, and capture refund. It is
used only when PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are set.

DemoSimulator mirrors the same states locally and stamps every result as
demo. It never pretends to be PayPal. Ledger messages written by the caller
carry the mode, so a demo run can never be mistaken for a real money run.
"""

import time
import uuid

import httpx

from . import money
from .config import SETTINGS


class PaymentError(Exception):
    pass


def _amt(amount_cents):
    """Integer cents to the "148.11" string PayPal expects.

    Built from the integer, so no float ever appears in a payload.
    Every money method on both rails takes integer cents (queue item V).
    """
    return money.fmt(amount_cents)


class PayPalClient:
    mode = "sandbox"

    def __init__(self, settings=SETTINGS):
        self.settings = settings
        self.base = settings.paypal_base_url
        self._token = None
        self._token_exp = 0.0

    async def _access_token(self, client):
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        resp = await client.post(
            f"{self.base}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self.settings.paypal_client_id,
                  self.settings.paypal_client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code >= 400:
            raise PaymentError(f"PayPal OAuth failed: {resp.status_code} {resp.text}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + data.get("expires_in", 3600)
        return self._token

    async def _request(self, method, path, json_body=None, request_id=None):
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._access_token(client)
            resp = await client.request(
                method,
                f"{self.base}{path}",
                json=json_body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    # PayPal-Request-Id only dedupes when the same logical
                    # operation reuses the same id on retry. Callers pass a
                    # deterministic id derived from the deal and the money
                    # leg; a random id is used only when no logical
                    # operation identity exists.
                    "PayPal-Request-Id": request_id or str(uuid.uuid4()),
                },
            )
            if resp.status_code >= 400:
                raise PaymentError(
                    f"PayPal {method} {path} failed: {resp.status_code} {resp.text}")
            return resp.json() if resp.content else {}

    async def create_order(self, amount, currency, reference, request_id=None,
                         contract_tag=None):
        purchase_unit = {
            "reference_id": reference,
            "amount": {"currency_code": currency, "value": _amt(amount)},
        }
        if contract_tag:
            # The deal id and the SHA-256 of the frozen spec ride on
            # PayPal's own order record, so the contract the verifier
            # judged is provably the contract the money moved under.
            purchase_unit["custom_id"] = contract_tag
        data = await self._request("POST", "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [purchase_unit],
        }, request_id=request_id)
        approval_url = None
        for link in data.get("links", []):
            if link.get("rel") in ("approve", "payer-action"):
                approval_url = link.get("href")
        return {"order_id": data["id"], "status": data.get("status"),
                "approval_url": approval_url, "demo": False, "rail": "rest",
                "hash_field": "custom_id" if contract_tag else None,
                "contract_tag": contract_tag}

    async def capture_order(self, order_id, request_id=None):
        data = await self._request(
            "POST", f"/v2/checkout/orders/{order_id}/capture", {},
            request_id=request_id)
        capture = {}
        try:
            capture = (data["purchase_units"][0]["payments"]
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
                "demo": False, "rail": "rest"}

    async def payout(self, receiver_email, amount, currency, note,
                     request_id=None):
        if not receiver_email:
            raise PaymentError(
                "No receiver email configured for this payout. Set the "
                "matching sandbox email variable and try again.")
        data = await self._request("POST", "/v1/payments/payouts", {
            "sender_batch_header": {
                # sender_batch_id is the payout idempotency key: a retry
                # of the same settlement leg must reuse the same value or
                # PayPal will run the payout twice.
                "sender_batch_id": request_id or str(uuid.uuid4()),
                "email_subject": "Pact settlement",
                "email_message": note,
            },
            "items": [{
                "recipient_type": "EMAIL",
                "receiver": receiver_email,
                "amount": {"currency": currency, "value": _amt(amount)},
                "note": note,
            }],
        })
        return {"payout_batch_id": data.get("batch_header", {}).get("payout_batch_id"),
                "status": data.get("batch_header", {}).get("batch_status"),
                "demo": False, "rail": "rest"}

    async def refund(self, capture_id, amount, currency, request_id=None):
        data = await self._request(
            "POST", f"/v2/payments/captures/{capture_id}/refund",
            {"amount": {"currency_code": currency, "value": _amt(amount)}},
            request_id=request_id)
        return {"refund_id": data.get("id"), "status": data.get("status"),
                "demo": False, "rail": "rest"}

    async def get_payout_status(self, payout_batch_id):
        """Read back a payout batch and its item statuses.

        Payouts are asynchronous: the create call only accepts the batch.
        Items can later be denied, returned, or blocked, so settlement
        must read the status back instead of trusting the create call.
        Returns {"batch_status": str, "items": [{"status": str,
        "receiver": str}]}.
        """
        data = await self._request(
            "GET", f"/v1/payments/payouts/{payout_batch_id}")
        header = data.get("batch_header", {}) or {}
        items = []
        for item in data.get("items", []) or []:
            items.append({
                "status": item.get("transaction_status"),
                "receiver": (item.get("payout_item", {}) or {}).get("receiver"),
            })
        return {"batch_status": header.get("batch_status"),
                "items": items}

    async def get_order_details(self, order_id):
        """Read an order back from PayPal, including payer and status."""
        return await self._request(
            "GET", f"/v2/checkout/orders/{order_id}")

    async def verify_webhook_signature(self, headers, event):
        """Ask PayPal to verify a webhook signature.

        Returns the verification_status string PayPal answers with,
        SUCCESS or FAILURE. headers keys must be lowercase.
        """
        data = await self._request(
            "POST", "/v1/notifications/verify-webhook-signature", {
                "auth_algo": headers.get("paypal-auth-algo"),
                "cert_url": headers.get("paypal-cert-url"),
                "transmission_id": headers.get("paypal-transmission-id"),
                "transmission_sig": headers.get("paypal-transmission-sig"),
                "transmission_time": headers.get("paypal-transmission-time"),
                "webhook_id": self.settings.paypal_webhook_id,
                "webhook_event": event,
            })
        return data.get("verification_status")


class DemoSimulator:
    """Local stand in that mirrors PayPal states for offline demos."""

    mode = "demo"

    def _id(self, prefix):
        return f"DEMO-{prefix}-{uuid.uuid4().hex[:10].upper()}"

    async def create_order(self, amount, currency, reference, request_id=None,
                         contract_tag=None):
        return {"order_id": self._id("ORDER"), "status": "CREATED",
                "demo": True, "rail": "demo_simulator",
                # Demo mode has no PayPal order record, so the tag is
                # carried on the result dict instead. Nothing here
                # pretends a PayPal call happened.
                "hash_field": "demo_result" if contract_tag else None,
                "contract_tag": contract_tag}

    async def capture_order(self, order_id, request_id=None):
        return {"capture_id": self._id("CAPTURE"), "status": "COMPLETED",
                "demo": True, "rail": "demo_simulator"}

    async def payout(self, receiver_email, amount, currency, note,
                     request_id=None):
        return {"payout_batch_id": self._id("PAYOUT"), "status": "SUCCESS",
                "demo": True, "rail": "demo_simulator"}

    async def refund(self, capture_id, amount, currency, request_id=None):
        return {"refund_id": self._id("REFUND"), "status": "COMPLETED",
                "demo": True, "rail": "demo_simulator"}

    async def get_payout_status(self, payout_batch_id):
        # The demo simulator resolves instantly, so behavior in demo mode
        # stays exactly as it was: payouts confirm on the first read.
        return {"batch_status": "SUCCESS", "items": []}


def get_payment_service():
    if SETTINGS.paypal_live:
        return PayPalClient()
    return DemoSimulator()

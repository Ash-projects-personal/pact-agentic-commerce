"""Live sandbox test for Pact.

Runs against a running Pact server (uvicorn) configured with real PayPal
sandbox credentials. PayPal requires the account holder to approve each
wallet payment before capture, so the live flow has two phases:

Phase "setup": create a deal, negotiate, and pay. Asserts the deal lands
in awaiting_approval with a PayPal approval URL on both the payment order
and the bond order, and prints the two links. A person then opens each
link, signs in with the matching sandbox test account, and approves.

Phase "finish": after both approvals, confirms the payment (capture of
both orders), delivers, verifies, and asserts the deal settles as
released. Run it with the same deal id printed by setup.

Usage:
  python tests/live_sandbox_test.py setup
  # approve both links in a browser as the sandbox buyer and seller
  python tests/live_sandbox_test.py finish <deal_id>

Set PACT_BASE_URL to the server origin (default http://127.0.0.1:8000).
"""

import os
import re
import sys

import requests

BASE = os.environ.get("PACT_BASE_URL", "http://127.0.0.1:8000")


def _token_headers(deal_id, path):
    """Queue item W: state-changing endpoints need the per-deal role
    token in the X-Deal-Token header. The deal view carries both
    tokens, so this reads them back from the API (demo-grade). Deliver
    acts as the seller; everything else acts as the buyer."""
    role = "seller" if path.rstrip("/").endswith("/deliver") else "buyer"
    deal = requests.get(f"{BASE}/api/deals/{deal_id}").json()
    return {"X-Deal-Token": deal[f"{role}_token"]}


def post(path, body=None, deal_id=None):
    headers = _token_headers(deal_id, path) if deal_id else None
    resp = requests.post(f"{BASE}{path}", json=body or {}, headers=headers)
    assert resp.status_code == 200, f"POST {path} -> {resp.status_code}: {resp.text}"
    return resp.json()


def setup():
    health = requests.get(f"{BASE}/api/health").json()
    print(f"Health: {health}")
    assert health["mode"] == "sandbox", health
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"})
    deal = post(f"/api/deals/{deal['id']}/negotiate/run", deal_id=deal["id"])
    assert deal["state"] == "agreed", deal["state"]
    deal = post(f"/api/deals/{deal['id']}/pay", deal_id=deal["id"])
    assert deal["state"] == "awaiting_approval", deal["state"]
    pay_url = deal["payment"]["approval_url"]
    bond_url = deal["bond"]["approval_url"]
    assert pay_url and "sandbox.paypal.com" in pay_url, deal["payment"]
    assert bond_url and "sandbox.paypal.com" in bond_url, deal["bond"]
    print(f"Deal {deal['id']} is awaiting approval.")
    print(f"Buyer approves the payment: {pay_url}")
    print(f"Seller approves the bond:  {bond_url}")
    print(f"Then run: python tests/live_sandbox_test.py finish {deal['id']}")


def finish(deal_id):
    deal = post(f"/api/deals/{deal_id}/pay/confirm", deal_id=deal_id)
    assert deal["state"] == "paid_held", deal["state"]
    assert deal["payment"]["status"] == "held", deal["payment"]
    assert deal["bond"]["status"] == "posted", deal["bond"]
    print(f"Captured. Payment capture {deal['payment']['capture_id']}, "
          f"bond capture {deal['bond']['capture_id']}.")
    deal = post(f"/api/deals/{deal_id}/deliver", {"quality": "auto"},
                deal_id=deal_id)
    deal = post(f"/api/deals/{deal_id}/verify", deal_id=deal_id)
    assert deal["state"] == "released", deal["state"]
    assert deal["payment"]["status"] == "released"
    assert deal["bond"]["status"] == "returned"
    print(f"Settlement: {deal.get('settlement')}")
    print("LIVE SANDBOX DEAL PASSED END TO END")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "setup":
        setup()
    elif len(sys.argv) >= 3 and sys.argv[1] == "finish":
        finish(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)

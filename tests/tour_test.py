"""Guided tour test for Pact (queue item AB).

Drives the tour's step sequence through the HTTP API in demo mode and
checks the tour control is served in the page:

1. The served index.html carries the Play the tour control, the tour
   step list, and the demo-only note.
2. The step list covers the four beats: negotiation, bond, verification,
   payout.
3. The served app.js carries the tour runner and its captions.
4. The tour's API sequence (create logo_brand_kit, negotiate, pay,
   deliver, verify) settles one real demo deal to released, with every
   tour step's expected ledger event present.

The tour itself is client side JavaScript; this test drives the exact
API sequence it calls, with the same role tokens and the same order, so
a broken step shows up here first.

Run with: NO_PROXY=localhost,127.0.0.1 python tests/tour_test.py
Exits non zero on the first failed assertion.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

# Force demo mode before the app modules read the environment.
for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

# Isolate persistence: point the test run at a throwaway database that
# never touches the real dev database at data/pact.db.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "tour-test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pact.main import app  # noqa: E402

CHECKS = 0


def check(cond, msg):
    global CHECKS
    CHECKS += 1
    assert cond, msg


# Per-deal role tokens (queue item W): state-changing deal endpoints
# require the token for the acting role in the X-Deal-Token header. The
# create response carries both tokens, the way the tour reads them from
# the deal view. Deliver acts as the seller; everything else acts as
# the buyer, exactly like the tour runner in pact/static/app.js.
_DEAL_TOKENS = {}


def _token_headers(path):
    m = re.match(r"^/api/deals/([^/]+)/", path)
    if not m:
        return None
    role = "seller" if path.rstrip("/").endswith("/deliver") else "buyer"
    tok = _DEAL_TOKENS.get(m.group(1), {}).get(role)
    return {"X-Deal-Token": tok} if tok else None


def _remember_tokens(data):
    if isinstance(data, dict) and data.get("id") and data.get("buyer_token"):
        _DEAL_TOKENS[data["id"]] = {
            "buyer": data.get("buyer_token"),
            "seller": data.get("seller_token"),
        }


def test_tour_control_served(client):
    print("TEST 1 tour control is served in the page")
    resp = client.get("/")
    check(resp.status_code == 200, f"GET / -> {resp.status_code}")
    page = resp.text
    check('id="tourCard"' in page, "tour card missing from the page")
    check('id="tourPlayBtn"' in page, "tour play button missing")
    check("Play the tour" in page, "tour play label missing")
    check('id="tourPauseBtn"' in page, "tour pause button missing")
    check('id="tourReplayBtn"' in page, "tour replay button missing")
    check('id="tourCaption"' in page, "tour caption area missing")
    check("The tour runs in demo mode only" in page,
          "demo-only note missing from the page")
    # The step list in the page must cover the four beats of the story.
    m = re.search(r'id="tourSteps"[^>]*>(.*?)</ol>', page, re.S)
    check(m is not None, "tour step list missing from the page")
    steps = m.group(1).lower()
    for beat in ("negotiat", "bond", "verif", "payout"):
        check(beat in steps, f"tour step list does not cover {beat}")
    print("  tour card, controls, caption, demo-only note present")
    print("  step list covers negotiation, bond, verification, payout")
    print("  PASS")


def test_tour_runner_served(client):
    print("TEST 2 tour runner and captions are served in app.js")
    resp = client.get("/static/app.js")
    check(resp.status_code == 200, f"GET /static/app.js -> {resp.status_code}")
    js = resp.text
    check("TOUR_SCENARIO" in js, "tour scenario constant missing")
    check('"logo_brand_kit"' in js, "tour does not use logo_brand_kit")
    check("runTour" in js, "tour runner missing")
    check("tourCaption" in js, "tour caption helper missing")
    check("tourWait" in js, "tour pause-aware wait missing")
    check("tourNewSeqs" in js, "tour ledger highlight missing")
    check("demoOnly" in js, "tour demo-mode gate missing")
    for beat in ("negotiat", "bond", "verif", "payout"):
        check(beat in js.lower(), f"tour captions do not cover {beat}")
    print("  runner, captions, highlight, and demo gate all served")
    print("  PASS")


def test_tour_sequence(client):
    print("TEST 3 tour step sequence settles a real demo deal to released")
    health = client.get("/api/health").json()
    check(health["mode"] == "demo", health)

    def post(path, body=None):
        resp = client.post(path, json=body or {},
                           headers=_token_headers(path))
        assert resp.status_code == 200, \
            f"POST {path} -> {resp.status_code}: {resp.text}"
        data = resp.json()
        _remember_tokens(data)
        return data

    # Step 1: create. The tour uses the logo_brand_kit defaults.
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"})
    check(deal["state"] == "negotiating", deal["state"])
    check(deal["buyer_token"] and deal["seller_token"],
          "tour deal carries no role tokens")

    # Step 2: negotiate. Price, bond, and checks are the numbers the
    # tour captions carry.
    deal = post(f"/api/deals/{deal['id']}/negotiate/run")
    check(deal["state"] == "agreed", deal["state"])
    spec = deal["spec"]
    check(spec["price"] == 222.17, spec["price"])
    check(spec["bond_amount"] == 44.43, spec["bond_amount"])
    check(spec["bond_percent"] == 20.0, spec["bond_percent"])
    check(len(spec["acceptance_checks"]) == 5, spec["acceptance_checks"])

    # Step 3: pay and post the bond. Demo mode holds both at once.
    deal = post(f"/api/deals/{deal['id']}/pay")
    check(deal["state"] == "paid_held", deal["state"])
    check(deal["payment"]["status"] == "held", deal["payment"])
    check(deal["bond"]["status"] == "posted", deal["bond"])

    # Step 4: deliver the honest brand kit.
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    check(deal["state"] == "delivered", deal["state"])

    # Step 5: verify, then release. The deterministic verifier passes
    # all 5 checks on the honest delivery.
    deal = post(f"/api/deals/{deal['id']}/verify")
    check(deal["state"] == "released", deal["state"])
    check(deal["payment"]["status"] == "released", deal["payment"])
    check(deal["bond"]["status"] == "returned", deal["bond"])
    check(deal["verification"]["passed_count"] == 5, deal["verification"])
    check(deal["verification"]["total_count"] == 5, deal["verification"])

    # Every tour step must leave its ledger event behind.
    types = [e["event_type"] for e in deal["ledger"]]
    for expected in ("deal_created", "price_agreed", "contract_written",
                     "payment_held", "bond_posted", "delivery_submitted",
                     "verification_summary", "payment_released",
                     "bond_returned", "reputation_change"):
        check(expected in types, f"missing ledger event {expected}")
    held = next(e for e in deal["ledger"]
                if e["event_type"] == "payment_held")
    released = next(e for e in deal["ledger"]
                    if e["event_type"] == "payment_released")
    check(held["data"].get("capture_id", "").startswith("DEMO-CAPTURE-"),
          held["data"])
    check(released["data"].get("payout_batch_id", "").startswith("DEMO-PAYOUT-"),
          released["data"])
    print(f"  price {spec['price']} USD, bond {spec['bond_amount']} USD, "
          f"checks {deal['verification']['passed_count']}/"
          f"{deal['verification']['total_count']}, "
          f"ledger events {len(types)}")
    print(f"  capture {held['data']['capture_id']}, "
          f"payout {released['data']['payout_batch_id']}")
    print("  PASS")


def main():
    # One shared portal for the whole file: TestClient without the
    # context manager gives every request its own event loop, and the
    # per-deal asyncio locks hang across loops (see the checkpoint).
    with TestClient(app) as client:
        test_tour_control_served(client)
        test_tour_runner_served(client)
        test_tour_sequence(client)
    print(f"ALL TOUR TESTS PASSED ({CHECKS} checks)")


if __name__ == "__main__":
    main()

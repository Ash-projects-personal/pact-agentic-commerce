"""Smoke test for Pact in demo mode.

Boots the app with no PayPal credentials and no LLM key, then runs three
deals end to end through the HTTP API:

1. Happy path: negotiate, pay, bond, deliver, verify, release.
2. Fail path: a delivery that passes no checks goes straight to a refund
   and a bond slash.
3. Cheat scenario: recycled copy is caught check by check, gets one
   revision round, fails again, and ends refunded with the bond slashed.

Run with: python tests/smoke_test.py
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

# Isolate persistence: the middleware writes the store to SQLite after
# every response, so point the test run at a throwaway database that
# never touches the real dev database at data/pact.db.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pact.main import app  # noqa: E402

client = TestClient(app)

# Demo client token store (queue item W): state-changing deal endpoints
# require the per-deal role token in the X-Deal-Token header. The create
# response carries both tokens, so this helper remembers them per deal
# id and attaches the right one, the way a real client would. Deliver
# acts as the seller; everything else here acts as the buyer.
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


def post(path, body=None):
    resp = client.post(path, json=body or {}, headers=_token_headers(path))
    assert resp.status_code == 200, f"POST {path} -> {resp.status_code}: {resp.text}"
    data = resp.json()
    _remember_tokens(data)
    return data


def agent_rep(agent_id):
    agents = client.get("/api/agents").json()
    return next(a["reputation"] for a in agents if a["id"] == agent_id)


def event_types(deal):
    return [e["event_type"] for e in deal["ledger"]]


def run_to_paid(scenario_id):
    deal = post("/api/deals", {"scenario_id": scenario_id})
    deal = post(f"/api/deals/{deal['id']}/negotiate/run")
    assert deal["state"] == "agreed", deal["state"]
    deal = post(f"/api/deals/{deal['id']}/pay")
    assert deal["state"] == "paid_held", deal["state"]
    assert deal["payment"]["status"] == "held"
    assert deal["bond"]["status"] == "posted"
    assert deal["payment"]["mode"] == "demo"
    assert deal["payment"]["rail"] == "demo_simulator"
    return deal


def test_happy_path():
    print("TEST 1 happy path: brand kit deal settles as released")
    buyer_before = agent_rep("buyer_main")
    seller_before = agent_rep("seller_forma")
    deal = run_to_paid("logo_brand_kit")

    spec = deal["spec"]
    checks = {c["id"]: c for c in spec["acceptance_checks"]}
    # The agents wrote these checks in negotiation. Values are the settled
    # midpoints of the buyer demand and the seller counter.
    assert checks["logo_concepts"]["value"] == 3, checks["logo_concepts"]
    assert checks["color_palette"]["value"] == 5, checks["color_palette"]
    assert checks["guide_length"]["value"] == 260, checks["guide_length"]
    assert spec["bond_amount"] == round(spec["price"] * spec["bond_percent"] / 100, 2)
    assert deal["seller_floor"] <= spec["price"] <= deal["buyer_max"]

    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    assert deal["state"] == "delivered"
    deal = post(f"/api/deals/{deal['id']}/verify")
    assert deal["state"] == "released", deal["state"]
    assert deal["payment"]["status"] == "released"
    assert deal["bond"]["status"] == "returned"
    assert deal["verification"]["all_passed"] is True
    assert agent_rep("seller_forma") == seller_before + 6
    assert agent_rep("buyer_main") == buyer_before + 3
    types = event_types(deal)
    for expected in ("contract_written", "payment_held", "bond_posted",
                     "payment_released", "bond_returned", "reputation_change"):
        assert expected in types, f"missing ledger event {expected}"
    print(f"  price {spec['price']} USD, bond {spec['bond_amount']} USD, "
          f"checks passed {deal['verification']['passed_count']}/"
          f"{deal['verification']['total_count']}, ledger events {len(types)}")
    print("  PASS")


def test_fail_path():
    print("TEST 2 fail path: empty delivery is refunded and the bond is slashed")
    seller_before = agent_rep("seller_forma")
    deal = run_to_paid("logo_brand_kit")
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": "poor"})
    deal = post(f"/api/deals/{deal['id']}/verify")
    assert deal["verification"]["passed_count"] == 0, deal["verification"]
    assert deal["state"] == "refunded", deal["state"]
    assert deal["payment"]["status"] == "refunded"
    assert deal["bond"]["status"] == "slashed"
    # Total fail means no revision cost, then refund cost and slash cost.
    assert agent_rep("seller_forma") == seller_before - 32
    types = event_types(deal)
    for expected in ("buyer_refunded", "bond_slashed", "revision_skipped"):
        assert expected in types, f"missing ledger event {expected}"
    print(f"  checks passed 0/{deal['verification']['total_count']}, "
          f"seller reputation {seller_before} -> {agent_rep('seller_forma')}")
    print("  PASS")


def test_cheat_scenario():
    print("TEST 3 cheat scenario: recycled copy caught, revised, caught again")
    seller_before = agent_rep("seller_fastcopy")
    deal = run_to_paid("cheat_attempt")
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    deal = post(f"/api/deals/{deal['id']}/verify")
    # Only the launch mention check passes on the recycled copy, so the
    # contract grants exactly one revision round.
    assert deal["state"] == "revision", deal["state"]
    assert deal["verification"]["passed_count"] == 1, deal["verification"]
    failed = [r["check_id"] for r in deal["verification"]["results"] if not r["passed"]]
    assert set(failed) == {"post_count", "hashtag_count", "pack_length",
                           "brand_named"}, failed
    deal = post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    assert deal["deliverable"]["version"] == 2
    deal = post(f"/api/deals/{deal['id']}/verify")
    assert deal["state"] == "refunded", deal["state"]
    assert deal["bond"]["status"] == "slashed"
    # Revision cost 3, refund cost 12, slash cost 20.
    assert agent_rep("seller_fastcopy") == seller_before - 35
    types = event_types(deal)
    for expected in ("revision_requested", "revision_submitted",
                     "buyer_refunded", "bond_slashed"):
        assert expected in types, f"missing ledger event {expected}"
    check_events = [e for e in deal["ledger"]
                    if e["event_type"] == "verification_check"]
    assert len(check_events) == 10, len(check_events)
    print(f"  round 1 catch: 4 of 5 checks failed on recycled copy")
    print(f"  round 2 catch: revision failed again, refunded, bond slashed")
    print(f"  seller reputation {seller_before} -> {agent_rep('seller_fastcopy')}")
    print("  PASS")


def main():
    health = client.get("/api/health").json()
    assert health["mode"] == "demo", health
    assert health["agent_toolkit"]["orders_rail"] == "demo_simulator", health
    print(f"Health: mode {health['mode']}, toolkit installed "
          f"{health['agent_toolkit']['installed']}")
    test_happy_path()
    test_fail_path()
    test_cheat_scenario()
    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()

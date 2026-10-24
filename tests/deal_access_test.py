"""Deal identity and access tests (queue item W).

Deal ids are random and unguessable (pact-<url-safe>), and every
state-changing endpoint requires the per-deal role token in the
X-Deal-Token header: the buyer token for negotiate, pay, and
pay/confirm; the seller token for deliver; either token for verify
(the verifier action itself stays server side). Unknown ids 404, and
the token check runs before the lock and the state check, so a bad
token never waits on a deal lock and never reaches the state machine.
Deals persisted before tokens shipped carry no tokens and are
grandfathered past the check, so old deals keep working.

Run with: NO_PROXY=localhost,127.0.0.1 python tests/deal_access_test.py
Exits non zero on the first failed assertion. Demo mode only.
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
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-access.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pact.main import app  # noqa: E402

TOKEN_HEADER = "X-Deal-Token"

CHECKS = 0


def check(name, cond, detail=""):
    """One counted check. Fails loudly on the first violation."""
    global CHECKS
    CHECKS += 1
    print(f"  {'PASS' if cond else 'FAIL'} {name}"
          f"{'' if cond else ' ' + str(detail)}")
    if not cond:
        raise AssertionError(f"FAILED: {name} {detail}")


def clean_403(resp):
    """A 403 with the clean error shape: human sentence, detail key,
    and none of the internal strings item X bans from error bodies."""
    try:
        body = resp.json()
    except Exception:
        return False
    detail = body.get("detail", "") if isinstance(body, dict) else ""
    banned = ("Traceback", "KeyError", "ValueError", 'File "',
              "buyer_token", "seller_token")
    return (resp.status_code == 403 and isinstance(detail, str)
            and len(detail) > 10
            and not any(b in detail for b in banned))


def create(client, scenario_id="logo_brand_kit"):
    resp = client.post("/api/deals", json={"scenario_id": scenario_id})
    assert resp.status_code == 200, f"create -> {resp.status_code}: {resp.text}"
    return resp.json()


def hdr(token):
    return {TOKEN_HEADER: token} if token else {}


def test_ids_unguessable(client):
    print("W1 deal ids are random, not sequential")
    a = create(client)
    b = create(client)
    for deal, label in ((a, "first"), (b, "second")):
        check(f"{label} id has the pact- prefix",
              deal["id"].startswith("pact-"), deal["id"])
        check(f"{label} id is not sequential",
              not re.fullmatch(r"deal-\d+", deal["id"]), deal["id"])
        check(f"{label} id is url-safe",
              re.fullmatch(r"[A-Za-z0-9_-]+", deal["id"]) is not None,
              deal["id"])
    check("two deals get different ids", a["id"] != b["id"],
          f"{a['id']} vs {b['id']}")
    check("buyer and seller tokens differ",
          a["buyer_token"] != a["seller_token"])
    check("tokens are unguessable length",
          len(a["buyer_token"]) >= 20 and len(a["seller_token"]) >= 20)
    check("tokens differ across deals",
          a["buyer_token"] != b["buyer_token"]
          and a["seller_token"] != b["seller_token"])


def test_unknown_id_404(client):
    print("W2 guessing a neighboring id fails with 404")
    resp = client.get("/api/deals/pact-no-such-deal")
    check("GET unknown deal -> 404", resp.status_code == 404,
          resp.status_code)
    resp = client.post("/api/deals/pact-no-such-deal/negotiate/run",
                       headers=hdr("bogus-token"))
    check("POST negotiate on unknown deal -> 404, not 403",
          resp.status_code == 404, resp.status_code)
    resp = client.post("/api/deals/deal-9999/pay", headers=hdr("bogus"))
    check("POST pay on old-format unknown id -> 404",
          resp.status_code == 404, resp.status_code)


def test_missing_token_403(client):
    print("W3 acting without a token -> 403 on every state endpoint")
    deal = create(client)
    did = deal["id"]
    buyer, seller = deal["buyer_token"], deal["seller_token"]

    resp = client.post(f"/api/deals/{did}/negotiate/run")
    check("negotiate without token -> 403", clean_403(resp),
          f"{resp.status_code}: {resp.text[:120]}")

    resp = client.post(f"/api/deals/{did}/negotiate/run",
                       headers=hdr(buyer))
    check("negotiate with buyer token -> 200", resp.status_code == 200,
          f"{resp.status_code}: {resp.text[:200]}")
    check("deal agreed", resp.json()["state"] == "agreed")

    resp = client.post(f"/api/deals/{did}/pay")
    check("pay without token -> 403", clean_403(resp),
          f"{resp.status_code}: {resp.text[:120]}")
    # Token check runs before the state check: pay/confirm on a deal
    # that is not awaiting approval still 403s on the missing token
    # instead of 409ing on the state.
    resp = client.post(f"/api/deals/{did}/pay/confirm")
    check("pay/confirm without token -> 403 (before state check)",
          clean_403(resp), f"{resp.status_code}: {resp.text[:120]}")

    resp = client.post(f"/api/deals/{did}/pay", headers=hdr(buyer))
    check("pay with buyer token -> 200", resp.status_code == 200,
          f"{resp.status_code}: {resp.text[:200]}")
    check("deal paid_held", resp.json()["state"] == "paid_held")

    resp = client.post(f"/api/deals/{did}/deliver", json={"quality": "auto"})
    check("deliver without token -> 403", clean_403(resp),
          f"{resp.status_code}: {resp.text[:120]}")

    resp = client.post(f"/api/deals/{did}/deliver",
                       json={"quality": "auto"}, headers=hdr(seller))
    check("deliver with seller token -> 200", resp.status_code == 200,
          f"{resp.status_code}: {resp.text[:200]}")

    resp = client.post(f"/api/deals/{did}/verify")
    check("verify without token -> 403", clean_403(resp),
          f"{resp.status_code}: {resp.text[:120]}")


def test_wrong_role_403(client):
    print("W4 wrong-role token -> 403, either token ok for verify")
    deal = create(client)
    did = deal["id"]
    buyer, seller = deal["buyer_token"], deal["seller_token"]

    resp = client.post(f"/api/deals/{did}/negotiate/run",
                       headers=hdr(seller))
    check("negotiate with seller token -> 403", clean_403(resp),
          f"{resp.status_code}: {resp.text[:120]}")
    resp = client.post(f"/api/deals/{did}/negotiate/run",
                       headers=hdr(buyer))
    check("negotiate with buyer token -> 200",
          resp.status_code == 200, resp.status_code)

    resp = client.post(f"/api/deals/{did}/pay", headers=hdr(seller))
    check("pay with seller token -> 403", clean_403(resp),
          f"{resp.status_code}: {resp.text[:120]}")
    resp = client.post(f"/api/deals/{did}/pay", headers=hdr(buyer))
    check("pay with buyer token -> 200", resp.status_code == 200,
          resp.status_code)

    resp = client.post(f"/api/deals/{did}/deliver",
                       json={"quality": "auto"}, headers=hdr(buyer))
    check("deliver with buyer token -> 403", clean_403(resp),
          f"{resp.status_code}: {resp.text[:120]}")
    resp = client.post(f"/api/deals/{did}/deliver",
                       json={"quality": "auto"}, headers=hdr(seller))
    check("deliver with seller token -> 200", resp.status_code == 200,
          resp.status_code)

    resp = client.post(f"/api/deals/{did}/verify",
                       headers=hdr("not-a-real-token"))
    check("verify with garbage token -> 403", clean_403(resp),
          f"{resp.status_code}: {resp.text[:120]}")
    resp = client.post(f"/api/deals/{did}/verify", headers=hdr(seller))
    check("verify accepts the seller token -> 200",
          resp.status_code == 200, f"{resp.status_code}: {resp.text[:200]}")

    # Second deal: verify accepts the buyer token too.
    deal2 = create(client)
    did2 = deal2["id"]
    b2, s2 = deal2["buyer_token"], deal2["seller_token"]
    assert client.post(f"/api/deals/{did2}/negotiate/run",
                       headers=hdr(b2)).status_code == 200
    assert client.post(f"/api/deals/{did2}/pay",
                       headers=hdr(b2)).status_code == 200
    assert client.post(f"/api/deals/{did2}/deliver",
                       json={"quality": "auto"},
                       headers=hdr(s2)).status_code == 200
    resp = client.post(f"/api/deals/{did2}/verify", headers=hdr(b2))
    check("verify accepts the buyer token -> 200",
          resp.status_code == 200, f"{resp.status_code}: {resp.text[:200]}")


def test_full_lifecycle(client):
    print("W5 full demo lifecycle with correct tokens -> released")
    deal = create(client)
    did = deal["id"]
    buyer, seller = deal["buyer_token"], deal["seller_token"]

    deal = client.post(f"/api/deals/{did}/negotiate/run",
                       headers=hdr(buyer)).json()
    check("negotiated", deal["state"] == "agreed", deal["state"])
    deal = client.post(f"/api/deals/{did}/pay",
                       headers=hdr(buyer)).json()
    check("paid and held", deal["state"] == "paid_held", deal["state"])
    deal = client.post(f"/api/deals/{did}/deliver",
                       json={"quality": "auto"},
                       headers=hdr(seller)).json()
    check("delivered", deal["state"] == "delivered", deal["state"])
    deal = client.post(f"/api/deals/{did}/verify",
                       headers=hdr(buyer)).json()
    check("released", deal["state"] == "released", deal["state"])

    view = client.get(f"/api/deals/{did}").json()
    check("deal view carries the buyer token",
          view["buyer_token"] == buyer)
    check("deal view carries the seller token",
          view["seller_token"] == seller)


def test_old_deal_grandfathered(client):
    print("W6 old-format persisted deal (no tokens) loads and works")
    from pact import money, persistence
    from pact import store as pact_store
    from pact.scenarios import SCENARIO_BY_ID

    # Build the record exactly as load_all() would produce it for a
    # deal persisted before tokens shipped: old deal-NNNN id, no token
    # keys at all.
    fresh = pact_store.new_deal(SCENARIO_BY_ID["logo_brand_kit"],
                                money.to_cents(300.0),
                                money.to_cents(200.0), 20.0)
    fresh_id = fresh["id"]
    del fresh["buyer_token"]
    del fresh["seller_token"]
    fresh["id"] = "deal-0001"
    pact_store.DEALS["deal-0001"] = pact_store.DEALS.pop(fresh_id)

    # Round trip through the real persistence layer: save, wipe the
    # working store, load, and the old deal must come back tokenless.
    persistence.save_all()
    pact_store.DEALS.clear()
    persistence.load_all()
    check("old deal loads from SQLite", "deal-0001" in pact_store.DEALS)
    loaded = pact_store.DEALS["deal-0001"]
    check("loaded deal has no buyer token",
          loaded.get("buyer_token") is None)
    check("loaded deal has no seller token",
          loaded.get("seller_token") is None)

    # Grandfathered past the token check: the whole lifecycle works
    # with no tokens at all.
    did = "deal-0001"
    resp = client.post(f"/api/deals/{did}/negotiate/run")
    check("old deal negotiates without a token",
          resp.status_code == 200, f"{resp.status_code}: {resp.text[:200]}")
    resp = client.post(f"/api/deals/{did}/pay")
    check("old deal pays without a token", resp.status_code == 200,
          f"{resp.status_code}: {resp.text[:200]}")
    resp = client.post(f"/api/deals/{did}/deliver",
                       json={"quality": "auto"})
    check("old deal delivers without a token", resp.status_code == 200,
          f"{resp.status_code}: {resp.text[:200]}")
    resp = client.post(f"/api/deals/{did}/verify")
    check("old deal verifies without a token", resp.status_code == 200,
          f"{resp.status_code}: {resp.text[:200]}")
    check("old deal released", resp.json()["state"] == "released",
          resp.json()["state"])
    view = client.get(f"/api/deals/{did}").json()
    check("old deal view reports null tokens",
          view["buyer_token"] is None and view["seller_token"] is None)


def main():
    # One shared portal for the whole run (PART J lesson): a bare
    # TestClient gives every request its own event loop, and the
    # per-deal asyncio locks hang or 500 across loops.
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["mode"] == "demo", \
            f"NOT DEMO MODE: {health['mode']} - refusing to run"
        print(f"Health: mode {health['mode']}")
        test_ids_unguessable(client)
        test_unknown_id_404(client)
        test_missing_token_403(client)
        test_wrong_role_403(client)
        test_full_lifecycle(client)
        test_old_deal_grandfathered(client)
    print(f"deal_access: {CHECKS} checks, ALL PASSED")


if __name__ == "__main__":
    main()

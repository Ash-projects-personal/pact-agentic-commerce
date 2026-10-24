"""Accuracy battery for Pact.

The product claim is that the verifier judges work exactly against the
contract the agents wrote. This battery tests that claim hard:

Part 1: unit tests of every check kind against hand labeled ground
truth, including boundary values and known traps (an 8 digit hex code
is not a 6 digit color; a hex color token is not a hashtag; a marker
inside a longer word does not count).

Part 2: generated cases. Texts are built from counted pieces, so the
true count is known by construction, and the verifier must reproduce
it exactly across 40 cases.

Part 3: engine integration in demo mode. Walk away deals move no
money, state guards reject out of order calls, the revision round can
still end in a pass when the seller actually fixes the work, bond math
rounds the way the ledger claims, and negotiation is deterministic.

Run with: .venv/bin/python tests/accuracy_test.py
Exits non zero on the first failed assertion.
"""

import os
import random
import sys
import tempfile
from pathlib import Path

for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

# Isolate persistence: the middleware writes the store to SQLite after
# every response, so point the test run at a throwaway database that
# never touches the real dev database at data/pact.db.
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "pact-test.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pact.verifier import evaluate_check  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name} {detail}")
        FAILURES.append(name)


def unit_tests():
    print("PART 1 verifier unit tests, hand labeled ground truth")

    c = {"id": "x", "label": "concepts", "kind": "min_items",
         "marker": "Concept ", "value": 3, "unit": "concepts"}
    r = evaluate_check(c, "Concept 1: alpha beta gamma. Concept 2: delta epsilon zeta. Concept 3: eta theta iota.")
    check("min_items exact count passes", r["passed"] and r["measured"] == 3, r)
    r = evaluate_check(c, "Concept 1: alpha beta gamma. Concept 2: delta epsilon zeta.")
    check("min_items one short fails", not r["passed"] and r["measured"] == 2, r)
    r = evaluate_check(c, "concept 1: a. concept 2: b. concept 3: c.")
    check("min_items is case sensitive", r["measured"] == 0 and not r["passed"], r)
    r = evaluate_check(c, "Conceptual notes. Concept 1: alpha beta gamma. Concept 2: delta epsilon zeta.")
    check("marker inside a longer word does not count",
          r["measured"] == 2 and not r["passed"], r)

    c = {"id": "x", "label": "colors", "kind": "min_hex", "value": 2}
    r = evaluate_check(c, "Palette: #AABBCC and #ddeeff.")
    check("min_hex counts upper and lower case", r["passed"] and r["measured"] == 2, r)
    r = evaluate_check(c, "Palette: #AABBCCDD is an 8 digit code.")
    check("8 digit hex is not a 6 digit color", r["measured"] == 0 and not r["passed"], r)
    r = evaluate_check(c, "Palette: #ABC is a 3 digit code.")
    check("3 digit hex does not count", r["measured"] == 0 and not r["passed"], r)
    r = evaluate_check(c, "Palette: #123456 numeric hex.")
    check("all digit hex counts as a color", r["measured"] == 1, r)

    c = {"id": "x", "label": "tags", "kind": "min_hashtags", "value": 2}
    r = evaluate_check(c, "Big news #LaunchDay is here #NewBrand")
    check("min_hashtags counts real hashtags", r["passed"] and r["measured"] == 2, r)
    r = evaluate_check(c, "A lone # sign and a # followed by space")
    check("bare hash signs do not count", r["measured"] == 0 and not r["passed"], r)
    r = evaluate_check(c, "Colors #AABBCC and #123456 with no hashtags")
    check("hex color tokens are not hashtags",
          r["measured"] == 0 and not r["passed"], r)

    c = {"id": "x", "label": "length", "kind": "min_words", "value": 5}
    r = evaluate_check(c, "one two three four five")
    check("min_words exact boundary passes", r["passed"] and r["measured"] == 5, r)
    r = evaluate_check(c, "one two three four")
    check("min_words one short fails", not r["passed"] and r["measured"] == 4, r)

    c = {"id": "x", "label": "brand", "kind": "contains", "value": "Northwind"}
    r = evaluate_check(c, "Written for Northwind studio.")
    check("contains finds the exact string", r["passed"] and r["measured"] == 1, r)
    r = evaluate_check(c, "Written for northwind studio.")
    check("contains is case sensitive", not r["passed"] and r["measured"] == 0, r)


def generated_cases():
    print("PART 2 generated cases, counts known by construction")
    rng = random.Random(42)
    bad = 0
    for i in range(40):
        n_items = rng.randint(0, 6)
        n_tags = rng.randint(0, 5)
        n_words = rng.randint(0, 40)
        parts = [f"Concept {j}: item number {j} described here." for j in range(n_items)]
        parts += [f"#Tag{j}" for j in range(n_tags)]
        parts += ["word"] * n_words
        text = " ".join(parts)
        total_words = len(text.split())
        r = evaluate_check({"id": "a", "label": "i", "kind": "min_items",
                            "marker": "Concept ", "value": n_items,
                            "unit": "concepts"}, text)
        if r["measured"] != n_items:
            bad += 1
            print(f"  FAIL case {i}: min_items measured {r['measured']} true {n_items}")
        r = evaluate_check({"id": "b", "label": "t", "kind": "min_hashtags",
                            "value": n_tags}, text)
        if r["measured"] != n_tags:
            bad += 1
            print(f"  FAIL case {i}: min_hashtags measured {r['measured']} true {n_tags}")
        r = evaluate_check({"id": "c", "label": "w", "kind": "min_words",
                            "value": total_words}, text)
        if r["measured"] != total_words:
            bad += 1
            print(f"  FAIL case {i}: min_words measured {r['measured']} true {total_words}")
    check("40 generated cases reproduce exact counts", bad == 0, f"{bad} bad")


def integration_tests():
    print("PART 3 engine integration, demo mode")
    import re

    from fastapi.testclient import TestClient
    from pact.main import app
    from pact.store import DEALS

    client = TestClient(app)

    # Demo client token store (queue item W): state-changing deal
    # endpoints require the per-deal role token in the X-Deal-Token
    # header. The create response carries both tokens, so this helper
    # remembers them per deal id and attaches the right one, the way a
    # real client would. Deliver acts as the seller; everything else
    # here acts as the buyer.
    deal_tokens = {}

    def post(path, body=None):
        m = re.match(r"^/api/deals/([^/]+)/", path)
        headers = None
        if m:
            role = ("seller" if path.rstrip("/").endswith("/deliver")
                    else "buyer")
            tok = deal_tokens.get(m.group(1), {}).get(role)
            if tok:
                headers = {"X-Deal-Token": tok}
        resp = client.post(path, json=body or {}, headers=headers)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                data = None
            if (isinstance(data, dict) and data.get("id")
                    and data.get("buyer_token")):
                deal_tokens[data["id"]] = {
                    "buyer": data.get("buyer_token"),
                    "seller": data.get("seller_token"),
                }
        return resp

    def must(path, body=None):
        resp = post(path, body)
        assert resp.status_code == 200, f"POST {path} -> {resp.status_code}: {resp.text}"
        return resp.json()

    # Walk away: buyer ceiling below the seller floor, no money moves.
    deal = must("/api/deals", {"scenario_id": "logo_brand_kit",
                               "buyer_max": 10, "seller_floor": 900})
    deal = must(f"/api/deals/{deal['id']}/negotiate/run")
    check("walk away deal fails cleanly", deal["state"] == "failed", deal["state"])
    check("walk away moves no money",
          deal["payment"]["status"] == "not_started"
          and deal["bond"]["status"] == "not_posted", deal["payment"])

    # State guards reject out of order calls.
    deal = must("/api/deals", {"scenario_id": "logo_brand_kit"})
    resp = post(f"/api/deals/{deal['id']}/pay")
    check("pay before agreement is rejected", resp.status_code in (400, 409, 422),
          resp.status_code)
    resp = post(f"/api/deals/{deal['id']}/verify")
    check("verify before delivery is rejected", resp.status_code in (400, 409, 422),
          resp.status_code)

    # Bond math and determinism across all scenarios.
    for scen in ("logo_brand_kit", "landing_page_copy", "cheat_attempt"):
        d1 = must("/api/deals", {"scenario_id": scen})
        d1 = must(f"/api/deals/{d1['id']}/negotiate/run")
        spec = d1["spec"]
        expect = round(spec["price"] * spec["bond_percent"] / 100, 2)
        check(f"{scen} bond is exactly the rounded percent",
              spec["bond_amount"] == expect, f"{spec['bond_amount']} vs {expect}")
        check(f"{scen} price inside the agreed bounds",
              d1["seller_floor"] <= spec["price"] <= d1["buyer_max"], spec["price"])
        d2 = must("/api/deals", {"scenario_id": scen})
        d2 = must(f"/api/deals/{d2['id']}/negotiate/run")
        check(f"{scen} negotiation is deterministic",
              d2["spec"]["price"] == spec["price"]
              and [c["value"] for c in d2["spec"]["acceptance_checks"]]
              == [c["value"] for c in spec["acceptance_checks"]])

    # Revision round can end in a pass when the seller fixes the work.
    deal = must("/api/deals", {"scenario_id": "cheat_attempt"})
    deal = must(f"/api/deals/{deal['id']}/negotiate/run")
    deal = must(f"/api/deals/{deal['id']}/pay")
    deal = must(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    deal = must(f"/api/deals/{deal['id']}/verify")
    check("cheat round 1 lands in revision", deal["state"] == "revision", deal["state"])
    deal = must(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    # Replace the recycled copy with work that truly meets the contract.
    parts = []
    words = 0
    for chk in deal["spec"]["acceptance_checks"]:
        if chk["kind"] == "min_items":
            for j in range(int(chk["value"])):
                parts.append(f"{chk['marker']}{j + 1}: written for this launch.")
        elif chk["kind"] == "min_hashtags":
            parts += [f"#Tag{j}" for j in range(int(chk["value"]))]
        elif chk["kind"] == "contains":
            parts.append(str(chk["value"]))
        elif chk["kind"] == "min_words":
            words = max(words, int(chk["value"]))
    text = " ".join(parts)
    if len(text.split()) < words:
        pool = [
            "This section was rewritten for this launch and checked twice.",
            "Every claim here matches the brief the buyer signed off on.",
            "The work is original and ready to post without edits.",
            "Each post names the brand and gives readers a reason to care.",
            "The captions speak to coffee drinkers in plain everyday words.",
            "Nothing in this pack is recycled from another client or brand.",
            "The pack covers the full launch week with room to spare.",
            "Every line was proofread against the contract before delivery.",
            "The tone matches the shop: warm, direct, and never pushy.",
            "Hashtags were researched for this niche, not copied from rivals.",
            "A second reader checked the pack and signed off on it.",
            "The closing post points readers to the launch offer clearly.",
        ]
        i = 0
        while len(text.split()) < words:
            text += " " + pool[i % len(pool)]
            i += 1
    DEALS[deal["id"]]["deliverable"]["content"] = text
    deal = must(f"/api/deals/{deal['id']}/verify")
    check("fixed work passes on revision and releases",
          deal["state"] == "released", deal["state"])
    check("release pays the full price and returns the full bond",
          deal["payment"]["status"] == "released"
          and deal["bond"]["status"] == "returned",
          (deal["payment"]["status"], deal["bond"]["status"]))


def main():
    unit_tests()
    generated_cases()
    integration_tests()
    if FAILURES:
        print(f"ACCURACY BATTERY FAILED: {len(FAILURES)} failures: {FAILURES}")
        sys.exit(1)
    print("ACCURACY BATTERY PASSED")


if __name__ == "__main__":
    main()

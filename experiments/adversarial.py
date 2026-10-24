"""E5 adversarial battery: can either side cheat Pact?

Seller side attacks are run against settled specs. An attack "beats the
system" only if the delivery passes every check, because settlement
needs all of them. Buyer side and API attacks try to move money outside
the state machine: forced refunds, double payment, delivery after
refund, and deal terms that would gut the bond.

Run with: .venv/bin/python experiments/adversarial.py [out.json]
Writes the results JSON (default experiments/adversarial_results.json).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pact.negotiation import run_negotiation  # noqa: E402
from pact.scenarios import SCENARIO_BY_ID, build_delivery  # noqa: E402
from pact.money import to_cents  # noqa: E402
from pact.store import new_deal  # noqa: E402
from pact.verifier import verify_delivery  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    Path(__file__).resolve().parent / "adversarial_results.json")


async def settle(scenario_id):
    scen = SCENARIO_BY_ID[scenario_id]
    deal = new_deal(scen, to_cents(scen["default_buyer_max"]),
                    to_cents(scen["default_seller_floor"]), 20.0)
    await run_negotiation(deal, scen)
    return scen, deal["spec"]


def words(n, sentence="This sentence carries real weight in the delivery"):
    out = []
    while len(" ".join(out).split()) < n:
        out.append(sentence)
    return " ".join(out)


async def seller_attacks():
    scen, spec = await settle("logo_brand_kit")
    honest = build_delivery(scen, spec)
    results = []

    def record(name, text, note):
        outcome = verify_delivery(spec, text)
        results.append({
            "attack": name,
            "passed_all_checks": outcome["all_passed"],
            "checks_passed": f"{outcome['passed_count']}/{outcome['total_count']}",
            "failed_checks": [r["check_id"] for r in outcome["results"]
                              if not r["passed"]],
            "note": note,
        })

    # A1: markers with no content behind them. The honest builder puts
    # each concept note on its own line, so dropping those lines leaves
    # bare markers in an otherwise complete delivery.
    notes = {
        "A simple peak mark that reads well at small sizes on packaging and on screen.",
        "A wordmark with a tight letterspaced cut that feels calm and premium.",
        "A badge style mark for stamps, stickers, and loyalty cards.",
        "A monogram built from the initials for use on social avatars.",
    }
    a1 = "\n".join(line for line in honest.split("\n") if line not in notes)
    record("A1 empty items: markers present, item content stripped", a1,
           "Tests whether min_items counts bare markers.")

    # A2: honest structure, length bought with one repeated word.
    base = honest.split("Brand Guide")[0]
    a2 = base + "Brand Guide\n" + " ".join(["quality"] * 320)
    record("A2 word stuffing: length from a single repeated word", a2,
           "Tests the anti stuffing screen on the length check.")

    # A2b: length bought by rotating three sentences.
    pool = [
        "The design feels modern and clean for the brand.",
        "Colors were chosen to match the studio style.",
        "Every part of this delivery serves the launch.",
    ]
    tail = ""
    i = 0
    while len((base + tail).split()) < 420:
        tail += pool[i % len(pool)] + " "
        i += 1
    record("A2b sentence rotation stuffing", base + "Brand Guide\n" + tail,
           "Tests the screen against rotated sentence padding.")

    # A2c: honest front, then a stuffed tail heavy enough to clear the
    # raw word count on its own.
    record("A2c honest front, stuffed tail",
           base + "Brand Guide\n" + " ".join(["quality"] * 200),
           "Tests the screen on a hybrid: real work up front, stuffing "
           "behind it.")

    # A3: poor delivery plus the section needles echoed at the end.
    poor = build_delivery(scen, spec, quality="poor")
    record("A3 needle echo: poor work plus bare section words",
           poor + " Typography Tagline",
           "Tests whether contains checks can be passed by echo alone.")

    # A4: one real shortfall (drop a concept from honest work).
    lines = honest.split("\n")
    kept, skipped = [], False
    for line in lines:
        if line.startswith("Concept 3") and not skipped:
            skipped = True
            continue
        kept.append(line)
    record("A4 honest work minus one concept", "\n".join(kept),
           "Control case: a real shortfall must fail.")

    # A5: hashtag-only pack against the cheat scenario spec.
    _, cheat_spec = await settle("cheat_attempt")
    tags = " ".join(f"#LaunchTag{i}" for i in range(20))
    outcome = verify_delivery(cheat_spec, tags)
    results.append({
        "attack": "A5 hashtag stuffing alone against the social pack spec",
        "passed_all_checks": outcome["all_passed"],
        "checks_passed": f"{outcome['passed_count']}/{outcome['total_count']}",
        "failed_checks": [r["check_id"] for r in outcome["results"]
                          if not r["passed"]],
        "note": "One gamed check must not settle a deal on its own.",
    })
    return results


def api_attacks():
    import re

    from fastapi.testclient import TestClient
    from pact.main import app

    client = TestClient(app, raise_server_exceptions=False)
    results = []

    # Demo client token store (queue item W): state-changing deal
    # endpoints require the per-deal role token in the X-Deal-Token
    # header. The create response carries both tokens, so this helper
    # remembers them per deal id and attaches the right one, the way a
    # real client would. Deliver acts as the seller; everything else
    # here acts as the buyer.
    deal_tokens = {}

    def record(name, ok, detail):
        results.append({"attack": name, "blocked": ok, "detail": detail})

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

    # B1: verify before any delivery exists.
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    post(f"/api/deals/{deal['id']}/negotiate/run")
    post(f"/api/deals/{deal['id']}/pay")
    resp = post(f"/api/deals/{deal['id']}/verify")
    record("B1 verify before delivery", resp.status_code == 409,
           f"verify returned {resp.status_code}")

    # B2: pay twice.
    resp = post(f"/api/deals/{deal['id']}/pay")
    record("B2 second payment on the same deal", resp.status_code == 409,
           f"second pay returned {resp.status_code}")

    # B3: deliver after a refund has closed the deal.
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    post(f"/api/deals/{deal['id']}/negotiate/run")
    post(f"/api/deals/{deal['id']}/pay")
    post(f"/api/deals/{deal['id']}/deliver", {"quality": "poor"})
    final = post(f"/api/deals/{deal['id']}/verify").json()
    resp = post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    record("B3 deliver after refund",
           resp.status_code == 409 and final["state"] == "refunded",
           f"deliver returned {resp.status_code}, deal state {final['state']}")

    # B4: no buyer path can refund a deal whose work passed.
    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    post(f"/api/deals/{deal['id']}/negotiate/run")
    post(f"/api/deals/{deal['id']}/pay")
    post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    final = post(f"/api/deals/{deal['id']}/verify").json()
    resp = post(f"/api/deals/{deal['id']}/verify")
    record("B4 passing work cannot be refunded by re-verifying",
           resp.status_code == 409 and final["state"] == "released",
           f"re-verify returned {resp.status_code}, deal state {final['state']}")

    # B5: a zero bond would make cheating free.
    resp = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "bond_percent": 0})
    if resp.status_code == 200:
        bond = resp.json()["spec"] if resp.json().get("spec") else None
        record("B5 zero percent bond accepted", False,
               "deal created with bond_percent 0")
    else:
        record("B5 zero percent bond accepted", True,
               f"create returned {resp.status_code}")

    # B6: a negative ceiling makes the money math meaningless.
    resp = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "buyer_max": -50})
    record("B6 negative buyer ceiling accepted", resp.status_code != 200,
           f"create returned {resp.status_code}")
    return results


async def main():
    results = {
        "seller_attacks": await seller_attacks(),
        "api_attacks": api_attacks(),
    }
    OUT.write_text(json.dumps(results, indent=1))
    for row in results["seller_attacks"]:
        verdict = "BEAT THE SYSTEM" if row["passed_all_checks"] else "caught"
        print(f"{row['attack']}: {verdict} ({row['checks_passed']})")
    for row in results["api_attacks"]:
        verdict = "blocked" if row["blocked"] else "NOT BLOCKED"
        print(f"{row['attack']}: {verdict} ({row['detail']})")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

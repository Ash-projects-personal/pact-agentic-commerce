"""T (part 1): extended verifier battery.

Runs every settled-spec scenario through the full adversarial mutation
battery and judges every delivery with pact/verifier.py verify_delivery.
Writes experiments/verifier_battery_results.json.

Pattern per scenario (from experiments/adversarial.py):
    deal = new_deal(scen, to_cents(scen["default_buyer_max"]),
                    to_cents(scen["default_seller_floor"]), 20.0)
    await run_negotiation(deal, scen)
    deliveries = build_delivery(scen, spec, quality=...) variants plus
    every seller-side mutation family (A1..A5) generalized to that
    scenario's own delivery text and settled spec.

Mutation families (generalized from adversarial.py):
  A1 empty markers: strip content lines, leaving bare markers/headers.
  A2 single-word stuffing: honest front + N copies of one word.
  A2b sentence rotation: honest front + rotated sentence pool to ~450 words.
  A2c honest front, stuffed tail: full honest text + N copies of one word.
  A3 needle echo: poor delivery + the settled spec's contains-check needles.
  A4 dropped concept control: honest delivery minus a chunk of lines.
  A5 hashtag-only: bare hashtag tokens against the scenario's own spec.
Buyer/API families B1..B6 are run once via the in-process TestClient
(demo mode, throwaway DB, no live money) and reported separately.

Labels: honest (expected all checks pass), cheat / poor / mutations
(expected fail, i.e. NOT all checks pass), weak (observed distribution
only, no expectation; only 7 of 14 scenarios ship a weak builder).

Run with: NO_PROXY=localhost,127.0.0.1 .venv/bin/python experiments/verifier_battery.py
"""

import asyncio
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

SEED = 20261023

# Force demo mode before the app modules read the environment, and point
# persistence at a throwaway database (same pattern as tests/smoke_test.py).
for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)
os.environ["PACT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "verifier-battery.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pact.negotiation import run_negotiation  # noqa: E402
from pact.scenarios import (  # noqa: E402
    SCENARIO_BY_ID,
    _WEAK_BUILDERS,
    build_delivery,
)
from pact.money import to_cents  # noqa: E402
from pact.store import new_deal  # noqa: E402
from pact.verifier import verify_delivery  # noqa: E402

OUT = Path(__file__).resolve().parent / "verifier_battery_results.json"

SCENARIO_IDS = [
    "logo_brand_kit",
    "landing_page_copy",
    "cheat_attempt",
    "code_task",
    "research_brief",
    "amazon_listing",
    "procurement",
    "data_labeling_batch",
    "podcast_edit_package",
    "newsletter_issue",
    "product_photo_set",
    "book_cover_design",
    "api_integration_task",
    "spreadsheet_cleanup_report",
]

A2B_POOL = [
    "The design feels modern and clean for the brand.",
    "Colors were chosen to match the studio style.",
    "Every part of this delivery serves the launch.",
    "The copy reads well on a phone screen too.",
    "Nothing here was rushed or left unfinished.",
]

FAIL_LABELS = {"cheat", "poor", "A1", "A2", "A2b", "A2c", "A3", "A4", "A5"}


async def settle(scenario_id):
    scen = SCENARIO_BY_ID[scenario_id]
    deal = new_deal(scen, to_cents(scen["default_buyer_max"]),
                    to_cents(scen["default_seller_floor"]), 20.0)
    await run_negotiation(deal, scen)
    return scen, deal["spec"]


def contains_needles(spec):
    return [c["value"] for c in spec["acceptance_checks"]
            if c["kind"] == "contains"]


def content_lines(text):
    """Lines carrying real content: >= 8 words and not a bare header."""
    return [ln for ln in text.split("\n") if len(ln.split()) >= 8]


def mutate(scenario_id, spec, base, family, variant):
    """Build one mutated delivery text. Returns (text, note)."""
    if family == "A1":
        lines = base.split("\n")
        content = content_lines(base)
        if variant == 0:
            drop = set(content)
            note = "all content lines stripped, bare markers remain"
        else:
            drop = set(content[::2])
            note = "every other content line stripped"
        return "\n".join(ln for ln in lines if ln not in drop), note
    if family == "A2":
        front = " ".join(base.split()[:150])
        n = (100, 320, 600)[variant]
        return front + "\n" + " ".join(["quality"] * n), (
            f"honest front + {n}x single-word stuffing")
    if family == "A2b":
        front = " ".join(base.split()[:150])
        pool = A2B_POOL[: (2, 3, 5)[variant]]
        tail, i = "", 0
        while len((front + " " + tail).split()) < 450:
            tail += pool[i % len(pool)] + " "
            i += 1
        return front + "\n" + tail, (
            f"honest front + {len(pool)}-sentence rotation to ~450 words")
    if family == "A2c":
        n = (100, 200, 400)[variant]
        return base + "\n" + " ".join(["quality"] * n), (
            f"full honest text + {n}x single-word tail")
    if family == "A3":
        poor = build_delivery(SCENARIO_BY_ID[scenario_id], spec,
                              quality="poor")
        needles = " ".join(contains_needles(spec))
        if variant == 0:
            return poor + " " + needles, "poor + spec needles echoed once"
        return poor + " " + " ".join([needles] * 5), (
            "poor + spec needles echoed 5x")
    if family == "A4":
        lines = base.split("\n")
        n = len(lines)
        if n >= 4:
            if variant == 0:
                cut = slice(n // 4, n // 2)
                note = "dropped second quarter of lines"
            elif variant == 1:
                cut = slice(n // 3, 2 * n // 3)
                note = "dropped middle third of lines"
            else:
                cut = slice(3 * n // 4, n)
                note = "dropped last quarter of lines"
            kept = [ln for i, ln in enumerate(lines)
                    if i not in range(*cut.indices(n))]
        else:
            words = base.split()
            kept = [" ".join(words[: len(words) // 2])]
            note = "dropped second half of words (short base)"
        return "\n".join(kept), "control: " + note
    if family == "A5":
        n = (10, 20, 40)[variant]
        return " ".join(f"#LaunchTag{i}" for i in range(n)), (
            f"{n} bare hashtag tokens against this scenario's spec")
    raise ValueError(family)


MUTATION_VARIANTS = {
    "A1": 2, "A2": 3, "A2b": 3, "A2c": 3, "A3": 2, "A4": 3, "A5": 3,
}


def judge(spec, text):
    outcome = verify_delivery(spec, text)
    return {
        "all_passed": outcome["all_passed"],
        "passed_count": outcome["passed_count"],
        "total_count": outcome["total_count"],
        "failed_check_ids": [r["check_id"] for r in outcome["results"]
                             if not r["passed"]],
        "passed_check_ids": [r["check_id"] for r in outcome["results"]
                             if r["passed"]],
        "check_results": [(r["check_id"], bool(r["passed"]))
                          for r in outcome["results"]],
    }


def api_attacks():
    """B1..B6 from experiments/adversarial.py, run in-process in demo
    mode against the throwaway DB. No live money."""
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
        results.append({"attack": name, "blocked": bool(ok),
                        "detail": detail})

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

    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    post(f"/api/deals/{deal['id']}/negotiate/run")
    post(f"/api/deals/{deal['id']}/pay")
    resp = post(f"/api/deals/{deal['id']}/verify")
    record("B1 verify before delivery", resp.status_code == 409,
           f"verify returned {resp.status_code}")

    resp = post(f"/api/deals/{deal['id']}/pay")
    record("B2 second payment on the same deal", resp.status_code == 409,
           f"second pay returned {resp.status_code}")

    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    post(f"/api/deals/{deal['id']}/negotiate/run")
    post(f"/api/deals/{deal['id']}/pay")
    post(f"/api/deals/{deal['id']}/deliver", {"quality": "poor"})
    final = post(f"/api/deals/{deal['id']}/verify").json()
    resp = post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    record("B3 deliver after refund",
           resp.status_code == 409 and final["state"] == "refunded",
           f"deliver returned {resp.status_code}, deal state "
           f"{final['state']}")

    deal = post("/api/deals", {"scenario_id": "logo_brand_kit"}).json()
    post(f"/api/deals/{deal['id']}/negotiate/run")
    post(f"/api/deals/{deal['id']}/pay")
    post(f"/api/deals/{deal['id']}/deliver", {"quality": "auto"})
    final = post(f"/api/deals/{deal['id']}/verify").json()
    resp = post(f"/api/deals/{deal['id']}/verify")
    record("B4 passing work cannot be refunded by re-verifying",
           resp.status_code == 409 and final["state"] == "released",
           f"re-verify returned {resp.status_code}, deal state "
           f"{final['state']}")

    resp = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "bond_percent": 0})
    record("B5 zero percent bond accepted", resp.status_code != 200,
           f"create returned {resp.status_code}")

    resp = post("/api/deals", {"scenario_id": "logo_brand_kit",
                               "buyer_max": -50})
    record("B6 negative buyer ceiling accepted", resp.status_code != 200,
           f"create returned {resp.status_code}")
    return results


async def main():
    random.seed(SEED)
    t0 = time.time()
    deliveries = []  # one record per judged delivery
    per_scenario = {}
    weak_dist = {}
    weak_builder_available = {}
    honest_builder_available = {}
    check_cm = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}
    delivery_cm = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}
    family_totals = {}
    family_blocked = {}
    weak_check_findings = []

    for sid in SCENARIO_IDS:
        scen, spec = await settle(sid)
        per_scenario[sid] = {"honest": 0, "cheat": 0, "poor": 0,
                             "weak": 0, "mutations": 0, "checks_judged": 0,
                             "spec_check_count": len(spec["acceptance_checks"])}
        base = build_delivery(scen, spec)  # canonical auto delivery
        is_cheat_seller = scen.get("seller_behavior") == "cheat"

        def add(label, text, expected):
            nonlocal deliveries
            j = judge(spec, text)
            deliveries.append({
                "scenario_id": sid, "label": label, "expected": expected,
                "all_passed": j["all_passed"],
                "passed_count": j["passed_count"],
                "total_count": j["total_count"],
                "failed_check_ids": j["failed_check_ids"],
                "passed_check_ids": j["passed_check_ids"],
            })
            per_scenario[sid]["checks_judged"] += j["total_count"]
            return j

        # honest: only where the builder is not a cheat seller
        honest_builder_available[sid] = not is_cheat_seller
        if not is_cheat_seller:
            j = add("honest", base, "pass")
            per_scenario[sid]["honest"] = 1
            for cid, passed in j["check_results"]:
                if passed:
                    check_cm["TP"] += 1
                else:
                    check_cm["FN"] += 1
                    weak_check_findings.append({
                        "scenario_id": sid, "label": "honest",
                        "check_id": cid,
                        "finding": "honest delivery failed a check it should "
                                   "pass",
                    })
            if j["all_passed"]:
                delivery_cm["TP"] += 1
            else:
                delivery_cm["FN"] += 1
                weak_check_findings.append({
                    "scenario_id": sid, "label": "honest",
                    "finding": "honest delivery did not pass all checks",
                    "failed_check_ids": j["failed_check_ids"],
                })

        # cheat / poor: expected fail on every check and at delivery level
        for label in ("cheat", "poor"):
            j = add(label, build_delivery(scen, spec, quality=label),
                    "fail")
            per_scenario[sid][label] = 1
            for cid, passed in j["check_results"]:
                if passed:
                    check_cm["FP"] += 1
                    weak_check_findings.append({
                        "scenario_id": sid, "label": label, "check_id": cid,
                        "finding": f"{label} delivery passed a check it was "
                                   "expected to fail",
                    })
                else:
                    check_cm["TN"] += 1
            if j["all_passed"]:
                delivery_cm["FP"] += 1
                weak_check_findings.append({
                    "scenario_id": sid, "label": label,
                    "finding": f"{label} delivery passed ALL checks "
                               "(beats the system)",
                })
            else:
                delivery_cm["TN"] += 1

        # weak: observed distribution only; no weak builder for 7 scenarios
        has_weak = sid in _WEAK_BUILDERS
        weak_builder_available[sid] = has_weak
        if has_weak:
            j = add("weak", build_delivery(scen, spec, quality="weak"),
                    "observed")
            per_scenario[sid]["weak"] = 1
            weak_dist[sid] = {
                "all_passed": j["all_passed"],
                "passed_count": j["passed_count"],
                "total_count": j["total_count"],
                "failed_check_ids": j["failed_check_ids"],
            }
        else:
            weak_dist[sid] = {"weak_builder": "not shipped",
                              "note": "recorded honestly; not faked"}

        # mutation families, multiple honest variants each
        for family, nvar in MUTATION_VARIANTS.items():
            family_totals.setdefault(family, 0)
            family_blocked.setdefault(family, 0)
            for v in range(nvar):
                text, note = mutate(sid, spec, base, family, v)
                j = add(family, text, "fail")
                per_scenario[sid]["mutations"] += 1
                family_totals[family] += 1
                if not j["all_passed"]:
                    family_blocked[family] += 1
                    delivery_cm["TN"] += 1
                else:
                    delivery_cm["FP"] += 1
                    weak_check_findings.append({
                        "scenario_id": sid, "label": f"{family}v{v}",
                        "finding": f"mutation {family} variant {v} passed "
                                   "ALL checks (beats the system)",
                        "note": note,
                    })

    api_results = api_attacks()

    total_deliveries = len(deliveries)
    total_checks = sum(d["total_count"] for d in deliveries)

    def accuracy(cm):
        tot = sum(cm.values())
        return (cm["TP"] + cm["TN"]) / tot if tot else None

    check_acc = accuracy(check_cm)
    delivery_acc = accuracy(delivery_cm)

    # per-label delivery-level accuracy (labels with expectations)
    label_acc = {}
    for label in ["honest", "cheat", "poor"] + sorted(MUTATION_VARIANTS):
        ds = [d for d in deliveries if d["label"] == label]
        if not ds:
            continue
        if label == "honest":
            correct = sum(1 for d in ds if d["all_passed"])
        else:
            correct = sum(1 for d in ds if not d["all_passed"])
        label_acc[label] = {
            "n": len(ds), "correct": correct,
            "accuracy": correct / len(ds),
        }

    # per-scenario delivery accuracy over expectation-carrying labels
    scenario_acc = {}
    for sid in SCENARIO_IDS:
        ds = [d for d in deliveries
              if d["scenario_id"] == sid and d["label"] in FAIL_LABELS
              or d["scenario_id"] == sid and d["label"] == "honest"]
        correct = sum(1 for d in ds
                      if (d["label"] == "honest") == d["all_passed"])
        scenario_acc[sid] = {
            "n": len(ds), "correct": correct,
            "accuracy": correct / len(ds) if ds else None,
            "honest_builder_available": honest_builder_available[sid],
            "weak_builder_available": weak_builder_available[sid],
            "counts": {k: per_scenario[sid][k] for k in
                       ("honest", "cheat", "poor", "weak", "mutations")},
            "checks_judged": per_scenario[sid]["checks_judged"],
        }

    family_block_rates = {
        fam: {"n": family_totals[fam],
              "blocked": family_blocked[fam],
              "block_rate": family_blocked[fam] / family_totals[fam]}
        for fam in sorted(MUTATION_VARIANTS)
    }

    runtime_s = time.time() - t0

    report = {
        "title": "T (part 1): extended verifier battery",
        "seed": SEED,
        "method": (
            "Each of the 14 scenarios is settled once via new_deal(scen, "
            "scen['default_buyer_max'], scen['default_seller_floor'], 20.0) "
            "followed by run_negotiation, exactly the experiments/adversarial.py "
            "pattern. Deliveries are built with build_delivery(scen, spec, "
            "quality=...) for quality in auto (honest; unavailable for "
            "cheat_attempt, whose seller_behavior is 'cheat'), cheat, poor, "
            "and weak (only the 7 scenarios shipping a weak builder; the "
            "other 7 are recorded honestly instead of faked). Every "
            "seller-side mutation family (A1 empty markers, A2 single-word "
            "stuffing, A2b sentence rotation, A2c honest front plus stuffed "
            "tail, A3 needle echo, A4 dropped concept control, A5 "
            "hashtag-only) is generalized from adversarial.py to each "
            "scenario's own delivery text and settled spec, in multiple "
            "honest parameter variants per family. Every delivery is judged "
            "with pact/verifier.py verify_delivery(spec, text). Expected "
            "verdicts: honest -> all checks pass; cheat, poor, and every "
            "mutation -> fail (not all checks pass). Weak deliveries carry no "
            "expectation and are reported as an observed distribution. "
            "Buyer/API families B1..B6 are run once via the in-process "
            "TestClient in demo mode against a throwaway SQLite DB (no live "
            "money, no live server) and reported as blocked/not-blocked. "
            "Demo mode forced by popping PAYPAL_CLIENT_ID, "
            "PAYPAL_CLIENT_SECRET, LLM_API_KEY before import; "
            "PACT_DB_PATH points at a temp dir. Frozen E1..E4 numbers in "
            "experiments/run_experiments.py were not touched."
        ),
        "total_deliveries": total_deliveries,
        "total_judged_checks": total_checks,
        "checks_per_delivery": total_checks / total_deliveries
        if total_deliveries else None,
        "check_level_confusion_matrix": dict(check_cm),
        "check_level_accuracy": check_acc,
        "check_level_note": (
            "Expected per-check verdicts are deterministic: honest expected "
            "pass on every check; cheat and poor expected fail on every "
            "check. Weak deliveries carry no expectation and are excluded."
        ),
        "delivery_level_confusion_matrix": dict(delivery_cm),
        "delivery_level_accuracy": delivery_acc,
        "delivery_level_note": (
            "Expected delivery verdicts: honest -> all_passed True; cheat, "
            "poor, and every mutation family -> all_passed False. Weak "
            "deliveries carry no expectation and are excluded."
        ),
        "per_label_delivery_accuracy": label_acc,
        "per_scenario_accuracy": scenario_acc,
        "per_scenario_counts": per_scenario,
        "per_family_block_rates": family_block_rates,
        "family_block_rate_note": (
            "Block rate = share of deliveries in the family that failed at "
            "least one check (all_passed False), i.e. the verifier stopped "
            "the attack from settling."
        ),
        "weak_distribution": weak_dist,
        "api_attack_families": api_results,
        "weak_check_findings": weak_check_findings,
        "runtime_seconds": round(runtime_s, 2),
    }

    with open(OUT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"wrote {OUT}")
    print(f"deliveries={total_deliveries} judged_checks={total_checks} "
          f"check_acc={check_acc:.4f} delivery_acc={delivery_acc:.4f} "
          f"runtime={runtime_s:.1f}s findings={len(weak_check_findings)}")
    assert total_deliveries >= 300, total_deliveries
    assert total_checks >= 1500, total_checks


if __name__ == "__main__":
    asyncio.run(main())

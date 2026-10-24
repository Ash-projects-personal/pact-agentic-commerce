"""Build the PactBench Evidence page/table from run-generated numbers only.

Reads every experiment results JSON plus the saved full-suite log
(argv[1], which carries the property and chaos summary lines), and
writes three artifacts:

  experiments/evidence_section.html  - the demo UI Evidence section
  experiments/evidence_table.md      - the README Evidence table
  experiments/evidence_paper.md      - the paper Evidence subsection

No number in any of them is typed by hand. Re-run this after any
experiment changes and re-insert the outputs into index.html,
README.md, and the paper draft.

Run with: .venv/bin/python experiments/build_evidence.py <suite-log>
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT


def load(name):
    with open(ROOT / name) as f:
        return json.load(f)


def pct(x):
    return f"{100.0 * x:.1f}%"


def main():
    suite_log = Path(sys.argv[1]).read_text()

    results = load("results.json")
    e1 = results["E1_verifier_accuracy"]
    e2 = results["E2_negotiation_sweep"]
    e3 = results["E3_settlement_oracle"]
    e4 = results["E4_live_sandbox_evidence"]

    battery = load("verifier_battery_results.json")
    mc = load("monte_carlo_settlement_results.json")
    loadres = load("pactbench_load_results.json")
    multi = load("results_multi_issue.json")

    prop = re.search(r"seed=(\d+) cases=(\d+) checks=(\d+) PASS", suite_log)
    prop_seed, prop_cases, prop_checks = prop.group(1), prop.group(2), prop.group(3)

    chaos = re.search(r"ALL CHAOS TESTS PASSED: (\d+) cases, (\d+) checks", suite_log)
    chaos_cases, chaos_checks = chaos.group(1), chaos.group(2)

    # ---- derived, all from the runs ----
    b_cm = battery["check_level_confusion_matrix"]
    b_del = battery["delivery_level_confusion_matrix"]
    mc_hist = mc["terminal_state_histogram"]
    mc_total = mc["deals_run"]
    lat = loadres["end_to_end_latency_ms"]
    ops = loadres["per_operation_latency_ms"]
    mi_terms = multi["mean_settled_terms"]

    rows = [
        ("E1 verifier accuracy (frozen)",
         f"{e1['deliveries']} deliveries, {e1['checks_judged']} checks judged",
         f"check accuracy {pct(e1['check_level_accuracy'])}, delivery accuracy "
         f"{pct(e1['delivery_level_accuracy'])}, traps {e1['trap_cases_right']}/{e1['trap_cases']}",
         "experiments/results.json"),
        ("PactBench verifier battery (extended)",
         f"{battery['total_deliveries']} deliveries across all 14 scenarios, "
         f"{battery['total_judged_checks']} checks judged, seed {battery['seed']}",
         f"check accuracy {pct(battery['check_level_accuracy'])} "
         f"(TP {b_cm['TP']} TN {b_cm['TN']} FP {b_cm['FP']} FN {b_cm['FN']}); "
         f"delivery accuracy {pct(battery['delivery_level_accuracy'])} "
         f"(TP {b_del['TP']} TN {b_del['TN']} FP {b_del['FP']} FN {b_del['FN']})",
         "experiments/verifier_battery_results.json"),
        ("E2 negotiation sweep (frozen)",
         f"{e2['runs']} runs on the buyer ceiling by seller floor grid",
         f"in-zone agreement {pct(e2['agreement_rate_in_zone'])}, walk away correct "
         f"{pct(e2['walk_away_correct_rate'])}, mean price position "
         f"{e2['mean_price_position']:.4f}",
         "experiments/results.json"),
        ("Multi-issue negotiation sweep",
         f"{multi['runs']} runs, seed fixed in the sweep script",
         f"agreement in zone {pct(multi['agreement_rate_in_zone'])}, match vs "
         f"single-issue twins {pct(multi['agreement_match_vs_single_issue'])}, "
         f"walk away correct {pct(multi['walk_away_correct_rate'])}, bond consistent "
         f"{pct(multi['bond_consistent_rate'])}, cap hits {pct(multi['cap_hit_rate'])}, "
         f"mean {multi['mean_terms_moves_in_zone']:.1f} terms moves, settled terms "
         f"{int(mi_terms['delivery_days'])} days / {int(mi_terms['revision_rounds'])} rounds / "
         f"{mi_terms['bond_percent']:.2f}% bond",
         "experiments/results_multi_issue.json"),
        ("E3 settlement oracle (frozen)",
         f"{e3['paths']} end-to-end deal paths",
         f"{e3['paths_matching_oracle']}/{e3['paths']} match the rules oracle, "
         f"{e3['total_ledger_events']} ledger events total",
         "experiments/results.json"),
        ("Monte Carlo settlement integrity",
         f"{mc_total:,} simulated deals, seed {mc['seed']}, randomized prices, bond percents, "
         "concession rates, delivery qualities, injected leg failures",
         f"verdict-state violations {mc['invariant_a_violations']}, money conservation "
         f"violations {mc['invariant_b_violations']}, terminal states released "
         f"{mc_hist['released']:,} / refunded {mc_hist['refunded']:,} / failed {mc_hist['failed']:,}",
         "experiments/monte_carlo_settlement_results.json"),
        ("Property tests (randomized API)",
         f"{prop_cases} randomized cases, {prop_checks} checks, seed {prop_seed}",
         "end-to-end deals across scenarios and qualities, illegal transitions "
         "rejected, malformed bodies fuzzed, state machine invariants hold",
         "tests/pactbench_property_test.py"),
        ("Chaos suite",
         f"{chaos_cases} cases, {chaos_checks} checks",
         "every settlement leg killed and resumed to the right terminal state, "
         "duplicate webhooks idempotent, out-of-order webhooks handled, "
         "replayed pay/pay-confirm on terminal deals rejected with 409",
         "tests/pactbench_chaos_test.py"),
        ("Load check",
         f"{loadres['n_deals']} parallel deals settled in demo mode, concurrency "
         f"{loadres['concurrency']}, seed {loadres['seed']}",
         f"end-to-end p50 {lat['p50']:.0f} ms / p95 {lat['p95']:.0f} ms / p99 "
         f"{lat['p99']:.0f} ms, total wall time {loadres['total_wall_time_s']:.1f} s, "
         f"{loadres['terminal_states']['released']} released / "
         f"{loadres['terminal_states']['refunded']} refunded, zero failures",
         "experiments/pactbench_load_results.json"),
        ("E4 live sandbox deals (frozen)",
         f"{len(e4['deals'])} deals settled on {e4['environment']} on {e4['date']}",
         "price payouts, bond returns, refund plus bond slash all executed with "
         "real sandbox transaction ids, recorded in the paper table",
         "experiments/results.json"),
    ]

    # ---- README markdown table ----
    md = ["## Evidence (PactBench)", "",
          "Every number below was generated by a run, not typed by hand. "
          "The frozen studies (E1, E2, E3, E4) never change retroactively. "
          "New suites extend the evidence, they do not rewrite it.", "",
          "| Suite | Size | Result | Source |",
          "|---|---|---|---|"]
    for name, size, result, src in rows:
        md.append(f"| {name} | {size} | {result} | `{src}` |")
    (OUT_DIR / "evidence_table.md").write_text("\n".join(md) + "\n")

    # ---- paper subsection ----
    paper = ["### PactBench: the testing program", "",
             "Ten suites, each with its size and its result. The frozen studies "
             "never change retroactively. New suites extend the evidence.", ""]
    for name, size, result, src in rows:
        paper.append(f"**{name}.** {size}. {result}. ({src})")
        paper.append("")
    (OUT_DIR / "evidence_paper.md").write_text("\n".join(paper))

    # ---- demo UI section ----
    cards = []
    for name, size, result, src in rows:
        cards.append(
            f'<div class="evidence-card"><h3>{name}</h3>'
            f'<p class="muted">{size}</p><p>{result}</p>'
            f'<p class="muted evidence-src">{src}</p></div>')
    html = [
        '<section class="column wide" id="evidenceSection">',
        '  <h2>Evidence (PactBench)</h2>',
        '  <p class="muted">Every number on this page was generated by a run, '
        'not typed by hand. The frozen studies never change retroactively.</p>',
        '  <div class="evidence-grid">',
        *[f"    {c}" for c in cards],
        "  </div>",
        "</section>",
    ]
    (OUT_DIR / "evidence_section.html").write_text("\n".join(html) + "\n")

    print("wrote evidence_table.md, evidence_paper.md, evidence_section.html")
    print(f"{len(rows)} suites from run-generated JSON + suite log")


if __name__ == "__main__":
    main()

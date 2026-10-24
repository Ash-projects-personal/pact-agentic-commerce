"""Anti stuffing upgrade evaluation: effective words vs the shipped screen.

Candidate upgrade (research/nlp-anti-stuffing-design.md): replace the raw
word count in the min_words check with EFFECTIVE words, where effective
words = W - dup and dup is the number of token positions covered by a
duplicate instance of a 5-token shingle (whitespace tokenization, no case
folding, first shingle instance never marked). Backstop candidate:
longest repeated token run share, hard fail at ceiling 0.15.

Calibration (decided before measuring, per the design):
- Honest corpus: every scenario's honest builder output over a settled
  value grid (buyer_max/seller_floor at default, x0.8, x1.2; skips where
  negotiation fails to settle). cheat_attempt is excluded on purpose: its
  builder returns the cheat seller's recycled copy, not an honest
  delivery, so it is not an honest data point for this statistic.
- Attack family, each member sized to the cheapest version that passes
  the OLD raw count: raw words = settled required value + 60, matching
  how builders pad to required + 60.
- Margins per kind (prose vs code-bearing), each delivery measured
  against ITS OWN settled required value V, gate computed only for
  texts >= 150 tokens:
    honest passes iff  worst honest effective  >= 1.10 * V
    attack fails iff   strongest attack effective <= 0.85 * V
- Longest repeat ceiling 0.15 is adoptable for a kind only if the
  honest max share and the attack min share are at least 3x apart.
- If the bands overlap for a kind, the statistic does not gate for
  that kind. The result is reported, not shipped.

Also computed: a HYPOTHETICAL honest variant that pads with the wide
24-sentence PAD_POOL from experiments/run_experiments.py instead of the
narrow shipped pools, to show whether a wider builder pool would clear
the margins. It does not change the adoption decision for the current
shipped builders.

Run with: NO_PROXY=localhost,127.0.0.1 .venv/bin/python \\
    experiments/effective_words_study.py
Writes experiments/effective_words_study.json.
"""

import asyncio
import json
import os
import random
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pact.scenarios as scenarios  # noqa: E402
from pact.negotiation import run_negotiation  # noqa: E402
from pact.scenarios import SCENARIO_BY_ID, build_delivery  # noqa: E402
from pact.money import dollars, pct_of, to_cents
from pact.store import new_deal  # noqa: E402
from pact.verifier import degeneracy  # noqa: E402

OUT = Path(__file__).resolve().parent / "effective_words_study.json"

# Wide padding pool for the HYPOTHETICAL variant. Copied verbatim from
# experiments/run_experiments.py PAD_POOL (the E1 experiment pool); it
# avoids every scenario needle, marker, hashtag, and hex pattern.
WIDE_POOL = [
    "The work follows the brief the buyer approved before the deal was signed.",
    "Every section was drafted for this client and checked against the notes twice.",
    "The tone stays plain and direct from the opening line to the close.",
    "Nothing here is copied from a template or reused from an older job.",
    "A first time reader should grasp the offer within a few seconds.",
    "The structure follows the order a real customer thinks in, step by step.",
    "Short sentences carry the main points so the page stays easy to scan.",
    "The closing part answers the strongest objection a buyer usually raises.",
    "Care was taken to keep the wording free of jargon and filler phrases.",
    "Each paragraph earns its place and nothing decorative was left in.",
    "The draft was read aloud once to catch lines that sounded stiff.",
    "Facts in this piece come from the material the buyer supplied.",
    "Where a number appears, it matches the figure in the buyer notes.",
    "The piece is ready to use as delivered, with no further edits needed.",
    "If the buyer wants a shorter version later, the structure supports it.",
    "The opening promises only what the rest of the piece can back up.",
    "Transitions were smoothed so the reading never stops and restarts.",
    "The voice matches the samples the buyer pointed to at the start.",
    "No claim in the text depends on a trend that will date quickly.",
    "The layout leaves room for the work to grow in a later round.",
    "Details were favored over general statements wherever the two competed.",
    "The final pass removed repeats and tightened every loose sentence.",
    "A skeptical reader was the test: each line had to survive one.",
    "The result is calm, clear, and built for the audience named in the brief.",
]

GRID_SCALES = (1.0, 0.8, 1.2)
GATE_MIN_TOKENS = 150
SHINGLE_N = 5

# 100 distinct plain words for the rotated cycle attacks.
CYCLE_VOCAB = (
    "alpha bravo cargo delta ember flint grove harbor ivory jolt karma "
    "lumen mesa north oak pine quill ridge stone tread umber vapor wheat "
    "xenon yield zebra anchor bloom crest drift elm frost gleam hearth "
    "inlet jade knoll lagoon maple notch opal prairie quartz river surge "
    "thorn unity vale willow amber basin cliff dune echo fern glade hymn "
    "isle jetty kiosk lark meadow nymph otter plumb quarry reef shell "
    "tide urn veldt wharf yearn aloft brisk cobble dusk embered fable "
    "grain husk ivied jovial kindle loam mirth noble ozone petal quaint "
    "rustic sober tangy utile vivid woven yarn zest"
).split()


def effective_words(text):
    """Return (effective, dup, W) for the 5-token duplicate shingle rule."""
    tokens = text.split()
    w = len(tokens)
    seen = set()
    marked = bytearray(w)
    for i in range(w - SHINGLE_N + 1):
        shingle = tuple(tokens[i:i + SHINGLE_N])
        if shingle in seen:
            for j in range(i, i + SHINGLE_N):
                marked[j] = 1
        else:
            seen.add(shingle)
    dup = sum(marked)
    return w - dup, dup, w


def longest_repeat_share(text):
    """Longest contiguous token run occurring at least twice (overlap ok)."""
    tokens = text.split()
    w = len(tokens)
    best = 0
    for i in range(w):
        if w - i <= best:
            break
        ti = tokens
        for j in range(i + 1, w):
            if w - j <= best:
                break
            k = 0
            while i + k < w and j + k < w and ti[i + k] == ti[j + k]:
                k += 1
            if k > best:
                best = k
    return (best / w if w else 0.0), best


def text_stats(text):
    eff, dup, w = effective_words(text)
    share, run_len = longest_repeat_share(text)
    degen, ratio, unique = degeneracy(text)
    raw = text.encode()
    return {
        "words": w,
        "effective": eff,
        "dup_positions": dup,
        "longest_repeat_share": round(share, 4),
        "longest_repeat_len": run_len,
        "zlib_ratio": round(ratio, 4) if ratio is not None else None,
        "four_gram_unique": round(unique, 4) if unique is not None else None,
        "shipped_degenerate": bool(degen),
    }


def _repeat_to(words, target):
    reps = (target // len(words)) + 1
    return " ".join((words * reps)[:target])


def attack_family(honest_text, target):
    """Parameterized stuffing family, every member at `target` raw words."""
    attacks = {}
    attacks["single repeated token"] = " ".join(["quality"] * target)
    sentence = ("This work was done with great care and attention to "
                "every detail of the brief.")
    attacks["one repeated sentence"] = _repeat_to(sentence.split(), target)
    for k in (5, 20, 100):
        attacks[f"rotated cycle of {k} tokens"] = _repeat_to(
            CYCLE_VOCAB[:k], target)
    base = CYCLE_VOCAB[:20]
    for m in (5, 10, 20):
        toks = [f"mx{i}" if i % m == 0 else base[i % len(base)]
                for i in range(target)]
        attacks[f"mutated cycle every {m} tokens"] = " ".join(toks)
    if honest_text:
        rng = random.Random(20261022)
        vocab = honest_text.split()
        shuffled = vocab[:]
        rng.shuffle(shuffled)
        attacks["own vocabulary shuffled salad"] = _repeat_to(shuffled, target)
        front = honest_text.split()
        for honest_pct in (25, 50, 75):
            n_honest = int(target * honest_pct / 100)
            stuffed = target - n_honest
            text = " ".join(front[:n_honest] + ["quality"] * stuffed)
            attacks[f"interleave honest {honest_pct}% stuffed "
                    f"{100 - honest_pct}%"] = text
    return attacks


async def settle(sid, scale):
    scen = SCENARIO_BY_ID[sid]
    deal = new_deal(
        scen,
        to_cents(scen["default_buyer_max"] * scale),
        to_cents(scen["default_seller_floor"] * scale),
        20.0,
    )
    await run_negotiation(deal, scen)
    return deal


def wide_pad_words(text, target):
    i = 0
    while len(text.split()) < target:
        text += " " + WIDE_POOL[i % len(WIDE_POOL)]
        i += 1
    return text


def wide_pad_comment_words(text, target):
    i = 0
    while len(text.split()) < target:
        text += f"\n# Note: {WIDE_POOL[i % len(WIDE_POOL)]}"
        i += 1
    return text


def kind_of(sid):
    return "code" if sid == "code_task" else "prose"


async def main():
    honest_records = []
    attack_records = []
    seen_honest = set()
    notes = []

    real_negotiation = await settle("logo_brand_kit", 1.0)
    notes.append(
        "Sanity: logo_brand_kit settles to state "
        f"{real_negotiation.get('state')} via run_negotiation.")

    for sid, scen in SCENARIO_BY_ID.items():
        kind = kind_of(sid)
        for scale in GRID_SCALES:
            deal = await settle(sid, scale)
            state = deal.get("state")
            if state != "agreed":
                notes.append(
                    f"Grid skip: {sid} at scale {scale} did not settle "
                    f"(state {state}).")
                continue
            mw = [c for c in deal["spec"]["acceptance_checks"]
                  if c["kind"] == "min_words"]
            if not mw:
                notes.append(f"Grid skip: {sid} has no min_words check.")
                continue
            value = int(mw[0]["value"])
            if sid == "cheat_attempt":
                notes.append(
                    "cheat_attempt excluded from the honest corpus: its "
                    "builder returns the cheat seller's recycled copy "
                    "(91 words against a 250 requirement), not an honest "
                    "delivery. It is not an honest data point.")
                # Attacks still built against its settled V=250 below.
                honest_text = None
            else:
                honest_text = build_delivery(scen, deal["spec"])
                key = (sid, honest_text)
                if key not in seen_honest:
                    seen_honest.add(key)
                    rec = {"scenario": sid, "kind": kind,
                           "grid_scale": scale, "settled_V": value}
                    rec.update(text_stats(honest_text))
                    honest_records.append(rec)
                else:
                    notes.append(
                        f"Dedupe: {sid} scale {scale} produced the same "
                        f"delivery as an earlier grid point; margins use "
                        f"unique deliveries only.")
            # Hypothetical wide pool variant (honest scenarios only).
            if sid != "cheat_attempt":
                orig_pad = scenarios._pad_words
                orig_cpad = scenarios._pad_comment_words
                scenarios._pad_words = wide_pad_words
                scenarios._pad_comment_words = wide_pad_comment_words
                try:
                    wide_text = build_delivery(scen, deal["spec"])
                finally:
                    scenarios._pad_words = orig_pad
                    scenarios._pad_comment_words = orig_cpad
                wrec = {"scenario": sid, "kind": kind,
                        "grid_scale": scale, "settled_V": value}
                wrec.update(text_stats(wide_text))
                wrec["pool"] = "wide_24_sentence_PAD_POOL_hypothetical"
                honest_records.append(wrec)
                notes.append(
                    f"Hypothetical: {sid} scale {scale} rebuilt with the "
                    f"wide 24-sentence pool (not a shipped builder).")
            # Attacks against this scenario's settled value.
            target = value + 60
            for name, text in attack_family(honest_text, target).items():
                arec = {"scenario": sid, "kind": kind, "name": name,
                        "settled_V": value, "target_words": target}
                arec.update(text_stats(text))
                attack_records.append(arec)

    def gated(recs):
        return [r for r in recs if r["words"] >= GATE_MIN_TOKENS
                and r.get("pool") is None]

    margins = {}
    for kind in ("prose", "code"):
        h = gated([r for r in honest_records if r["kind"] == kind])
        a = gated([r for r in attack_records if r["kind"] == kind])
        h_ratios = [r["effective"] / r["settled_V"] for r in h]
        a_ratios = [r["effective"] / r["settled_V"] for r in a]
        h_min, a_max = min(h_ratios), max(a_ratios)
        h_worst = min(h, key=lambda r: r["effective"] / r["settled_V"])
        a_best = max(a, key=lambda r: r["effective"] / r["settled_V"])
        h_shares = [r["longest_repeat_share"] for r in h]
        a_shares = [r["longest_repeat_share"] for r in a]
        sep = (min(a_shares) / max(h_shares)
               if max(h_shares) > 0 else float("inf"))
        wh = [r for r in honest_records
              if r["kind"] == kind and r.get("pool") is not None
              and r["words"] >= GATE_MIN_TOKENS]
        wh_min = min(r["effective"] / r["settled_V"] for r in wh)
        margins[kind] = {
            "n_honest": len(h), "n_attacks": len(a),
            "honest_worst_ratio": round(h_min, 4),
            "honest_worst": (f"{h_worst['scenario']} "
                             f"(effective {h_worst['effective']} vs "
                             f"V {h_worst['settled_V']})"),
            "honest_margin_holds": h_min >= 1.10,
            "attack_best_ratio": round(a_max, 4),
            "attack_best": (f"{a_best['scenario']}: {a_best['name']} "
                            f"(effective {a_best['effective']} vs "
                            f"V {a_best['settled_V']})"),
            "attack_margin_holds": a_max <= 0.85,
            "longest_repeat_honest_max": round(max(h_shares), 4),
            "longest_repeat_attack_min": round(min(a_shares), 4),
            "longest_repeat_separation_x": (round(sep, 2)
                                            if sep != float("inf") else None),
            "longest_repeat_3x_separation": sep >= 3.0,
            "hypothetical_wide_pool_honest_worst_ratio": round(wh_min, 4),
            "hypothetical_wide_pool_clears_110": wh_min >= 1.10,
        }

    adoption = {}
    for kind in ("prose", "code"):
        m = margins[kind]
        if m["honest_margin_holds"] and m["attack_margin_holds"]:
            decision = ("ADOPT: effective-words gate for min_words on "
                        f"{kind} deliveries (texts >= 100 words).")
            reason = ("Worst honest clears 1.10xV and strongest attack "
                      "falls 0.15xV short on the current shipped builders.")
        else:
            causes = []
            if not m["honest_margin_holds"]:
                causes.append(
                    "the current builder padding pools are too repetitive "
                    "for the effective measure: worst honest delivery "
                    f"reaches only {m['honest_worst_ratio']}xV "
                    f"({m['honest_worst']}), below the 1.10xV honest "
                    "margin. A builder pool fix is out of scope for this "
                    "item; the hypothetical wide-pool variant reaches "
                    f"{m['hypothetical_wide_pool_honest_worst_ratio']}xV, "
                    "which shows the pool is the cause.")
            if not m["attack_margin_holds"]:
                causes.append(
                    "the parameterized attack family defeats the "
                    "effective-words statistic: the strongest attack "
                    f"reaches {m['attack_best_ratio']}xV "
                    f"({m['attack_best']}), above the 0.85xV attack "
                    "margin. Surface statistics cannot price mutated and "
                    "shuffled filler at zero; that is a documented limit "
                    "of the statistic, not a tuning problem.")
            decision = "KEEP SHIPPED SCREEN"
            reason = ("Keep the shipped zlib plus 4-gram screen for "
                      f"{kind} deliveries. " + " ".join(causes))
        adoption[kind] = {"decision": decision, "reason": reason}
        adoption[kind]["longest_repeat_gate"] = (
            "ADOPT ceiling 0.15" if m["longest_repeat_3x_separation"]
            else "LOG ONLY: longest-repeat share separation is under 3x, "
                 "so the 0.15 ceiling stays a logged diagnostic, not a gate.")

    shipped_comparison = {}
    for kind in ("prose", "code"):
        a = gated([r for r in attack_records if r["kind"] == kind])
        caught = sum(1 for r in a if r["shipped_degenerate"])
        shipped_comparison[kind] = {
            "attacks_evaluated": len(a),
            "attacks_flagged_by_shipped_screen": caught,
            "attacks_missed_by_shipped_screen":
                [r["name"] + f" ({r['scenario']})" for r in a
                 if not r["shipped_degenerate"]],
        }

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "honest_corpus": "run_negotiation over buyer_max/seller_floor "
                             "grid (1.0, 0.8, 1.2), build_delivery, "
                             "cheat_attempt excluded (cheat seller copy, "
                             "not an honest delivery)",
            "attack_sizing": "raw words = settled V + 60 (cheapest pass "
                             "of the old raw count, matching builder "
                             "padding)",
            "gate_texts": f"texts >= {GATE_MIN_TOKENS} tokens only",
            "honest_margin": "worst honest effective >= 1.10 * V",
            "attack_margin": "strongest attack effective <= 0.85 * V",
            "kinds": "prose (5 scenarios) vs code (code_task)",
        },
        "honest": honest_records,
        "attacks": attack_records,
        "margins": margins,
        "adoption": adoption,
        "shipped_screen_comparison": shipped_comparison,
        "notes": notes,
    }
    OUT.write_text(json.dumps(result, indent=1))

    print(f"{'kind':<6} {'honest worst':<13} {'attack best':<12} "
          f"{'honest>=1.10':<12} {'attack<=0.85':<12} {'wide-pool worst'}")
    for kind in ("prose", "code"):
        m = margins[kind]
        print(f"{kind:<6} {m['honest_worst_ratio']:<13} "
              f"{m['attack_best_ratio']:<12} "
              f"{str(m['honest_margin_holds']):<12} "
              f"{str(m['attack_margin_holds']):<12} "
              f"{m['hypothetical_wide_pool_honest_worst_ratio']}")
    print()
    for kind in ("prose", "code"):
        m = margins[kind]
        print(f"{kind}: worst honest = {m['honest_worst']}")
        print(f"{kind}: best attack  = {m['attack_best']}")
        print(f"{kind}: longest-repeat honest max "
              f"{m['longest_repeat_honest_max']}, attack min "
              f"{m['longest_repeat_attack_min']}, separation "
              f"{m['longest_repeat_separation_x']}x")
        print(f"{kind}: decision = {adoption[kind]['decision']}")
    print()
    print("Shipped screen on this attack family:")
    for kind in ("prose", "code"):
        s = shipped_comparison[kind]
        print(f"  {kind}: flagged {s['attacks_flagged_by_shipped_screen']}/"
              f"{s['attacks_evaluated']}")
        for miss in s["attacks_missed_by_shipped_screen"]:
            print(f"    MISSED: {miss}")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

"""Semantic second signal study (queue item U).

The documented limit of the deterministic verifier is quality blindness:
a delivery of varied words in scrambled order still passes the checks,
because the checks measure structure (markers, counts, required strings)
and never meaning. This study tests a semantic coherence signal as a
candidate SECOND signal, reported separately, never as a verdict changer:

  score = 0.5 * brief_sim + 0.5 * sent_coherence

  brief_sim:      mean cosine similarity of each sentence embedding
                  against the brief embedding (local MiniLM).
  sent_coherence: mean cosine similarity of consecutive sentence
                  embeddings.

Labeled set (seeded, built from the shipped honest builders):
  careful:            honest builder output per scenario over the
                      settled value grid (1.0, 0.8, 1.2), deduplicated.
                      cheat_attempt excluded: its builder returns the
                      cheat seller's recycled copy, not an honest
                      delivery.
  scrambled:          each careful text with its sentences permuted.
                      Same words, same markers, no discourse order.
  word_salad:         each careful text with ALL words shuffled and
                      re-chunked into sentences. Same vocabulary, no
                      syntax at all.
  keyword_dump:       semantic garbage built from the brief's own
                      content words, but carrying every check needle
                      (markers, required strings, hex codes, price
                      line), so the deterministic verifier still
                      passes it. This is the sharp form of the limit.

Adoption rule, decided before measuring (mirrors the item F margins):
  ADOPT as a separately reported verifier signal ONLY if
    min(careful) >= 1.15 * max(scrambled, word_salad, keyword_dump)
  AND no careful sample falls below the would-be gate threshold.
  Otherwise the negative result goes into the paper's limits section.

Either way the deterministic checks remain the settlement authority in
this version; the study never silently changes verdicts.

Also measured and reported: the deterministic pass rate of each attack
class, which quantifies the documented quality-blindness limit.

Run with: NO_PROXY=localhost,127.0.0.1 .venv/bin/python \\
    experiments/semantic_coherence_study.py
Writes experiments/semantic_coherence_study.json.
Requires: sentence-transformers (experiment only, not a shipped dep).
"""

import asyncio
import json
import os
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pact.scenarios import SCENARIO_BY_ID, build_delivery  # noqa: E402
from pact.money import dollars, pct_of, to_cents
from pact.store import new_deal  # noqa: E402
from pact.negotiation import run_negotiation  # noqa: E402
from pact.verifier import (  # noqa: E402
    HEX_RE, HASHTAG_RE, verify_delivery,
)

OUT = Path(__file__).resolve().parent / "semantic_coherence_study.json"
SEED = 20261023
GRID_SCALES = (1.0, 0.8, 1.2)
ADOPT_MARGIN = 1.15

STOPWORDS = set(
    "a an the and or of to in on for with is are was were be been being "
    "it its this that these those as at by from we you they he she them "
    "his her our their your my me us do does did will would can could "
    "shall should may might must have has had not no yes if then than so "
    "such very each every all any some into over under between through "
    "during about above below up down out off again once here there when "
    "where which who whom whose what how why and per via within".split()
)

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentences(text):
    parts = [s.strip() for s in SENT_SPLIT.split(text.strip()) if s.strip()]
    return parts if len(parts) >= 2 else [text.strip()]


def content_words(text):
    return [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text)
            if w.lower() not in STOPWORDS]


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


def brief_text(scen, spec):
    parts = [scen["title"], scen.get("service_summary", "")]
    parts.extend(scen.get("deliverables", []) or [])
    parts.extend(c["label"] for c in spec["acceptance_checks"])
    return ". ".join(p for p in parts if p)


def scramble_sentences(text, rng):
    sents = sentences(text)
    order = list(range(len(sents)))
    rng.shuffle(order)
    return " ".join(sents[i] for i in order)


def word_salad(text, rng):
    words = text.split()
    rng.shuffle(words)
    sents = sentences(text)
    chunks, idx = [], 0
    for s in sents:
        n = max(1, len(s.split()))
        chunks.append(" ".join(words[idx:idx + n]))
        idx += n
    rest = " ".join(words[idx:])
    if rest:
        chunks.append(rest)
    out = ". ".join(c for c in chunks if c)
    return out if out.endswith(".") else out + "."


def keyword_dump(brief, spec, careful_text, rng, target_pad=60):
    """Semantic garbage that still carries every check needle."""
    vocab = content_words(brief + " " + careful_text)
    if not vocab:
        vocab = ["work", "delivery", "brief", "quality"]
    checks = spec["acceptance_checks"]
    chunks = []
    for c in checks:
        kind, value = c["kind"], c["value"]
        if kind == "min_items":
            for _ in range(int(value)):
                filler = " ".join(rng.choice(vocab) for _ in range(6))
                chunks.append(f"{c['marker']} {filler}.")
        elif kind == "min_hex":
            hexes = HEX_RE.findall(careful_text)
            need = int(value)
            while len(hexes) < need:
                hexes.append("#%06x" % rng.randrange(16 ** 6))
            chunks.append("Colors: " + " ".join(hexes[:need]) + ".")
        elif kind == "min_hashtags":
            tags = [t for t in HASHTAG_RE.findall(careful_text)]
            need = int(value)
            while len(tags) < need:
                tags.append("#" + rng.choice(vocab))
            chunks.append("Tags: " + " ".join(tags[:need]) + ".")
        elif kind == "contains":
            chunks.append(str(value) + ".")
        elif kind == "max_price":
            ceiling = round(float(value), 2)
            paid = round(max(0.01, ceiling - 1.00), 2)
            chunks.append(f"Price paid: ${paid:.2f}.")
        elif kind == "min_words":
            pass  # handled by the padding below
    mw = [c for c in checks if c["kind"] == "min_words"]
    target = (int(mw[0]["value"]) + target_pad) if mw else 200
    body = " ".join(chunks)
    while len(body.split()) < target:
        n = min(12, target - len(body.split()))
        body += " " + " ".join(rng.choice(vocab) for _ in range(n)) + "."
    return body


def main():
    from sentence_transformers import SentenceTransformer
    import numpy as np

    rng = random.Random(SEED)
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    dim = model.get_sentence_embedding_dimension()

    async def build_corpus():
        careful = []
        seen = set()
        notes = []
        for sid, scen in SCENARIO_BY_ID.items():
            if sid == "cheat_attempt":
                notes.append(
                    "cheat_attempt excluded from the careful class: its "
                    "builder returns the cheat seller's recycled copy, "
                    "not an honest delivery.")
                continue
            for scale in GRID_SCALES:
                deal = await settle(sid, scale)
                if deal.get("state") != "agreed":
                    notes.append(
                        f"Grid skip: {sid} scale {scale} did not settle "
                        f"(state {deal.get('state')}).")
                    continue
                text = build_delivery(scen, deal["spec"])
                key = (sid, text)
                if key in seen:
                    continue
                seen.add(key)
                careful.append({
                    "scenario": sid,
                    "scale": scale,
                    "text": text,
                    "brief": brief_text(scen, deal["spec"]),
                    "spec_checks": deal["spec"]["acceptance_checks"],
                })
        return careful, notes

    careful, notes = _run(build_corpus)

    # Attack classes derived from each careful sample.
    samples = []
    for rec in careful:
        samples.append({**rec, "class": "careful"})
        samples.append({**rec, "class": "scrambled",
                        "text": scramble_sentences(rec["text"], rng)})
        samples.append({**rec, "class": "word_salad",
                        "text": word_salad(rec["text"], rng)})
        scen = SCENARIO_BY_ID[rec["scenario"]]
        spec = {"acceptance_checks": [
            {"kind": c["kind"], "value": c["value"],
             **({"marker": c["marker"]} if c.get("marker") else {})}
            for c in rec["spec_checks"]]}
        samples.append({**rec, "class": "keyword_dump",
                        "text": keyword_dump(rec["brief"], spec, rec["text"],
                                             rng)})

    # Deterministic pass rates per class: quantifies the documented
    # quality-blindness limit.
    det_rates = {}
    for cls in ("careful", "scrambled", "word_salad", "keyword_dump"):
        cls_samples = [s for s in samples if s["class"] == cls]
        passed = 0
        for s in cls_samples:
            spec = {"acceptance_checks": s["spec_checks"]}
            if verify_delivery(spec, s["text"])["all_passed"]:
                passed += 1
        det_rates[cls] = {"n": len(cls_samples), "deterministic_pass": passed}

    # Embed everything in batches.
    all_sents = []
    sent_index = []
    briefs = []
    for s in samples:
        sents = sentences(s["text"])
        sent_index.append((len(all_sents), len(all_sents) + len(sents)))
        all_sents.extend(sents)
        briefs.append(s["brief"])
    sent_embs = model.encode(all_sents, batch_size=64,
                             show_progress_bar=False,
                             normalize_embeddings=True)
    brief_embs = model.encode(briefs, batch_size=64,
                              show_progress_bar=False,
                              normalize_embeddings=True)

    records = []
    for i, s in enumerate(samples):
        a, b = sent_index[i]
        embs = sent_embs[a:b]
        bemb = brief_embs[i]
        brief_sim = float(np.mean(embs @ bemb))
        if len(embs) >= 2:
            coh = float(np.mean(
                np.sum(embs[:-1] * embs[1:], axis=1)))
        else:
            coh = 1.0
        score = 0.5 * brief_sim + 0.5 * coh
        records.append({
            "scenario": s["scenario"],
            "scale": s["scale"],
            "class": s["class"],
            "n_sentences": len(embs),
            "brief_sim": round(brief_sim, 4),
            "sent_coherence": round(coh, 4),
            "score": round(score, 4),
        })

    by_class = {}
    for cls in ("careful", "scrambled", "word_salad", "keyword_dump"):
        vals = [r["score"] for r in records if r["class"] == cls]
        bs = [r["brief_sim"] for r in records if r["class"] == cls]
        cs = [r["sent_coherence"] for r in records if r["class"] == cls]
        by_class[cls] = {
            "n": len(vals),
            "score_min": round(min(vals), 4),
            "score_max": round(max(vals), 4),
            "score_mean": round(sum(vals) / len(vals), 4),
            "brief_sim_mean": round(sum(bs) / len(bs), 4),
            "sent_coherence_mean": round(sum(cs) / len(cs), 4),
        }

    careful_min = by_class["careful"]["score_min"]
    attack_max = max(by_class[c]["score_max"]
                     for c in ("scrambled", "word_salad", "keyword_dump"))
    margin_ratio = careful_min / attack_max if attack_max > 0 else float("inf")
    threshold = (careful_min + attack_max) / 2
    false_fails = sum(1 for r in records
                      if r["class"] == "careful" and r["score"] < threshold)

    if margin_ratio >= ADOPT_MARGIN and false_fails == 0:
        decision = "ADOPT"
        reason = (
            f"Worst careful score {careful_min:.4f} clears the best attack "
            f"score {attack_max:.4f} by {margin_ratio:.2f}x (>= "
            f"{ADOPT_MARGIN}x), with zero careful samples below the "
            f"gate threshold {threshold:.4f}. Adopt as a separately "
            "reported verifier signal only; deterministic checks stay "
            "the settlement authority.")
    else:
        causes = []
        if margin_ratio < ADOPT_MARGIN:
            worst_cls = max(
                ("scrambled", "word_salad", "keyword_dump"),
                key=lambda c: by_class[c]["score_max"])
            causes.append(
                f"the margin does not hold: worst careful "
                f"{careful_min:.4f} vs best attack {attack_max:.4f} "
                f"({worst_cls}) is only {margin_ratio:.2f}x, below the "
                f"{ADOPT_MARGIN}x bar. The signal cannot separate "
                "honest work from scrambled or dumped text cleanly.")
        if false_fails:
            causes.append(
                f"{false_fails} careful deliveries fall below the "
                f"gate threshold {threshold:.4f}: the signal would "
                "false-fail honest work.")
        decision = "DO NOT ADOPT"
        reason = ("Keep the deterministic verifier as the only signal. "
                  + " ".join(causes))

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "model": "sentence-transformers/all-MiniLM-L6-v2 (local)",
        "embedding_dim": dim,
        "signal": ("score = 0.5 * mean cosine(sentence, brief) + 0.5 * "
                   "mean cosine(consecutive sentences)"),
        "adoption_rule": (
            f"ADOPT iff min(careful) >= {ADOPT_MARGIN} * "
            "max(scrambled, word_salad, keyword_dump) and zero careful "
            "samples below the gate threshold; decided before measuring."),
        "classes": {
            "careful": "honest builder output over the settled grid",
            "scrambled": "careful text with sentences permuted",
            "word_salad": "careful text with all words shuffled",
            "keyword_dump": ("brief content words as grammar-free "
                             "sentences, carrying every check needle"),
        },
        "deterministic_pass_rates": det_rates,
        "class_summary": by_class,
        "careful_min": round(careful_min, 4),
        "attack_max": round(attack_max, 4),
        "margin_ratio": round(margin_ratio, 4),
        "gate_threshold": round(threshold, 4),
        "careful_below_threshold": false_fails,
        "decision": decision,
        "decision_reason": reason,
        "samples": records,
        "notes": notes,
    }
    OUT.write_text(json.dumps(result, indent=1))

    print(f"careful n={by_class['careful']['n']}: "
          f"score range {by_class['careful']['score_min']}.."
          f"{by_class['careful']['score_max']}")
    for cls in ("scrambled", "word_salad", "keyword_dump"):
        b = by_class[cls]
        print(f"{cls} n={b['n']}: score range {b['score_min']}..{b['score_max']} "
              f"(brief_sim mean {b['brief_sim_mean']}, "
              f"sent_coh mean {b['sent_coherence_mean']})")
    print(f"margin ratio {margin_ratio:.3f} (bar {ADOPT_MARGIN}), "
          f"false fails {false_fails}")
    print("Deterministic verifier pass rates (the documented limit):")
    for cls, d in det_rates.items():
        print(f"  {cls}: {d['deterministic_pass']}/{d['n']} pass")
    print(f"DECISION: {decision}")
    print(f"Wrote {OUT}")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro())
    finally:
        loop.close()


if __name__ == "__main__":
    main()

"""Anti stuffing measurement study.

The min_words check counts raw words, and a delivery padded with one
repeated word passes it (attack A2 in the adversarial battery). This
study measures candidate degeneracy statistics on an honest corpus
(every scenario builder output, plus the cheat scenario's recycled
prose, which is natural text) against a family of stuffing attacks at
several strengths, and reports which statistic separates the two with
a clean margin.

Statistics per text:
- zlib ratio: compressed size over raw size. Stuffed text is highly
  predictable, so it compresses far more than natural text.
- distinct ratio: unique tokens over total tokens.
- 4 gram uniqueness: unique word 4 grams over total 4 grams.
- top token share: the most frequent token's share of all tokens.

Run with: .venv/bin/python experiments/stuffing_study.py
Writes experiments/stuffing_study.json.
"""

import asyncio
import json
import os
import sys
import zlib
from pathlib import Path

for var in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "LLM_API_KEY"):
    os.environ.pop(var, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pact.negotiation import run_negotiation  # noqa: E402
from pact.scenarios import SCENARIO_BY_ID, build_delivery  # noqa: E402
from pact.money import to_cents  # noqa: E402
from pact.store import new_deal  # noqa: E402

OUT = Path(__file__).resolve().parent / "stuffing_study.json"


def stats(text):
    raw = text.encode()
    tokens = text.split()
    n = max(1, len(tokens))
    grams = [" ".join(tokens[i:i + 4]) for i in range(max(0, len(tokens) - 3))]
    freq = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    return {
        "words": len(tokens),
        "zlib_ratio": len(zlib.compress(raw, 9)) / max(1, len(raw)),
        "distinct_ratio": len(set(tokens)) / n,
        "four_gram_unique": (len(set(grams)) / len(grams)) if grams else 1.0,
        "top_token_share": max(freq.values()) / n if freq else 0.0,
    }


async def honest_corpus():
    texts = {}
    for sid, scen in SCENARIO_BY_ID.items():
        deal = new_deal(scen, to_cents(scen["default_buyer_max"]),
                        to_cents(scen["default_seller_floor"]), 20.0)
        await run_negotiation(deal, scen)
        texts[f"builder:{sid}"] = build_delivery(scen, deal["spec"])
    return texts


def attack_corpus(honest_logo):
    front = honest_logo.split("Brand Guide")[0] + "Brand Guide\n"
    attacks = {}
    attacks["A2 single word tail (the battery attack)"] = (
        front + " ".join(["quality"] * 320))
    attacks["pure single word, 600 words"] = " ".join(["quality"] * 600)
    attacks["one sentence repeated to 600 words"] = (
        "This work was done with great care and attention to every "
        "detail of the brief " * 40)
    pool = [
        "The design feels modern and clean for the brand.",
        "Colors were chosen to match the studio style.",
        "Every part of this delivery serves the launch.",
    ]
    text = ""
    i = 0
    while len(text.split()) < 600:
        text += pool[i % len(pool)] + " "
        i += 1
    attacks["three sentence rotation to 600 words"] = text
    vocab = ("brand design color layout modern clean launch studio "
             "quality work delivery brief style guide palette").split()
    salad = " ".join(vocab[i % len(vocab)] for i in range(600))
    attacks["sixteen word cycle to 600 words"] = salad
    attacks["honest front, half stuffed tail"] = (
        front + " ".join(["quality"] * 130))
    return attacks


async def main():
    honest = await honest_corpus()
    attacks = attack_corpus(honest["builder:logo_brand_kit"])
    rows = {"honest": {}, "attacks": {}}
    for name, text in honest.items():
        rows["honest"][name] = stats(text)
    for name, text in attacks.items():
        rows["attacks"][name] = stats(text)
    OUT.write_text(json.dumps(rows, indent=1))
    keys = ["zlib_ratio", "distinct_ratio", "four_gram_unique",
            "top_token_share"]
    print(f"{'statistic':<18} {'honest range':<22} {'attack range':<22} separated")
    for k in keys:
        h = [v[k] for v in rows["honest"].values()]
        a = [v[k] for v in rows["attacks"].values()]
        if k == "top_token_share":
            sep = max(a) < min(h) or min(a) > max(h)
            sep = max(h) < min(a)
        else:
            sep = max(a) < min(h)
        print(f"{k:<18} {min(h):.3f} to {max(h):.3f}      "
              f"{min(a):.3f} to {max(a):.3f}      {sep}")
    print()
    for name, s in rows["honest"].items():
        print(f"H {name:<38} zlib {s['zlib_ratio']:.3f} words {s['words']}")
    for name, s in rows["attacks"].items():
        print(f"A {name:<38} zlib {s['zlib_ratio']:.3f} words {s['words']}")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

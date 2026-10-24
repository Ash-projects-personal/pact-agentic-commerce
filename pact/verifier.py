"""Rule based verification against the negotiated contract checks.

The verifier reads the settled acceptance checks out of the deal spec and
tests the delivered text against each one. Every check returns a measured
value, the required value, a pass or fail verdict, and a plain reason. The
verdicts are computed here and never by a language model, so a catch is a
catch and can be reproduced.
"""

import re
import zlib

from . import money

HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
HASHTAG_RE = re.compile(r"#\w+")
HEX_TOKEN_RE = re.compile(r"#[0-9A-Fa-f]{6}")
PRICE_PAID_RE = re.compile(
    r"Price paid:\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")

# Anti stuffing screen for length checks. Thresholds come from the
# measurement study in experiments/stuffing_study.py: across every
# honest builder delivery the zlib ratio stayed at or above 0.280 and
# 4 gram uniqueness at or above 0.531, while every stuffing attack
# scored at or below 0.254 and 0.441. A text must fail BOTH bounds to
# count as degenerate, so a merely repetitive honest text is safe.
DEGENERATE_ZLIB_MAX = 0.27
DEGENERATE_GRAM_MIN = 0.50
DEGENERATE_MIN_WORDS = 100


def degeneracy(text):
    """Return (is_degenerate, zlib_ratio, four_gram_unique)."""
    tokens = text.split()
    if len(tokens) < DEGENERATE_MIN_WORDS:
        return False, None, None
    raw = text.encode()
    ratio = len(zlib.compress(raw, 9)) / max(1, len(raw))
    grams = [" ".join(tokens[i:i + 4]) for i in range(len(tokens) - 3)]
    unique = len(set(grams)) / len(grams) if grams else 1.0
    return (ratio < DEGENERATE_ZLIB_MAX and unique < DEGENERATE_GRAM_MIN,
            ratio, unique)


def evaluate_check(check, text):
    kind = check["kind"]
    if kind == "min_items":
        # An item counts only when it carries content: at least three
        # words must follow the marker before the next marker starts.
        # Without this rule a delivery of bare markers ("Concept 1
        # Concept 2 Concept 3") passed the check while delivering
        # nothing. The adversarial battery in experiments/ caught it.
        marker = check["marker"]
        starts = []
        idx = text.find(marker)
        while idx != -1:
            starts.append(idx)
            idx = text.find(marker, idx + len(marker))
        measured = 0
        for pos, start in enumerate(starts):
            end = starts[pos + 1] if pos + 1 < len(starts) else len(text)
            segment = text[start + len(marker):end]
            if len(segment.split()) >= 3:
                measured += 1
        required = int(check["value"])
        passed = measured >= required
        reason = (
            f"Found {measured} of the required {required} "
            f"{check['unit']} with content in the delivery. An item "
            f"counts only when words follow its marker."
        )
    elif kind == "min_hex":
        measured = len(HEX_RE.findall(text))
        required = int(check["value"])
        passed = measured >= required
        reason = (
            f"Found {measured} hex color codes in the delivery. "
            f"The contract requires at least {required}."
        )
    elif kind == "min_hashtags":
        # A token that is exactly a hex color code is a color, not a
        # hashtag. Without this ruling a delivery with no hashtags at
        # all could pass a hashtag check on color codes alone.
        tokens = HASHTAG_RE.findall(text)
        measured = sum(1 for t in tokens if not HEX_TOKEN_RE.fullmatch(t))
        required = int(check["value"])
        passed = measured >= required
        reason = (
            f"Found {measured} hashtags in the delivery. "
            f"The contract requires at least {required}."
        )
    elif kind == "min_words":
        measured = len(text.split())
        required = int(check["value"])
        passed = measured >= required
        reason = (
            f"The delivery runs {measured} words. "
            f"The contract requires at least {required}."
        )
        if passed:
            degenerate, ratio, unique = degeneracy(text)
            if degenerate:
                passed = False
                reason = (
                    f"The delivery runs {measured} words, but the text "
                    f"is degenerate: it compresses to {ratio:.0%} of its "
                    f"size and only {unique:.0%} of its four word "
                    f"phrases are unique. Repetition padded to length "
                    f"is not length."
                )
    elif kind == "contains":
        found = check["value"] in text
        measured = 1 if found else 0
        passed = found
        reason = (
            f"The required content {check['value']} is present in the delivery."
            if found
            else f"The required content {check['value']} is missing from the delivery."
        )
    elif kind == "max_price":
        # The delivery must state its price on a "Price paid:" line, and
        # that price must come in at or under the settled ceiling. A
        # report with no stated price fails: an unstated price cannot be
        # checked, and an unchecked price is how overcharges hide. The
        # comparison runs on integer cents (queue item V): the check value
        # is stored in cents and the stated price is parsed to cents, so
        # no float ever decides a verdict. measured/required stay dollars
        # in the result, exactly as the API and the dispute packet show.
        required_c = int(check["value"])
        match = PRICE_PAID_RE.search(text)
        if match:
            measured_c = money.to_cents(match.group(1).replace(",", ""))
            passed = measured_c <= required_c
            measured = money.dollars(measured_c)
            required = money.dollars(required_c)
            reason = (
                f"The delivery states a price paid of {measured:.2f} USD. "
                f"The contract ceiling is {required:.2f} USD. "
                + ("The purchase came in at or under the ceiling."
                   if passed else
                   "The purchase went over the ceiling.")
            )
        else:
            measured = None
            passed = False
            required = money.dollars(required_c)
            reason = (
                f"The delivery states no price paid on a 'Price paid:' "
                f"line, so the contract ceiling of {required:.2f} USD "
                f"cannot be verified and the check fails."
            )
    else:
        measured = 0
        passed = False
        reason = f"Unknown check kind {kind}."
    # required_out is what the API, the UI, and the dispute packet show:
    # dollars for the max_price check (its stored value is cents), the
    # raw check value for every other kind.
    required_out = check["value"]
    if kind == "max_price":
        required_out = money.dollars(int(check["value"]))
    return {
        "check_id": check["id"],
        "label": check["label"],
        "kind": kind,
        "measured": measured,
        "required": required_out,
        "passed": passed,
        "reason": reason,
    }


def verify_delivery(spec, text):
    results = [evaluate_check(c, text) for c in spec["acceptance_checks"]]
    passed_count = sum(1 for r in results if r["passed"])
    return {
        "results": results,
        "passed_count": passed_count,
        "total_count": len(results),
        "all_passed": passed_count == len(results),
        "any_passed": passed_count > 0,
    }

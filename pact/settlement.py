"""Graded settlement: pay per passed check, slash the bond in proportion.

The old settlement was all or nothing: every check passed and the seller
was paid in full with the bond returned, or anything failed and the buyer
was refunded in full with the whole bond slashed. That wastes the work
that did pass, and it pays a seller nothing for a delivery that was
four fifths right.

Graded settlement splits the money by the verifier's own per check
results. If N of M acceptance checks pass, the seller is paid N/M of
the price, the buyer is refunded the other (M-N)/M, the bond returns
N/M to the seller, and the failed share of the bond slashes to the
buyer. All pass and none pass are the same rule at the ends: N = M is
the old release, N = 0 is the old refund. The rule is one formula, not
three branches, so there is no seam where a partial outcome falls
through.

Money is integer cents throughout (see pact/money.py). The seller's
share of the price and the returned share of the bond are each rounded
half-even once; the buyer's shares are the remainders, so the four legs
always sum exactly to the price plus the bond. No cent is created or
lost by rounding, ever.
"""

from . import money


def grade_breakdown(price_c, bond_c, passed, total):
    """Split price and bond by passed/total checks. All amounts cents.

    Returns {"passed", "total", "price_paid_c", "price_refunded_c",
    "bond_returned_c", "bond_slashed_c"}, each money field an integer
    number of cents. The two paid/returned shares are rounded half-even
    once each; the refunded/slashed shares are the remainders.
    Invariants, by construction:
    price_paid_c + price_refunded_c == price_c, and
    bond_returned_c + bond_slashed_c == bond_c.
    """
    if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        raise ValueError(f"total checks must be a positive integer, got {total!r}")
    if not isinstance(passed, int) or isinstance(passed, bool):
        raise ValueError(f"passed checks must be an integer, got {passed!r}")
    if passed < 0 or passed > total:
        raise ValueError(
            f"passed checks {passed} outside 0..{total}")
    if not isinstance(price_c, int) or isinstance(price_c, bool) or price_c < 0:
        raise ValueError(f"price must be non-negative integer cents, got {price_c!r}")
    if not isinstance(bond_c, int) or isinstance(bond_c, bool) or bond_c < 0:
        raise ValueError(f"bond must be non-negative integer cents, got {bond_c!r}")
    price_paid_c = money.div_round(price_c * passed, total)
    bond_returned_c = money.div_round(bond_c * passed, total)
    return {
        "passed": passed,
        "total": total,
        "price_paid_c": price_paid_c,
        "price_refunded_c": price_c - price_paid_c,
        "bond_returned_c": bond_returned_c,
        "bond_slashed_c": bond_c - bond_returned_c,
    }


def graded_seller_reputation_delta(passed, total):
    """Seller reputation delta for a graded settlement. One number.

    Formula: round-half-even(6 * passed/total) minus
    round-half-even(20 * failed/total), all in integer math. The 6 is
    the release gain for a fully passed delivery and the 20 is the
    bond slash hit, so a partial delivery keeps the passed share of
    the gain and takes the failed share of the hit. At 1 of 5 that is
    1 - 16 = -15; at 4 of 5 it is 5 - 4 = +1. The formula runs only on
    the graded path (some checks passed, some failed): all pass takes
    the release gain and none pass takes the refund hits.
    """
    if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        raise ValueError(f"total checks must be a positive integer, got {total!r}")
    if not isinstance(passed, int) or isinstance(passed, bool):
        raise ValueError(f"passed checks must be an integer, got {passed!r}")
    if passed < 0 or passed > total:
        raise ValueError(
            f"passed checks {passed} outside 0..{total}")
    failed = total - passed
    return (money.div_round(6 * passed, total)
            - money.div_round(20 * failed, total))

"""Integer-cent money handling for Pact.

Every money amount inside Pact is an integer number of US cents. Binary
floats never hold money: a float cannot represent most cent values
exactly, so repeated float math drifts by a cent here and there, which
is unacceptable in a settlement system.

The rule, in one place:

* Each money value crosses from the outside world into integer cents
  exactly once, at a documented parse boundary, via to_cents(), with
  round-half-even (banker's) rounding. Sources: API request bodies,
  scenario default bounds, Channel3 market prices.
* Every computation after that is exact integer arithmetic on cents:
  div_round() for division, pct_of() for percent-of-amount (bond,
  concession steps), add_scaled() for concession moves.
* Dollars appear only at the public edges, never as math inputs:
  API responses (store.public_deal), ledger messages, the dispute
  packet, and PayPal payload strings via fmt().

Percents and rates (bond_percent, CONCESSION) are not money. They stay
decimal values with a 2-decimal boundary where the old code had one,
and pct_of() consumes their exact decimal value, so a percent like
23.54 always means exactly 23.54.

Rounding is round-half-even everywhere, matching what the old
round(x, 2) float code produced on every non-hairline input, so the
migration changes no settled price: the frozen experiment outcomes
(E1, E2, E3, E4, real cases, PactBench) come out identical to the cent.
"""

from decimal import Decimal, ROUND_HALF_EVEN, InvalidOperation

_HALF_EVEN = ROUND_HALF_EVEN
_ONE = Decimal("1")


def _as_decimal(value):
    """Coerce a dollar amount or rate to an exact Decimal.

    Floats go through str() (shortest round-trip repr), so 23.54 means
    exactly 23.54, never the binary approximation. Strings may carry a
    leading $ and thousands separators, because PayPal-facing text and
    pasted listing prices do.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError(f"not a money amount: {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"not a finite money amount: {value!r}")
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            raise ValueError(f"not a parseable money amount: {value!r}")
    raise TypeError(f"not a money amount: {type(value).__name__}")


def to_cents(value):
    """Parse a dollar amount to integer cents. THE parse boundary.

    Rounds half-even, exactly once. to_cents(19.999) == 2000,
    to_cents("0.015") == 2, to_cents("0.005") == 0.
    """
    return int((_as_decimal(value) * 100).quantize(_ONE, rounding=_HALF_EVEN))


def dollars(cents):
    """Integer cents back to float dollars for display and API output.

    This is exactly cents/100, correctly rounded: dollars(14811) is the
    same float the old round(x, 2) code produced for 148.11. Never use
    the result as a math input; convert back with to_cents() instead.
    """
    return int(cents) / 100


def fmt(cents):
    """Integer cents to a PayPal-style amount string: fmt(14811) == "148.11".

    Built from the integer, so no float is ever involved in a payload.
    """
    c = int(cents)
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}{c // 100}.{c % 100:02d}"


def div_round(numer, denom):
    """Integer division with round-half-even: div_round(1000, 3) == 333.

    The single rounding rule for money math. Both inputs are exact
    integers, so the result is deterministic, unlike float division
    followed by round().
    """
    if denom == 0:
        raise ZeroDivisionError("div_round with zero denominator")
    return int((Decimal(int(numer)) / Decimal(int(denom))).quantize(
        _ONE, rounding=_HALF_EVEN))


def pct_of(amount_cents, pct):
    """amount_cents * pct / 100, rounded half-even to cents.

    The bond computation and every percent-of-price step live here.
    pct is consumed as its exact decimal value: pct_of(14811, 23.54)
    == 3487, because 14811 * 23.54 / 100 == 3486.5094 exactly.
    """
    return int((Decimal(int(amount_cents)) * _as_decimal(pct) / 100).quantize(
        _ONE, rounding=_HALF_EVEN))


def add_scaled(base_cents, delta_cents, rate):
    """base_cents + delta_cents * rate, rounded half-even to cents.

    The negotiation concession step: the old float code computed
    round(offer + gap * 0.45, 2); this computes the same formula in
    exact decimal arithmetic on integer cents. rate is consumed as its
    exact decimal value (0.45 means exactly 0.45). delta_cents may be
    negative for the seller's downward moves.
    """
    return int((Decimal(int(base_cents))
                + Decimal(int(delta_cents)) * _as_decimal(rate)).quantize(
                    _ONE, rounding=_HALF_EVEN))

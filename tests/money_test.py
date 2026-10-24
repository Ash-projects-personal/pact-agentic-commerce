"""Unit tests for pact/money.py: cent-exact arithmetic (queue item V).

Every money value inside Pact is an integer number of cents; these tests
pin the parse boundary and the exact-arithmetic helpers, including the
odd inputs the item calls out: thirds, half cents at the rounding
boundary, and bond percents from the multi-issue band (10 to 30).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pact import money

failures = []


def check(cond, label, detail=None):
    if cond:
        print(f"  ok: {label}")
    else:
        print(f"  FAIL: {label} :: {detail}")
        failures.append(label)


def main():
    print("TEST 1 parse boundary: dollars in, integer cents out")
    check(money.to_cents(150.0) == 15000, "whole dollars", money.to_cents(150.0))
    check(money.to_cents(148.11) == 14811, "two decimal float",
          money.to_cents(148.11))
    check(money.to_cents("239.97") == 23997, "string dollars",
          money.to_cents("239.97"))
    check(money.to_cents("$1,234.56") == 123456, "pasted listing price",
          money.to_cents("$1,234.56"))
    check(money.to_cents(200) == 20000, "int dollars", money.to_cents(200))
    # Thirds: 10/3 dollars can never be exact; the boundary rounds once.
    check(money.to_cents(10 / 3) == 333, "a third of ten dollars",
          money.to_cents(10 / 3))
    check(money.to_cents(100 / 3) == 3333, "a third of a hundred",
          money.to_cents(100 / 3))
    # Half cents at the boundary: round-half-even, not half-up.
    check(money.to_cents("0.005") == 0, "half cent rounds to even (0)",
          money.to_cents("0.005"))
    check(money.to_cents("0.015") == 2, "half cent rounds to even (2)",
          money.to_cents("0.015"))
    check(money.to_cents("2.675") == 268, "2.675 -> 268 (even)",
          money.to_cents("2.675"))
    check(money.to_cents("2.665") == 266, "2.665 -> 266 (even)",
          money.to_cents("2.665"))
    check(money.to_cents(19.999) == 2000, "19.999 rounds up to 2000",
          money.to_cents(19.999))
    for bad in (float("nan"), float("inf"), "not money"):
        try:
            money.to_cents(bad)
            check(False, f"rejects {bad!r}")
        except (ValueError, TypeError):
            check(True, f"rejects {bad!r}")

    print("TEST 2 display: cents out, dollars for humans only")
    check(money.dollars(14811) == 148.11, "dollars(14811) == 148.11",
          money.dollars(14811))
    check(money.dollars(9000) == 90.0, "dollars(9000) == 90.0",
          money.dollars(9000))
    check(money.fmt(14811) == "148.11", 'fmt(14811) == "148.11"',
          money.fmt(14811))
    check(money.fmt(9000) == "90.00", 'fmt(9000) == "90.00"',
          money.fmt(9000))
    check(money.fmt(5) == "0.05", 'fmt(5) == "0.05"', money.fmt(5))
    # fmt never touches a float: 1 cent under a dollar boundary.
    check(money.fmt(199999) == "1999.99", 'fmt(199999) == "1999.99"',
          money.fmt(199999))

    print("TEST 3 div_round: the single rounding rule for money math")
    check(money.div_round(1000, 3) == 333, "1000/3 -> 333",
          money.div_round(1000, 3))
    check(money.div_round(1, 2) == 0, "1/2 -> 0 (half-even)",
          money.div_round(1, 2))
    check(money.div_round(3, 2) == 2, "3/2 -> 2 (half-even)",
          money.div_round(3, 2))
    check(money.div_round(14811 + 9000, 2) == 11906, "settle midpoint",
          money.div_round(14811 + 9000, 2))
    try:
        money.div_round(1, 0)
        check(False, "div_round by zero raises")
    except ZeroDivisionError:
        check(True, "div_round by zero raises")

    print("TEST 4 pct_of: bond computation in exact cents")
    # The multi-issue band is 10 to 30 percent; 23.54 is the settled value
    # from the 196-run multi-issue sweep.
    check(money.pct_of(14811, 23.54) == 3487,
          "14811c at 23.54% == 3487c (the $148.11 / $34.87 deal)",
          money.pct_of(14811, 23.54))
    check(money.pct_of(14811, 20.0) == 2962, "14811c at 20% == 2962c",
          money.pct_of(14811, 20.0))
    check(money.pct_of(14811, 10) == 1481, "band floor 10%",
          money.pct_of(14811, 10))
    check(money.pct_of(14811, 30) == 4443, "band ceiling 30%",
          money.pct_of(14811, 30))
    # Thirds of a percent: 10000c at 33.333% == 3333.3c -> 3333c.
    check(money.pct_of(10000, 33.333) == 3333, "third-percent rounds once",
          money.pct_of(10000, 33.333))
    # Exact half-cent bond: 1c at 50% == 0.5c -> 0c (half-even).
    check(money.pct_of(1, 50) == 0, "1c at 50% -> 0c (half-even)",
          money.pct_of(1, 50))
    check(money.pct_of(3, 50) == 2, "3c at 50% -> 2c (half-even)",
          money.pct_of(3, 50))
    # Concession opens: 60% of the ceiling, 135% of the floor.
    check(money.pct_of(20000, 60) == 12000, "offer opens at 60% of ceiling",
          money.pct_of(20000, 60))
    check(money.pct_of(15000, 135) == 20250, "ask opens at 135% of floor",
          money.pct_of(15000, 135))

    print("TEST 5 add_scaled: concession steps in exact cents")
    check(money.add_scaled(9000, 6000, 0.45) == 11700,
          "9000 + 6000*0.45 == 11700", money.add_scaled(9000, 6000, 0.45))
    check(money.add_scaled(20250, -6000, 0.45) == 17550,
          "seller move down is exact", money.add_scaled(20250, -6000, 0.45))
    check(money.add_scaled(0, 1, 0.5) == 0, "half cent step -> 0 (half-even)",
          money.add_scaled(0, 1, 0.5))
    check(money.add_scaled(0, 3, 0.5) == 2, "1.5c step -> 2 (half-even)",
          money.add_scaled(0, 3, 0.5))
    # Sweep concession rates from the E2 grid are exact too.
    for rate, want in ((0.2, 1200), (0.35, 2100), (0.6, 3600)):
        got = money.add_scaled(0, 6000, rate)
        check(got == want, f"rate {rate} exact", got)

    print("TEST 6 round trip: parse -> math -> display never invents a cent")
    for amount in ("1.00", "0.50", "148.11", "239.97", "270.52", "1000000.00"):
        c = money.to_cents(amount)
        check(money.fmt(c) == f"{float(amount):.2f}",
              f"round trip {amount}", (c, money.fmt(c)))

    if failures:
        print(f"\n{len(failures)} FAILURES")
        sys.exit(1)
    print("\nALL MONEY TESTS PASSED")


if __name__ == "__main__":
    main()

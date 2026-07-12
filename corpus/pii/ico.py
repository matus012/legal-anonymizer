"""IČO (organisation id) — 8 digits + weighted mod-11 checksum (context.md §4.1).

Algorithm (identical to the Czech IČO): weight the first 7 digits by 8..2, take the sum
mod 11; the 8th (check) digit is 11-mod, with the two edge cases mod==0→1 and mod==1→0.
Anchored in tests against Slovak Telekom's real IČO 35763469.
"""
from __future__ import annotations

import random

_WEIGHTS = (8, 7, 6, 5, 4, 3, 2)


def _check_digit(first7: str) -> int:
    s = sum(int(c) * w for c, w in zip(first7, _WEIGHTS))
    mod = s % 11
    if mod == 0:
        return 1
    if mod == 1:
        return 0
    return 11 - mod


def is_valid(ico: str) -> bool:
    d = "".join(c for c in ico if c.isdigit())
    if len(d) != 8:
        return False
    return _check_digit(d[:7]) == int(d[7])


def generate(rng: random.Random, *, valid: bool = True) -> str:
    """Return an 8-digit IČO. ``valid=False`` keeps the shape but breaks the checksum."""
    first7 = f"{rng.randint(0, 9_999_999):07d}"
    check = _check_digit(first7)
    if not valid:
        check = (check + 1) % 10
        if _check_digit(first7) == check:  # collision guard (won't happen, +1 mod 10)
            check = (check + 1) % 10
    return first7 + str(check)

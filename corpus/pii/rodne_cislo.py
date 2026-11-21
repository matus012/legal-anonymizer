"""Rodné číslo (Slovak birth number) — format + mod-11 checksum (context.md §4.1).

Modern (post-1953) RČ is 10 digits ``YYMMDD/CCCX`` and the whole 10-digit value must be
divisible by 11. Women carry a +50 month offset (post-2004 overflow allocations may use
+70). We only generate the modern 10-digit form so every emitted RČ is checksum-bearing.
"""
from __future__ import annotations

import random
import re

_RC_SHAPE = re.compile(r"^\d{6}/?\d{4}$")


def _digits(rc: str) -> str:
    return "".join(c for c in rc if c.isdigit())


def is_rc_shaped(rc: str) -> bool:
    """True if ``rc`` looks like a RČ: 6+4 digits and a plausible (offset) month/day."""
    d = _digits(rc)
    if len(d) != 10:
        return False
    month = int(d[2:4])
    for off in (0, 50, 20, 70):  # +20/+70 are overflow allocations
        m = month - off
        if 1 <= m <= 12:
            break
    else:
        return False
    return 1 <= int(d[4:6]) <= 31


def is_valid(rc: str) -> bool:
    """True if ``rc`` is RČ-shaped AND its 10 digits are divisible by 11 (mod-11 check)."""
    d = _digits(rc)
    if len(d) != 10 or not is_rc_shaped(rc):
        return False
    return int(d) % 11 == 0


def generate(
    rng: random.Random,
    *,
    female: bool | None = None,
    valid: bool = True,
    with_slash: bool = True,
) -> str:
    """Return a synthetic RČ.

    ``valid=True``  → divisible by 11.
    ``valid=False`` → RČ-shaped and date-plausible but NOT divisible by 11 (a typo'd RČ:
                      still PII, must reach the review bucket, must not be auto-redacted).
    """
    if female is None:
        female = rng.random() < 0.5
    year = rng.randint(40, 99)  # 1940–1999
    month = rng.randint(1, 12) + (50 if female else 0)
    day = rng.randint(1, 28)
    base9 = int(f"{year:02d}{month:02d}{day:02d}{rng.randint(0, 999):03d}")

    check = (-base9 * 10) % 11
    if check == 10:
        # No single check digit yields divisibility for this base; nudge the serial.
        return generate(rng, female=female, valid=valid, with_slash=with_slash)
    ten = base9 * 10 + check  # divisible by 11 by construction

    s = f"{ten:010d}"
    if not valid:
        last = int(s[9])
        s = s[:9] + str((last + 1) % 10)  # break the checksum, keep the shape
    return f"{s[:6]}/{s[6:]}" if with_slash else s

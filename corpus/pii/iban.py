"""Bank account identifiers (context.md §4.1).

Two forms:
* SK **IBAN** — ISO 13616 mod-97 check (``is_valid`` / ``generate``).
* Legacy SK **domestic** account ``prefix-base/bankcode`` — each of prefix and base carries
  its own weighted mod-11 checksum (``is_valid_domestic`` / ``generate_domestic``).
"""
from __future__ import annotations

import random
import re

_BANK_CODES = ("0200", "0900", "1100", "0800", "5200", "7500", "8330", "1111")

# weights applied right-to-left to the SK domestic prefix / base number
_PREFIX_WEIGHTS = (10, 5, 8, 4, 2, 1)
_BASE_WEIGHTS = (6, 3, 7, 9, 10, 5, 8, 4, 2, 1)

_LEGACY_RE = re.compile(r"^(?:(\d{1,6})-)?(\d{2,10})/(\d{4})$")


def _mod97(iban: str) -> int:
    """ISO 7064 mod-97 over an IBAN with the first 4 chars rotated to the end."""
    s = iban[4:] + iban[:4]
    digits = "".join(str(int(c, 36)) for c in s)  # A→10 … Z→35, 0-9 unchanged
    return int(digits) % 97


def is_valid(iban: str) -> bool:
    v = iban.replace(" ", "").upper()
    if not re.fullmatch(r"SK\d{22}", v):
        return False
    return _mod97(v) == 1


def generate(rng: random.Random, *, valid: bool = True) -> str:
    """Return a formatted SK IBAN (groups of 4). ``valid=False`` breaks the mod-97 check."""
    bank = rng.choice(_BANK_CODES)
    prefix = f"{rng.randint(0, 999_999):06d}"
    acct = f"{rng.randint(0, 9_999_999_999):010d}"
    bban = bank + prefix + acct  # 20 digits
    check = 98 - _mod97("SK00" + bban)
    v = f"SK{check:02d}{bban}"
    if not valid:
        check = check % 100 + 1 if check < 99 else 1
        v = f"SK{check:02d}{bban}"
        if is_valid(v):  # extremely unlikely, but guarantee invalidity
            v = f"SK{(check + 1) % 100:02d}{bban}"
    return " ".join(v[i : i + 4] for i in range(0, len(v), 4))


# ------------------------------------------------------------------ legacy domestic account
def _weighted_mod11_ok(number: str, weights: tuple[int, ...]) -> bool:
    tail = number[-len(weights) :]
    s = sum(int(c) * w for c, w in zip(reversed(tail), reversed(weights)))
    return s % 11 == 0


def _make_number(rng: random.Random, length: int, weights: tuple[int, ...]) -> str:
    """Random ``length``-digit number whose weighted mod-11 checksum is 0."""
    for _ in range(200):
        n = "".join(str(rng.randint(0, 9)) for _ in range(length))
        if _weighted_mod11_ok(n, weights):
            return n
    raise RuntimeError("could not build a checksum-valid domestic account number")


def is_valid_domestic(acc: str) -> bool:
    m = _LEGACY_RE.match(acc.strip())
    if not m:
        return False
    prefix, base, _bank = m.groups()
    if prefix is not None and not _weighted_mod11_ok(prefix, _PREFIX_WEIGHTS):
        return False
    return _weighted_mod11_ok(base, _BASE_WEIGHTS)


def generate_domestic(rng: random.Random, *, valid: bool = True) -> str:
    """Return a legacy ``prefix-base/bankcode`` account. ``valid=False`` breaks the base sum."""
    prefix = _make_number(rng, 6, _PREFIX_WEIGHTS)
    base = _make_number(rng, 10, _BASE_WEIGHTS)
    bank = rng.choice(_BANK_CODES)
    if not valid:
        wrong = str((int(base[-1]) + 1) % 10)
        base = base[:-1] + wrong
        if _weighted_mod11_ok(base, _BASE_WEIGHTS):
            base = base[:-1] + str((int(base[-1]) + 1) % 10)
    return f"{prefix}-{base}/{bank}"

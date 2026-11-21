"""Corpus PII generators for v1.1 round B2 (CONTRACTS_v11.md §9): the six
identity-document / vehicle-document types owned by ``detect/documents.py`` --
CISLO_OP, CISLO_PASU, VODICSKY_PREUKAZ, ECV, VIN, BIC.

Each ``make_<type>(rng)`` returns ``(surface, PiiSpec)`` -- the surface AS AUTHORED (no
anchor phrase; templates add anchor context in a later round) and its ground truth. None
of these six types carries a checksum, so every occurrence is
``auto_redact=True, should_flag=False`` unconditionally (context.md §6, recall over
precision: there is no "checksum-invalid" state for a shape-only type).

Each generator randomises across every surface variant its sibling detector accepts (the
separator style for CISLO_OP/CISLO_PASU/ECV, the token length for VODICSKY_PREUKAZ) so
that enough corpus builds exercise every variant the leak gate must prove against. Shapes
were verified against ``detect/documents.py``'s own patterns independently -- this file
does not import ``detect/``.

``corpus.groundtruth.PiiSpec`` does not yet carry a ``checksum`` field this round (a later
round adds it per CONTRACTS_v11.md §7); every ``PiiSpec(...)`` call below therefore omits
it.
# TODO(v1.1): pass checksum="n/a" to every PiiSpec(...) below once PiiSpec carries the field.
"""
from __future__ import annotations

import random
import string

from corpus.groundtruth import PiiSpec

NBSP = " "
_VIN_ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"  # ISO 3779: excludes I, O, Q


def _letters(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.ascii_uppercase) for _ in range(n))


# --------------------------------------------------------------------------- CISLO_OP
def make_cislo_op(rng: random.Random) -> tuple[str, PiiSpec]:
    sep = rng.choice(("", " ", NBSP))
    surface = f"{_letters(rng, 2)}{sep}{rng.randint(0, 999_999):06d}"
    spec = PiiSpec(surface=surface, type="CISLO_OP", auto_redact=True, should_flag=False)
    return surface, spec


# --------------------------------------------------------------------------- CISLO_PASU
def make_cislo_pasu(rng: random.Random) -> tuple[str, PiiSpec]:
    sep = rng.choice(("", " ", NBSP))
    surface = f"{_letters(rng, 2)}{sep}{rng.randint(0, 9_999_999):07d}"
    spec = PiiSpec(surface=surface, type="CISLO_PASU", auto_redact=True, should_flag=False)
    return surface, spec


# --------------------------------------------------------------------------- VODICSKY_PREUKAZ
def make_vodicsky_preukaz(rng: random.Random) -> tuple[str, PiiSpec]:
    chars = string.ascii_uppercase + string.digits
    length = rng.randint(6, 10)
    surface = "".join(rng.choice(chars) for _ in range(length))
    spec = PiiSpec(
        surface=surface, type="VODICSKY_PREUKAZ", auto_redact=True, should_flag=False
    )
    return surface, spec


# --------------------------------------------------------------------------- ECV
def make_ecv(rng: random.Random) -> tuple[str, PiiSpec]:
    sep1 = rng.choice(("", "-", " ", NBSP))
    sep2 = rng.choice(("", " ", NBSP))
    surface = f"{_letters(rng, 2)}{sep1}{rng.randint(0, 999):03d}{sep2}{_letters(rng, 2)}"
    spec = PiiSpec(surface=surface, type="ECV", auto_redact=True, should_flag=False)
    return surface, spec


# --------------------------------------------------------------------------- VIN
def make_vin(rng: random.Random) -> tuple[str, PiiSpec]:
    # rejection sample until the digit+letter mix requirement is met (near-certain on
    # the first draw given a 34-char alphabet split across letters and digits)
    while True:
        surface = "".join(rng.choice(_VIN_ALPHABET) for _ in range(17))
        if any(c.isdigit() for c in surface) and any(c.isalpha() for c in surface):
            break
    spec = PiiSpec(surface=surface, type="VIN", auto_redact=True, should_flag=False)
    return surface, spec


# --------------------------------------------------------------------------- BIC
def make_bic(rng: random.Random) -> tuple[str, PiiSpec]:
    # Country code fixed to "SK": this is a Slovak-law-office corpus, so every generated
    # BIC is a real Slovak bank's SWIFT shape, and fixing "SK" at positions 5-6 means the
    # surface is self-detectable by the country-code exception even before a template
    # round adds a BIC/SWIFT anchor around it (CONTRACTS_v11.md B2 spec §BIC).
    alnum = string.ascii_uppercase + string.digits
    branch = "".join(rng.choice(alnum) for _ in range(3)) if rng.random() < 0.5 else ""
    surface = f"{_letters(rng, 4)}SK{''.join(rng.choice(alnum) for _ in range(2))}{branch}"
    spec = PiiSpec(surface=surface, type="BIC", auto_redact=True, should_flag=False)
    return surface, spec


def make_all(rng: random.Random) -> list[tuple[str, PiiSpec]]:
    return [
        make_cislo_op(rng),
        make_cislo_pasu(rng),
        make_vodicsky_preukaz(rng),
        make_ecv(rng),
        make_vin(rng),
        make_bic(rng),
    ]

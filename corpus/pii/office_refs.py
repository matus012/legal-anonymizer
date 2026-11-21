"""Corpus PII generators for v1.1 round B2 (CONTRACTS_v11.md §9): the four bank/office
reference types owned by ``detect/office_refs.py`` -- NAZOV_UCTU, CISLO_KLIENTA,
KOD_BANKY, FAX -- drawn from Vyhláška MS SR 482/2011 and Inštrukcia MS SR 24/2011, the
authoritative Slovak list of data subject to anonymisation in court decisions.

Each ``make_<type>(rng)`` returns ``(surface, PiiSpec)`` -- the surface AS AUTHORED (no
anchor phrase; templates add the required anchor context in a later round, since all
four of these types are anchor-required per CONTRACTS_v11.md §8) and its ground truth.
None of these four types carries a checksum, so every occurrence is
``auto_redact=True, should_flag=False`` unconditionally.

The KOD_BANKY 4-digit codes below are plausible SK bank codes for realistic fixtures
only, mirroring the style already used in ``corpus/pii/iban.py``'s ``_BANK_CODES`` --
this is NOT the NBS allow-list ``detect.office_refs._detect_kod_banky`` takes as an
optional parameter; that list is deliberately not invented by either module this round.

``corpus.groundtruth.PiiSpec`` does not yet carry a ``checksum`` field this round (a later
round adds it per CONTRACTS_v11.md §7); every ``PiiSpec(...)`` call below therefore omits
it.
# TODO(v1.1): pass checksum="n/a" to every PiiSpec(...) below once PiiSpec carries the field.
"""
from __future__ import annotations

import random

from corpus.groundtruth import PiiSpec

_BANK_CODES = ("0200", "0900", "1100", "0800", "5200", "7500", "8330", "1111")

_ACCOUNT_NAMES = (
    "Ján Novák",
    "Jana Kováčová",
    "Peter Malý",
    "Eva Horváthová",
    "Firma XYZ s.r.o.",
    "Obec Sadová",
)


# --------------------------------------------------------------------------- NAZOV_UCTU
def make_nazov_uctu(rng: random.Random) -> tuple[str, PiiSpec]:
    surface = rng.choice(_ACCOUNT_NAMES)
    spec = PiiSpec(surface=surface, type="NAZOV_UCTU", auto_redact=True, should_flag=False)
    return surface, spec


# --------------------------------------------------------------------------- CISLO_KLIENTA
def make_cislo_klienta(rng: random.Random) -> tuple[str, PiiSpec]:
    style = rng.choice(("plain", "dash", "slash"))
    if style == "plain":
        surface = str(rng.randint(100_000, 999_999))
    elif style == "dash":
        surface = f"{rng.randint(2015, 2025)}-{rng.randint(1, 9999):04d}"
    else:
        surface = f"ZK/{rng.randint(100_000, 999_999)}"
    spec = PiiSpec(surface=surface, type="CISLO_KLIENTA", auto_redact=True, should_flag=False)
    return surface, spec


# --------------------------------------------------------------------------- KOD_BANKY
def make_kod_banky(rng: random.Random) -> tuple[str, PiiSpec]:
    surface = rng.choice(_BANK_CODES)
    spec = PiiSpec(surface=surface, type="KOD_BANKY", auto_redact=True, should_flag=False)
    return surface, spec


# --------------------------------------------------------------------------- FAX
def make_fax(rng: random.Random) -> tuple[str, PiiSpec]:
    style = rng.choice(("intl_plus", "intl_00", "domestic"))
    area = f"{rng.randint(2, 59):02d}"
    local = f"{rng.randint(0, 999_999):06d}"
    if style == "intl_plus":
        surface = f"+421 {area} {local[:3]} {local[3:]}"
    elif style == "intl_00":
        surface = f"00421{area}{local}"
    else:
        surface = f"0{area}{local}"
    spec = PiiSpec(surface=surface, type="FAX", auto_redact=True, should_flag=False)
    return surface, spec


def make_all(rng: random.Random) -> list[tuple[str, PiiSpec]]:
    return [
        make_nazov_uctu(rng),
        make_cislo_klienta(rng),
        make_kod_banky(rng),
        make_fax(rng),
    ]

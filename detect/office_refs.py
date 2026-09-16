"""v1.1 detection engine, round B2 (CONTRACTS_v11.md §8): four bank/office reference
types drawn from the authoritative Slovak list of data subject to anonymisation in court
decisions -- Vyhláška MS SR 482/2011 (the anonymisation decree) and Inštrukcia MS SR
24/2011 (the implementing instruction) -- NAZOV_UCTU, CISLO_KLIENTA, KOD_BANKY, FAX.
Text-in, spans-out. Imports only ``re``, ``detect.core.Candidate``,
``detect.config.DetectConfig``. Never ``corpus/`` or ``eval/``.

Governing rule (context.md §6): recall over precision. None of these four types carries a
checksum, so every emitted Candidate is ``auto=True, checksum="n/a"``.

All four types are ANCHOR-REQUIRED: none of NAZOV_UCTU / CISLO_KLIENTA / KOD_BANKY / FAX
has a shape distinctive enough to stand on its own (a bare 4-digit run is a year or a
house number; a bare phone-shaped digit run is any phone number; free text is free text)
-- the anchor is what turns an otherwise-ordinary string into one of these types. The
anchor text itself is never part of the redacted surface; only the value after it is.
"""
from __future__ import annotations

import re

from .config import DetectConfig
from .core import Candidate

NBSP = " "
_SP = f"[ {NBSP}]"  # a literal space or NBSP, exactly where Slovak typography allows one


# --------------------------------------------------------------------------- NAZOV_UCTU
# "názov účtu[:] <value>" / "majiteľ účtu ..." / "vlastník účtu ...". The value runs to
# the end of the line or the end of the table cell: it stops at a newline, a tab, or a
# run of 2+ spaces (a table renders as 2+ space-padded columns once its structure is
# flattened to text), whichever comes first. A single internal space is part of the
# value (multi-word account names), so the stop condition specifically requires TWO or
# more consecutive space/NBSP chars, not one.
_NAZOV_UCTU_RE = re.compile(
    rf"(?:názov účtu|majiteľ účtu|vlastník účtu){_SP}*:?{_SP}*"
    rf"([^\n\t]+?)(?={_SP}{{2,}}|\t|\n|$)",
    re.IGNORECASE,
)


def _detect_nazov_uctu(text: str) -> list[Candidate]:
    out = []
    for m in _NAZOV_UCTU_RE.finditer(text):
        out.append(
            Candidate(
                type="NAZOV_UCTU",
                surface=m.group(1),
                start=m.start(1),
                end=m.end(1),
                auto=True,
                checksum="n/a",
            )
        )
    return out


# --------------------------------------------------------------------------- CISLO_KLIENTA
# "číslo klienta[:] <token>" / "klientske číslo ..." / "zákaznícke číslo ..." / "č.
# klienta ...". The value is the single following alphanumeric token, which may itself
# contain "-" or "/" (client numbers are frequently segmented, e.g. "2024-0091").
_CISLO_KLIENTA_RE = re.compile(
    rf"(?:číslo klienta|klientske číslo|zákaznícke číslo|č\.{_SP}klienta){_SP}*:?{_SP}*"
    r"([A-Za-z0-9][A-Za-z0-9\-/]*)",
    re.IGNORECASE,
)


def _detect_cislo_klienta(text: str) -> list[Candidate]:
    out = []
    for m in _CISLO_KLIENTA_RE.finditer(text):
        out.append(
            Candidate(
                type="CISLO_KLIENTA",
                surface=m.group(1),
                start=m.start(1),
                end=m.end(1),
                auto=True,
                checksum="n/a",
            )
        )
    return out


# --------------------------------------------------------------------------- KOD_BANKY
# A bare 4-digit run is a year, a house number, or an amount -- it is NEVER matched
# without one of two anchors:
#   (a) "kód banky[:] <4 digits>" -- an explicit label.
#   (b) the 4-digit group after the "/" in a full legacy domestic account,
#       "<prefix>-<base>/<bankcode>" (e.g. "123456-1234567890/1100") -- ONLY the trailing
#       bankcode group is claimed; the full legacy-account shape (prefix AND base AND a
#       4-digit tail) must be present, or this never fires (a bare ".../1100" with no
#       prefix-base in front is not enough).
# ``bank_codes`` is an OPTIONAL NBS allow-list, wired in by a later round; ``None`` (this
# round's only caller) means "accept any 4 digits" -- no list is invented or hardcoded here.
_KOD_BANKY_LABEL_RE = re.compile(rf"kód banky{_SP}*:?{_SP}*(\d{{4}})(?!\d)", re.IGNORECASE)
_LEGACY_ACCOUNT_RE = re.compile(r"(?<!\d)\d{1,6}-\d{2,10}/(\d{4})(?!\d)")


def _detect_kod_banky(text: str, bank_codes: frozenset[str] | None = None) -> list[Candidate]:
    out = []
    for pattern in (_KOD_BANKY_LABEL_RE, _LEGACY_ACCOUNT_RE):
        for m in pattern.finditer(text):
            code = m.group(1)
            if bank_codes is not None and code not in bank_codes:
                continue
            out.append(
                Candidate(
                    type="KOD_BANKY",
                    surface=code,
                    start=m.start(1),
                    end=m.end(1),
                    auto=True,
                    checksum="n/a",
                )
            )
    return out


# --------------------------------------------------------------------------- FAX
# "fax[:] <number>" / "faxové číslo ..." / "fax č. ...", then a phone-shaped run: an
# international "+421" or "00421" prefix, or a domestic leading "0", followed by 6-12
# more digits with optional space/NBSP/"-"/"." separators between any two digits. The
# longer anchor phrases are listed before the bare "fax" alternative so the match reports
# the fuller anchor context; bare "fax" still catches it via backtracking if the longer
# phrases don't apply.
_FAX_SEPCHAR = f"[-.{NBSP} ]"
_FAX_RE = re.compile(
    rf"(?:faxové číslo|fax č\.|fax){_SP}*:?{_SP}*"
    rf"((?:\+421|00421|0)(?:{_FAX_SEPCHAR}?\d){{6,12}})(?!\d)",
    re.IGNORECASE,
)


def _detect_fax(text: str) -> list[Candidate]:
    out = []
    for m in _FAX_RE.finditer(text):
        out.append(
            Candidate(
                type="FAX",
                surface=m.group(1),
                start=m.start(1),
                end=m.end(1),
                auto=True,
                checksum="n/a",
            )
        )
    return out


def detect_office_refs(text: str, config: DetectConfig) -> list[Candidate]:
    del config  # no toggle in this round affects these four types
    out: list[Candidate] = []
    out.extend(_detect_nazov_uctu(text))
    out.extend(_detect_cislo_klienta(text))
    out.extend(_detect_kod_banky(text))
    out.extend(_detect_fax(text))
    return out

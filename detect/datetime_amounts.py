"""v1 detection engine, layer 1 (context.md §4.1, §6): DATUM and SUMA, the two
shape-only date/amount identifier types. Text-in, spans-out. No file I/O, no docx/pdf,
no ground truth, no import of corpus/ (the dev-only fixture generator) or eval/.

Both types have no checksum: shape validity is the only gate, so every match is always
Candidate(auto=True). There is no review-bucket path for either type.
"""
from __future__ import annotations

import re

from .core import Candidate

_SEP = "[  ]"  # NBSP-or-space; every generator separator is one of the two, never \s

# --------------------------------------------------------------------------- DATUM
_MONTH_WORDS = (
    "januára", "februára", "marca", "apríla", "mája", "júna",
    "júla", "augusta", "septembra", "októbra", "novembra", "decembra",
)
_MONTH_WORDS_ALT = "|".join(_MONTH_WORDS)

_DATUM_RE = re.compile(
    rf"\b\d{{1,2}}\.\d{{1,2}}\.\d{{4}}\b"  # dotted: D.M.YYYY, no leading zeros, no spaces
    rf"|"
    rf"\b\d{{2}}\.{_SEP}\d{{2}}\.{_SEP}\d{{4}}\b"  # spaced: DD. MM. YYYY, zero-padded
    rf"|"
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b"  # iso: YYYY-MM-DD, fully zero-padded
    rf"|"
    rf"\b\d{{1,2}}\.{_SEP}(?:{_MONTH_WORDS_ALT}){_SEP}\d{{4}}\b"  # words: D. <month> YYYY
)


def _detect_datum(text: str) -> list[Candidate]:
    return [
        Candidate(type="DATUM", surface=m.group(0), start=m.start(), end=m.end(), auto=True)
        for m in _DATUM_RE.finditer(text)
    ]


# --------------------------------------------------------------------------- SUMA
# Thousands separator and the separator before the currency token are independently
# seeded NBSP-or-space; the regex accepts any mix of the two. The currency token is the
# anchor -- a bare grouped number with no currency suffix is never matched.
_SUMA_INT = rf"\d{{1,3}}(?:{_SEP}\d{{3}})*"

_SUMA_RE = re.compile(
    rf"\b{_SUMA_INT},\d{{2}}{_SEP}€"  # eur_symbol: <grouped>,CC<sep>€
    rf"|"
    rf"\b{_SUMA_INT},\d{{2}}{_SEP}EUR\b"  # eur_word: <grouped>,CC<sep>EUR
    rf"|"
    rf"\b{_SUMA_INT},-{_SEP}€"  # dash_cents: <grouped>,-<sep>€, no digits in the cents
    rf"|"
    rf"\b{_SUMA_INT}{_SEP}Sk\b"  # sk_legacy: <grouped><sep>Sk, no decimal part at all
)


def _detect_suma(text: str) -> list[Candidate]:
    return [
        Candidate(type="SUMA", surface=m.group(0), start=m.start(), end=m.end(), auto=True)
        for m in _SUMA_RE.finditer(text)
    ]


def detect_datetime_amounts(text: str) -> list[Candidate]:
    return _detect_datum(text) + _detect_suma(text)

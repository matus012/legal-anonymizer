"""v1 detection engine, layer 1 (context.md §4.1, §6): DATUM and SUMA, the two
shape-only date/amount identifier types. Text-in, spans-out. No file I/O, no docx/pdf,
no ground truth, no import of corpus/ (the dev-only fixture generator) or eval/.

Neither type has a checksum. SUMA is therefore always Candidate(auto=True).

DATUM is NOT (v1.1). Every date is DETECTED, but only a DATE OF BIRTH is auto-redacted by
default; every other date goes to the review bucket (auto=False) where the reviewer can tick
it. The reason is readability, not privacy theatre: a contract is a chain of dates -- signed
on, effective from, payable by, registered on -- and destroying all of them leaves a document
nobody can use, which is how a redaction tool stops being used at all. A date of birth is the
one that identifies a person, and it is exactly the one an anchor can find.

DetectConfig(redact_all_dates=True) auto-redacts every date, for an office that wants it.

This module previously ignored its config entirely -- it did not even accept one -- so the
flag was dead and every date was auto-redacted regardless. Found by the GUI round, which
refused to ship a checkbox describing behaviour the engine did not have.
"""
from __future__ import annotations

import re
import unicodedata

from .config import DEFAULT, DetectConfig
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


# A date of birth announces itself with a Slovak birth word nearby. The window is symmetric
# and generous (60 chars) and the match is diacritic-folded, because the cost of a false
# POSITIVE here is one extra auto-redacted date -- the recall-safe direction -- while a false
# negative puts a date of birth in an unticked bucket.
_DOB_WINDOW = 60
_DOB_ANCHOR_RE = re.compile(
    # NOTE: every alternative is a RAW string. An earlier edit of this block wrote the word
    # boundary as an escaped "\b" through a non-raw string, which produced a literal
    # BACKSPACE (U+0008) in the compiled pattern instead of a word boundary. The regex then
    # matched nothing at all and every date silently fell into the review bucket -- the exact
    # invisible-character trap the project handoff warns about. Verified after the fix by
    # asserting repr(_DOB_ANCHOR_RE.pattern) contains no control characters.
    r"\bnar\."
    r"|\bnaroden[yao]"
    r"|\bnarodil|\bnarodila"
    r"|\bdatum\s+narodenia"
    r"|\bdat\.\s?nar\."
    r"|\br\.?\s?c\.?"          # a rodne cislo sits next to a birth date constantly
    r"|\brodne(?:ho)?\s+cisl[oa]"
)


def _fold(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(ch)
    )


def _is_dob(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - _DOB_WINDOW) : end + _DOB_WINDOW]
    return _DOB_ANCHOR_RE.search(_fold(window)) is not None


def _detect_datum(text: str, config: DetectConfig = DEFAULT) -> list[Candidate]:
    out = []
    for m in _DATUM_RE.finditer(text):
        auto = config.redact_all_dates or _is_dob(text, m.start(), m.end())
        out.append(
            Candidate(
                type="DATUM", surface=m.group(0), start=m.start(), end=m.end(), auto=auto
            )
        )
    return out


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


def detect_datetime_amounts(text: str, config: DetectConfig = DEFAULT) -> list[Candidate]:
    return _detect_datum(text, config) + _detect_suma(text)

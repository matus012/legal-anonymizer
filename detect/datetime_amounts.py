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

from .config import DEFAULT, DetectConfig
from .core import Candidate
from .identifiers import ascii_fold as _fold
from .identifiers import diacritic_pattern

# v1.1 SEPARATOR WIDENING (red-team round 2, finding R2-1). This class used to be exactly
# a space or an NBSP. That accepted the one spelling the corpus generator writes and
# rejected every other way the same text reaches us: a TAB (a form-style DOCX table cell is
# tab-aligned), TWO SPACES (column padding), or a LINE BREAK (a PDF text layer wraps on
# every page). Measured over 2559 corpus surfaces, a line break in these positions took
# overall detection robustness to 0.113 and CISLO_KLIENTA to 0.000 -- the very type whose
# anchor was widened after it leaked a client number out of a wrapped PDF. That earlier fix
# widened the separator BETWEEN THE WORDS OF AN ANCHOR and not the one between an anchor
# and its VALUE, so a wrap one word later leaked the same number again.
#
# The class below is horizontal whitespace only -- space, NBSP, tab -- with line breaks
# still EXCLUDED, because a separator INSIDE a surface must not join two lines into one
# phone number. Anchor-to-value separators are widened to full whitespace separately.
# v1.1 LINE-BREAK TOLERANCE INSIDE A VALUE (mutation class line_break_mid).
# This class used to EXCLUDE the line break, with the reasoning that "a separator INSIDE a
# surface must not join two lines into one phone number". That was the wrong trade and the
# mutation gate priced it: line_break_mid measured 0.119 with the exclusion in place, and a
# wrapped PDF text layer had already leaked a client number out of a corpus document.
#
# A PDF text layer wraps every page, so the break lands between the groups of a phone number,
# an IBAN, a date or an amount as a matter of routine. Joining them can over-match; refusing
# to join them demonstrably leaks, and the governing rule (context.md 6) is recall over
# precision. Every separator in this module sits inside a value whose shape the pattern
# already bounds, so a joined match cannot run away down the page -- which is exactly why the
# free-text value patterns elsewhere (a field label's value, NAZOV_UCTU) keep the narrow
# class: those BOUND THEMSELVES on a line break, and widening them would let a value swallow
# the rest of the document.
_SEP = r'\s'

# --------------------------------------------------------------------------- DATUM
_MONTH_WORDS = (
    "januára", "februára", "marca", "apríla", "mája", "júna",
    "júla", "augusta", "septembra", "októbra", "novembra", "decembra",
)
# CASE / DIACRITICS (round-2 red-team): a month word is anchor vocabulary, never evidence,
# so it folds on both axes at its own site -- diacritic_pattern widens the pattern (offsets
# still come off the original text) and the whole alternation is scoped case-insensitive.
_MONTH_WORDS_ALT = "|".join(diacritic_pattern(w) for w in _MONTH_WORDS)

_DATUM_RE = re.compile(
    rf"\b\d{{1,2}}\.\d{{1,2}}\.\d{{4}}\b"  # dotted: D.M.YYYY, no leading zeros, no spaces
    rf"|"
    rf"\b\d{{2}}\.{_SEP}\d{{2}}\.{_SEP}\d{{4}}\b"  # spaced: DD. MM. YYYY, zero-padded
    rf"|"
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b"  # iso: YYYY-MM-DD, fully zero-padded
    rf"|"
    rf"\b\d{{1,2}}\.{_SEP}(?:{_MONTH_WORDS_ALT}){_SEP}\d{{4}}\b",  # words: D. <month> YYYY
    re.IGNORECASE,
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
    rf"\b{_SUMA_INT}{_SEP}Sk\b",  # sk_legacy: <grouped><sep>Sk, no decimal part at all
    re.IGNORECASE,  # currency literals ("EUR", "Sk") are anchor vocabulary, not evidence
)


def _detect_suma(text: str) -> list[Candidate]:
    return [
        Candidate(type="SUMA", surface=m.group(0), start=m.start(), end=m.end(), auto=True)
        for m in _SUMA_RE.finditer(text)
    ]


def detect_datetime_amounts(text: str, config: DetectConfig = DEFAULT) -> list[Candidate]:
    return _detect_datum(text, config) + _detect_suma(text)

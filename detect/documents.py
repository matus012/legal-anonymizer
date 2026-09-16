"""v1.1 detection engine, round B2 (CONTRACTS_v11.md §8): six identity-document /
vehicle-document types -- CISLO_OP, CISLO_PASU, VODICSKY_PREUKAZ, ECV, VIN, BIC. Text-in,
spans-out. Imports only ``re``, ``detect.core.Candidate``, ``detect.config.DetectConfig``.
Never ``corpus/`` or ``eval/``.

Governing rule (context.md §6): recall over precision. Every ambiguous decision below
resolves toward over-detection; none of these six types carries a checksum, so every
emitted Candidate is ``auto=True, checksum="n/a"``.

None of these six types matches a free-running Slovak *word* -- CISLO_OP / CISLO_PASU /
ECV / VIN / BIC are all official document/vehicle codes whose alphabet is fixed by law
(a licence plate, a passport number, a VIN, a SWIFT code) to plain Latin A-Z, never
diacritics. Bare ``[A-Z]`` is therefore correct and deliberate for those character
classes -- it is not the "capitalized Slovak word" case the sprint brief warns about,
because none of these six shapes ever captures free text. (VODICSKY_PREUKAZ's captured
token and, in ``office_refs.py``, the free-text account-name value, are the closest thing
to that case in this round and are intentionally left as broad character classes rather
than restricted to bare ASCII.)

One shape-purity rule recurs below and is factored into one helper, ``_standalone``: a
match is "standalone" (not part of a longer letter or digit run) when the character
immediately before its start and immediately after its end both fail ``str.isalnum()``
-- a letter or digit on either side means the real-world token is longer than what we
matched, so an unanchored claim on it is unsafe. An ANCHORED claim is allowed to ignore
this (the surrounding anchor already proves intent), per the CISLO_OP / CISLO_PASU spec:
"emit anchored matches always."
"""
from __future__ import annotations

import re

from .config import DetectConfig
from .core import Candidate
from .identifiers import diacritic_pattern

NBSP = " "
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
_SP = '[^\\S\\n\\r]'


def _standalone(text: str, start: int, end: int) -> bool:
    """True if the char before ``start`` and the char at ``end`` are not alphanumeric --
    i.e. the match is not a sub-run of a longer letter/digit token."""
    before_ok = start == 0 or not text[start - 1].isalnum()
    after_ok = end == len(text) or not text[end].isalnum()
    return before_ok and after_ok


def _anchored(text: str, start: int, anchor_re: re.Pattern[str], window: int = 40) -> bool:
    return anchor_re.search(text[max(0, start - window) : start]) is not None


def _emit(type_: str, m: re.Match[str]) -> Candidate:
    return Candidate(
        type=type_, surface=m.group(0), start=m.start(), end=m.end(), auto=True, checksum="n/a"
    )


# --------------------------------------------------------------------------- CISLO_OP
# 2 uppercase letters + 6 digits, optional space/NBSP between. The (?!\d) after the digit
# run is load-bearing: on a 2-letter+7-digit string (a passport, not an OP) it stops the
# 6-digit alternative from claiming the first 6 of the 7 digits, so CISLO_OP and
# CISLO_PASU never both fire on the same document number (spec's explicit guard).
# CASE: kept case-SENSITIVE (reverted from an earlier `re.IGNORECASE` attempt). This shape
# has no separator-based right boundary -- an ordinary two-letter lowercase Slovak word
# ("je", "sa", "na") directly followed by six digits is common, and folding case turned every
# one of them into a false CISLO_OP, which then partially overlapped and corrupted a REAL
# RODNE_CISLO candidate a few characters later (measured: `test_normalize_property.py`'s
# corruption-detector fixture). A real OP/passport code is issued in caps by convention, so
# nothing is lost for a genuine document; the anchored path (`_OP_ANCHOR_RE`, already
# case-insensitive) still catches an anchored lowercase OP number.
_OP_CORE_RE = re.compile(rf"[A-Z]{{2}}{_SP}?\d{{6}}(?!\d)")

_C = diacritic_pattern("č")
_OP_ANCHOR_RE = re.compile(
    r"\bOP\b"
    rf"|{_C}\.{_SP}OP\b"
    rf"|\bOP{_SP}{_C}\."
    rf"|{diacritic_pattern('občiansky preukaz')}"
    rf"|{diacritic_pattern('občianskeho preukazu')}"
    rf"|{diacritic_pattern('preukaz totožnosti')}"
    rf"|{diacritic_pattern('doklad totožnosti')}",
    re.IGNORECASE,
)


def _detect_cislo_op(text: str) -> list[Candidate]:
    out = []
    for m in _OP_CORE_RE.finditer(text):
        if _anchored(text, m.start(), _OP_ANCHOR_RE) or _standalone(text, m.start(), m.end()):
            out.append(_emit("CISLO_OP", m))
    return out


# --------------------------------------------------------------------------- CISLO_PASU
# 2 uppercase letters + 7 digits, optional space/NBSP between. Same anchored-always /
# unanchored-standalone-only policy as CISLO_OP; same (?!\d) run-purity guard.
# CASE: reverted to case-SENSITIVE for the same reason as `_OP_CORE_RE` above -- an
# unanchored fold turns any "xx1234567" lowercase run into a false positive.
_PASU_CORE_RE = re.compile(rf"[A-Z]{{2}}{_SP}?\d{{7}}(?!\d)")

_PASU_ANCHOR_RE = re.compile(
    r"\bpas\b"
    r"|\bpasu\b"
    rf"|{diacritic_pattern('cestovný pas')}"
    rf"|{diacritic_pattern('cestovného pasu')}"
    rf"|{_C}\.{_SP}pasu",
    re.IGNORECASE,
)


def _detect_cislo_pasu(text: str) -> list[Candidate]:
    out = []
    for m in _PASU_CORE_RE.finditer(text):
        if _anchored(text, m.start(), _PASU_ANCHOR_RE) or _standalone(
            text, m.start(), m.end()
        ):
            out.append(_emit("CISLO_PASU", m))
    return out


# --------------------------------------------------------------------------- VODICSKY_PREUKAZ
# Anchor-required -- a bare 6-10 char alphanumeric token is far too generic to match on
# its own (it would claim ordinary order/invoice numbers). Everything between the anchor
# and the token (a literal "č.", a colon, spaces) is swallowed by the non-alnum filler;
# the token itself is captured, and the surface is that TOKEN, not the anchor -- the
# anchor is match context, never part of the redacted span.
_VP_RE = re.compile(
    rf"(?:{diacritic_pattern('vodičský preukaz')}|{diacritic_pattern('vodičského preukazu')}"
    rf"|VP{_SP}{_C}\.|{_C}\.{_SP}VP|{diacritic_pattern('vodičák')})"
    r"[^A-Za-z0-9]{0,20}"
    r"([A-Za-z0-9]{6,10})(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _detect_vodicsky_preukaz(text: str) -> list[Candidate]:
    out = []
    for m in _VP_RE.finditer(text):
        out.append(
            Candidate(
                type="VODICSKY_PREUKAZ",
                surface=m.group(1),
                start=m.start(1),
                end=m.end(1),
                auto=True,
                checksum="n/a",
            )
        )
    return out


# --------------------------------------------------------------------------- ECV
# Slovak licence plate: 2 uppercase letters, optional "-" or space/NBSP, 3 digits,
# optional space/NBSP, 2 uppercase letters ("KE123AB", "KE-123AB", "BA 123 XY"). No
# anchor required -- the shape is distinctive enough on its own. The (?!\d) after the
# digit run and the \b at both ends stop a plate from being read out of a longer digit
# or letter run (e.g. a 4-digit number or a longer all-caps abbreviation run).
# CASE: kept case-SENSITIVE. This is a fixed-shape identifier with no anchor at all (a
# licence plate is written in caps by law), so `[A-Z]{2}` here IS the evidence, not anchor
# vocabulary -- folding it turns any lowercase "xx123xy"-shaped run into a false ECV, same
# lesson as `_OP_CORE_RE`/`_PASU_CORE_RE` above.
_ECV_RE = re.compile(rf"\b[A-Z]{{2}}[-{NBSP} ]?\d{{3}}(?!\d){_SP}?[A-Z]{{2}}\b")


def _detect_ecv(text: str) -> list[Candidate]:
    return [_emit("ECV", m) for m in _ECV_RE.finditer(text)]


# --------------------------------------------------------------------------- VIN
# 17 chars from the ISO 3779 VIN alphabet, which excludes I, O and Q (they are visually
# confusable with 1 and 0) -- that exclusion, plus requiring at least one digit AND one
# letter, is exactly what stops this from matching an arbitrary 17-character run of caps
# (a pure-digit or pure-letter 17-run is refused below).
# CASE: kept case-SENSITIVE. Same reasoning -- a VIN is stamped in caps and has no anchor;
# `re.IGNORECASE` here would fold the excluded-letter guard (I/O/Q) onto lowercase i/o/q too,
# which is harmless on its own, but the class would also start matching ordinary lowercase
# 17-character runs across word boundaries, which is evidence-shaped, not anchor-shaped.
_VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def _detect_vin(text: str) -> list[Candidate]:
    out = []
    for m in _VIN_RE.finditer(text):
        surface = m.group(0)
        if any(c.isdigit() for c in surface) and any(c.isalpha() for c in surface):
            out.append(_emit("VIN", m))
    return out


# --------------------------------------------------------------------------- BIC
# BIC/SWIFT: 4 letters (bank) + 2 letters (country) + 2 alphanumeric (location) +
# optional 3 alphanumeric (branch) -- 8 or 11 chars total. An 8-letter all-caps run is
# shape-identical to an ordinary ALL-CAPS Slovak word ("ROZHODNUTIE", "SPLNOMOCNENIE"),
# so shape alone is deliberately NOT enough: this is the one precision exception in this
# module. A match is only emitted when EITHER a BIC/SWIFT anchor sits within 30 chars
# before it, OR positions 5-6 (the ISO 3166 country code) read "SK" -- an all-caps
# Slovak word essentially never has "SK" sitting at exactly that position, while every
# real Slovak BIC does. Without one of those two signals, the red-team ALL-CAPS mutation
# (rewriting any word in caps) would turn every capitalised word in the corpus into a
# false BIC positive.
_BIC_RE = re.compile(r"\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
_BIC_ANCHOR_RE = re.compile(r"\bBIC\b|\bSWIFT\b|BIC/SWIFT|SWIFT kód|BIC kód", re.IGNORECASE)


def _detect_bic(text: str) -> list[Candidate]:
    out = []
    for m in _BIC_RE.finditer(text):
        surface = m.group(0)
        if _anchored(text, m.start(), _BIC_ANCHOR_RE, window=30) or surface[4:6] == "SK":
            out.append(_emit("BIC", m))
    return out


def detect_documents(text: str, config: DetectConfig) -> list[Candidate]:
    del config  # no toggle in this round affects these six types
    out: list[Candidate] = []
    out.extend(_detect_cislo_op(text))
    out.extend(_detect_cislo_pasu(text))
    out.extend(_detect_vodicsky_preukaz(text))
    out.extend(_detect_ecv(text))
    out.extend(_detect_vin(text))
    out.extend(_detect_bic(text))
    return out

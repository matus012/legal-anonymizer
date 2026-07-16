"""v1 detection engine, layer 1 (context.md §4.1, §6): the four Slovak
registry-reference types — LV, PARCELA, ORSR_VLOZKA, SPISOVA_ZNACKA. Text-in,
spans-out. No file I/O, no docx/pdf, no ground truth, no import of corpus/ (the
dev-only fixture generator) or eval/.

All four types are shape-only: no checksum exists for any of them, so every match is
always Candidate(auto=True). There is no review-bucket path for these types.

The registry prefix ("LV č.", "parc. č.", "Oddiel: …, Vložka č.", the cadastral
letter or the fused court agenda) is part of the GT surface, so the whole span
including the prefix is matched. NBSP-or-space occurs only immediately after "č." —
every other space in these surfaces is authored as a plain space and matched
literally, never widened to \\s.
"""
from __future__ import annotations

import re

from .core import Candidate

NBSP = "\u00a0"
_SP = f"[ {NBSP}]"  # NBSP-or-space; only ever directly after "č."

# --------------------------------------------------------------------------- LV
# "LV č. <1-4 digits>"; (?!\d) refuses to split a 5+ digit run mid-number.
_LV_RE = re.compile(rf"\bLV č\.{_SP}\d{{1,4}}(?!\d)")

# --------------------------------------------------------------------------- PARCELA
# One detector over the four authored styles: plain "parc. č. 123", subdivided
# "parc. č. 123/4", and the long cadastral forms with the „C“/„E“ register (Slovak
# quotes U+201E/U+201C are part of the surface). (?!\d) guards the end so a longer
# digit run is never split.
_PARCELA_RE = re.compile(
    rf"\bparc\. č\.{_SP}\d{{1,4}}(?:/\d{{1,2}})?(?!\d)"  # plain / sub
    rf"|"
    rf"\bparcela registra „[CE]“ KN č\.{_SP}\d{{1,4}}/\d{{1,2}}(?!\d)"  # kn_c / kn_e
)

# --------------------------------------------------------------------------- ORSR_VLOZKA
# The whole "Oddiel: <section>, Vložka č. <3-5 digits>/<court letter>" string is the
# GT surface; the spaces after "Oddiel:" and after the comma are always plain spaces.
_ORSR_VLOZKA_RE = re.compile(
    rf"\bOddiel: (?:Sro|Sa|Pš|Dr), Vložka č\.{_SP}\d{{3,5}}/[VBTNZ]\b"
)

# --------------------------------------------------------------------------- SPISOVA_ZNACKA
# cadastral: registry-office filing number; the letter+dash prefix is required, so a
# bare "1234/2025" is never claimed. court: the agenda letters are fused to the
# leading digits with no space. Two-char agendas (Cb, Ro, Er) must precede the
# single-char C in the alternation, or C consumes the C of Cb and the match dies on
# the leftover "b".
_SPISOVA_ZNACKA_RE = re.compile(
    r"\b[VZPXR]-\d{1,4}/\d{4}(?!\d)"  # cadastral: V-1234/2025 (also Z, P, X, R)
    r"|"
    r"\b\d{1,2}(?:Cb|Ro|Er|C|T|D)/\d{1,3}/\d{4}(?!\d)"  # court: 12Cb/345/2025
)


def _matches(pattern: re.Pattern[str], type_: str, text: str) -> list[Candidate]:
    return [
        Candidate(type=type_, surface=m.group(0), start=m.start(), end=m.end(), auto=True)
        for m in pattern.finditer(text)
    ]


def detect_registry(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    out.extend(_matches(_LV_RE, "LV", text))
    out.extend(_matches(_PARCELA_RE, "PARCELA", text))
    out.extend(_matches(_ORSR_VLOZKA_RE, "ORSR_VLOZKA", text))
    out.extend(_matches(_SPISOVA_ZNACKA_RE, "SPISOVA_ZNACKA", text))
    return out

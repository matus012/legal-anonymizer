"""v1.1 detection engine, layer 1 (CONTRACTS_v11.md §8, B1 round): the six Slovak
address-block types — PSC, ADRESA, SUPISNE_CISLO, CISLO_BYTU, VCHOD, POSCHODIE.
Text-in, spans-out. No file I/O, no docx/pdf, no ground truth, no import of corpus/
or eval/.

None of these six types carries a checksum, so every match is always
``Candidate(auto=True, checksum="n/a")`` (governing rule, context.md §6: recall over
precision — a false positive costs a reviewer two seconds, a false negative is a client
data breach).

Slovak text mixes a normal space and a non-breaking space (U+00A0, ``NBSP``) anywhere a
space can appear in an authored document (Slovak typography puts an NBSP after
abbreviations like "č."), so every separator in these patterns accepts either. Capitalized
tokens (street names, obce) must accept Slovak diacritics — an ASCII ``[A-Z]``/``[a-z]``
class would silently drop ``Štúrova``/``Košice``/``Ľubochňa``, so the upper/lower classes
below are spelled out explicitly instead.

ADRESA is the composite type and OUTRANKS its own parts (contract §4): where a street +
house number is immediately followed by ", " + PSC + a Capitalized obec token, the ADRESA
match is EXTENDED to swallow them into one span. This module does not itself resolve the
resulting overlap between the extended ADRESA and the standalone PSC/OBEC candidates on
the same text — that is `detect/core.py`'s generalised containment resolver (contract §5),
run in a later integration round. Emitting both here is by design.

Each of the six regexes below is checked with `finditer`, whose matches never overlap
each other on the same pattern, so a single type's own regex never emits two candidates on
the same span. Cross-type overlap (e.g. ADRESA's extended span vs. a standalone PSC) is
left to the core resolver as noted above.
"""
from __future__ import annotations

import re

from .config import DetectConfig
from .core import Candidate

NBSP = " "
_SEP = f"[ {NBSP}]"  # normal space or NBSP, anywhere a space can appear

# Slovak alphabet, explicit (no bare [A-Z]/[a-z] — those silently drop diacritics).
_SK_UPPER = "AÁÄBCČDĎEÉFGHIÍJKLĹĽMNŇOÓÔPQRŔSŠTŤUÚVWXYÝZŽ"
_SK_LOWER = "aáäbcčdďeéfghiíjklĺľmnňoóôpqrŕsštťuúvwxyýzž"
_CAP = rf"[{_SK_UPPER}][{_SK_LOWER}]+"  # one Capitalized token (street/obec name)
_TOKEN_SEQ = rf"{_CAP}(?:{_SEP}{_CAP}){{0,2}}"  # 1-3 Capitalized tokens
_HOUSENUM = rf"(?<!\d)\d{{1,4}}(?:/[A-Za-z0-9]{{1,3}})?(?!\d)"  # house + optional /orient


def _make(type_: str, text: str, start: int, end: int) -> Candidate:
    return Candidate(
        type=type_, surface=text[start:end], start=start, end=end, auto=True, checksum="n/a"
    )


# --------------------------------------------------------------------------- PSC
# Spaced form (\d{3} SEP \d{2}) matches with EITHER an explicit "PSČ"/"PSC" anchor within
# 20 chars before, OR when followed by an optional comma+space then a Capitalized obec
# token ("040 01 Košice"). The contiguous 5-digit form is far more ambiguous (it is also a
# page count / amount / file number), so it matches ONLY with the explicit anchor, or when
# BOTH preceded by ", " and followed by whitespace + a Capitalized token — never on the
# anchor-less follow-token rule alone. (?<!\d)/(?!\d) on both guard a longer digit run from
# ever being split.
_PSC_SPACED_RE = re.compile(rf"(?<!\d)\d{{3}}{_SEP}\d{{2}}(?!\d)")
_PSC_CONTIG_RE = re.compile(r"(?<!\d)\d{5}(?!\d)")
_PSC_ANCHOR_RE = re.compile(r"psč|psc", re.IGNORECASE)


def _psc_anchor_before(text: str, pos: int) -> bool:
    return _PSC_ANCHOR_RE.search(text[max(0, pos - 20) : pos]) is not None


def _psc_followed_by_obec(text: str, pos: int, *, allow_comma: bool) -> bool:
    rest = text[pos:]
    pattern = rf"^,?{_SEP}*{_CAP}" if allow_comma else rf"^{_SEP}+{_CAP}"
    return re.match(pattern, rest) is not None


def _psc_preceded_by_comma_space(text: str, pos: int) -> bool:
    before = text[max(0, pos - 2) : pos]
    return before in (", ", "," + NBSP)


def _detect_psc(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    for m in _PSC_SPACED_RE.finditer(text):
        if _psc_anchor_before(text, m.start()) or _psc_followed_by_obec(
            text, m.end(), allow_comma=True
        ):
            out.append(_make("PSC", text, m.start(), m.end()))
    for m in _PSC_CONTIG_RE.finditer(text):
        if _psc_anchor_before(text, m.start()):
            out.append(_make("PSC", text, m.start(), m.end()))
        elif _psc_preceded_by_comma_space(
            text, m.start()
        ) and _psc_followed_by_obec(text, m.end(), allow_comma=False):
            out.append(_make("PSC", text, m.start(), m.end()))
    return out


# --------------------------------------------------------------------------- ADRESA
# Keyword form: one of the street/square/avenue/road/estate keywords (matched
# case-insensitively via the scoped (?i:...) group, so the class doesn't also loosen the
# Capitalized-token requirement), then 1-3 Capitalized tokens, then a house number.
_ADRESA_KEYWORD_RE = re.compile(
    rf"(?i:ul\.|ulica|nám\.|námestie|trieda|cesta|sídlisko)"
    rf"{_SEP}+{_TOKEN_SEQ}{_SEP}+{_HOUSENUM}"
)

# Keyword-less form: 1-3 Capitalized tokens + house number, matched only when an address
# anchor phrase appears within 40 chars before ("trvale bytom Hlavná 12/A").
_ADRESA_BARE_RE = re.compile(rf"{_TOKEN_SEQ}{_SEP}+{_HOUSENUM}")
_ADRESA_ANCHOR_RE = re.compile(
    r"trvale bytom|trvalé bydlisko|bytom|bydlisko|so sídlom|sídlo"
    r"|miesto podnikania|na adrese|adresa",
    re.IGNORECASE,
)

# Extension: ", " (or ","+NBSP) + PSC (spaced or contiguous) + SEP + Capitalized obec token
# immediately after either form swallows the PSC/obec into the ADRESA span.
_ADRESA_EXT_RE = re.compile(
    rf",{_SEP}(?:\d{{3}}{_SEP}\d{{2}}|\d{{5}}){_SEP}{_CAP}"
)


def _extend_adresa(text: str, start: int, end: int) -> tuple[int, int]:
    m = _ADRESA_EXT_RE.match(text[end:])
    return (start, end + m.end()) if m else (start, end)


def _detect_adresa(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    spans: list[tuple[int, int]] = []
    for m in _ADRESA_KEYWORD_RE.finditer(text):
        start, end = _extend_adresa(text, m.start(), m.end())
        spans.append((start, end))
        out.append(_make("ADRESA", text, start, end))
    for m in _ADRESA_BARE_RE.finditer(text):
        if not _ADRESA_ANCHOR_RE.search(text[max(0, m.start() - 40) : m.start()]):
            continue
        start, end = _extend_adresa(text, m.start(), m.end())
        if any(s <= start and end <= e for s, e in spans):
            continue  # already covered by a keyword-form match on this exact tail
        spans.append((start, end))
        out.append(_make("ADRESA", text, start, end))
    return out


# --------------------------------------------------------------------------- SUPISNE_CISLO
# Keyword prefix is part of the matched surface (registry_refs.py convention). The combined
# "súpisné/orientačné číslo" alternative is listed first only for readability -- it starts
# with a different literal ("sú...") than every other alternative, so ordering cannot cause
# a partial match.
_SUPISNE_CISLO_RE = re.compile(
    rf"(?i:súpisné/orientačné číslo|súpisné číslo|súp\. č\.|orientačné číslo|or\. č\.|s\. č\.)"
    rf"{_SEP}+\d{{1,4}}(?:/\d{{1,4}})?"
)

# --------------------------------------------------------------------------- CISLO_BYTU
_CISLO_BYTU_RE = re.compile(
    rf"(?i:byt č\.|byt číslo|číslo bytu|b\. č\.){_SEP}+\d{{1,4}}"
)

# --------------------------------------------------------------------------- VCHOD
# "vchod" + optional "č." or ":" (each optionally preceded by SEP) + SEP + 1-3 alnum chars
# (a house/orientation number or a bare capital letter, "vchod A").
_VCHOD_RE = re.compile(
    rf"(?i:vchod)(?:{_SEP}*č\.|{_SEP}*:)?{_SEP}+[A-Za-z0-9]{{1,3}}"
)

# --------------------------------------------------------------------------- POSCHODIE
# Four authored surface shapes: "na <n>. poschodí" (locative, "na" is part of the surface
# per the authored example), "<n>. poschodie" (prefix, nominative, no leading "na"),
# "poschodie[:] <n>" (suffix), and the standalone "prízemie" (ground floor, no number at
# all). The locative alternative is listed first and matches ONLY the "-í" ending (never
# "-ie") so it cannot swallow the "na" out of a following nominative "3. poschodie" match.
_POSCHODIE_RE = re.compile(
    rf"(?i:"
    rf"na{_SEP}\d{{1,2}}\. poschodí"
    rf"|\d{{1,2}}\. poschod(?:ie|í)"
    rf"|poschod(?:ie|í)(?:{_SEP}*:)?{_SEP}+\d{{1,2}}"
    rf"|prízemie"
    rf")"
)


def _matches(pattern: re.Pattern[str], type_: str, text: str) -> list[Candidate]:
    return [_make(type_, text, m.start(), m.end()) for m in pattern.finditer(text)]


def detect_addresses(text: str, config: DetectConfig) -> list[Candidate]:
    """Detect PSC, ADRESA, SUPISNE_CISLO, CISLO_BYTU, VCHOD, POSCHODIE spans.

    ``config`` carries no toggle relevant to this module (both DetectConfig fields govern
    checksum-tagging and DATUM redaction only); it is accepted to match the frozen
    per-module signature (contract §8) so the orchestrator's later dispatch wiring is
    uniform across every detector module.
    """
    del config
    out: list[Candidate] = []
    out.extend(_detect_adresa(text))
    out.extend(_detect_psc(text))
    out.extend(_matches(_SUPISNE_CISLO_RE, "SUPISNE_CISLO", text))
    out.extend(_matches(_CISLO_BYTU_RE, "CISLO_BYTU", text))
    out.extend(_matches(_VCHOD_RE, "VCHOD", text))
    out.extend(_matches(_POSCHODIE_RE, "POSCHODIE", text))
    return out

"""v1 detection engine, layer 1 (context.md §4.1, §6): the five checksum/format-bearing
identifier types. Text-in, spans-out. No file I/O, no docx/pdf, no ground truth.

Every checksum here is reimplemented from the spec independently of corpus/pii/* (the
dev-only fixture generator) so the generator and the detector can never silently agree
while both are wrong.

v1.1 (CONTRACTS_v11.md §6, policy A1): THE CHECKSUM IS A TAG, NOT A FILTER. A shape-valid
but checksum-INVALID identifier is still redacted by default (auto=True) and merely carries
checksum="invalid". The rationale is context.md §6, recall over precision: a mistyped IČO is
still an IČO, and leaving it un-redacted because one digit is wrong is the exact failure mode
this tool exists to prevent. The reviewer sees the "invalid" tag in the report and in the GUI
review column instead of having to notice an un-redacted number. DetectConfig(
strict_checksums=True) restores the v1 behaviour (auto=False -> review bucket) and still sets
the tag.

DIC and IC_DPH have no documented checksum (context.md §4.1: "10 digits" / "SK + DIČ"
only). For those two, shape validity is the only gate: shape valid -> auto=True always,
checksum="n/a".
"""
from __future__ import annotations

import re
import unicodedata

from .config import DEFAULT, DetectConfig
from .core import Candidate

NBSP = " "


def _checksum_verdict(ok: bool, config: DetectConfig) -> tuple[bool, str]:
    """(auto, checksum tag) for a shape-valid surface of a checksum-bearing type."""
    if ok:
        return True, "valid"
    return (not config.strict_checksums), "invalid"


# --------------------------------------------------------------------------- RODNE_CISLO
# CONTRACTS_v11.md §6a. Two lengths with different rules:
#   10 digits YYMMDD/XXXX -> mod-11 applies.
#   9 digits  YYMMDD/XXX  -> issued before 1954, HAS NO CHECKSUM AT ALL. Applying mod-11
#                            to it is the A2 bug; it is always checksum="n/a", auto=True.
# Separator between the two groups: '/', space, NBSP, or nothing. Internal space/NBSP
# inside either digit group is accepted and is part of the matched surface.
#
# Two patterns rather than one optional separator, deliberately: the SEPARATED form may
# carry internal whitespace, the CONTIGUOUS form may not. Allowing both at once makes
# "0905 123 456" parse as "0905 12" + "" + "3 456" and steals every phone number from
# TELEFON. Requiring the separator-less form to be a solid digit run removes that whole
# class of mis-parse without losing any authored RČ shape.
_D6 = rf"\d(?:[ {NBSP}]?\d){{5}}"
_D4 = rf"\d(?:[ {NBSP}]?\d){{3}}"
_D3 = rf"\d(?:[ {NBSP}]?\d){{2}}"
_RC_SEP_RE = re.compile(rf"(?<!\d)({_D6})[/ {NBSP}](?:{_D4}|{_D3})(?!\d)")
_RC_CONTIG_RE = re.compile(r"(?<!\d)\d{9,10}(?!\d)")

# The contiguous form is only armed by an RČ context anchor within 40 characters before
# the match (§6a). Without it a bare 9/10-digit run stays owned by DIC exactly as in v1 —
# matching it unconditionally would claim every 10-digit number in every document.
# Matched against a diacritic-stripped, lowercased copy of the window, so "r.č." / "rč" /
# "rodné číslo" / "rodného čísla" / "nar." all reduce to their ASCII skeletons.
_RC_ANCHOR_WINDOW = 40
_RC_ANCHOR_RE = re.compile(
    r"\br\.?[  ]?c\.?"  # r.č. / rč / r č
    r"|\brodne(?:ho)?[  ]+cisl[oa]"  # rodné číslo / rodného čísla
    r"|\bnar\."
)


def _ascii_fold(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(ch)
    )


def _rc_anchored(text: str, start: int) -> bool:
    return _RC_ANCHOR_RE.search(_ascii_fold(text[max(0, start - _RC_ANCHOR_WINDOW) : start])) is not None


def _rc_shape_ok(digits: str) -> bool:
    month = int(digits[2:4])
    for offset in (0, 50, 20, 70):  # +20/+70 are post-2004 overflow allocations
        m = month - offset
        if 1 <= m <= 12:
            break
    else:
        return False
    return 1 <= int(digits[4:6]) <= 31


def _rc_checksum_ok(digits: str) -> bool:
    return int(digits) % 11 == 0


def _detect_rc(text: str, config: DetectConfig = DEFAULT) -> list[Candidate]:
    spans = [(m.start(), m.end()) for m in _RC_SEP_RE.finditer(text)]
    spans += [
        (m.start(), m.end())
        for m in _RC_CONTIG_RE.finditer(text)
        if _rc_anchored(text, m.start())
    ]
    out = []
    for start, end in spans:
        surface = text[start:end]
        digits = "".join(ch for ch in surface if ch.isdigit())
        if not _rc_shape_ok(digits):
            continue
        if len(digits) == 9:  # pre-1954 form: no checksum exists, never tag it "invalid"
            auto, checksum = True, "n/a"
        else:
            auto, checksum = _checksum_verdict(_rc_checksum_ok(digits), config)
        out.append(
            Candidate(
                type="RODNE_CISLO",
                surface=surface,
                start=start,
                end=end,
                auto=auto,
                checksum=checksum,
            )
        )
    return out


# --------------------------------------------------------------------------- ICO
# THE DIGIT/LETTER BOUNDARY DEFECT (v1.1). `\b` sits between a word char and a NON-word
# char. A digit and a letter are BOTH word chars, so there is no `\b` between them, and
# `\b\d{8}\b` does NOT match the eight digits in "43235222IBAN". That is not hypothetical:
# it is what a PDF text layer produces where two layout cells abut with no space, and what
# a DOCX table produces when cell text is reconstructed without separators. The identifier
# is then INVISIBLE to detection and leaks -- and worse, the widened RODNE_CISLO pattern
# can match a fragment of it instead. So every numeric identifier here is guarded with
# `(?<!\d)`/`(?!\d)`: still refusing to split a longer digit run, but no longer suppressed
# by an adjacent LETTER. Recall over precision (context.md 6).
_ICO_RE = re.compile(r"(?<!\d)\d{8}(?!\d)")
_ICO_WEIGHTS = (8, 7, 6, 5, 4, 3, 2)


def _ico_checksum_ok(digits: str) -> bool:
    s = sum(int(c) * w for c, w in zip(digits[:7], _ICO_WEIGHTS))
    mod = s % 11
    check = 1 if mod == 0 else (0 if mod == 1 else 11 - mod)
    return check == int(digits[7])


def _detect_ico(text: str, config: DetectConfig = DEFAULT) -> list[Candidate]:
    out = []
    for m in _ICO_RE.finditer(text):
        digits = m.group(0)
        auto, checksum = _checksum_verdict(_ico_checksum_ok(digits), config)
        out.append(
            Candidate(
                type="ICO",
                surface=digits,
                start=m.start(),
                end=m.end(),
                auto=auto,
                checksum=checksum,
            )
        )
    return out


# --------------------------------------------------------------------------- IC_DPH / DIC
# IC_DPH is "SK" + 10 digits. v1 relied on a `\b` ACCIDENT to stop the bare-DIC pattern
# re-claiming those same ten digits ("K" is a word char, so `\b\d{10}\b` could not match
# inside "SK1234567890"). That accident is GONE under the digit guards above, so DIC now
# DOES emit a candidate on the inner span. Handled explicitly instead of by luck: the
# IC_DPH span strictly CONTAINS the DIC span, so detect.core's containment resolver drops
# the inner DIC and keeps IC_DPH. Identical outcome, documented mechanism not a side effect.
_IC_DPH_RE = re.compile(r"(?<![A-Za-z0-9])SK(\d{10})(?!\d)")
_DIC_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")


def _detect_ic_dph(text: str) -> list[Candidate]:
    return [
        Candidate(type="IC_DPH", surface=m.group(0), start=m.start(), end=m.end(), auto=True)
        for m in _IC_DPH_RE.finditer(text)
    ]


def _detect_dic(text: str) -> list[Candidate]:
    return [
        Candidate(type="DIC", surface=m.group(0), start=m.start(), end=m.end(), auto=True)
        for m in _DIC_RE.finditer(text)
    ]


# --------------------------------------------------------------------------- IBAN
_IBAN_RE = re.compile(r"(?<![A-Za-z0-9])SK\d{2}(?: ?\d{4}){5}(?!\d)")


def _iban_mod97_ok(compact: str) -> bool:
    s = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in s)  # A-Z -> 10-35
    return int(digits) % 97 == 1


def _detect_iban(text: str, config: DetectConfig = DEFAULT) -> list[Candidate]:
    out = []
    for m in _IBAN_RE.finditer(text):
        compact = m.group(0).replace(" ", "")
        auto, checksum = _checksum_verdict(_iban_mod97_ok(compact), config)
        out.append(
            Candidate(
                type="IBAN",
                surface=m.group(0),
                start=m.start(),
                end=m.end(),
                auto=auto,
                checksum=checksum,
            )
        )
    return out


# --------------------------------------------------------------------------- BANKOVY_UCET
# Legacy SK domestic account, prefix-base/bankcode (GT labels this BANKOVY_UCET, not
# IBAN). The dashed prefix is REQUIRED: a bare base/bankcode (no dash) collides with
# decoy order numbers ("Obj. c. 123/2019"), so the prefixless form is deliberately not
# matched. The bank code is not validated against any list.
_BANKOVY_UCET_RE = re.compile(r"(?<!\d)(\d{1,6})-(\d{2,10})/(\d{4})(?!\d)")

_PREFIX_WEIGHTS = (10, 5, 8, 4, 2, 1)
_BASE_WEIGHTS = (6, 3, 7, 9, 10, 5, 8, 4, 2, 1)


def _weighted_mod11_ok(number: str, weights: tuple[int, ...]) -> bool:
    tail = number[-len(weights):]
    s = sum(int(c) * w for c, w in zip(reversed(tail), reversed(weights)))
    return s % 11 == 0


def _detect_bankovy_ucet(text: str, config: DetectConfig = DEFAULT) -> list[Candidate]:
    out = []
    for m in _BANKOVY_UCET_RE.finditer(text):
        prefix, base = m.group(1), m.group(2)
        valid = _weighted_mod11_ok(prefix, _PREFIX_WEIGHTS) and _weighted_mod11_ok(
            base, _BASE_WEIGHTS
        )
        auto, checksum = _checksum_verdict(valid, config)
        out.append(
            Candidate(
                type="BANKOVY_UCET",
                surface=m.group(0),
                start=m.start(),
                end=m.end(),
                auto=auto,
                checksum=checksum,
            )
        )
    return out


# --------------------------------------------------------------------------- EMAIL
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")


def _detect_email(text: str) -> list[Candidate]:
    return [
        Candidate(type="EMAIL", surface=m.group(0), start=m.start(), end=m.end(), auto=True)
        for m in _EMAIL_RE.finditer(text)
    ]


# --------------------------------------------------------------------------- URL
# Bare-scheme form ("name.tld") is shape-identical to an email domain part; EMAIL wins
# via containment suppression in detect.core, not via type precedence (no exact-span collision).
# A scheme-less match ("name.tld") is otherwise indistinguishable from a filename
# ("dokument.pdf"), so it is only accepted when the final label is a real-world TLD;
# an explicit http(s)/www scheme disambiguates intent, so that form keeps the looser rule.
_URL_TLD_ALLOW = r"(?:sk|cz|com|eu|org|net|info|biz|edu|gov|io|dev)"
_URL_RE = re.compile(
    r"\b(?:https?://(?:www\.)?|www\.)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"
    r"|"
    rf"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.{_URL_TLD_ALLOW}\b"
)


def _detect_url(text: str) -> list[Candidate]:
    return [
        Candidate(type="URL", surface=m.group(0), start=m.start(), end=m.end(), auto=True)
        for m in _URL_RE.finditer(text)
    ]


# --------------------------------------------------------------------------- TELEFON
# Every generated phone carries structure (+421, a leading-0 mobile prefix, or an
# area/local slash) with a group separator that is a normal space or NBSP (U+00A0),
# never both collapsed into a bare \s (that would also swallow newlines). A contiguous
# digit run (RODNE_CISLO, DIC, ICO) is never matched: every alternative below requires
# a literal separator or slash between digit groups, which a bare digit run lacks.
_SEP = "[  ]"
_TELEFON_RE = re.compile(
    r"\+421"
    rf"{_SEP}\d{{1,3}}{_SEP}\d{{3,4}}{_SEP}\d{{3,4}}"  # mobile_intl / landline_intl
    r"|"
    rf"\b0\d{{3}}{_SEP}\d{{3}}{_SEP}\d{{3}}\b"  # mobile_local
    r"|"
    rf"\b0\d{{1,2}}/\d{{3}}{_SEP}\d{{3}}{_SEP}\d{{3}}\b"  # landline_local
)


def _detect_telefon(text: str) -> list[Candidate]:
    return [
        Candidate(type="TELEFON", surface=m.group(0), start=m.start(), end=m.end(), auto=True)
        for m in _TELEFON_RE.finditer(text)
    ]

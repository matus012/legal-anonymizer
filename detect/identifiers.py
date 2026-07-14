"""v1 detection engine, layer 1 (context.md §4.1, §6): the five checksum/format-bearing
identifier types. Text-in, spans-out. No file I/O, no docx/pdf, no ground truth.

Every checksum here is reimplemented from the spec independently of corpus/pii/* (the
dev-only fixture generator) so the generator and the detector can never silently agree
while both are wrong.

Checksum-invalid but shape-valid identifiers are still PII: they are always returned as
a Candidate, routed to the review bucket (auto=False), never dropped.

DIC and IC_DPH have no documented checksum (context.md §4.1: "10 digits" / "SK + DIČ"
only). For those two, shape validity is the only gate: shape valid -> auto=True always.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    type: str
    surface: str
    start: int
    end: int
    auto: bool


# --------------------------------------------------------------------------- RODNE_CISLO
_RC_RE = re.compile(r"\b(\d{6})(/?)(\d{4})\b")


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


def _detect_rc(text: str) -> list[Candidate]:
    out = []
    for m in _RC_RE.finditer(text):
        digits = m.group(1) + m.group(3)
        if not _rc_shape_ok(digits):
            continue
        out.append(
            Candidate(
                type="RODNE_CISLO",
                surface=m.group(0),
                start=m.start(),
                end=m.end(),
                auto=_rc_checksum_ok(digits),
            )
        )
    return out


# --------------------------------------------------------------------------- ICO
_ICO_RE = re.compile(r"\b\d{8}\b")
_ICO_WEIGHTS = (8, 7, 6, 5, 4, 3, 2)


def _ico_checksum_ok(digits: str) -> bool:
    s = sum(int(c) * w for c, w in zip(digits[:7], _ICO_WEIGHTS))
    mod = s % 11
    check = 1 if mod == 0 else (0 if mod == 1 else 11 - mod)
    return check == int(digits[7])


def _detect_ico(text: str) -> list[Candidate]:
    out = []
    for m in _ICO_RE.finditer(text):
        digits = m.group(0)
        out.append(
            Candidate(
                type="ICO",
                surface=digits,
                start=m.start(),
                end=m.end(),
                auto=_ico_checksum_ok(digits),
            )
        )
    return out


# --------------------------------------------------------------------------- IC_DPH / DIC
# IC_DPH ("SK" + 10 digits) is matched first; \b before the digit run of a bare 10-digit
# number requires a non-word char, and "K" (in "SK") is a word char, so the bare-DIC
# pattern below can never re-claim the same digits an IC_DPH match already consumed.
# This is the documented precedence: IC_DPH wins, bare DIC never double-claims its digits.
_IC_DPH_RE = re.compile(r"\bSK(\d{10})\b")
_DIC_RE = re.compile(r"\b\d{10}\b")


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
_IBAN_RE = re.compile(r"\bSK\d{2}(?: ?\d{4}){5}\b")
_LEGACY_RE = re.compile(r"\b(?:(\d{1,6})-)?(\d{2,10})/(\d{4})\b")

_PREFIX_WEIGHTS = (10, 5, 8, 4, 2, 1)
_BASE_WEIGHTS = (6, 3, 7, 9, 10, 5, 8, 4, 2, 1)


def _iban_mod97_ok(compact: str) -> bool:
    s = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in s)  # A-Z -> 10-35
    return int(digits) % 97 == 1


def _weighted_mod11_ok(number: str, weights: tuple[int, ...]) -> bool:
    tail = number[-len(weights):]
    s = sum(int(c) * w for c, w in zip(reversed(tail), reversed(weights)))
    return s % 11 == 0


def _detect_iban(text: str) -> list[Candidate]:
    out = []
    for m in _IBAN_RE.finditer(text):
        compact = m.group(0).replace(" ", "")
        out.append(
            Candidate(
                type="IBAN",
                surface=m.group(0),
                start=m.start(),
                end=m.end(),
                auto=_iban_mod97_ok(compact),
            )
        )
    for m in _LEGACY_RE.finditer(text):
        prefix, base, _bank = m.group(1), m.group(2), m.group(3)
        if len(base) != 10:
            continue
        if prefix is not None and not _weighted_mod11_ok(prefix, _PREFIX_WEIGHTS):
            valid = False
        else:
            valid = _weighted_mod11_ok(base, _BASE_WEIGHTS)
        out.append(
            Candidate(
                type="IBAN",
                surface=m.group(0),
                start=m.start(),
                end=m.end(),
                auto=valid,
            )
        )
    return out


# --------------------------------------------------------------- FLAG-SURVIVAL PRECEDENCE RULE
# A shape-valid span can be claimed by more than one detector (e.g. a slashless RČ is
# also a bare 10-digit DIC). If any detector on that exact span calls it a checksum
# failure (auto=False), that verdict wins outright: every auto=True candidate on the
# same (start, end) is dropped. A span some detector believes fails its checksum must
# reach the review bucket — losing an auto-redaction there costs the reviewer one tick;
# auto-redacting it is the §4.1 flag-survival bug the checksum requirement exists to
# prevent. Partial overlaps (different spans) are untouched by this rule.
def _resolve_flag_survival(candidates: list[Candidate]) -> list[Candidate]:
    by_span: dict[tuple[int, int], list[Candidate]] = {}
    for c in candidates:
        by_span.setdefault((c.start, c.end), []).append(c)
    out = []
    for group in by_span.values():
        if any(not c.auto for c in group) and any(c.auto for c in group):
            out.extend(c for c in group if not c.auto)
        else:
            out.extend(group)
    return out


# --------------------------------------------------------------------------- TYPE PRECEDENCE
# If flag-survival resolution still leaves more than one candidate on the same exact
# span (both agreed auto=True, or both agreed auto=False), pick one by type: most
# specific shape/checksum first. DIC is last because it is pure shape (\b\d{10}\b)
# with no checksum -- the weakest claim on a span, so it always yields. A genuine DIC
# that coincidentally looks like an RC gets labelled RODNE_CISLO; it is still redacted,
# only the report label differs. Recall over precision (context.md §6).
_TYPE_PRECEDENCE = ("RODNE_CISLO", "IBAN", "IC_DPH", "ICO", "DIC")
_TYPE_RANK = {t: i for i, t in enumerate(_TYPE_PRECEDENCE)}


def _resolve_type_precedence(candidates: list[Candidate]) -> list[Candidate]:
    by_span: dict[tuple[int, int], list[Candidate]] = {}
    for c in candidates:
        by_span.setdefault((c.start, c.end), []).append(c)
    out = []
    for group in by_span.values():
        out.append(min(group, key=lambda c: _TYPE_RANK[c.type]))
    return out


def detect(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    candidates.extend(_detect_rc(text))
    candidates.extend(_detect_ico(text))
    candidates.extend(_detect_ic_dph(text))
    candidates.extend(_detect_dic(text))
    candidates.extend(_detect_iban(text))
    candidates = _resolve_flag_survival(candidates)
    candidates = _resolve_type_precedence(candidates)
    candidates.sort(key=lambda c: (c.start, c.end))
    spans = [(c.start, c.end) for c in candidates]
    assert len(spans) == len(set(spans)), "duplicate candidates on identical span"
    return candidates

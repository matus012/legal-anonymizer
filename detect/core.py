"""v1 detection engine core (context.md §4.1, §6): the shared Candidate type and the
detect() dispatcher over all layer-1 detector modules. Text-in, spans-out. No file I/O,
no docx/pdf, no ground truth, no import of corpus/ or eval/.

Candidate is defined before any detector module is imported, so detector modules can
``from detect.core import Candidate`` without a circular import.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    type: str
    surface: str
    start: int
    end: int
    auto: bool


# Detector imports come AFTER Candidate so that detector modules importing Candidate
# from this partially-initialized module always find it already defined.
from .datetime_amounts import detect_datetime_amounts  # noqa: E402
from .known_entities import detect_known_entities  # noqa: E402
from .registry_refs import detect_registry  # noqa: E402
from .identifiers import (  # noqa: E402
    _detect_bankovy_ucet,
    _detect_dic,
    _detect_email,
    _detect_ic_dph,
    _detect_ico,
    _detect_iban,
    _detect_rc,
    _detect_telefon,
    _detect_url,
)


# --------------------------------------------------------------- FLAG-SURVIVAL PRECEDENCE RULE
# A shape-valid span can be claimed by more than one detector. When that happens and any
# detector on that EXACT span calls it a checksum failure (auto=False), that verdict wins
# outright: every auto=True candidate on the same (start, end) is dropped. A span some
# detector believes fails its checksum must reach the review bucket — losing an
# auto-redaction there costs the reviewer one tick; auto-redacting it is the §4.1
# flag-survival bug the checksum requirement exists to prevent. The rule is stated for
# any such pairing rather than for one worked example: the shape-only types (DIC, IC_DPH)
# never produce auto=False, so a disagreement can only come from a checksum-bearing
# detector, and its auto=False must survive. Partial overlaps (different spans) are
# untouched by this rule — those are handled by containment suppression below.
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
# with no checksum -- the weakest claim on a span, so it always yields. RC no longer
# competes for a bare 10-digit run at all: a rodné číslo is always written with a slash
# (6/4), so _RC_RE requires one and a slashless run is owned by DIC directly, with no
# RODNE_CISLO candidate on that span. Recall over precision (context.md §6).
_TYPE_PRECEDENCE = ("RODNE_CISLO", "IBAN", "BANKOVY_UCET", "IC_DPH", "ICO", "DIC", "MENO")
_TYPE_RANK = {t: i for i, t in enumerate(_TYPE_PRECEDENCE)}


def _resolve_type_precedence(candidates: list[Candidate]) -> list[Candidate]:
    by_span: dict[tuple[int, int], list[Candidate]] = {}
    for c in candidates:
        by_span.setdefault((c.start, c.end), []).append(c)
    out = []
    for group in by_span.values():
        out.append(min(group, key=lambda c: _TYPE_RANK[c.type]))
    return out


# ------------------------------------------------------------------ CONTAINMENT SUPPRESSION
# A BANKOVY_UCET surface (prefix-base/bankcode) always carries a 10-digit base as a
# strict sub-span, and that base independently matches the bare-DIC shape (and can
# match the slashless-RC shape). Those are DIFFERENT (start, end) spans, so neither
# flag-survival nor type precedence (both exact-span) ever sees the collision — without
# this step detect() would double-emit the full account AND an inner DIC/RC. The full
# account claims everything strictly inside it; equal spans are left to the exact-span
# precedence stages.
def _suppress_identifiers_inside_bankovy_ucet(
    candidates: list[Candidate],
) -> list[Candidate]:
    account_spans = [
        (c.start, c.end) for c in candidates if c.type == "BANKOVY_UCET"
    ]
    return [
        c
        for c in candidates
        if c.type == "BANKOVY_UCET"
        or not any(
            s <= c.start and c.end <= e and (c.start, c.end) != (s, e)
            for s, e in account_spans
        )
    ]


def _suppress_urls_inside_emails(candidates: list[Candidate]) -> list[Candidate]:
    email_spans = [(c.start, c.end) for c in candidates if c.type == "EMAIL"]
    return [
        c
        for c in candidates
        if not (
            c.type == "URL"
            and any(c.start >= es and c.end <= ee for es, ee in email_spans)
        )
    ]


def detect(text: str, known_entities: list[str] | None = None) -> list[Candidate]:
    if known_entities is None:
        known_entities = []
    candidates: list[Candidate] = []
    candidates.extend(_detect_rc(text))
    candidates.extend(_detect_ico(text))
    candidates.extend(_detect_ic_dph(text))
    candidates.extend(_detect_dic(text))
    candidates.extend(_detect_iban(text))
    candidates.extend(_detect_bankovy_ucet(text))
    candidates.extend(detect_known_entities(text, known_entities))
    candidates = _suppress_identifiers_inside_bankovy_ucet(candidates)
    candidates = _resolve_flag_survival(candidates)
    candidates = _resolve_type_precedence(candidates)
    candidates.extend(_detect_email(text))
    candidates.extend(_detect_url(text))
    candidates.extend(_detect_telefon(text))
    candidates.extend(detect_datetime_amounts(text))
    candidates.extend(detect_registry(text))
    candidates = _suppress_urls_inside_emails(candidates)
    candidates.sort(key=lambda c: (c.start, c.end))
    spans = [(c.start, c.end) for c in candidates]
    assert len(spans) == len(set(spans)), "duplicate candidates on identical span"
    return candidates

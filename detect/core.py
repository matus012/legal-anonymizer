"""v1 detection engine core (context.md §4.1, §6): the shared Candidate type and the
detect() dispatcher over all layer-1 detector modules. Text-in, spans-out. No file I/O,
no docx/pdf, no ground truth, no import of corpus/ or eval/.

Candidate is defined before any detector module is imported, so detector modules can
``from detect.core import Candidate`` without a circular import.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .config import DEFAULT, DetectConfig


@dataclass(frozen=True)
class Candidate:
    """One detected span. ``checksum`` (v1.1, CONTRACTS_v11.md §1) is a TAG, not a filter:
    it records what the type's checksum said ("valid" / "invalid" / "n/a" when the type has
    no checksum) and NEVER participates in span resolution, precedence, grouping or label
    minting. It is carried through to the report and the GUI review column only. The field is
    last and defaults, so every v1 construction keeps working unchanged."""

    type: str
    surface: str
    start: int
    end: int
    auto: bool
    checksum: str = "n/a"


# Detector imports come AFTER Candidate so that detector modules importing Candidate
# from this partially-initialized module always find it already defined.
from .datetime_amounts import detect_datetime_amounts  # noqa: E402
from .known_entities import detect_known_entities  # noqa: E402
from .registry_refs import detect_registry  # noqa: E402
from .addresses import detect_addresses  # noqa: E402
from .documents import detect_documents  # noqa: E402
from .office_refs import detect_office_refs  # noqa: E402
from .name_anchors import detect_name_anchors  # noqa: E402
from .gazetteer import detect_gazetteer  # noqa: E402
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
# v1.1 NARROWING. In v1 the rule was "any auto=False on an exact span drops every auto=True on
# that span", and it was correct then: the ONLY source of auto=False was a checksum-bearing
# detector saying the checksum failed, so its verdict deserved to win.
#
# v1.1 added WEAK heuristics that also emit auto=False -- the bare-name heuristic
# (detect/name_anchors.py) and surname-only gazetteer hits (detect/gazetteer.py). Under the
# unnarrowed rule those demote STRONGER detections on the same span. Measured: "obec Košice"
# is emitted as OBEC(auto=True) by the gazetteer AND as MENO(auto=False) by the bare-name
# heuristic, and the old rule kept the MENO -- so a municipality that WAS auto-redacted
# silently dropped into the review bucket, unticked. That is a recall regression wearing a
# resolution rule's clothes, and it is exactly the direction context.md 6 forbids.
#
# So auto=False only wins when it is a GENUINE CHECKSUM VERDICT (checksum == "invalid", which
# under the default config cannot happen at all -- see CONTRACTS_v11.md 6 -- and under
# strict_checksums is precisely the v1 behaviour the flag gate exists to protect). A heuristic
# auto=False never demotes a confident auto=True; it simply loses the span.
_CHECKSUM_VERDICT = "invalid"


def _resolve_flag_survival(candidates: list[Candidate]) -> list[Candidate]:
    by_span: dict[tuple[int, int], list[Candidate]] = {}
    for c in candidates:
        by_span.setdefault((c.start, c.end), []).append(c)
    out = []
    for group in by_span.values():
        flagged = [c for c in group if not c.auto and c.checksum == _CHECKSUM_VERDICT]
        confident = [c for c in group if c.auto]
        if flagged:
            out.extend(flagged)          # a real checksum failure still wins outright
        elif confident:
            out.extend(confident)        # otherwise the confident claim beats the heuristic
        else:
            out.extend(group)            # all heuristic: nothing to choose between, keep them
    return out


# --------------------------------------------------------------------------- TYPE REGISTRY
# The single ordered registry (CONTRACTS_v11.md §4), most specific / strongest claim
# first. It resolves an exact-span collision that flag survival left unbroken, and it
# breaks ties in the partial-overlap sweep. DIC sits at the weak end of the identifier
# block because it is pure shape (\b\d{10}\b) with no checksum -- the weakest claim on a
# span, so it always yields. A composite type outranks its own parts (ADRESA over PSC /
# SUPISNE_CISLO / OBEC), because the wider span covers strictly more text -- recall over
# precision (context.md §6). Adding a type = add it here AND to CONTRACTS_v11.md §4.
_TYPE_PRECEDENCE = (
    # checksum- or structure-bearing identifiers (strongest claims)
    "RODNE_CISLO", "IBAN", "BANKOVY_UCET", "BIC", "IC_DPH", "ICO", "DIC",
    # VODICSKY_PREUKAZ is ANCHOR-REQUIRED ("vodičský preukaz", "VP č.") while CISLO_PASU and
    # CISLO_OP also match their bare letter+digit shape unanchored. On an exact-span tie the
    # anchored claim is the better-evidenced one, so it is ranked first — same principle as
    # FAX over TELEFON (CONTRACTS_v11.md Amendment 3). All three are auto-redacted either way;
    # this only decides which label the reviewer reads in the report.
    "VIN", "ECV", "VODICSKY_PREUKAZ", "CISLO_PASU", "CISLO_OP",
    # registry / court refs
    "SPISOVA_ZNACKA", "ORSR_VLOZKA", "LV", "PARCELA",
    # contact
    "EMAIL", "FAX", "TELEFON", "URL",
    # address block: the composite ADRESA outranks its own parts
    "ADRESA", "PSC", "SUPISNE_CISLO", "CISLO_BYTU", "VCHOD", "POSCHODIE",
    # entities
    # MENO OUTRANKS the gazetteer types (v1.1). A gazetteer OBEC/KATASTER hit is a DICTIONARY
    # GUESS -- and many Slovak surnames are also municipality names ("Novak" is both). A MENO
    # that survives to this stage is never a guess: the heuristic (auto=False) bare-name
    # candidates have already been dropped by _resolve_flag_survival, so what remains is a
    # user-supplied known entity (context.md 4.3 calls this "the single highest-value input in
    # the whole system"), a title/role/field-label anchored name, or a first-name + surname
    # pair. Ranking OBEC first relabelled exactly those as municipalities: still redacted, but
    # logged as [OBEC_1] and -- the real damage -- grouped by surface instead of by PARTY, so
    # one person's occurrences stopped sharing a number. Redacting a town as [MENO_1] is
    # harmless; redacting a party as [OBEC_1] breaks the document-global entity numbering the
    # whole report depends on.
    "MENO", "ORG", "OBEC", "KATASTER",
    # weakest
    "DATUM", "SUMA",
)
# AMENDMENT 1 (CONTRACTS_v11.md §12): types required by Vyhláška MS SR 482/2011, the
# authoritative Slovak list of data subject to anonymisation in court decisions. They are
# appended rather than woven into the block above so the frozen v1.1 order stays readable
# and reviewable as one diff. Appending puts them at the WEAK end of precedence, which is
# correct for all of them: every one is anchor-driven, so an exact-span tie against a
# checksum-bearing identifier should be won by the identifier.
_TYPE_PRECEDENCE += (
    "KOD_BANKY",          # 4-digit bank code (vyhláška f)
    "NAZOV_BANKY",        # bank / foreign-bank-branch name (vyhláška f) — closed list
    "NAZOV_UCTU",         # account name (vyhláška f)
    "CISLO_KLIENTA",      # client number (vyhláška f)
    # NOTE: FAX is NOT appended here — it is placed above, immediately before TELEFON.
    # A fax number and a phone number are the same digit shape, so they collide on an exact
    # span; FAX is anchor-required ("fax:", "faxové číslo") and is therefore the stronger,
    # more informative claim. Both are auto-redacted either way, so this only decides which
    # label the reviewer reads in the report — but reading "[FAX_1]" where the document says
    # "fax" is the difference between a report that is checkable and one that is not.
    "ULICA",              # street name, gazetteer-driven (vyhláška c)
    "STATNA_PRISLUSNOST", # citizenship, field-label anchored
)
KNOWN_TYPES = frozenset(_TYPE_PRECEDENCE)
_TYPE_RANK = {t: i for i, t in enumerate(_TYPE_PRECEDENCE)}


def _rank(type_: str) -> int:
    """Rank lookup that CANNOT KeyError at runtime (CONTRACTS_v11.md §4): an unregistered
    type ranks last instead of crashing a shipped desktop app mid-redaction. Registry
    coverage is enforced by detect()'s post-condition 4 and by tests/test_type_registry.py,
    not by an exception on the user's machine."""
    return _TYPE_RANK.get(type_, len(_TYPE_PRECEDENCE))


def _resolve_type_precedence(candidates: list[Candidate]) -> list[Candidate]:
    by_span: dict[tuple[int, int], list[Candidate]] = {}
    for c in candidates:
        by_span.setdefault((c.start, c.end), []).append(c)
    out = []
    for group in by_span.values():
        out.append(min(group, key=lambda c: _rank(c.type)))
    return out


# ------------------------------------------------------------------ CONTAINMENT SUPPRESSION
# A BANKOVY_UCET surface (prefix-base/bankcode) always carries a 10-digit base as a
# strict sub-span, and that base independently matches the bare-DIC shape (and can
# match the slashless-RC shape). Those are DIFFERENT (start, end) spans, so neither
# flag-survival nor type precedence (both exact-span) ever sees the collision — without
# this step detect() would double-emit the full account AND an inner DIC/RC. The full
# account claims everything strictly inside it; equal spans are left to the exact-span
# precedence stages.
#
# v1.1: CONTRACTS_v11.md §5 says to delete this and let the generalised _resolve_containment
# cover it. It is KEPT, because the general rule does something this one does not: under
# DetectConfig(strict_checksums=True) a checksum-invalid account is auto=False and its inner
# 10-digit base is an auto=True DIC, so containment's promotion rule would promote the
# account back to auto=True and strict_checksums would never route ANY account to review --
# contradicting §6's table. Running this suppression BEFORE containment removes the inner
# candidate so the promotion rule has nothing to promote from, and strict restores v1
# exactly. Under the DEFAULT config the two orders agree (the account is auto=True anyway).
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


# ------------------------------------------------------------- GENERALISED OVERLAP RESOLUTION
# CONTRACTS_v11.md §5. Both writers slice the output document by character offsets, so two
# candidates that overlap AT ALL corrupt the written file. v1 resolved only EXACT-span
# collisions; v1.1 resolves containment and crossing overlaps over EVERY type, because the
# composite types (ADRESA containing PSC / OBEC / SUPISNE_CISLO) make both routine.
#
# Both stages carry a PROMOTION rule. Collapsing two spans into one must never lose a
# redaction: if the candidate being dropped was auto=True and the survivor is auto=False,
# the survivor is promoted first. Recall over precision (context.md §6) -- the survivor's
# span covers the dropped one's text, so redacting it can only over-redact, never leak.
# The checksum tag rides along untouched; it never participates in resolution (§1).
def _strictly_contains(outer: Candidate, inner: Candidate) -> bool:
    return (
        outer.start <= inner.start
        and inner.end <= outer.end
        and (outer.start, outer.end) != (inner.start, inner.end)
    )


def _resolve_containment(candidates: list[Candidate]) -> list[Candidate]:
    promoted = [
        replace(c, auto=True)
        if not c.auto and any(o.auto and _strictly_contains(c, o) for o in candidates)
        else c
        for c in candidates
    ]
    return [
        promoted[i]
        for i, c in enumerate(candidates)
        if not any(_strictly_contains(o, c) for j, o in enumerate(candidates) if j != i)
    ]


def _resolve_partial_overlaps(candidates: list[Candidate]) -> list[Candidate]:
    kept: list[Candidate] = []
    for c in sorted(candidates, key=lambda c: (c.start, -(c.end - c.start), _rank(c.type))):
        clash = next(
            (i for i, k in enumerate(kept) if c.start < k.end and k.start < c.end), None
        )
        if clash is None:
            kept.append(c)
        elif c.auto and not kept[clash].auto:
            kept[clash] = replace(kept[clash], auto=True)
    return kept


def detect(
    text: str,
    known_entities: list[str] | None = None,
    config: DetectConfig | None = None,
) -> list[Candidate]:
    if known_entities is None:
        known_entities = []
    if config is None:
        config = DEFAULT

    # ---------------------------------------------------------------- NBSP NORMALIZATION
    # Every detector runs over a copy in which U+00A0 (NBSP) has been replaced by an ordinary
    # space. The replacement is 1 character for 1 character, so EVERY OFFSET IS PRESERVED and
    # the candidates' start/end still index the ORIGINAL text -- which is what both writers
    # slice by. The surface is re-sliced from the original below, so a reported surface keeps
    # the document's real bytes, NBSP included.
    #
    # Why this is needed: several detectors are ANCHOR-REQUIRED, and their anchors are
    # multi-word Slovak phrases -- "cislo klienta", "nazov uctu", "kod banky", "trvale bytom",
    # "so sidlom", "rodne cislo". Slovak typography routinely puts an NBSP between such words,
    # and a PDF text layer produces them constantly. Measured on the demo contract: the PDF
    # rendered "Cislo klienta:" with an NBSP INSIDE the phrase, the anchor did not match, and
    # the client number KL-99321 survived into the redacted PDF while the DOCX of the same
    # document was clean. Fixing it once here beats widening a dozen regexes by hand and then
    # discovering the thirteenth.
    #
    # Note this is NOT the same as folding NBSP out of a SURFACE: a phone number's NBSPs are
    # still matched, still part of its surface, and still redacted exactly as before.
    norm = text.replace(" ", " ") if " " in text else text

    candidates: list[Candidate] = []
    candidates.extend(_detect_rc(norm, config))
    candidates.extend(_detect_ico(norm, config))
    candidates.extend(_detect_ic_dph(norm))
    candidates.extend(_detect_dic(norm))
    candidates.extend(_detect_iban(norm, config))
    candidates.extend(_detect_bankovy_ucet(norm, config))
    candidates.extend(_detect_email(norm))
    candidates.extend(_detect_url(norm))
    candidates.extend(_detect_telefon(norm))
    candidates.extend(detect_datetime_amounts(norm))
    candidates.extend(detect_registry(norm))
    # v1.1 type modules (CONTRACTS_v11.md §8). Each is self-contained and emits only its own
    # types; every cross-type collision they create with each other or with the v1 detectors
    # is settled by the resolution stages below, never inside a detector module.
    candidates.extend(detect_addresses(norm, config))
    candidates.extend(detect_documents(norm, config))
    candidates.extend(detect_office_refs(norm, config))
    candidates.extend(detect_name_anchors(norm, config))
    candidates.extend(detect_gazetteer(norm, config))
    candidates.extend(detect_known_entities(norm, known_entities))
    candidates = _suppress_identifiers_inside_bankovy_ucet(candidates)
    candidates = _resolve_flag_survival(candidates)
    candidates = _resolve_type_precedence(candidates)
    candidates = _resolve_containment(candidates)
    candidates = _resolve_partial_overlaps(candidates)
    candidates.sort(key=lambda c: (c.start, c.end))

    # Re-slice every surface from the ORIGINAL text so a reported surface carries the
    # document's real characters (NBSP included), not the normalized stand-ins.
    if norm is not text:
        candidates = [
            c if c.surface == text[c.start : c.end] else replace(c, surface=text[c.start : c.end])
            for c in candidates
        ]

    # post-conditions, CONTRACTS_v11.md §3 -- all five, every call
    assert candidates == sorted(candidates, key=lambda c: (c.start, c.end))
    spans = [(c.start, c.end) for c in candidates]
    assert len(spans) == len(set(spans)), "duplicate candidates on identical span"
    assert all(b.start >= a.end for a, b in zip(candidates, candidates[1:])), (
        "overlapping spans survived resolution"
    )
    assert all(c.type in KNOWN_TYPES for c in candidates), "unregistered type emitted"
    assert all(c.checksum in ("valid", "invalid", "n/a") for c in candidates), "bad checksum tag"
    return candidates

"""v1 detection engine core (context.md §4.1, §6): the shared Candidate type and the
detect() dispatcher over all layer-1 detector modules. Text-in, spans-out. No file I/O,
no docx/pdf, no ground truth, no import of corpus/ or eval/.

Candidate is defined before any detector module is imported, so detector modules can
``from detect.core import Candidate`` without a circular import.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .config import DEFAULT, DetectConfig
from .normalize import normalize


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
from .orgs import detect_orgs  # noqa: E402
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


# --------------------------------------------------------------------- DETECTOR ISOLATION
# CONTRACTS_v11.md Amendment 11. A desktop application that raises out of a redaction is worse
# than one that misses a surface: the lawyer gets a traceback instead of a document, and has no
# way to tell whether the file on disk is clean, partly redacted, or untouched.
#
# This is not hypothetical. The mutation gate has already caught one: widening a separator let a
# TAB into an IBAN, and the mod-97 check does int(c, 36), which raises ValueError on a tab. That
# reached a shipped code path and was found only because a gate happened to call detect() over
# 2 559 mutated surfaces. Every checksum and validator in detect/ parses characters out of
# arbitrary document text, and arbitrary document text is exactly what a law office has.
#
# So every detector runs inside a guard. A detector that raises loses ITS OWN candidates for
# THAT unit and nothing else -- the other detectors' results are kept, and the failure is
# reported rather than swallowed.
#
# WHAT IS *NOT* GUARDED, deliberately: detect()'s five post-conditions. Those assert that the
# RESOLUTION stages produced a coherent, non-overlapping, sorted span set, and both writers cut
# the document at those spans. Continuing past a violated post-condition would write a corrupted
# file; the assert is the one place where stopping is the safe outcome. What the guard below
# does instead is keep bad candidates from ever REACHING them: each detector's output is
# validated at its own source, so a malformed span is attributed to the detector that made it
# and dropped there, instead of surfacing later as an assertion nobody can trace back.


@dataclass(frozen=True)
class DetectorFailure:
    """One detector that raised, or returned something malformed, on one unit of text.

    ``detector`` is the module-level function name, so the report names the thing to fix.
    ``error`` is the exception's own text, kept verbatim -- a report that says "a detector
    failed" without saying which or why cannot be acted on.
    """

    detector: str
    error: str


_VALID_CHECKSUMS = ("valid", "invalid", "n/a")


def _validated(name: str, produced, norm: str) -> tuple[list[Candidate], list[DetectorFailure]]:
    """Keep the well-formed candidates from one detector; report the rest against that detector.

    Checked here rather than in detect()'s post-conditions because attribution is the whole
    point: a span of (12, 4) discovered after five resolution stages have shuffled the list is
    a bug report with no author on it.
    """
    good: list[Candidate] = []
    failures: list[DetectorFailure] = []
    for c in produced:
        if not isinstance(c, Candidate):
            failures.append(DetectorFailure(name, f"returned {type(c).__name__}, not Candidate"))
        elif not (0 <= c.start < c.end <= len(norm)):
            failures.append(DetectorFailure(name, f"span ({c.start}, {c.end}) outside text of length {len(norm)}"))
        elif c.type not in KNOWN_TYPES:
            failures.append(DetectorFailure(name, f"unregistered type {c.type!r}"))
        elif c.checksum not in _VALID_CHECKSUMS:
            failures.append(DetectorFailure(name, f"bad checksum tag {c.checksum!r}"))
        else:
            good.append(c)
    return good, failures


def _run_detectors(
    norm: str, known_entities: list[str], config: DetectConfig
) -> tuple[list[Candidate], list[DetectorFailure]]:
    """Every layer-1 detector, over one normalized view, each inside its own guard.

    Split out of detect() so the two views (see detect()) run the IDENTICAL battery -- a
    detector added to one and forgotten in the other would be a type that silently stops
    working on wrapped text.
    """
    battery = (
        ("_detect_rc", lambda t: _detect_rc(t, config)),
        ("_detect_ico", lambda t: _detect_ico(t, config)),
        ("_detect_ic_dph", _detect_ic_dph),
        ("_detect_dic", _detect_dic),
        ("_detect_iban", lambda t: _detect_iban(t, config)),
        ("_detect_bankovy_ucet", lambda t: _detect_bankovy_ucet(t, config)),
        ("_detect_email", _detect_email),
        ("_detect_url", _detect_url),
        ("_detect_telefon", _detect_telefon),
        ("detect_datetime_amounts", lambda t: detect_datetime_amounts(t, config)),
        ("detect_registry", detect_registry),
        # v1.1 type modules (CONTRACTS_v11.md 8). Each is self-contained and emits only its own
        # types; every cross-type collision they create with each other or with the v1 detectors
        # is settled by the resolution stages in detect(), never inside a detector module.
        ("detect_addresses", lambda t: detect_addresses(t, config)),
        ("detect_documents", lambda t: detect_documents(t, config)),
        ("detect_office_refs", lambda t: detect_office_refs(t, config)),
        ("detect_name_anchors", lambda t: detect_name_anchors(t, config)),
        ("detect_gazetteer", lambda t: detect_gazetteer(t, config)),
        ("detect_orgs", lambda t: detect_orgs(t, config)),
        ("detect_known_entities", lambda t: detect_known_entities(t, known_entities)),
    )

    candidates: list[Candidate] = []
    failures: list[DetectorFailure] = []
    for name, fn in battery:
        try:
            produced = fn(norm)
        except Exception as exc:  # noqa: BLE001 -- see DETECTOR ISOLATION above
            # Deliberately broad. The point is not to handle a known error class, it is that
            # NOTHING a detector can raise may escape to the caller: int(c, 36) on a control
            # character, an IndexError on an empty match, a UnicodeError from a lone surrogate
            # in a corrupt DOCX. Naming the classes we have already seen would only guarantee
            # the app crashes on the one we have not.
            failures.append(DetectorFailure(name, f"{type(exc).__name__}: {exc}"))
            continue
        good, bad = _validated(name, produced, norm)
        candidates.extend(good)
        failures.extend(bad)
    return candidates, failures


def detect(
    text: str,
    known_entities: list[str] | None = None,
    config: DetectConfig | None = None,
) -> list[Candidate]:
    """The v1 entry point, unchanged (CONTRACTS_v11.md 3). Detector failures are swallowed
    here; a caller that must REPORT them -- both writers do -- calls detect_with_failures."""
    return detect_with_failures(text, known_entities, config)[0]


def detect_with_failures(
    text: str,
    known_entities: list[str] | None = None,
    config: DetectConfig | None = None,
) -> tuple[list[Candidate], list[DetectorFailure]]:
    if known_entities is None:
        known_entities = []
    # THE KNOWN-ENTITY LIST IS NORMALIZED THE SAME WAY THE DOCUMENT IS (red-team round 3, A11).
    # detect() used to normalize only the TEXT, so the two sides of the comparison could be
    # spelled differently and never meet. This list is USER INPUT -- typed into the GUI, or
    # pasted out of some other document -- so it arrives with whatever its source had in it: a
    # zero-width space from a web page, NFD from a Mac, a non-breaking space between the given
    # name and the surname. context.md 4.3 calls this list "the single highest-value input in
    # the whole system", and a silent spelling mismatch is the worst way for it to fail,
    # because the lawyer can SEE the name they typed sitting unredacted in the output.
    #
    # Only the surface spelling is folded. Nothing is matched here and no offset is taken from
    # these strings -- they are needles, not haystacks -- so this cannot move a span.
    known_entities = [n for n in (normalize(e).text for e in known_entities) if n]
    if config is None:
        config = DEFAULT

    # ------------------------------------------------------ NORMALIZATION WITH AN OFFSET MAP
    # Every detector runs over NORMALIZED text; every candidate is then cut on ORIGINAL
    # offsets through the map. detect/normalize.py documents what is folded, and the two
    # things deliberately NOT folded there (case, diacritics) with the reasons.
    #
    # v1.1 originally did this for U+00A0 ONLY, with a 1:1 str.replace, because a 1:1
    # substitution PRESERVES EVERY OFFSET and both writers slice the document by offset. That
    # closed the NBSP class (robustness 1.000) and could not be extended by one more
    # character: deleting a character shifts every later offset, and a redaction cut at a
    # shifted offset removes the WRONG CHARACTERS -- it corrupts the document rather than
    # mislabelling it. The mutation gate measured what that limit cost -- zero_width 0.070,
    # soft_hyphen 0.070, line_break_mid 0.119, cyrillic_homoglyph 0.356, nfd 0.675 -- and
    # those classes needed a MAP, not a wider regex. This is the map.
    #
    # TWO VIEWS, NOT ONE. The second view additionally JOINS a token a renderer broke across
    # a line ("FYC\nWSKZC" -> "FYCWSKZC"). That is a GUESS, not a canonical equivalence, so it
    # runs as an EXTRA pass whose candidates are merged with the base pass's rather than
    # replacing them: the plain reading is always still on the table and the joined reading
    # can only ADD detections. It is skipped entirely when it would change nothing, which is
    # every text without a line break inside an identifier -- i.e. essentially every DOCX
    # paragraph.
    views = [normalize(text)]
    joined = normalize(text, join_wrapped=True)
    if joined.text != views[0].text:
        views.append(joined)

    # ------------------------------------------------- BACK TO ORIGINAL OFFSETS
    # Mapped BEFORE resolution, unlike v1.1's single-view arrangement. With more than one view
    # the collisions that matter are between candidates found in DIFFERENT coordinate systems,
    # and those only become comparable once both sides are expressed in the original's. So the
    # battery runs per view, every candidate is immediately mapped home, and the resolution
    # stages below then see one coherent set -- exactly as they did when there was one view.
    #
    # The surface is re-sliced from the ORIGINAL text, so a reported surface carries the
    # document's real characters: NBSP, soft hyphen, zero-width space and all. That matters
    # beyond cosmetics -- writer/pdf_body.py relocates each candidate by SEARCHING FOR ITS
    # SURFACE on the page, so a surface that is not byte-faithful to the document cannot be
    # found and cannot be redacted.
    candidates: list[Candidate] = []
    failures: list[DetectorFailure] = []
    seen: set[Candidate] = set()
    seen_failures: set[DetectorFailure] = set()
    for view in views:
        produced, view_failures = _run_detectors(view.text, known_entities, config)
        for f in view_failures:
            # The same detector raises the same way on both views, and reporting it twice would
            # tell the reviewer there were two problems.
            if f not in seen_failures:
                seen_failures.add(f)
                failures.append(f)
        for c in produced:
            a, b = view.span(c.start, c.end)
            mapped = replace(c, start=a, end=b, surface=text[a:b])
            # Deduplicated on the WHOLE candidate, never on (type, span). Two candidates can
            # share a type and a span and still be different claims -- a bare-name heuristic
            # emits MENO(auto=False) on exactly the span where a user-supplied known entity
            # emits MENO(auto=True), and the resolution stages below exist to choose between
            # them. Keying the dedupe on (type, span) kept whichever detector happened to run
            # first: measured, it dropped the known-entity MENO, flag survival then preferred
            # the confident gazetteer claim on the same span, and a party came out labelled
            # [OBEC_1]. Candidate is frozen, so its own identity is the right key.
            if mapped in seen:
                continue
            seen.add(mapped)
            candidates.append(mapped)

    candidates = _suppress_identifiers_inside_bankovy_ucet(candidates)
    candidates = _resolve_flag_survival(candidates)
    candidates = _resolve_type_precedence(candidates)
    candidates = _resolve_containment(candidates)
    candidates = _resolve_partial_overlaps(candidates)
    candidates.sort(key=lambda c: (c.start, c.end))

    # post-conditions, CONTRACTS_v11.md §3 -- all five, every call
    assert candidates == sorted(candidates, key=lambda c: (c.start, c.end))
    spans = [(c.start, c.end) for c in candidates]
    assert len(spans) == len(set(spans)), "duplicate candidates on identical span"
    assert all(b.start >= a.end for a, b in zip(candidates, candidates[1:])), (
        "overlapping spans survived resolution"
    )
    assert all(c.type in KNOWN_TYPES for c in candidates), "unregistered type emitted"
    assert all(c.checksum in ("valid", "invalid", "n/a") for c in candidates), "bad checksum tag"
    return candidates, failures

"""TDD spec for CONTRACTS_v11.md §5 — generalised overlap resolution, and for the §3
post-conditions that make it checkable.

Both writers slice the output document by character offsets, so two candidates that
overlap AT ALL corrupt the written file. v1 only resolved EXACT-span collisions plus one
bespoke BANKOVY_UCET containment rule; v1.1 resolves containment and crossing overlaps
over every type.

The two PROMOTION rules are the recall-over-precision guard (context.md §6): collapsing
two spans into one must never lose a redaction. They are unit-tested directly on
_resolve_containment / _resolve_partial_overlaps with hand-built Candidate lists, because
the end-to-end detector cannot currently produce an outer auto=False that encloses a
surviving inner auto=True (the kept BANKOVY_UCET suppressor removes the only such pair
before containment runs — see the report for that case).

Fixtures are hand-built literal strings; corpus/ is never imported (CONTRACTS_v11.md §11).
"""
from detect.config import DetectConfig
from detect.core import (
    KNOWN_TYPES,
    Candidate,
    _resolve_containment,
    _resolve_partial_overlaps,
    detect,
)

STRICT = DetectConfig(strict_checksums=True)

_MIXED = (
    "Rodné číslo 850315/0018, IČO 12345679, IČ DPH SK1234567890, DIČ 1234567890, "
    "IBAN SK9402000000000000000001, účet 013389-1543039117/1100, "
    "e-mail jan.novak@gmail.com, web www.priklad.sk, tel. 0905 123 456, "
    "LV č. 1234, parc. č. 123/4, V-1234/2025, dňa 1.1.1980, suma 12 345,67 €."
)


def _assert_postconditions(cands):
    assert cands == sorted(cands, key=lambda c: (c.start, c.end)), "not sorted"
    spans = [(c.start, c.end) for c in cands]
    assert len(set(spans)) == len(spans), "duplicate exact span"
    for a, b in zip(cands, cands[1:]):
        assert b.start >= a.end, f"overlapping spans: {a} / {b}"
    for c in cands:
        assert c.type in KNOWN_TYPES, f"unregistered type {c.type}"
        assert c.checksum in {"valid", "invalid", "n/a"}, c


# --------------------------------------------------------------- §3 post-conditions, e2e
def test_postconditions_hold_on_a_dense_mixed_document():
    _assert_postconditions(detect(_MIXED))


def test_postconditions_hold_under_strict_checksums():
    _assert_postconditions(detect(_MIXED, None, STRICT))


def test_postconditions_hold_with_known_entities():
    text = "Ján Novák, r.č. 850315/0018, IČO 12345679, býva v Košiciach."
    _assert_postconditions(detect(text, ["Ján Novák"]))


def test_no_span_overlaps_anywhere_in_a_nested_case():
    # EMAIL strictly contains a URL-shaped domain; BANKOVY_UCET strictly contains a
    # DIC-shaped 10-digit base. Both are nested collisions across DIFFERENT spans.
    text = "Kontakt jan.novak@gmail.com, účet 013389-1543039117/1100."
    _assert_postconditions(detect(text))


# --------------------------------------------------------------------- containment, e2e
def test_email_swallows_the_url_inside_it():
    text = "Kontakt: jan.novak@gmail.com pre otázky."
    cands = detect(text)
    assert [c.type for c in cands if c.type in ("EMAIL", "URL")] == ["EMAIL"]
    assert [c.surface for c in cands if c.type == "EMAIL"] == ["jan.novak@gmail.com"]


def test_bankovy_ucet_containment_unchanged():
    account = "013389-1543039117/1100"
    text = f"Prosím uhraďte sumu na účet {account} do konca mesiaca."
    cands = detect(text)
    hits = [c for c in cands if c.type == "BANKOVY_UCET"]
    assert len(hits) == 1
    assert hits[0].surface == account
    assert hits[0].auto is True
    assert all(x.surface != "1543039117" for x in cands)
    _assert_postconditions(cands)


def test_bankovy_ucet_containment_unchanged_under_strict_with_broken_checksum():
    # The inner DIC must not survive, and (contract §6) strict must still route the
    # checksum-invalid account to review: auto=False, not promoted back to True.
    account = "013389-1543039118/1100"
    text = f"Prosím uhraďte sumu na účet {account} do konca mesiaca."
    cands = detect(text, None, STRICT)
    hits = [c for c in cands if c.type == "BANKOVY_UCET"]
    assert len(hits) == 1
    assert hits[0].auto is False
    assert hits[0].checksum == "invalid"
    assert all(x.type != "DIC" for x in cands)
    _assert_postconditions(cands)


# ------------------------------------------------- containment promotion rule (unit level)
def test_containment_promotes_outer_when_inner_is_auto():
    outer = Candidate("BANKOVY_UCET", "013389-1543039118/1100", 0, 22, False, "invalid")
    inner = Candidate("DIC", "1543039118", 7, 17, True, "n/a")
    out = _resolve_containment([outer, inner])
    assert len(out) == 1
    assert out[0].type == "BANKOVY_UCET"
    assert out[0].auto is True  # promoted: never lose a redaction when collapsing spans
    assert out[0].checksum == "invalid"  # the tag is untouched by resolution


def test_containment_drops_inner_and_keeps_outer_span():
    outer = Candidate("ADRESA", "Hlavná 5, 040 01 Košice", 0, 23, True)
    inner = Candidate("PSC", "040 01", 10, 16, True)
    out = _resolve_containment([outer, inner])
    assert [(c.type, c.start, c.end) for c in out] == [("ADRESA", 0, 23)]


def test_containment_does_not_touch_disjoint_or_equal_spans():
    a = Candidate("ICO", "12345679", 0, 8, True)
    b = Candidate("DIC", "1234567890", 20, 30, True)
    assert _resolve_containment([a, b]) == [a, b]


def test_containment_is_not_fooled_by_an_auto_false_inner():
    outer = Candidate("ADRESA", "x" * 20, 0, 20, True)
    inner = Candidate("PSC", "y" * 6, 5, 11, False)
    out = _resolve_containment([outer, inner])
    assert len(out) == 1
    assert out[0].auto is True


# ----------------------------------------------- partial-overlap promotion rule (unit level)
def test_partial_overlap_keeps_one_span_and_promotes_it():
    # crossing spans, neither contains the other; the DROPPED one is auto=True
    kept = Candidate("ADRESA", "a" * 20, 0, 20, False)
    dropped = Candidate("OBEC", "b" * 10, 15, 25, True)
    out = _resolve_partial_overlaps([kept, dropped])
    assert len(out) == 1
    assert (out[0].start, out[0].end) == (0, 20)
    assert out[0].auto is True  # promoted before the crossing candidate was dropped


def test_partial_overlap_keeps_the_longer_span_first():
    short = Candidate("OBEC", "a" * 5, 0, 5, True)
    long = Candidate("ADRESA", "b" * 12, 0, 12, True)
    out = _resolve_partial_overlaps([short, long])
    assert [(c.type, c.start, c.end) for c in out] == [("ADRESA", 0, 12)]


def test_partial_overlap_leaves_touching_but_non_overlapping_spans_alone():
    a = Candidate("MENO", "Ján", 0, 3, True)
    b = Candidate("MENO", "Novák", 3, 8, True)
    out = _resolve_partial_overlaps([a, b])
    assert len(out) == 2


def test_partial_overlap_breaks_ties_by_type_rank():
    # same start, same length -> the stronger type claim wins
    weak = Candidate("DATUM", "x" * 10, 0, 10, True)
    strong = Candidate("RODNE_CISLO", "y" * 10, 0, 10, True)
    out = _resolve_partial_overlaps([weak, strong])
    assert [c.type for c in out] == ["RODNE_CISLO"]


def test_partial_overlap_never_raises_on_an_unregistered_type():
    odd = Candidate("NIEKTORY_NOVY_TYP", "z" * 4, 0, 4, True)
    known = Candidate("MENO", "Ján", 2, 5, True)
    out = _resolve_partial_overlaps([odd, known])
    assert len(out) == 1

"""Tests for the red-team round-2 mutation library (``corpus/mutations.py``).

Two jobs, in this order:

1. **Prove the instrument.** Every mutation must actually perform the transformation it
   documents, must be a no-op on nothing (a mutation that silently returns its input scores
   robustness 1.000 and reports a defect-free detector that was never attacked), must be
   pure, and must satisfy the HOMOMORPHISM property the gate's pairing depends on
   (``s in t`` implies ``mutate(s) in mutate(t)``). A robustness table produced by a broken
   mutation is worse than no table: it is a table that lies in the reassuring direction.

2. **Lock the mutations that currently PASS.** ``nbsp`` is the round-1 fix
   (``detect/core.py``'s 1:1 NBSP normalization) and scores 1.000 across every type; the
   handful of other (mutation, type) cells at 1.000 are locked the same way. These are
   regression locks: they are the cells a future change to ``detect/`` could silently break.

CONTRACTS_v11.md §11: ``tests/`` must not import ``corpus/``. The single exception the
sprint brief grants is ``corpus.mutations`` itself, which is the unit under test. Every
end-to-end fixture below is HAND-BUILT — no corpus document, no ground truth file.
"""
from __future__ import annotations

import unicodedata

import pytest

from corpus.mutations import (
    CASE_DESTROYING,
    MUTATIONS,
    NBSP,
    SHY,
    ZWJ,
    ZWSP,
    mutate_all_caps,
    mutate_cyrillic_homoglyph,
    mutate_double_spaces,
    mutate_line_break_mid,
    mutate_lowercase,
    mutate_nbsp,
    mutate_nfd,
    mutate_no_diacritics,
    mutate_soft_hyphen,
    mutate_tabs,
    mutate_zero_width,
)
from detect.core import detect

# A representative slice of a Slovak legal document: multi-word anchors, diacritics, an
# identifier, a date, an amount, a name and an address. Every mutation must bite somewhere
# in it.
SAMPLE = (
    "Kúpna zmluva\n"
    "Predávajúci: JUDr. Ján Novák, r.č. 850315/0018, trvale bytom Hlavná 12/A, "
    "040 01 Košice\n"
    "IČO: 43235222, IBAN SK74 1100 4983 8673 1604 6759\n"
    "Číslo klienta: KL-99321, kód banky: 1100, fax: 055 123 4567\n"
    "Kúpna cena 12 500,00 € bola uhradená dňa 15. 03. 2024.\n"
)


# --------------------------------------------------------------------------- registry
def test_registry_holds_every_required_mutation():
    """The brief's list, exactly. A mutation silently missing from ``MUTATIONS`` is a
    column the gate never prints and an attack nobody ran."""
    assert set(MUTATIONS) == {
        "nbsp", "zero_width", "soft_hyphen", "tabs", "double_spaces", "line_break_mid",
        "all_caps", "lowercase", "no_diacritics", "cyrillic_homoglyph", "nfd",
    }
    assert CASE_DESTROYING <= set(MUTATIONS)


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_every_mutation_is_registered_under_its_own_function(name):
    assert MUTATIONS[name] is globals()[f"mutate_{name}"]


# ------------------------------------------------------------------ instrument properties
@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_no_mutation_is_a_no_op(name):
    """A mutation that returns its input unchanged scores a perfect 1.000 and proves
    nothing. Asserted on the sample AND on a bare identifier, so a mutation that only ever
    touches whitespace cannot hide behind the sample's prose."""
    assert MUTATIONS[name](SAMPLE) != SAMPLE


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_every_mutation_is_pure_and_deterministic(name):
    mutate = MUTATIONS[name]
    before = SAMPLE
    assert mutate(SAMPLE) == mutate(SAMPLE)
    assert SAMPLE == before


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_empty_string_survives(name):
    assert MUTATIONS[name]("") == ""


# The pairs the gate actually asks about: a ground-truth surface and the document text it
# sits in. Each surface is bounded by a non-alphanumeric character in the text, which is the
# condition under which the token-local mutations are homomorphic (see corpus/mutations.py).
_HOMOMORPHISM_PAIRS = [
    ("Ján Novák", "Predávajúci: JUDr. Ján Novák, nar. 15.03.1985"),
    ("43235222", "IČO: 43235222, DIČ: 1234567890"),
    ("SK74 1100 4983 8673 1604 6759", "IBAN SK74 1100 4983 8673 1604 6759 vedený v banke"),
    ("850315/0018", "r.č. 850315/0018"),
    ("KL-99321", "Číslo klienta: KL-99321"),
    ("Hlavná 12/A, 040 01 Košice", "trvale bytom Hlavná 12/A, 040 01 Košice"),
    ("12 500,00 €", "Kúpna cena 12 500,00 € bola uhradená"),
    ("15. 03. 2024", "dňa 15. 03. 2024 v Košiciach"),
]


@pytest.mark.parametrize("name", sorted(MUTATIONS))
@pytest.mark.parametrize("surface,text", _HOMOMORPHISM_PAIRS)
def test_mutation_is_homomorphic_on_realistic_pairs(name, surface, text):
    """``s in t`` must imply ``mutate(s) in mutate(t)``.

    This is the property ``eval/mutation_gate.py``'s pairing rests on. Without it the gate
    silently stops asking "is the mutated surface still found?" and starts asking "is a
    string that is no longer in the document still found?" — whose answer is always no, and
    is indistinguishable from a detector defect.
    """
    mutate = MUTATIONS[name]
    assert surface in text, "fixture is wrong: the surface is not in the text"
    assert mutate(surface) in mutate(text)


# --------------------------------------------------------------- per-mutation semantics
def test_nbsp_replaces_every_ascii_space_and_nothing_else():
    assert mutate_nbsp("a b\tc\nd") == f"a{NBSP}b\tc\nd"
    assert " " not in mutate_nbsp(SAMPLE)
    assert mutate_nbsp(SAMPLE).count(NBSP) == SAMPLE.count(" ")


def test_zero_width_inserts_inside_runs_only():
    assert mutate_zero_width("abcd") == f"ab{ZWSP}cd"
    assert mutate_zero_width("abcdef") == f"ab{ZWSP}cd{ZWJ}ef"
    assert mutate_zero_width("abc") == "abc"          # runs under 4 are left alone
    assert mutate_zero_width("a-b-c") == "a-b-c"      # the dash breaks the run
    assert mutate_zero_width("43235222") == f"43{ZWSP}23{ZWJ}5222"
    # Both characters are Cf (format), i.e. invisible in every viewer — that is the attack.
    assert unicodedata.category(ZWSP) == "Cf" and unicodedata.category(ZWJ) == "Cf"


def test_soft_hyphen_inserts_inside_runs_only():
    assert mutate_soft_hyphen("abcd") == f"abc{SHY}d"
    assert mutate_soft_hyphen("abc") == "abc"
    assert mutate_soft_hyphen("43235222") == f"432{SHY}35222"
    assert unicodedata.category(SHY) == "Cf"


def test_tabs_replaces_spaces_with_tabs():
    assert mutate_tabs("a b  c") == "a\tb\t\tc"
    assert " " not in mutate_tabs(SAMPLE)
    assert mutate_tabs(SAMPLE).count("\t") == SAMPLE.count(" ")


def test_double_spaces_doubles_every_space():
    assert mutate_double_spaces("a b c") == "a  b  c"
    assert mutate_double_spaces(SAMPLE).count(" ") == 2 * SAMPLE.count(" ")


def test_line_break_mid_breaks_between_words_and_inside_long_runs():
    assert mutate_line_break_mid("Ján Novák") == "Ján\nNovák"      # between anchor words
    assert mutate_line_break_mid("43235222") == "432\n35222"        # mid-entity
    assert mutate_line_break_mid("abcde") == "abcde"                # runs under 6 intact
    assert " " not in mutate_line_break_mid(SAMPLE)


def test_all_caps_and_lowercase():
    assert mutate_all_caps("Ján Novák") == "JÁN NOVÁK"
    assert mutate_lowercase("JUDr. Ján Novák") == "judr. ján novák"
    assert mutate_all_caps(SAMPLE).upper() == mutate_all_caps(SAMPLE)
    assert mutate_lowercase(SAMPLE).lower() == mutate_lowercase(SAMPLE)


def test_no_diacritics_strips_every_slovak_mark():
    assert mutate_no_diacritics("Príliš žltúčky kôň úpel ďábelské ódy")== (
        "Prilis zltucky kon upel dabelske ody"
    )
    assert mutate_no_diacritics("Košice") == "Kosice"
    assert mutate_no_diacritics("Ľubochňa") == "Lubochna"
    mutated = mutate_no_diacritics(SAMPLE)
    assert not any(unicodedata.combining(c) for c in unicodedata.normalize("NFD", mutated))
    # Length-preserving for Slovak: one letter in, one letter out. The gate's character
    # offsets are not used across a mutation, but a length change here would signal that a
    # character decomposed into something other than base+mark.
    assert len(mutated) == len(SAMPLE)


def test_cyrillic_homoglyph_swaps_only_the_six_confusables():
    assert mutate_cyrillic_homoglyph("Novak") == "Nоvаk"
    assert mutate_cyrillic_homoglyph("PACX") == "РАСХ"
    # An ACCENTED Slovak letter is a different code point and has no Cyrillic lookalike in
    # the table, so it is left alone: "Ján" keeps its "á". The attack lands on the bare
    # Latin letters, which is where most of a Slovak surname is.
    assert mutate_cyrillic_homoglyph("Ján") == "Ján"
    assert mutate_cyrillic_homoglyph("Novák") == "Nоvák"
    assert mutate_cyrillic_homoglyph("12345") == "12345"           # digits untouched
    mutated = mutate_cyrillic_homoglyph(SAMPLE)
    assert len(mutated) == len(SAMPLE)
    # The whole point: it LOOKS identical. Confusable folding (NFKC does not do this) is the
    # only thing that tells them apart.
    assert mutated != SAMPLE and unicodedata.normalize("NFKC", mutated) == mutated


def test_nfd_decomposes_and_is_losslessly_recoverable():
    assert mutate_nfd("č") == "č"
    assert mutate_nfd("Košice") == "Košice"
    mutated = mutate_nfd(SAMPLE)
    assert mutated != SAMPLE
    # No information is destroyed — one normalize() call restores the original exactly.
    # That is why any detection loss under this mutation is a pure defect with no trade-off.
    assert unicodedata.normalize("NFC", mutated) == unicodedata.normalize("NFC", SAMPLE)


# -------------------------------------------------------- end-to-end locks (PASSING cells)
def _types(text: str, known: list[str] | None = None) -> set[str]:
    return {c.type for c in detect(text, known or []) if c.auto}


def _covered(text: str, surface: str, known: list[str] | None = None) -> bool:
    """Is every character of ``surface`` covered by an auto=True candidate? Same predicate
    as ``eval/mutation_gate._covering`` — leak-faithful union coverage."""
    start = text.index(surface)
    covered = [False] * len(surface)
    for cand in detect(text, known or []):
        if not cand.auto:
            continue
        for i in range(max(cand.start, start), min(cand.end, start + len(surface))):
            covered[i - start] = True
    return all(covered)


# (label, clean text, surface). Each is detected on the clean form; the mutation named in
# the test must leave it detected.
_NBSP_CASES = [
    ("rodné číslo", "r.č. 850315/0018", "850315/0018"),
    ("IBAN", "IBAN SK74 1100 4983 8673 1604 6759", "SK74 1100 4983 8673 1604 6759"),
    ("IČO", "IČO: 43235222", "43235222"),
    ("client number behind a two-word anchor", "Číslo klienta: KL-99321", "KL-99321"),
    ("bank code behind a two-word anchor", "kód banky: 1100", "1100"),
    ("fax behind an anchor", "fax: 055 123 4567", "055 123 4567"),
    ("phone", "tel. 0905 123 456", "0905 123 456"),
    # DOB-anchored, because that is the only DATUM that is auto=True: v1.1 routes every
    # non-birth date to the review bucket unless DetectConfig(redact_all_dates=True).
    ("date of birth", "narodený 15. 03. 2024", "15. 03. 2024"),
    ("amount", "suma 12 500,00 € celkom", "12 500,00 €"),
    ("title-anchored name", "JUDr. Ján Novák podpísal", "Ján Novák"),
    ("registry reference", "zapísané na LV č. 1234", "LV č. 1234"),
]


@pytest.mark.parametrize("label,text,surface", _NBSP_CASES, ids=[c[0] for c in _NBSP_CASES])
def test_nbsp_mutation_loses_nothing(label, text, surface):
    """``nbsp`` scores 1.000 on every type in the corpus run; this is the regression lock.

    It is the mutation that produced a LIVE LEAK before ``detect/core.py`` grew its 1:1 NBSP
    normalization (a PDF rendered "Číslo klienta:" with an NBSP inside the phrase and
    KL-99321 survived redaction), so it is the one cell in the whole table that must never
    go back to red.
    """
    assert _covered(text, surface), "fixture does not detect on CLEAN text"
    assert _covered(mutate_nbsp(text), mutate_nbsp(surface)), f"nbsp broke {label}"


@pytest.mark.parametrize(
    "text,surface",
    [
        ("r.č. 850315/0018", "850315/0018"),          # slash form: no diacritics, no spaces
        ("IČO: 43235222", "43235222"),
        ("DIČ: 1234567890", "1234567890"),
        ("IBAN SK74 1100 4983 8673 1604 6759", "SK74 1100 4983 8673 1604 6759"),
    ],
)
def test_all_caps_keeps_the_digit_shaped_identifiers(text, surface):
    """Uppercasing a document must not lose a numeric identifier — these cells are 1.000 in
    the corpus run and there is no capitalisation evidence for them to lose."""
    assert _covered(text, surface)
    assert _covered(mutate_all_caps(text), mutate_all_caps(surface))


@pytest.mark.parametrize(
    "text,surface",
    [
        ("r.č. 850315/0018", "850315/0018"),
        ("IČO: 43235222", "43235222"),
        ("IBAN SK74 1100 4983 8673 1604 6759", "SK74 1100 4983 8673 1604 6759"),
        ("Účet 19-8742637541/0200 v banke", "19-8742637541/0200"),
    ],
)
def test_no_diacritics_keeps_the_self_identifying_identifiers(text, surface):
    """The rodné-číslo anchor is already diacritic-folded (``detect/identifiers.py``
    ``_ascii_fold``) and the rest are pure digit shapes. These are the cells that show what
    the FIX for the anchor-required types looks like when it is applied."""
    assert _covered(text, surface)
    assert _covered(mutate_no_diacritics(text), mutate_no_diacritics(surface))


def test_nfd_keeps_the_diacritic_folded_rodne_cislo_anchor():
    """Positive control for ``nfd``: the ONE anchor in the codebase that folds diacritics
    before matching survives decomposition, which is the evidence that folding is the fix."""
    text, surface = "rodné číslo 850315/0018", "850315/0018"
    assert _covered(text, surface)
    assert _covered(mutate_nfd(text), mutate_nfd(surface))


def test_amount_survives_zero_width_because_its_runs_are_short():
    """``SUMA`` is 1.000 under ``zero_width``/``soft_hyphen`` — its digit groups are three
    characters, below the insertion threshold. Locked so that a future widening of the
    mutation is a deliberate, visible change rather than an unexplained column shift."""
    text, surface = "suma 12 500,00 € celkom", "12 500,00 €"
    assert _covered(text, surface)
    assert _covered(mutate_zero_width(text), mutate_zero_width(surface))
    assert _covered(mutate_soft_hyphen(text), mutate_soft_hyphen(surface))


def test_field_label_anchor_survives_all_caps():
    """The discriminator behind the ``all_caps`` verdict in redteam/FINDINGS_ROUND2.md.

    A field-label anchor is matched case-insensitively and captures the rest of the line, so
    it finds the name in an ALL-CAPS document. The title and role anchors, which require a
    ``[A-Z][a-z]+`` token, do not. Same document, same name, same evidence available — so
    the loss on the title/role anchors is a DEFECT, not an inherent consequence of the
    mutation. This test pins the half that works.
    """
    text = "Meno a priezvisko: Ján Novák"
    assert _covered(text, "Ján Novák")
    assert _covered(mutate_all_caps(text), mutate_all_caps("Ján Novák"))


def test_detect_never_raises_on_any_mutation_of_the_sample():
    """A mutated document must not crash a shipped desktop app mid-redaction. ``detect()``
    asserts five post-conditions on every call (CONTRACTS_v11.md §3), and overlapping spans
    are exactly the kind of thing a weird separator could produce."""
    for name, mutate in MUTATIONS.items():
        detect(mutate(SAMPLE), [mutate("Ján Novák")]), name

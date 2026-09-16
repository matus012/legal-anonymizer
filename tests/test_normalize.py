"""Unit spec for detect/normalize.py — the v1.1 offset-mapped normalization layer.

This module's whole job is that a span found in NORMALIZED coordinates maps back to the span
in ORIGINAL coordinates that CONTAINS every character which produced it. Getting that wrong
does not mislabel a document, it CORRUPTS one: both writers cut the file at these offsets, so
an off-by-one here deletes the wrong characters from a lawyer's contract.

So the invariants are asserted directly, not inferred from detect()'s output.
"""
import unicodedata

import pytest

from detect.normalize import Normalized, normalize, strip_format_chars

ZWSP = "​"
ZWNJ = "‌"
SHY = "­"
BOM = "﻿"
NBSP = " "


# --------------------------------------------------------------------------- invariants
def _assert_invariants(original: str, n: Normalized) -> None:
    if n.unchanged:
        assert n.text == original
        return
    assert len(n.starts) == len(n.text)
    assert len(n.ends) == len(n.text)
    for i in range(len(n.text)):
        assert 0 <= n.starts[i] < n.ends[i] <= len(original), i
    # MONOTONE: this is the property detect()'s "no overlapping spans survived resolution"
    # post-condition rests on. If the map were not monotone, two spans that did not overlap
    # in normalized coordinates could overlap in the original, and the writers would be handed
    # two redactions fighting over the same characters.
    for i in range(1, len(n.text)):
        assert n.starts[i] >= n.starts[i - 1], i
        assert n.ends[i] >= n.ends[i - 1], i
        assert n.starts[i] >= n.ends[i - 1] or n.starts[i] == n.starts[i - 1], i


SAMPLES = [
    "",
    "plain ascii",
    "Ján Novák, rodné číslo 850315/0018",
    f"IBAN SK68{ZWSP}0720 0002 8919 8742 6353",
    f"Rodné{SHY} číslo: 850315/0018",
    f"{BOM}Zmluva\tmedzi\nstranami",
    "Dátum:  01.  01.  1980",
    f"Číslo{NBSP}klienta: KL-99321",
    unicodedata.normalize("NFD", "Ján Novák, Košice, č. 12"),
    "ＳＫ６８ ０７２０",           # fullwidth
    "jаn.nоvаk@аdvоkаt.sk",      # cyrillic homoglyphs
    "ﬁrma s.r.o.",               # ligature
    f"{ZWNJ}{ZWSP}{SHY}",        # nothing but format characters
    "\n\n\n",
    "a" * 500,
]


@pytest.mark.parametrize("text", SAMPLES)
def test_map_invariants_hold(text):
    _assert_invariants(text, normalize(text))


@pytest.mark.parametrize("text", SAMPLES)
def test_normalization_is_idempotent(text):
    once = normalize(text).text
    assert normalize(once).text == once


@pytest.mark.parametrize("text", SAMPLES)
def test_every_normalized_span_maps_inside_the_original(text):
    n = normalize(text)
    for start in range(len(n.text)):
        for end in range(start + 1, len(n.text) + 1):
            a, b = n.span(start, end)
            assert 0 <= a < b <= len(text)
            assert n.surface(start, end) == text[a:b]


def test_empty_span_is_rejected():
    n = normalize(f"a{ZWSP}b")
    with pytest.raises(ValueError):
        n.span(1, 1)


# --------------------------------------------------- what each transformation actually does
def test_format_characters_are_deleted():
    assert normalize(f"850{ZWSP}315").text == "850315"
    assert normalize(f"850{SHY}315").text == "850315"
    assert normalize(f"{BOM}850315").text == "850315"


def test_a_deleted_format_char_stays_INSIDE_the_mapped_span():
    """The point of the whole module. A zero-width space sitting inside an account number must
    be covered by the redaction that removes the account number — otherwise the writer cuts
    around it and leaves an orphan character between two labels, which is both visible damage
    and a fragment of the original token."""
    text = f"850{ZWSP}315"
    n = normalize(text)
    a, b = n.span(0, len(n.text))
    assert text[a:b] == text  # the span covers the invisible character too


def test_whitespace_runs_collapse_to_one_character():
    assert normalize("a\t\tb").text == "a b"
    assert normalize("a  b").text == "a b"
    assert normalize(f"a{NBSP}b").text == "a b"


def test_a_run_that_crossed_a_line_collapses_to_a_LINE_BREAK_not_a_space():
    """The line boundary survives normalization, and that is deliberate.

    Collapsing it to a space was tried and broke two detectors in opposite directions: the
    bare-name heuristic paired the last word of one line with the first word of the next as a
    first name and surname, and the field-label pattern — which uses [\\n\\r\\t] to terminate a
    label's VALUE — lost its terminator and let a value run to the end of the page.

    Normalization makes the SPELLING of whitespace uniform. Whether a detector may see through
    a line break stays that detector's decision, spelled \\s or [^\\S\\n\\r] at its own site."""
    assert normalize("a\nb").text == "a\nb"
    assert normalize("a\r\nb").text == "a\nb"
    assert normalize(f"a \n\t{NBSP} b").text == "a\nb"
    assert normalize("a \t b").text == "a b"


def test_collapsed_whitespace_run_maps_over_the_whole_run():
    text = "a  \t b"
    n = normalize(text)
    assert n.text == "a b"
    a, b = n.span(0, 3)
    assert text[a:b] == text


def test_cyrillic_homoglyphs_fold_to_latin():
    assert normalize("jаn.nоvаk").text == "jan.novak"   # Cyrillic а and о in the input
    # Cyrillic К, О, С, Е all have Latin twins and fold; the word becomes plain Latin.
    assert normalize("КОСIСЕ").text == "KOCICE"


def test_genuinely_cyrillic_text_is_not_mangled_beyond_the_confusables():
    """Slovakia has a large Ukrainian-speaking population and a filing may legitimately contain
    Cyrillic. Only VISUAL CONFUSABLES fold; a letter with no Latin lookalike is left alone, so
    the text stays readable as what it is."""
    assert "б" in normalize("абв").text
    assert "д" in normalize("где").text


def test_nfd_composes_to_nfc():
    decomposed = unicodedata.normalize("NFD", "Ján Novák č")
    assert normalize(decomposed).text == "Ján Novák č"


def test_nfd_span_covers_the_combining_mark():
    text = unicodedata.normalize("NFD", "Ján")   # J a U+0301 n
    n = normalize(text)
    assert n.text == "Ján"
    a, b = n.span(0, 3)
    assert text[a:b] == text     # the mark is inside the span, not orphaned after it


def test_fullwidth_digits_fold():
    assert normalize("ＳＫ６８").text == "SK68"


def test_ligature_expands_and_maps_back_to_one_character():
    text = "ﬁrma"
    n = normalize(text)
    assert n.text == "firma"
    # Both 'f' and 'i' came from the single ligature character, so a span over either covers it.
    assert n.surface(0, 1) == "ﬁ"
    assert n.surface(1, 2) == "ﬁ"


def test_case_is_NOT_folded():
    """Deliberate. detect/orgs.py and the bare-name heuristic use CAPITALISATION AS EVIDENCE;
    folding case here would not make them case-insensitive, it would delete their only signal
    and turn every capitalized-token rule into a match-everything rule."""
    assert normalize("Ján NOVÁK").text == "Ján NOVÁK"


def test_diacritics_are_NOT_stripped():
    """Also deliberate. Folding č -> c here would silently widen every Slovak-word pattern in
    detect/ at once. The no_diacritics class is handled per detector, on the anchor test."""
    assert "č" in normalize("rodné číslo").text


# --------------------------------------------------------------------------- fast path
def test_ordinary_text_takes_the_identity_path():
    n = normalize("Kupna zmluva medzi stranami")
    assert n.unchanged
    assert n.span(2, 5) == (2, 5)


def test_text_whose_normalization_is_a_no_op_also_takes_the_identity_path():
    """'€' is outside the cheap character class so it trips the "interesting" screen, but
    nothing about it actually changes. The module must still collapse to the identity rather
    than carrying a full map for no reason."""
    n = normalize("Cena 12 345,67 €")
    assert n.unchanged


# --------------------------------------------------------------------------- shared helper
def test_strip_format_chars_matches_what_normalize_deletes():
    text = f"a{ZWSP}b{SHY}c{BOM}d{ZWNJ}e"
    assert strip_format_chars(text) == "abcde"
    assert normalize(text).text == "abcde"

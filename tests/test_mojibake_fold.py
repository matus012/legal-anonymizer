"""The cp1250-as-WinAnsi fold (red-team round 4, R4-I3): the table, the evidence threshold,
the offset-preservation property the writers depend on, and the refusal for the half that
cannot be repaired.

The measurements these tests pin are the ones that justify the design, so they are asserted
rather than written down in a report nobody re-runs:

  * FALSE-REPAIR RISK. Over the whole clean corpus -- 3 855 detect() units from the 71 corpus
    .docx plus the demo, and 82 pages from the 71 corpus .pdf plus the demo -- the evidence
    test fires ZERO times, and the corpus text contains ZERO evidence characters. That is what
    licenses a threshold of ONE occurrence.
  * FALSE-REFUSAL RISK. The same 82 pages, zero refusals. This module's history is exactly why
    that is asserted and not reasoned about: an ``isprintable()`` guard added to
    writer/pdf_body.py once looked right and would have refused 70 of 71 corpus PDFs, because
    PyMuPDF renders an ordinary hyphen as U+00AD.
  * SENSITIVITY. Every corpus unit the mutation actually changes fires the evidence test.

The corpus scans are skipped, not failed, when data/synthetic is absent -- the same
convention the other corpus-backed tests in this suite use.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import fitz
import pytest

from corpus.mutations import mutate_mojibake_cp1250
from detect.core import detect
from detect.normalize import (
    MOJIBAKE_AMBIGUOUS,
    has_mojibake_evidence,
    mojibake_is_unrepairable,
    normalize,
)
from eval.mutation_gate import docx_units
from writer.pdf_body import MojibakeTextLayerError, page_is_unrepairable_mojibake

CORPUS = Path(__file__).resolve().parent.parent / "data" / "synthetic"
DEMO = Path(__file__).resolve().parent.parent / "demo"


# ------------------------------------------------------------------------------- the table
def test_fold_inverts_the_mutation_for_every_unambiguous_character():
    """The fold is the exact inverse of the attack, character for character, except on the
    images the WinAnsi code page collapses. Derived independently on both sides (detect/ may
    not import corpus/), so this is a real cross-check and not a tautology.

    Each character is placed in a unit that carries evidence, because the fold is deliberately
    conditional -- a lone "Ã" is Romanian, not damage."""
    prefix = "pod¾a "          # mis-decoded "podľa": the evidence, in one word
    for code in range(0x20, 0x2500):
        ch = chr(code)
        damaged = mutate_mojibake_cp1250(ch)
        if damaged == ch or damaged in MOJIBAKE_AMBIGUOUS:
            continue
        repaired = normalize(f"{prefix}x{damaged}x").text
        # Compared against the NORMALIZED clean text, not the raw clean text: the five bare
        # spacing diacritics in the table ("˘", "˝", ...) are compatibility forms that
        # per-character NFKC expands on both sides. What is being asserted is that the fold
        # lands on the same character the clean document would have arrived as.
        assert repaired == normalize(f"podľa x{ch}x").text, (
            f"{ch!r} -> {damaged!r} -> {repaired!r}"
        )


def test_pymupdf_renders_a_lost_byte_as_a_bullet(tmp_path):
    """The measurement the bullet half of the ambiguous set rests on. Keying the refusal on
    U+FFFD alone -- which is what the mutation produces on TEXT -- would have left it DEAD
    CODE on the only path it exists for: a PDF reader shows U+2022 instead.
    """
    from tests.test_redteam_round4 import pdf_text, write_pdf

    src = write_pdf(tmp_path, "lost", [
        (72, 90, "štátna príslušnosť slovenská".encode("cp1250"))])
    assert "príslušnos•" in pdf_text(src)


def test_the_ambiguous_set_is_the_two_renderings_of_an_undefined_byte():
    """U+FFFD and U+2022 are the whole of the unrepairable set: "Ť", "ť" and "Ź" all encode to a cp1250
    byte that WinAnsi leaves undefined. If this ever grows, the refusal below widens with it
    and that must be a deliberate, measured change."""
    assert MOJIBAKE_AMBIGUOUS == frozenset({"\ufffd", "\u2022"})
    assert mutate_mojibake_cp1250("Ť") == mutate_mojibake_cp1250("ť") == "\ufffd"


# ---------------------------------------------------------------------------- the property
def test_the_fold_is_offset_preserving():
    """The property the whole design rests on. Both writers CUT THE DOCUMENT at detector
    offsets, so a repair that changed lengths would corrupt files rather than mislabel them."""
    clean = "Predávajúci Ľubomír Ďurčo, bytom Hlavná 25, Košice, byt č. 5"
    damaged = mutate_mojibake_cp1250(clean)
    norm = normalize(damaged)
    assert len(norm.text) == len(damaged)
    for i in range(len(norm.text)):
        assert norm.span(i, i + 1) == (i, i + 1)


def test_the_surface_reported_is_the_documents_own_mojibake_spelling():
    """Detection runs over the repaired view; the surface comes back in the ORIGINAL spelling,
    which is what is actually drawn on the page and therefore what search_for must find."""
    damaged = mutate_mojibake_cp1250("Predávajúci: Ľubomír Ďurčo, nar. 1.1.1980")
    cands = detect(damaged, ["Ľubomír Ďurčo"])
    meno = [c for c in cands if c.type == "MENO"]
    assert meno, cands
    assert "¼ubomír" in meno[0].surface
    assert damaged[meno[0].start:meno[0].end] == meno[0].surface


def test_the_fold_is_idempotent():
    damaged = mutate_mojibake_cp1250("nehnuteľnosť podľa Ľubomíra Ďurča")
    once = normalize(damaged).text
    assert normalize(once).text == once


# --------------------------------------------------------------------------- the evidence
def test_a_foreign_name_is_not_repaired():
    """A Slovak contract may legitimately name a French or Swedish party, and neither of these
    spellings is mojibake: "ë" and "ö" are IDENTICAL in cp1250 and cp1252, so they are not in
    the table at all."""
    for text in ("Citroën Slovakia s.r.o.", "Malmö", "zmluva à la carte"):
        assert not has_mojibake_evidence(text), text
        assert normalize(text).text == text


def test_evidence_needs_a_word_or_abbreviation_context():
    assert not has_mojibake_evidence("cena 100 £ a 50 %")
    assert has_mojibake_evidence("pod¾a")          # ľ inside a word
    assert has_mojibake_evidence("byt è. 151")     # č. -- the Slovak abbreviation point


@pytest.mark.skipif(not CORPUS.exists(), reason="corpus not generated")
def test_zero_false_repairs_over_the_clean_corpus():
    units = 0
    for path in sorted(CORPUS.glob("*.docx")) + [DEMO / "kupna_zmluva_demo.docx"]:
        for unit in docx_units(path):
            units += 1
            assert not has_mojibake_evidence(unit), (path.name, unit[:120])
    assert units > 3000, units


@pytest.mark.skipif(not CORPUS.exists(), reason="corpus not generated")
def test_zero_false_refusals_over_every_corpus_pdf():
    pages = 0
    for path in sorted(CORPUS.glob("*.pdf")) + [DEMO / "kupna_zmluva_demo.pdf"]:
        doc = fitz.open(path)
        for page in doc:
            pages += 1
            assert not page_is_unrepairable_mojibake(page.get_text("text")), path.name
        doc.close()
    assert pages > 70, pages


@pytest.mark.skipif(not CORPUS.exists(), reason="corpus not generated")
def test_evidence_fires_on_every_mutated_unit_the_mutation_changed():
    changed = 0
    for path in sorted(CORPUS.glob("*.docx")):
        for unit in docx_units(path):
            damaged = mutate_mojibake_cp1250(unit)
            if damaged == unit:
                continue
            changed += 1
            assert has_mojibake_evidence(damaged), (path.name, damaged[:120])
    assert changed > 1000, changed


# ---------------------------------------------------------------------------- the refusal
def test_unrepairable_needs_both_halves():
    """U+FFFD on its own is not evidence of anything -- a decoder emits it for any byte it
    could not place. It means "the repair cannot be finished" only on a page that ALSO carries
    the mojibake signature."""
    assert not mojibake_is_unrepairable("text with a stray \ufffd character")
    assert not mojibake_is_unrepairable("pod\u00bea\n\u2022 prv\u00fd bod\n\u2022 druh\u00fd bod")
    assert mojibake_is_unrepairable("Štátna príslušnos\ufffd: slovenská")


def test_the_refusal_message_says_no_file_was_written():
    """The house style of UnreadableTextLayerError / ShreddedTextLayerError: the reviewer must
    be able to tell, from the message alone, whether there is now a half-redacted document on
    disk."""
    err = MojibakeTextLayerError("C:/x/zmluva.pdf", [2, 5])
    text = str(err)
    assert "NO FILE WAS WRITTEN" in text
    assert "2, 5" in text
    assert "zmluva.pdf" in text


def test_unrepairable_page_is_refused_end_to_end(tmp_path):
    """A page whose Slovak "ť" was destroyed by the WinAnsi code page is refused, and no output
    file exists afterwards."""
    from tests.test_redteam_round4 import write_pdf

    src = write_pdf(tmp_path, "moji", [
        (72, 90, "Predavajuci: Ľubomír Ďurčo, štátna príslušnosť slovenská".encode("cp1250")),
        (72, 120, "Kupna cena bola uhradena v plnej vyske pri podpise.".encode("cp1250")),
        (72, 150, "Zmluva nadobuda ucinnost dnom vkladu do katastra.".encode("cp1250"))])
    out = tmp_path / "moji_r.pdf"

    from writer.pdf_body import redact_pdf
    with pytest.raises(MojibakeTextLayerError):
        redact_pdf(str(src), str(out), ["Ľubomír Ďurčo"])
    assert not out.exists()


def test_evidence_characters_are_only_the_slovak_ones():
    """"m³" and "1ª" must not be evidence that a page is mis-decoded: they are ordinary text,
    and "³"/"ª" are the images of Polish and Turkish letters, not Slovak ones."""
    for text in ("výmera 120 m³", "výmera 120 m²", "položka 1ª"):
        assert not has_mojibake_evidence(text), text
    assert all(
        unicodedata.category(ch).startswith(("L", "N", "S", "P", "C"))
        for ch in MOJIBAKE_AMBIGUOUS
    )

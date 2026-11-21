"""R3-C1: a PDF whose text layer is shredded into single characters must be REFUSED.

THE WORST FINDING OF RED-TEAM ROUND 3
--------------------------------------------------------------------------------------
When a PDF's glyph advances do not match its text, ``get_text()`` returns
``"P re d a v a ju ci: Ja n N o va k"``. Two things then happen, and the second is what makes
this the worst shape in the project:

  1. ``detect()`` finds nothing, so nothing is redacted; and
  2. ``eval/extract.py`` reads the SAME mangled string, so the ground-truth needle is absent
     from every surface — including ``raw_bytes``, since each glyph is its own show-text
     operator — and **the leak gate scores an entirely unredacted document CLEAN**.

Corpus-wide, as the ``letterspaced`` mutation: 0.113 blind, the largest number in the project.

Real sources: a document-management system export, a PDF/A converter, any OCR text layer, and
Word's own character spacing. An OCR'd filing is out of v1 scope only when it has NO text layer
— one that HAS a text layer is accepted and processed.

WHAT THIS FIX IS, AND IS NOT
The correct fix is to re-segment the words from the per-character geometry in ``rawdict``: the
inter-character gaps carry the word boundaries even when the flat text does not. PyMuPDF's own
``get_text("words")`` does not help — measured, it fragments identically — so that is a piece
of work, not a one-liner, and it is written up rather than rushed.

This is the honest interim: REFUSE. It converts "silently ships an unredacted document that
the gate calls clean" into "says it cannot read this file, and why". Refusing costs a
re-export. The alternative costs the client's data.

The threshold is on the PAGE and needs a substantial amount of text, because Slovak notarial
practice letter-spaces headings and party designations on purpose (*razvetrené písmo*) — a
spaced heading must not cost a document its redaction.
"""
import os
import tempfile

import fitz
import pytest

from writer.pdf_body import (
    NoTextLayerError,
    ShreddedTextLayerError,
    page_is_shredded,
    redact_pdf,
)

LINES = [
    "Predavajuci: Jan Novak, rodne cislo 835112/0008",
    "Kupujuci: Maria Kovacova, ICO 47123456",
    "Ucet SK68 0720 0002 8919 8742 6353, email jan.novak@advokat.sk",
    "Nehnutelnost v obci Kosice, zapisana na LV c. 1234",
]


def _build(path, tracking: float) -> None:
    """Draw each character at an advance scaled by ``tracking``. At 1.0 this is an ordinary
    page; above ~1.2 the extractor starts inserting spaces between the glyphs."""
    doc = fitz.open()
    page = doc.new_page()
    font = fitz.Font("helv")
    y = 90
    for line in LINES:
        x = 60.0
        writer = fitz.TextWriter(page.rect)
        for ch in line:
            writer.append((x, y), ch, font=font, fontsize=10)
            x += font.text_length(ch, 10) * tracking
        writer.write_text(page)
        y += 26
    doc.save(str(path))
    doc.close()


@pytest.mark.parametrize("tracking,shredded", [
    (1.0, False),     # an ordinary page
    (1.15, False),    # slightly tracked — still extracts as words
    (1.3, True),      # the red team's measured leak point
    (1.8, True),
])
def test_page_is_shredded_matches_the_measured_boundary(tracking, shredded):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "t.pdf")
        _build(src, tracking)
        with fitz.open(src) as doc:
            assert any(page_is_shredded(p.get_text("text")) for p in doc) is shredded


def test_a_shredded_pdf_is_REFUSED():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.pdf")
        out = os.path.join(tmp, "out.pdf")
        _build(src, 1.8)
        with pytest.raises(ShreddedTextLayerError) as excinfo:
            redact_pdf(src, out, known_entities=["Jan Novak"])
        assert excinfo.value.pages == [1]


def test_an_ordinary_pdf_is_still_processed():
    """The quiet half, and the one that decides whether this guard survives contact with the
    office. A refusal that fires on normal documents is the tool declining its own job."""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.pdf")
        out = os.path.join(tmp, "out.pdf")
        _build(src, 1.0)
        redact_pdf(src, out, known_entities=["Jan Novak"])
        with fitz.open(out) as doc:
            text = "\n".join(p.get_text("text") for p in doc)
        assert "835112/0008" not in text
        assert "Novak" not in text


def test_a_short_spaced_heading_does_not_condemn_the_page():
    """Letter-spacing a HEADING is ordinary Slovak notarial typography. The test is on the
    whole page and needs a minimum amount of text, so a spaced title line cannot cost the
    document its redaction."""
    assert page_is_shredded("K Ú P N A  Z M L U V A") is False


def test_the_refusal_is_a_NoTextLayerError_subclass():
    assert issubclass(ShreddedTextLayerError, NoTextLayerError)


def test_the_gui_does_not_call_it_a_scan():
    from gui.model import MSG_NO_TEXT_LAYER, MSG_SHREDDED_TEXT, MSG_UNREADABLE_TEXT

    assert len({MSG_SHREDDED_TEXT, MSG_UNREADABLE_TEXT, MSG_NO_TEXT_LAYER}) == 3
    assert "NIE JE to sken" in MSG_SHREDDED_TEXT


def test_no_corpus_pdf_is_refused():
    """The false-refusal check, run against the real corpus rather than reasoned about."""
    import glob

    pdfs = sorted(glob.glob(os.path.join("data", "synthetic", "*.pdf")))
    if not pdfs:
        pytest.skip("corpus not generated")
    refused = []
    for path in pdfs:
        with fitz.open(path) as doc:
            if any(page_is_shredded(p.get_text("text")) for p in doc):
                refused.append(os.path.basename(path))
    assert not refused, f"guard fires on ordinary corpus documents: {refused}"

"""R3-C4: a PDF whose text is DRAWN but cannot be DECODED must be refused, not "anonymised".

THE FAILURE
--------------------------------------------------------------------------------------
A PDF that uses a subset font with no ``/ToUnicode`` map extracts as raw glyph codes —
control characters. The old ``has_text_layer`` asked only whether ``get_text()`` returned
something non-blank, and control characters are non-blank, so:

  * the app ACCEPTED the file (it is not a scan, so it was never refused),
  * ``detect()`` saw control characters where the rodné číslo was, and removed nothing,
  * ``eval/extract.py`` read the SAME control characters, so the ground-truth needle was
    absent from every surface and **the leak gate scored the document CLEAN**,
  * and the number stayed drawn on the page, where a human reads it perfectly.

The dangerous shape is not a page of pure garbage. It is a page where MOST text decodes and
ONE FIELD does not, because only that field is set in the subset font — the name is found and
redacted, the rodné číslo beside it is not, and the output looks like a successful redaction.

``context.md`` §3 promises a refusal for a PDF the tool cannot read. These tests hold the
promise to text the tool cannot INTERPRET, not only to text that is absent.
"""
import os
import tempfile

import fitz
import pytest

from writer.pdf_body import (
    NoTextLayerError,
    UnreadableTextLayerError,
    has_text_layer,
    page_has_unreadable_text,
    page_text_is_readable,
    redact_pdf,
)

CONTROL_RC = "".join(chr(c) for c in (8, 5, 3, 3, 1, 5)) + "/" + "".join(chr(c) for c in (3, 3, 1, 8))


# ------------------------------------------------------------------ the predicates
@pytest.mark.parametrize("text,readable", [
    ("Predávajúci: Ján Novák, rodné číslo 850315/0018.", True),
    ("", False),
    ("   \n\t  ", False),
    (CONTROL_RC, False),
    ("krátky", False),                       # below the minimum character count
])
def test_page_text_is_readable(text, readable):
    assert page_text_is_readable(text) is readable


@pytest.mark.parametrize("text,refuse", [
    ("Predávajúci: Ján Novák, rodné číslo 850315/0018.", False),
    ("", False),                              # an image page: nothing drawn for us to miss
    (CONTROL_RC, True),
    (f"Predávajúci: Ján Novák\nRodné číslo: {CONTROL_RC}", True),   # THE REAL SHAPE
    ("Ordinary text with one stray \x01 artefact", False),
])
def test_page_has_unreadable_text(text, refuse):
    assert page_has_unreadable_text(text) is refuse


def test_an_empty_page_is_not_called_unreadable():
    """The distinction the whole fix rests on. A page with NO text is an image — there is
    nothing drawn that we failed to read, and it is handled by has_text_layer/NoTextLayerError.
    A page with text we cannot decode is the opposite: something IS drawn and we missed it."""
    assert page_has_unreadable_text("") is False
    assert page_text_is_readable("") is False


# ------------------------------------------------------------------ end to end
def _pdf(path, lines):
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for line in lines:
        page.insert_text((72, y), line, fontname="helv", fontsize=11)
        y += 30
    doc.save(str(path))
    doc.close()


def test_a_page_of_undecodable_text_is_REFUSED_not_redacted():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.pdf")
        out = os.path.join(tmp, "out.pdf")
        _pdf(src, ["Predavajuci: Jan Novak", f"Rodne cislo: {CONTROL_RC}"])
        with pytest.raises(UnreadableTextLayerError) as excinfo:
            redact_pdf(src, out, known_entities=["Novak"])
        assert excinfo.value.pages == [1]


def test_the_refusal_is_a_NoTextLayerError_subclass():
    """Every caller that already refuses a PDF without a text layer refuses this one too,
    with no change. The distinct type exists only so the GUI can explain it differently —
    telling the lawyer to rescan a document that has perfectly good text in it would send
    them to do the one thing that cannot help."""
    assert issubclass(UnreadableTextLayerError, NoTextLayerError)


def test_an_ordinary_pdf_is_still_accepted():
    """The quiet half. A guard that fires on normal documents would be removed within a week."""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.pdf")
        out = os.path.join(tmp, "out.pdf")
        _pdf(src, ["Predavajuci: Jan Novak", "Rodne cislo: 835112/0008"])
        redact_pdf(src, out, known_entities=["Novak"])
        with fitz.open(out) as doc:
            assert has_text_layer(doc)
            text = "\n".join(p.get_text("text") for p in doc)
        assert "835112/0008" not in text
        assert "Novak" not in text


def test_the_gui_explains_it_is_not_a_scan():
    from gui.model import MSG_NO_TEXT_LAYER, MSG_UNREADABLE_TEXT

    assert MSG_UNREADABLE_TEXT != MSG_NO_TEXT_LAYER
    assert "NIE JE to sken" in MSG_UNREADABLE_TEXT

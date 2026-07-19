"""Phase 5 P1 (spec): detect PDF text-layer presence and refuse to redact scanned/image-only
PDFs. Detection + refuse ONLY in this round -- no redaction, no output file is ever written by
redact_pdf() in P1 (a text-layer PDF raises NotImplementedError instead of proceeding).

Fixtures are hand-built in-test with fitz (NO corpus import): a one-page doc with an inserted
text run, and a blank page with no text at all.
"""
from __future__ import annotations

import fitz

from writer.pdf_body import NoTextLayerError, has_text_layer, redact_pdf


def _text_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Jan Novak")
    doc.save(str(path))
    doc.close()


def _empty_pdf(path) -> None:
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()


def test_has_text_layer_true_for_page_with_text(tmp_path):
    p = tmp_path / "text.pdf"
    _text_pdf(p)
    doc = fitz.open(str(p))
    assert has_text_layer(doc) is True
    doc.close()


def test_has_text_layer_false_for_blank_page(tmp_path):
    p = tmp_path / "empty.pdf"
    _empty_pdf(p)
    doc = fitz.open(str(p))
    assert has_text_layer(doc) is False
    doc.close()


def test_redact_pdf_raises_no_text_layer_error_and_writes_nothing(tmp_path):
    src = tmp_path / "empty.pdf"
    out = tmp_path / "empty_out.pdf"
    _empty_pdf(src)

    try:
        redact_pdf(str(src), str(out))
        assert False, "expected NoTextLayerError"
    except NoTextLayerError as e:
        assert str(src) in str(e)

    assert not out.exists()


def test_redact_pdf_raises_not_implemented_for_text_layer_and_writes_nothing(tmp_path):
    src = tmp_path / "text.pdf"
    out = tmp_path / "text_out.pdf"
    _text_pdf(src)

    try:
        redact_pdf(str(src), str(out))
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass

    assert not out.exists()

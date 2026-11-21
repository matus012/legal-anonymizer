"""Phase 5 P1 (spec): detect PDF text-layer presence and gate redaction on it. A no-text-layer
(scanned/image-only) PDF is REFUSED -- redact_pdf() raises NoTextLayerError and writes no output
-- while a text-layer PDF PROCEEDS to redaction (P2) and produces a valid, non-empty output file.

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


def test_text_layer_pdf_is_redacted_not_refused(tmp_path):
    """P2 superseded P1's stub: a text-layer PDF is redacted, not refused. NotImplementedError
    exists nowhere in writer/ anymore -- this only guards that redaction proceeds and produces
    a valid, non-empty output file. Label/PII-removal specifics are covered in
    tests/test_writer_pdf_redact.py."""
    src = tmp_path / "text.pdf"
    out = tmp_path / "text_out.pdf"
    _text_pdf(src)

    redact_pdf(str(src), str(out))

    assert out.exists()

    doc = fitz.open(str(out))
    text = "".join(page.get_text("text") for page in doc)
    doc.close()
    assert text.strip() != ""
